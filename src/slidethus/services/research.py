from __future__ import annotations

import copy
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import (
    ResearchCacheError,
    ResearchOfflineError,
    ResearchPlanningError,
    ResearchProviderError,
    ResearchRuntimeError,
    WorkspaceError,
)
from slidethus.io_utils import (
    atomic_create_json,
    atomic_write_json,
    canonical_json_bytes,
    ensure_within,
    read_json,
    sha256_file,
    sha256_json,
)
from slidethus.protocols import (
    ResearchLimits,
    ResearchPlan,
    ResearchProvider,
    ResearchQuery,
    ResearchResult,
)
from slidethus.schema_registry import SchemaRegistry

try:  # pragma: no cover - platform-specific import
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - platform-specific import
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]


Clock = Callable[[], datetime]
_SOURCE_TIERS = {"primary", "secondary", "community", "unknown"}
_EXTERNAL_SOURCE_TIERS = ("primary", "secondary", "community", "unknown")
_RUN_ID = re.compile(r"^RRN-[A-F0-9]{16}$")
_CYCLE_ID = re.compile(r"^RSC-[0-9]{3}$")
_QUERY_ID = re.compile(r"^RQ-[0-9]{3}$")
_SLIDE_ID = re.compile(r"^S-[0-9]{3}$")
_NON_FACTUAL_SLIDE_TYPES = {"cover", "agenda", "section", "section_divider", "closing"}
_PLACEHOLDER_TEXT = {"待补充", "tbd", "todo", "unknown", "n/a", "none"}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchRuntimeError(f"Invalid research timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _researchable_text(value: Any) -> str:
    normalized = _normalize_text(value)
    return "" if normalized.casefold() in _PLACEHOLDER_TEXT else normalized


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for raw in values:
        value = _normalize_text(raw)
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return tuple(output)


def validate_research_limits(limits: ResearchLimits) -> None:
    """Validate public Research limits before planning or application execution."""

    _validate_limits(limits)


def _validate_limits(limits: ResearchLimits) -> None:
    values = asdict(limits)
    if any(not isinstance(value, int) for value in values.values()):
        raise ResearchPlanningError("Research limits must be integers")
    if min(
        limits.max_queries,
        limits.max_query_chars,
        limits.max_results_per_query,
        limits.max_total_results,
        limits.max_title_chars,
        limits.max_summary_chars,
        limits.max_metadata_bytes,
    ) < 1:
        raise ResearchPlanningError("Research limits except cache_ttl_seconds must be positive")
    if limits.cache_ttl_seconds < 0:
        raise ResearchPlanningError("cache_ttl_seconds must be zero or positive")
    if limits.max_queries > 999:
        raise ResearchPlanningError("max_queries cannot exceed stable query ID space (999)")
    if limits.max_results_per_query > 1000 or limits.max_total_results > 10_000:
        raise ResearchPlanningError("Research result limits exceed admitted runtime bounds")
    if limits.max_metadata_bytes > 10 * 1024 * 1024:
        raise ResearchPlanningError("max_metadata_bytes exceeds admitted runtime bound")


def _external_tiers(brief: dict[str, Any]) -> tuple[str, ...]:
    allowed = brief.get("source_policy", {}).get("allowed_source_tiers", [])
    tiers = tuple(tier for tier in _EXTERNAL_SOURCE_TIERS if tier in allowed)
    if not tiers:
        raise ResearchPlanningError(
            "External research is enabled but no external source tier is admitted"
        )
    return tiers


def _next_cycle_id(evidence: dict[str, Any]) -> str:
    numbers = [
        int(str(item.get("cycle_id", "RSC-000")).split("-")[-1])
        for item in evidence.get("research_cycles", [])
        if _CYCLE_ID.fullmatch(str(item.get("cycle_id", "")))
    ]
    next_number = max(numbers, default=0) + 1
    if next_number > 999:
        raise ResearchPlanningError("Research cycle ID space is exhausted")
    return f"RSC-{next_number:03d}"


def _resolve_cycle_id(
    workspace: Path,
    kind: str,
    outline_version: int | None,
    requested: str | None,
) -> str:
    evidence = read_json(workspace / "evidence/evidence_ledger.json")
    cycles = list(evidence.get("research_cycles", []))
    if requested is not None:
        if not _CYCLE_ID.fullmatch(requested):
            raise ResearchPlanningError(f"Invalid research cycle ID: {requested}")
        existing = next(
            (item for item in cycles if item.get("cycle_id") == requested),
            None,
        )
        if existing is None:
            expected_new = _next_cycle_id(evidence)
            if requested != expected_new:
                raise ResearchPlanningError(
                    f"New research cycle must use next available ID {expected_new}, got {requested}"
                )
            return requested
        if existing.get("kind") != kind:
            raise ResearchPlanningError(
                f"Research cycle {requested} is {existing.get('kind')}, not {kind}"
            )
        if kind == "orientation" and existing.get("outline_version") is not None:
            raise ResearchPlanningError(f"Orientation cycle {requested} has an outline version")
        if kind == "targeted" and existing.get("outline_version") != outline_version:
            raise ResearchPlanningError(
                f"Targeted cycle {requested} is bound to outline version "
                f"{existing.get('outline_version')}, not {outline_version}"
            )
        return requested

    matches = [
        item
        for item in cycles
        if item.get("kind") == kind
        and (kind == "orientation" or item.get("outline_version") == outline_version)
    ]
    if matches:
        return str(matches[0]["cycle_id"])
    return _next_cycle_id(evidence)


def _plan_payload(
    *,
    project_id: str,
    cycle_id: str,
    cycle_kind: str,
    outline_version: int | None,
    queries: Iterable[ResearchQuery],
    limits: ResearchLimits,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "cycle_id": cycle_id,
        "cycle_kind": cycle_kind,
        "outline_version": outline_version,
        "queries": [asdict(query) for query in queries],
        "limits": asdict(limits),
    }


def _plan_id(payload: dict[str, Any]) -> str:
    return f"RPL-{sha256_json(payload)[:16].upper()}"


def research_plan_hash(plan: ResearchPlan) -> str:
    payload = _plan_payload(
        project_id=plan.project_id,
        cycle_id=plan.cycle_id,
        cycle_kind=plan.cycle_kind,
        outline_version=plan.outline_version,
        queries=plan.queries,
        limits=plan.limits,
    )
    return f"sha256:{sha256_json(payload)}"


def _validate_plan(plan: ResearchPlan) -> None:
    _validate_limits(plan.limits)
    if plan.cycle_kind not in {"orientation", "targeted"}:
        raise ResearchPlanningError(f"Unknown research cycle kind: {plan.cycle_kind}")
    if not _CYCLE_ID.fullmatch(plan.cycle_id):
        raise ResearchPlanningError(f"Invalid research cycle ID: {plan.cycle_id}")
    if plan.cycle_kind == "orientation" and plan.outline_version is not None:
        raise ResearchPlanningError("Orientation research cannot bind an outline version")
    if plan.cycle_kind == "targeted" and (
        not isinstance(plan.outline_version, int) or plan.outline_version < 1
    ):
        raise ResearchPlanningError("Targeted research requires a positive outline version")
    if not plan.queries:
        raise ResearchPlanningError("Research plan must contain at least one query")
    if len(plan.queries) > plan.limits.max_queries:
        raise ResearchPlanningError(
            f"Research plan has {len(plan.queries)} queries, max is {plan.limits.max_queries}"
        )
    expected_ids = [f"RQ-{index:03d}" for index in range(1, len(plan.queries) + 1)]
    if [query.query_id for query in plan.queries] != expected_ids:
        raise ResearchPlanningError("Research query IDs must be contiguous from RQ-001")
    for query in plan.queries:
        text = _normalize_text(query.query)
        if not text:
            raise ResearchPlanningError(f"Research query is blank: {query.query_id}")
        if len(text) > plan.limits.max_query_chars:
            raise ResearchPlanningError(
                f"Research query exceeds max_query_chars: {query.query_id}"
            )
        if query.cycle_id != plan.cycle_id or query.cycle_kind != plan.cycle_kind:
            raise ResearchPlanningError(f"Query cycle mismatch: {query.query_id}")
        if query.outline_version != plan.outline_version:
            raise ResearchPlanningError(f"Query outline version mismatch: {query.query_id}")
        if query.slide_id is not None and not _SLIDE_ID.fullmatch(query.slide_id):
            raise ResearchPlanningError(f"Invalid slide ID on {query.query_id}: {query.slide_id}")
        if len(set(query.preferred_source_tiers)) != len(query.preferred_source_tiers):
            raise ResearchPlanningError(f"Duplicate source tier on {query.query_id}")
        if any(tier not in _SOURCE_TIERS for tier in query.preferred_source_tiers):
            raise ResearchPlanningError(f"Unknown source tier on {query.query_id}")
    payload = _plan_payload(
        project_id=plan.project_id,
        cycle_id=plan.cycle_id,
        cycle_kind=plan.cycle_kind,
        outline_version=plan.outline_version,
        queries=plan.queries,
        limits=plan.limits,
    )
    if plan.plan_id != _plan_id(payload):
        raise ResearchPlanningError("Research plan identity does not match its content")


def _build_plan(
    *,
    project_id: str,
    cycle_id: str,
    cycle_kind: str,
    outline_version: int | None,
    candidates: Iterable[tuple[str, str, str | None]],
    freshness_requirement: str | None,
    preferred_source_tiers: tuple[str, ...],
    limits: ResearchLimits,
) -> ResearchPlan:
    unique: list[tuple[str, str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for raw_query, raw_purpose, slide_id in candidates:
        query = _normalize_text(raw_query)
        purpose = _normalize_text(raw_purpose)
        identity = (query.casefold(), slide_id)
        if query and identity not in seen:
            seen.add(identity)
            unique.append((query, purpose, slide_id))
    if not unique:
        raise ResearchPlanningError("No non-empty research query could be formed")
    if len(unique) > limits.max_queries:
        raise ResearchPlanningError(
            f"Research plan requires {len(unique)} queries, max_queries={limits.max_queries}"
        )
    queries = tuple(
        ResearchQuery(
            query_id=f"RQ-{index:03d}",
            query=query,
            cycle_id=cycle_id,
            cycle_kind=cycle_kind,
            outline_version=outline_version,
            freshness_requirement=_normalize_text(freshness_requirement) or None,
            preferred_source_tiers=preferred_source_tiers,
            purpose=purpose,
            slide_id=slide_id,
        )
        for index, (query, purpose, slide_id) in enumerate(unique, start=1)
    )
    payload = _plan_payload(
        project_id=project_id,
        cycle_id=cycle_id,
        cycle_kind=cycle_kind,
        outline_version=outline_version,
        queries=queries,
        limits=limits,
    )
    plan = ResearchPlan(
        plan_id=_plan_id(payload),
        project_id=project_id,
        cycle_id=cycle_id,
        cycle_kind=cycle_kind,
        outline_version=outline_version,
        queries=queries,
        limits=limits,
    )
    _validate_plan(plan)
    return plan


def plan_orientation_research(
    workspace: Path,
    *,
    cycle_id: str | None = None,
    limits: ResearchLimits | None = None,
) -> ResearchPlan:
    """Build a bounded orientation plan from the current Project Brief."""

    workspace = workspace.resolve()
    brief = read_json(workspace / "brief/project_brief.json")
    state = read_json(workspace / "project_state.json")
    if not brief.get("source_policy", {}).get("external_research"):
        raise ResearchPlanningError("Project Brief disables external research")
    admitted_limits = limits or ResearchLimits()
    _validate_limits(admitted_limits)
    title = _researchable_text(brief.get("title"))
    intent = brief.get("intent", {})
    purpose = _researchable_text(intent.get("purpose"))
    desired = _researchable_text(intent.get("desired_outcome"))
    candidates: list[tuple[str, str, str | None]] = []
    if purpose:
        candidates.append((f"{title} {purpose}", "Establish topic and problem context", None))
    if desired and desired != purpose:
        candidates.append((f"{title} {desired}", "Understand decision and outcome context", None))
    for audience in brief.get("audiences", []):
        role = _researchable_text(audience.get("role"))
        needs = tuple(
            value
            for value in _dedupe(audience.get("needs", []))
            if _researchable_text(value)
        )
        if role:
            candidates.append(
                (
                    f"{title} {role} {' '.join(needs[:2])}",
                    f"Understand evidence needs for audience role: {role}",
                    None,
                )
            )
    resolved_cycle_id = _resolve_cycle_id(workspace, "orientation", None, cycle_id)
    return _build_plan(
        project_id=str(state["project_id"]),
        cycle_id=resolved_cycle_id,
        cycle_kind="orientation",
        outline_version=None,
        candidates=candidates,
        freshness_requirement=brief.get("source_policy", {}).get("freshness_requirement"),
        preferred_source_tiers=_external_tiers(brief),
        limits=admitted_limits,
    )


def plan_targeted_research(
    workspace: Path,
    *,
    cycle_id: str | None = None,
    slide_ids: Iterable[str] | None = None,
    limits: ResearchLimits | None = None,
) -> ResearchPlan:
    """Build an outline-versioned, per-slide targeted research plan."""

    workspace = workspace.resolve()
    brief = read_json(workspace / "brief/project_brief.json")
    state = read_json(workspace / "project_state.json")
    if not brief.get("source_policy", {}).get("external_research"):
        raise ResearchPlanningError("Project Brief disables external research")
    outline_entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == "deck_outline"
        ),
        None,
    )
    if outline_entry is None:
        raise ResearchPlanningError("Targeted research requires a registered deck_outline")
    outline_version = int(outline_entry["version"])
    outline = read_json(workspace / str(outline_entry["path"]))
    requested = set(slide_ids or ())
    if requested and any(not _SLIDE_ID.fullmatch(slide_id) for slide_id in requested):
        raise ResearchPlanningError("Targeted research received an invalid slide ID")
    candidates: list[tuple[str, str, str | None]] = []
    found: set[str] = set()
    for slide in outline.get("slides", []):
        slide_id = str(slide.get("slide_id", ""))
        if slide.get("status") == "excluded":
            continue
        if requested and slide_id not in requested:
            continue
        found.add(slide_id)
        if slide.get("slide_type") in _NON_FACTUAL_SLIDE_TYPES:
            continue
        headline = _researchable_text(slide.get("headline"))
        takeaway = _researchable_text(slide.get("takeaway"))
        purpose = _researchable_text(slide.get("purpose"))
        query = _normalize_text(f"{headline} {takeaway}")
        if query:
            candidates.append((query, purpose or f"Fill evidence needs for {slide_id}", slide_id))
    missing = requested - found
    if missing:
        raise ResearchPlanningError(
            "Targeted research references unknown active slides: " + ", ".join(sorted(missing))
        )
    admitted_limits = limits or ResearchLimits()
    resolved_cycle_id = _resolve_cycle_id(
        workspace,
        "targeted",
        outline_version,
        cycle_id,
    )
    return _build_plan(
        project_id=str(state["project_id"]),
        cycle_id=resolved_cycle_id,
        cycle_kind="targeted",
        outline_version=outline_version,
        candidates=candidates,
        freshness_requirement=brief.get("source_policy", {}).get("freshness_requirement"),
        preferred_source_tiers=_external_tiers(brief),
        limits=admitted_limits,
    )


def plan_explicit_targeted_research(
    workspace: Path,
    candidates: Iterable[tuple[str, str, str | None]],
    *,
    cycle_id: str | None = None,
    limits: ResearchLimits | None = None,
) -> ResearchPlan:
    """Build a targeted plan from schema-backed gap suggestions.

    Each candidate is ``(query, purpose, slide_id)``. This helper preserves the
    same cycle/outline/provider-neutral contracts as ordinary targeted planning;
    it does not execute research or create Evidence.
    """

    workspace = workspace.resolve()
    brief = read_json(workspace / "brief/project_brief.json")
    state = read_json(workspace / "project_state.json")
    if not brief.get("source_policy", {}).get("external_research"):
        raise ResearchPlanningError("Project Brief disables external research")
    outline_entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == "deck_outline"
        ),
        None,
    )
    if outline_entry is None:
        raise ResearchPlanningError("Targeted research requires a registered deck_outline")
    outline_version = int(outline_entry["version"])
    outline = read_json(workspace / str(outline_entry["path"]))
    active_slide_ids = {
        str(item["slide_id"])
        for item in outline.get("slides", [])
        if item.get("status") != "excluded"
    }
    candidate_list = list(candidates)
    unknown_slide_ids = {
        str(slide_id)
        for _query, _purpose, slide_id in candidate_list
        if slide_id is not None and str(slide_id) not in active_slide_ids
    }
    if unknown_slide_ids:
        raise ResearchPlanningError(
            "Explicit targeted research references unknown active slides: "
            + ", ".join(sorted(unknown_slide_ids))
        )
    admitted_limits = limits or ResearchLimits()
    resolved_cycle_id = _resolve_cycle_id(
        workspace,
        "targeted",
        outline_version,
        cycle_id,
    )
    return _build_plan(
        project_id=str(state["project_id"]),
        cycle_id=resolved_cycle_id,
        cycle_kind="targeted",
        outline_version=outline_version,
        candidates=candidate_list,
        freshness_requirement=brief.get("source_policy", {}).get("freshness_requirement"),
        preferred_source_tiers=_external_tiers(brief),
        limits=admitted_limits,
    )


def run_research(
    provider: ResearchProvider,
    queries: Sequence[ResearchQuery],
) -> Sequence[ResearchResult]:
    """Compatibility helper for a direct provider call without runtime persistence."""

    return provider.search(queries)


class OfflineResearchProvider:
    """Explicit no-network provider used to represent research-unavailable hosts."""

    name = "offline"
    version = "1.0.0"

    def search(self, queries: Sequence[ResearchQuery]) -> tuple[ResearchResult, ...]:
        del queries
        raise ResearchOfflineError("External research capability is unavailable in offline mode")


class _ProviderIdentity:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version

    def search(self, queries: Sequence[ResearchQuery]) -> tuple[ResearchResult, ...]:
        del queries
        raise AssertionError("provider identity proxy cannot execute research")


class _ResearchLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def __enter__(self) -> _ResearchLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                self._handle.write("\0")
                self._handle.flush()
            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._handle is not None:
            if fcntl is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            self._handle.close()


def _load_schema(schema_dir: Path, name: str) -> dict[str, Any]:
    path = schema_dir / name
    if not path.exists():
        raise ResearchRuntimeError(f"Missing research runtime schema: {path}")
    data = read_json(path)
    Draft202012Validator.check_schema(data)
    return data


def _schema_errors(data: dict[str, Any], schema: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(schema).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    )


def _query_payload(query: ResearchQuery) -> dict[str, Any]:
    payload = asdict(query)
    payload["preferred_source_tiers"] = list(query.preferred_source_tiers)
    return payload


def _result_limits_payload(limits: ResearchLimits) -> dict[str, int]:
    return {
        "max_results_per_query": limits.max_results_per_query,
        "max_title_chars": limits.max_title_chars,
        "max_summary_chars": limits.max_summary_chars,
        "max_metadata_bytes": limits.max_metadata_bytes,
        "cache_ttl_seconds": limits.cache_ttl_seconds,
    }


def _input_key(query: ResearchQuery, provider: ResearchProvider, limits: ResearchLimits) -> str:
    return sha256_json(
        {
            "query": _query_payload(query),
            "provider": {"name": provider.name, "version": provider.version},
            "result_limits": _result_limits_payload(limits),
        }
    )


def _run_id(plan: ResearchPlan, provider: ResearchProvider) -> str:
    return "RRN-" + sha256_json(
        {"plan_id": plan.plan_id, "provider": {"name": provider.name, "version": provider.version}}
    )[:16].upper()


def _result_id(input_key: str, result: ResearchResult) -> str:
    return "RSLT-" + sha256_json(
        {
            "input_key": input_key,
            "locator": _normalize_text(result.locator),
            "url": _normalize_text(result.url),
        }
    )[:16].upper()


def _validate_provider(provider: ResearchProvider) -> None:
    name = _normalize_text(getattr(provider, "name", ""))
    version = _normalize_text(getattr(provider, "version", ""))
    if not name or len(name) > 128:
        raise ResearchRuntimeError("Research provider must declare a bounded name")
    if not version or len(version) > 128:
        raise ResearchRuntimeError("Research provider must declare a bounded version")


class ResearchRuntime:
    """Crash-resumable, provider-neutral research executor with immutable query cache."""

    def __init__(
        self,
        workspace: Path,
        provider: ResearchProvider,
        *,
        schema_dir: Path | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        if not (self.workspace / "project_state.json").is_file():
            raise ResearchRuntimeError(f"Missing project_state.json: {self.workspace}")
        _validate_provider(provider)
        self.provider = provider
        self.provider_identity = _ProviderIdentity(
            _normalize_text(provider.name),
            _normalize_text(provider.version),
        )
        self.clock = clock or _now_utc
        self.schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
        self.run_schema = _load_schema(self.schema_dir, "research_run.schema.json")
        self.cache_schema = _load_schema(self.schema_dir, "research_cache_snapshot.schema.json")
        self.runtime_dir = self.workspace / ".slidethus/research"
        self.runs_dir = self.runtime_dir / "runs"
        self.cache_dir = self.workspace / ".slidethus/cache/research"
        self.lock_path = self.runtime_dir / "runtime.lock"
        self.project_id = str(read_json(self.workspace / "project_state.json")["project_id"])

    def _lock(self) -> _ResearchLock:
        return _ResearchLock(self.lock_path)

    def _run_path(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ResearchRuntimeError(f"Invalid research run ID: {run_id}")
        try:
            return ensure_within(self.workspace, self.runs_dir / f"{run_id}.json")
        except WorkspaceError as exc:
            raise ResearchRuntimeError(str(exc)) from exc

    def _validate_run(self, data: dict[str, Any]) -> tuple[str, ...]:
        errors = list(_schema_errors(data, self.run_schema))
        if errors:
            return tuple(errors)
        if data.get("project_id") != self.project_id:
            errors.append("run project_id mismatch")
        tasks = data.get("tasks", [])
        if [task.get("task_id") for task in tasks] != [
            f"RT-{index:03d}" for index in range(1, len(tasks) + 1)
        ]:
            errors.append("task IDs must be contiguous from RT-001")
        if [task.get("query_id") for task in tasks] != [
            f"RQ-{index:03d}" for index in range(1, len(tasks) + 1)
        ]:
            errors.append("query IDs must be contiguous from RQ-001")
        provider = data.get("provider", {})
        queries = tuple(
            ResearchQuery(
                query_id=str(task["query_id"]),
                query=str(task["query"]),
                cycle_id=str(data["cycle_id"]),
                cycle_kind=str(data["cycle_kind"]),
                outline_version=data.get("outline_version"),
                freshness_requirement=task.get("freshness_requirement"),
                preferred_source_tiers=tuple(task.get("preferred_source_tiers", [])),
                purpose=str(task.get("purpose", "")),
                slide_id=task.get("slide_id"),
            )
            for task in tasks
        )
        limits = ResearchLimits(**data["limits"])
        payload = _plan_payload(
            project_id=str(data["project_id"]),
            cycle_id=str(data["cycle_id"]),
            cycle_kind=str(data["cycle_kind"]),
            outline_version=data.get("outline_version"),
            queries=queries,
            limits=limits,
        )
        expected_plan_id = _plan_id(payload)
        if data.get("plan_id") != expected_plan_id:
            errors.append("run plan_id mismatch")
        if data.get("plan_hash") != f"sha256:{sha256_json(payload)}":
            errors.append("run plan hash mismatch")
        expected_run_id = "RRN-" + sha256_json(
            {"plan_id": expected_plan_id, "provider": provider}
        )[:16].upper()
        if data.get("run_id") != expected_run_id:
            errors.append("run identity mismatch")
        provider_proxy = _ProviderIdentity(str(provider.get("name", "")), str(provider.get("version", "")))
        for task, query in zip(tasks, queries, strict=True):
            if task.get("input_key") != _input_key(query, provider_proxy, limits):
                errors.append(f"task input key mismatch: {task.get('task_id')}")
            if task.get("status") == "complete":
                if not task.get("cache_snapshot_path") or not task.get("cache_snapshot_sha256"):
                    errors.append(f"complete task lacks cache snapshot: {task.get('task_id')}")
                if task.get("result_count") != len(task.get("result_ids", [])):
                    errors.append(f"task result count mismatch: {task.get('task_id')}")
        return tuple(errors)

    def _write_run(self, run: dict[str, Any]) -> None:
        errors = self._validate_run(run)
        if errors:
            raise ResearchRuntimeError("Invalid research run: " + "; ".join(errors))
        atomic_write_json(self._run_path(str(run["run_id"])), run)

    def _load_run_unlocked(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id)
        if not path.is_file():
            raise ResearchRuntimeError(f"Unknown research run: {run_id}")
        try:
            data = read_json(path)
        except Exception as exc:  # noqa: BLE001
            raise ResearchRuntimeError(f"Research run cannot be read: {run_id}: {exc}") from exc
        errors = self._validate_run(data)
        if errors:
            raise ResearchRuntimeError("Invalid research run: " + "; ".join(errors))
        self._validate_complete_cache_refs(data)
        if self._reconcile_invalidations(data):
            self._write_run(data)
        return data

    def load_run(self, run_id: str) -> dict[str, Any]:
        """Load and verify one persisted Research Run and all completed cache refs."""

        with self._lock():
            return copy.deepcopy(self._load_run_unlocked(run_id))

    def _new_run(self, plan: ResearchPlan) -> dict[str, Any]:
        _validate_plan(plan)
        if plan.project_id != self.project_id:
            raise ResearchPlanningError("Research plan project_id does not match workspace")
        now = _iso(self.clock())
        tasks = [
            {
                "task_id": f"RT-{index:03d}",
                "query_id": query.query_id,
                "query": query.query,
                "purpose": query.purpose,
                "slide_id": query.slide_id,
                "freshness_requirement": query.freshness_requirement,
                "preferred_source_tiers": list(query.preferred_source_tiers),
                "input_key": _input_key(query, self.provider_identity, plan.limits),
                "status": "pending",
                "attempts": 0,
                "cache_status": "not_checked",
                "cache_snapshot_path": None,
                "cache_snapshot_sha256": None,
                "result_count": 0,
                "result_ids": [],
                "error": None,
                "started_at": None,
                "completed_at": None,
                "invalidated_at": None,
            }
            for index, query in enumerate(plan.queries, start=1)
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": self.project_id,
            "plan_id": plan.plan_id,
            "run_id": _run_id(plan, self.provider_identity),
            "cycle_id": plan.cycle_id,
            "cycle_kind": plan.cycle_kind,
            "outline_version": plan.outline_version,
            "plan_hash": research_plan_hash(plan),
            "provider": {
                "name": self.provider_identity.name,
                "version": self.provider_identity.version,
            },
            "limits": asdict(plan.limits),
            "status": "planned",
            "created_at": now,
            "updated_at": now,
            "tasks": tasks,
        }

    def prepare(self, plan: ResearchPlan) -> dict[str, Any]:
        """Create or load the stable run for one plan/provider identity."""

        _validate_plan(plan)
        run_id = _run_id(plan, self.provider_identity)
        with self._lock():
            path = self._run_path(run_id)
            if path.exists():
                run = self._load_run_unlocked(run_id)
                if run.get("plan_hash") != research_plan_hash(plan):
                    raise ResearchRuntimeError("Existing run has different plan content")
                return copy.deepcopy(run)
            run = self._new_run(plan)
            self._write_run(run)
            return copy.deepcopy(run)

    def _invalidation_path(self, input_key: str) -> Path:
        return self.cache_dir / input_key / "invalidated.json"

    def _cache_generation(self, input_key: str) -> int:
        marker = self._invalidation_path(input_key)
        if not marker.exists():
            return 0
        try:
            data = read_json(marker)
        except Exception as exc:  # noqa: BLE001
            raise ResearchCacheError(f"Invalid research cache invalidation marker: {exc}") from exc
        if data.get("input_key") != input_key:
            raise ResearchCacheError("Research cache invalidation input_key mismatch")
        generation = data.get("generation")
        if not isinstance(generation, int) or generation < 1:
            raise ResearchCacheError("Research cache invalidation generation is invalid")
        _parse_time(str(data.get("invalidated_at", "")))
        if not _normalize_text(data.get("reason")):
            raise ResearchCacheError("Research cache invalidation reason is missing")
        return generation

    def _validate_cache_snapshot(
        self,
        path: Path,
        *,
        input_key: str,
        expected_generation: int | None = None,
    ) -> dict[str, Any]:
        try:
            data = read_json(path)
        except Exception as exc:  # noqa: BLE001
            raise ResearchCacheError(f"Research cache snapshot cannot be read: {path}: {exc}") from exc
        errors = _schema_errors(data, self.cache_schema)
        if errors:
            raise ResearchCacheError("Invalid research cache snapshot: " + "; ".join(errors))
        if data.get("project_id") != self.project_id:
            raise ResearchCacheError("Research cache project_id mismatch")
        if data.get("input_key") != input_key:
            raise ResearchCacheError("Research cache input_key mismatch")
        provider_data = {
            "name": self.provider_identity.name,
            "version": self.provider_identity.version,
        }
        if data.get("provider") != provider_data:
            raise ResearchCacheError("Research cache provider identity mismatch")
        query_data = data.get("query", {})
        cached_query = ResearchQuery(
            query_id=str(query_data.get("query_id", "")),
            query=str(query_data.get("query", "")),
            cycle_id=str(query_data.get("cycle_id", "")),
            cycle_kind=str(query_data.get("cycle_kind", "")),
            outline_version=query_data.get("outline_version"),
            freshness_requirement=query_data.get("freshness_requirement"),
            preferred_source_tiers=tuple(query_data.get("preferred_source_tiers", [])),
            purpose=str(query_data.get("purpose", "")),
            slide_id=query_data.get("slide_id"),
        )
        result_limits = data.get("result_limits", {})
        cache_limits = ResearchLimits(
            max_results_per_query=int(result_limits["max_results_per_query"]),
            max_title_chars=int(result_limits["max_title_chars"]),
            max_summary_chars=int(result_limits["max_summary_chars"]),
            max_metadata_bytes=int(result_limits["max_metadata_bytes"]),
            cache_ttl_seconds=int(result_limits["cache_ttl_seconds"]),
        )
        expected_input_key = _input_key(
            cached_query,
            self.provider_identity,
            cache_limits,
        )
        if expected_input_key != input_key:
            raise ResearchCacheError("Research cache input key does not match query/provider/limits")
        created_at = _parse_time(str(data["created_at"]))
        expected_expires = created_at + timedelta(seconds=cache_limits.cache_ttl_seconds)
        if _parse_time(str(data["expires_at"])) != expected_expires:
            raise ResearchCacheError("Research cache expiry does not match cache TTL")
        if expected_generation is not None and data.get("generation") != expected_generation:
            raise ResearchCacheError("Research cache generation mismatch")
        if path.name != f"{sha256_json(data)}.json":
            raise ResearchCacheError("Research cache content-addressed filename mismatch")
        result_ids: list[str] = []
        for item in data.get("results", []):
            result = ResearchResult(
                query_id=str(data["query"]["query_id"]),
                title=str(item["title"]),
                locator=str(item["locator"]),
                summary=str(item["summary"]),
                source_tier=str(item["source_tier"]),
                retrieved_at=str(item["retrieved_at"]),
                url=item.get("url"),
                published_at=item.get("published_at"),
                metadata=dict(item.get("metadata", {})),
            )
            _parse_time(result.retrieved_at)
            if result.url is not None:
                parsed_url = urlparse(str(result.url))
                if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                    raise ResearchCacheError(f"Unsafe URL in cached result: {item.get('result_id')}")
            if len(canonical_json_bytes(result.metadata)) > cache_limits.max_metadata_bytes:
                raise ResearchCacheError(f"Cached metadata exceeds limit: {item.get('result_id')}")
            expected_id = _result_id(input_key, result)
            if item.get("result_id") != expected_id:
                raise ResearchCacheError(f"Research result identity mismatch: {item.get('result_id')}")
            result_ids.append(expected_id)
        if len(result_ids) != len(set(result_ids)):
            raise ResearchCacheError("Duplicate research result identity in one query snapshot")
        if [item.get("ordinal") for item in data.get("results", [])] != list(
            range(1, len(data.get("results", [])) + 1)
        ):
            raise ResearchCacheError("Research result ordinals must be contiguous from 1")
        return data

    def _cache_candidates(self, input_key: str) -> list[Path]:
        directory = self.cache_dir / input_key
        if not directory.exists():
            return []
        return sorted(
            path
            for path in directory.glob("*.json")
            if path.is_file() and path.name != "invalidated.json"
        )

    def _lookup_cache(
        self,
        input_key: str,
        *,
        now: datetime,
    ) -> tuple[str, Path | None, dict[str, Any] | None]:
        generation = self._cache_generation(input_key)
        snapshots: list[tuple[datetime, Path, dict[str, Any]]] = []
        for path in self._cache_candidates(input_key):
            data = self._validate_cache_snapshot(path, input_key=input_key)
            if data.get("generation") == generation:
                snapshots.append((_parse_time(str(data["created_at"])), path, data))
        if not snapshots:
            return ("invalidated" if generation else "miss", None, None)
        snapshots.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        _created_at, path, data = snapshots[0]
        expires_at = data.get("expires_at")
        if expires_at is not None and now >= _parse_time(str(expires_at)):
            return "stale", path, data
        return "hit", path, data

    def _cache_snapshot_from_results(
        self,
        *,
        query: ResearchQuery,
        input_key: str,
        generation: int,
        results: tuple[ResearchResult, ...],
        limits: ResearchLimits,
        now: datetime,
    ) -> dict[str, Any]:
        normalized_results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in results:
            if result.query_id != query.query_id:
                raise ResearchRuntimeError(
                    f"Provider result query_id mismatch: {result.query_id} != {query.query_id}"
                )
            title = _normalize_text(result.title)
            locator = _normalize_text(result.locator)
            summary = _normalize_text(result.summary)
            if not title or len(title) > limits.max_title_chars:
                raise ResearchRuntimeError(f"Provider returned invalid title for {query.query_id}")
            if not locator or len(locator) > 4000:
                raise ResearchRuntimeError(f"Provider returned invalid locator for {query.query_id}")
            if not summary or len(summary) > limits.max_summary_chars:
                raise ResearchRuntimeError(f"Provider returned invalid summary for {query.query_id}")
            if result.source_tier not in _SOURCE_TIERS:
                raise ResearchRuntimeError(
                    f"Provider returned unknown source tier for {query.query_id}: {result.source_tier}"
                )
            _parse_time(result.retrieved_at)
            url = _normalize_text(result.url) or None
            if url is not None:
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ResearchRuntimeError(f"Provider returned unsafe URL for {query.query_id}")
            try:
                metadata = dict(result.metadata)
                metadata_bytes = canonical_json_bytes(metadata)
            except (TypeError, ValueError) as exc:
                raise ResearchRuntimeError(
                    f"Provider metadata is not JSON-serializable for {query.query_id}"
                ) from exc
            if len(metadata_bytes) > limits.max_metadata_bytes:
                raise ResearchRuntimeError(
                    f"Provider metadata exceeds max_metadata_bytes for {query.query_id}"
                )
            canonical_result = replace(
                result,
                title=title,
                locator=locator,
                summary=summary,
                url=url,
                metadata=metadata,
            )
            result_id = _result_id(input_key, canonical_result)
            if result_id in seen:
                continue
            seen.add(result_id)
            normalized_results.append(
                {
                    "result_id": result_id,
                    "ordinal": len(normalized_results) + 1,
                    "title": title,
                    "locator": locator,
                    "url": url,
                    "summary": summary,
                    "source_tier": canonical_result.source_tier,
                    "retrieved_at": canonical_result.retrieved_at,
                    "published_at": canonical_result.published_at,
                    "metadata": metadata,
                }
            )
        if len(normalized_results) > limits.max_results_per_query:
            raise ResearchRuntimeError(
                f"Provider returned {len(normalized_results)} results for {query.query_id}; "
                f"max_results_per_query={limits.max_results_per_query}"
            )
        created_at = _iso(now)
        expires_at = (
            _iso(now + timedelta(seconds=limits.cache_ttl_seconds))
            if limits.cache_ttl_seconds > 0
            else created_at
        )
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "project_id": self.project_id,
            "input_key": input_key,
            "query": _query_payload(query),
            "provider": {
                "name": self.provider_identity.name,
                "version": self.provider_identity.version,
            },
            "result_limits": _result_limits_payload(limits),
            "generation": generation,
            "created_at": created_at,
            "expires_at": expires_at,
            "results": normalized_results,
        }
        errors = _schema_errors(snapshot, self.cache_schema)
        if errors:
            raise ResearchRuntimeError("Provider produced invalid cache snapshot: " + "; ".join(errors))
        return snapshot

    def _publish_cache_snapshot(
        self,
        input_key: str,
        snapshot: dict[str, Any],
    ) -> tuple[Path, str]:
        digest = sha256_json(snapshot)
        relative = Path(".slidethus/cache/research") / input_key / f"{digest}.json"
        try:
            path = ensure_within(self.workspace, self.workspace / relative)
        except WorkspaceError as exc:
            raise ResearchCacheError(str(exc)) from exc
        created = atomic_create_json(path, snapshot)
        if not created:
            existing = self._validate_cache_snapshot(
                path,
                input_key=input_key,
                expected_generation=int(snapshot["generation"]),
            )
            if existing != snapshot:
                raise ResearchCacheError("Immutable research cache path contains different content")
        return path, sha256_file(path)

    @staticmethod
    def _apply_cache_to_task(
        task: dict[str, Any],
        *,
        workspace: Path,
        path: Path,
        file_hash: str,
        snapshot: dict[str, Any],
        cache_status: str,
    ) -> None:
        task["status"] = "complete"
        task["cache_status"] = cache_status
        task["cache_snapshot_path"] = path.relative_to(workspace).as_posix()
        task["cache_snapshot_sha256"] = file_hash
        task["result_count"] = len(snapshot.get("results", []))
        task["result_ids"] = [str(item["result_id"]) for item in snapshot.get("results", [])]
        task["error"] = None
        task["completed_at"] = str(snapshot["created_at"])
        task["invalidated_at"] = None

    def _validate_complete_cache_refs(self, run: dict[str, Any]) -> None:
        for task in run.get("tasks", []):
            if task.get("status") != "complete":
                continue
            raw_path = task.get("cache_snapshot_path")
            try:
                relative = Path(str(raw_path))
                if relative.is_absolute():
                    raise WorkspaceError("Absolute research cache path is not allowed")
                path = ensure_within(self.workspace, self.workspace / relative)
            except (OSError, ValueError, WorkspaceError) as exc:
                raise ResearchCacheError(str(exc)) from exc
            if not path.is_file():
                raise ResearchCacheError(f"Research cache snapshot is missing: {raw_path}")
            if sha256_file(path) != task.get("cache_snapshot_sha256"):
                raise ResearchCacheError(f"Research cache file hash mismatch: {task.get('task_id')}")
            data = self._validate_cache_snapshot(path, input_key=str(task["input_key"]))
            if len(data.get("results", [])) != task.get("result_count"):
                raise ResearchCacheError(f"Research cache result count mismatch: {task.get('task_id')}")
            ids = [str(item["result_id"]) for item in data.get("results", [])]
            if ids != task.get("result_ids"):
                raise ResearchCacheError(f"Research cache result IDs mismatch: {task.get('task_id')}")

    def _reconcile_invalidations(self, run: dict[str, Any]) -> bool:
        changed = False
        latest_invalidation: str | None = None
        for task in run.get("tasks", []):
            if task.get("status") != "complete" or not task.get("cache_snapshot_path"):
                continue
            path = ensure_within(
                self.workspace,
                self.workspace / str(task["cache_snapshot_path"]),
            )
            snapshot = self._validate_cache_snapshot(path, input_key=str(task["input_key"]))
            if int(snapshot.get("generation", 0)) == self._cache_generation(str(task["input_key"])):
                continue
            marker = read_json(self._invalidation_path(str(task["input_key"])))
            invalidated_at = str(marker["invalidated_at"])
            latest_invalidation = max(latest_invalidation or invalidated_at, invalidated_at)
            task["status"] = "invalidated"
            task["cache_status"] = "invalidated"
            task["cache_snapshot_path"] = None
            task["cache_snapshot_sha256"] = None
            task["result_count"] = 0
            task["result_ids"] = []
            task["error"] = None
            task["completed_at"] = None
            task["invalidated_at"] = invalidated_at
            changed = True
        if changed:
            run["status"] = "planned"
            run["updated_at"] = latest_invalidation or _iso(self.clock())
        return changed

    def _checkpoint_failure(
        self,
        run: dict[str, Any],
        task: dict[str, Any],
        error: Exception | str,
        *,
        persist_detail: bool = True,
    ) -> None:
        if persist_detail:
            message = str(error)[:4000]
        else:
            error_type = type(error).__name__ if isinstance(error, Exception) else "ProviderError"
            message = f"{error_type}: provider failure; sensitive details omitted"
        task["status"] = "failed"
        task["error"] = message
        task["cache_snapshot_path"] = None
        task["cache_snapshot_sha256"] = None
        task["result_count"] = 0
        task["result_ids"] = []
        task["completed_at"] = _iso(self.clock())
        run["status"] = (
            "partial"
            if any(item is not task and item.get("status") == "complete" for item in run["tasks"])
            else "failed"
        )
        run["updated_at"] = task["completed_at"]
        self._write_run(run)

    def execute(self, plan: ResearchPlan, *, refresh: bool = False) -> dict[str, Any]:
        """Execute/resume one plan sequentially and checkpoint each query task."""

        _validate_plan(plan)
        if plan.project_id != self.project_id:
            raise ResearchPlanningError("Research plan project_id does not match workspace")
        run_id = _run_id(plan, self.provider_identity)
        queries = {query.query_id: query for query in plan.queries}
        with self._lock():
            path = self._run_path(run_id)
            run = self._load_run_unlocked(run_id) if path.exists() else self._new_run(plan)
            if run.get("plan_hash") != research_plan_hash(plan):
                raise ResearchRuntimeError("Research run plan hash changed")
            if (
                not refresh
                and run.get("status") == "complete"
                and all(task.get("status") == "complete" for task in run.get("tasks", []))
            ):
                return copy.deepcopy(run)
            run["status"] = "running"
            run["updated_at"] = _iso(self.clock())
            self._write_run(run)

            for task in run["tasks"]:
                query = queries[str(task["query_id"])]
                if task.get("status") == "complete" and not refresh:
                    continue
                now = self.clock()
                if not refresh:
                    try:
                        cache_status, cache_path, cache_data = self._lookup_cache(
                            str(task["input_key"]), now=now
                        )
                    except ResearchCacheError as exc:
                        self._checkpoint_failure(run, task, exc)
                        raise
                    task["cache_status"] = cache_status
                    if cache_status == "hit" and cache_path is not None and cache_data is not None:
                        prospective_total = sum(
                            int(item.get("result_count", 0))
                            for item in run["tasks"]
                            if item is not task and item.get("status") == "complete"
                        ) + len(cache_data.get("results", []))
                        if prospective_total > plan.limits.max_total_results:
                            error = ResearchRuntimeError(
                                "Research run would exceed max_total_results from cache reuse"
                            )
                            self._checkpoint_failure(run, task, error)
                            raise error
                        self._apply_cache_to_task(
                            task,
                            workspace=self.workspace,
                            path=cache_path,
                            file_hash=sha256_file(cache_path),
                            snapshot=cache_data,
                            cache_status="hit",
                        )
                        run["updated_at"] = _iso(now)
                        self._write_run(run)
                        continue
                else:
                    task["cache_status"] = "miss"

                task["status"] = "running"
                task["attempts"] = int(task.get("attempts", 0)) + 1
                task["started_at"] = _iso(now)
                task["completed_at"] = None
                task["cache_snapshot_path"] = None
                task["cache_snapshot_sha256"] = None
                task["result_count"] = 0
                task["result_ids"] = []
                task["error"] = None
                run["updated_at"] = _iso(now)
                self._write_run(run)
                try:
                    provider_results = self.provider.search((query,))
                    raw_results = tuple(
                        islice(provider_results, plan.limits.max_results_per_query + 1)
                    )
                except ResearchOfflineError as exc:
                    task["status"] = "blocked"
                    task["error"] = str(exc)[:4000]
                    task["completed_at"] = _iso(self.clock())
                    run["status"] = "blocked"
                    run["updated_at"] = task["completed_at"]
                    self._write_run(run)
                    return copy.deepcopy(run)
                except Exception as exc:  # noqa: BLE001
                    self._checkpoint_failure(
                        run,
                        task,
                        exc,
                        persist_detail=False,
                    )
                    raise ResearchProviderError(
                        f"Research provider failed on {query.query_id}; run {run_id} is resumable"
                    ) from exc

                if len(raw_results) > plan.limits.max_results_per_query:
                    error = ResearchRuntimeError(
                        f"Provider returned more than max_results_per_query for {query.query_id}"
                    )
                    self._checkpoint_failure(run, task, error)
                    raise error

                try:
                    generation = self._cache_generation(str(task["input_key"]))
                    snapshot = self._cache_snapshot_from_results(
                        query=query,
                        input_key=str(task["input_key"]),
                        generation=generation,
                        results=raw_results,
                        limits=plan.limits,
                        now=self.clock(),
                    )
                    prospective_total = sum(
                        int(item.get("result_count", 0))
                        for item in run["tasks"]
                        if item is not task and item.get("status") == "complete"
                    ) + len(snapshot["results"])
                    if prospective_total > plan.limits.max_total_results:
                        raise ResearchRuntimeError("Research run exceeds max_total_results")
                    cache_path, cache_hash = self._publish_cache_snapshot(
                        str(task["input_key"]), snapshot
                    )
                except (ResearchRuntimeError, ResearchCacheError) as exc:
                    self._checkpoint_failure(run, task, exc)
                    raise
                self._apply_cache_to_task(
                    task,
                    workspace=self.workspace,
                    path=cache_path,
                    file_hash=cache_hash,
                    snapshot=snapshot,
                    cache_status="miss",
                )
                run["updated_at"] = _iso(self.clock())
                self._write_run(run)

            statuses = {str(task["status"]) for task in run["tasks"]}
            if statuses == {"complete"}:
                run["status"] = "complete"
            elif "blocked" in statuses:
                run["status"] = "blocked"
            elif "failed" in statuses and "complete" in statuses:
                run["status"] = "partial"
            elif "failed" in statuses:
                run["status"] = "failed"
            else:
                run["status"] = "partial"
            run["updated_at"] = _iso(self.clock())
            self._write_run(run)
            return copy.deepcopy(run)

    def invalidate(
        self,
        run_id: str,
        *,
        query_ids: Iterable[str] | None = None,
        reason: str,
    ) -> dict[str, Any]:
        """Invalidate selected cache generations without deleting historical snapshots."""

        reason = _normalize_text(reason)
        if not reason:
            raise ResearchRuntimeError("Research cache invalidation requires a reason")
        selected = set(query_ids or ())
        if selected and any(not _QUERY_ID.fullmatch(query_id) for query_id in selected):
            raise ResearchRuntimeError("Research cache invalidation received an invalid query ID")
        with self._lock():
            run = self._load_run_unlocked(run_id)
            known = {str(task["query_id"]) for task in run["tasks"]}
            missing = selected - known
            if missing:
                raise ResearchRuntimeError(
                    "Research cache invalidation references unknown queries: "
                    + ", ".join(sorted(missing))
                )
            targets = [
                task
                for task in run["tasks"]
                if not selected or str(task["query_id"]) in selected
            ]
            now = _iso(self.clock())
            for task in targets:
                input_key = str(task["input_key"])
                generation = self._cache_generation(input_key) + 1
                atomic_write_json(
                    self._invalidation_path(input_key),
                    {
                        "input_key": input_key,
                        "generation": generation,
                        "invalidated_at": now,
                        "reason": reason[:2000],
                    },
                )
                task["status"] = "invalidated"
                task["cache_status"] = "invalidated"
                task["cache_snapshot_path"] = None
                task["cache_snapshot_sha256"] = None
                task["result_count"] = 0
                task["result_ids"] = []
                task["error"] = None
                task["completed_at"] = None
                task["invalidated_at"] = now
            run["status"] = "planned"
            run["updated_at"] = now
            self._write_run(run)
            return copy.deepcopy(run)

    def list_runs(self) -> tuple[dict[str, Any], ...]:
        """List verified research runs for this provider identity."""

        with self._lock():
            if not self.runs_dir.exists():
                return ()
            output = []
            for path in sorted(self.runs_dir.glob("RRN-*.json")):
                raw = read_json(path)
                if raw.get("provider") != {
                    "name": self.provider_identity.name,
                    "version": self.provider_identity.version,
                }:
                    continue
                data = self._load_run_unlocked(path.stem)
                output.append(_run_summary(data))
            return tuple(output)


def _run_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": data["run_id"],
        "plan_id": data["plan_id"],
        "cycle_id": data["cycle_id"],
        "cycle_kind": data["cycle_kind"],
        "outline_version": data["outline_version"],
        "provider": data["provider"],
        "status": data["status"],
        "task_count": len(data["tasks"]),
        "updated_at": data["updated_at"],
    }


def inspect_research_run(workspace: Path, run_id: str) -> dict[str, Any]:
    """Verify a persisted run using the provider identity recorded in that run."""

    workspace = workspace.resolve()
    if not _RUN_ID.fullmatch(run_id):
        raise ResearchRuntimeError(f"Invalid research run ID: {run_id}")
    path = ensure_within(
        workspace,
        workspace / ".slidethus/research/runs" / f"{run_id}.json",
    )
    if not path.is_file():
        raise ResearchRuntimeError(f"Unknown research run: {run_id}")
    raw = read_json(path)
    provider = raw.get("provider", {})
    proxy = _ProviderIdentity(
        _normalize_text(provider.get("name")),
        _normalize_text(provider.get("version")),
    )
    return ResearchRuntime(workspace, proxy).load_run(run_id)


def list_research_runs(workspace: Path) -> tuple[dict[str, Any], ...]:
    """List all verified runs regardless of provider identity."""

    workspace = workspace.resolve()
    runs_dir = workspace / ".slidethus/research/runs"
    if not runs_dir.exists():
        return ()
    output = []
    for path in sorted(runs_dir.glob("RRN-*.json")):
        data = inspect_research_run(workspace, path.stem)
        output.append(_run_summary(data))
    return tuple(output)


def invalidate_research_run(
    workspace: Path,
    run_id: str,
    *,
    query_ids: Iterable[str] | None = None,
    reason: str,
) -> dict[str, Any]:
    """Invalidate a persisted run without requiring the original provider object."""

    data = inspect_research_run(workspace, run_id)
    provider = data["provider"]
    proxy = _ProviderIdentity(str(provider["name"]), str(provider["version"]))
    return ResearchRuntime(workspace, proxy).invalidate(
        run_id,
        query_ids=query_ids,
        reason=reason,
    )


def research_workspace_errors(workspace: Path) -> tuple[tuple[str, str], ...]:
    """Validate all persisted research runs, cache history, and invalidation markers."""

    workspace = workspace.resolve()
    errors: list[tuple[str, str]] = []
    runs_dir = workspace / ".slidethus/research/runs"
    if runs_dir.exists():
        for path in sorted(runs_dir.glob("*.json")):
            relative = path.relative_to(workspace).as_posix()
            if not _RUN_ID.fullmatch(path.stem):
                errors.append((relative, "unexpected research run filename"))
                continue
            try:
                raw = read_json(path)
                provider = raw.get("provider", {})
                proxy = _ProviderIdentity(
                    _normalize_text(provider.get("name")),
                    _normalize_text(provider.get("version")),
                )
                runtime = ResearchRuntime(workspace, proxy)
                run_errors = runtime._validate_run(raw)
                if run_errors:
                    raise ResearchRuntimeError("Invalid research run: " + "; ".join(run_errors))
                runtime._validate_complete_cache_refs(raw)
            except Exception as exc:  # noqa: BLE001
                errors.append((relative, str(exc)))

    cache_root = workspace / ".slidethus/cache/research"
    if not cache_root.exists():
        return tuple(errors)
    for directory in sorted(path for path in cache_root.iterdir() if path.is_dir()):
        input_key = directory.name
        if not re.fullmatch(r"[a-f0-9]{64}", input_key):
            errors.append((directory.relative_to(workspace).as_posix(), "invalid cache input-key directory"))
            continue
        marker = directory / "invalidated.json"
        if marker.exists():
            try:
                marker_data = read_json(marker)
                if marker_data.get("input_key") != input_key:
                    raise ResearchCacheError("invalidation marker input_key mismatch")
                generation = marker_data.get("generation")
                if not isinstance(generation, int) or generation < 1:
                    raise ResearchCacheError("invalidation marker generation is invalid")
                _parse_time(str(marker_data.get("invalidated_at", "")))
                if not _normalize_text(marker_data.get("reason")):
                    raise ResearchCacheError("invalidation marker reason is missing")
            except Exception as exc:  # noqa: BLE001
                errors.append((marker.relative_to(workspace).as_posix(), str(exc)))
        for path in sorted(directory.glob("*.json")):
            if path.name == "invalidated.json":
                continue
            relative = path.relative_to(workspace).as_posix()
            try:
                raw = read_json(path)
                provider = raw.get("provider", {})
                proxy = _ProviderIdentity(
                    _normalize_text(provider.get("name")),
                    _normalize_text(provider.get("version")),
                )
                runtime = ResearchRuntime(workspace, proxy)
                runtime._validate_cache_snapshot(path, input_key=input_key)
            except Exception as exc:  # noqa: BLE001
                errors.append((relative, str(exc)))
    return tuple(errors)
