"""Durable Host Create task identity and per-invocation operational facts."""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

from slidethus.errors import HostCreateConflictError, HostCreateRecordError
from slidethus.io_utils import (
    atomic_create_json,
    atomic_write_json,
    ensure_within,
    read_json,
    sha256_file,
    sha256_json,
)
from slidethus.protocols import BriefCompletionHints, PlanningLimits
from slidethus.schema_registry import SchemaRegistry

if TYPE_CHECKING:
    from slidethus.services.m2_application import M2ApplicationLimits

SESSION_PATH = Path(".slidethus/host-create/session.json")
OPERATIONS_ROOT = Path(".slidethus/host-create/operations")
TERMINAL_STATUSES = {
    "host_input_required",
    "rework_required",
    "blocked",
    "failed",
    "design_ready",
    "candidate_office_review_pending",
    "render_failed",
    "render_timed_out",
    "calibration_office_evidence_pending",
    "calibration_review_pending",
    "calibration_rework",
    "calibration_approved",
    "full_office_evidence_pending",
    "whole_deck_review_pending",
    "whole_deck_rework",
    "whole_deck_approved",
}


@dataclass(frozen=True)
class HostCreateOperationContext:
    """In-memory timer and identity for one already-persisted started event."""

    workspace: Path
    session_id: str
    attempt_id: str
    action: str
    started_at: str
    started_monotonic_ns: int | None
    config_hash: str
    invocation_hash: str
    state_before: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _operation_duration_ms(
    context: HostCreateOperationContext,
    finished_at: str,
) -> int:
    """Measure live operations monotonically and recovered operations from durable timestamps."""

    if context.started_monotonic_ns is not None:
        return max(
            0,
            int((time.monotonic_ns() - context.started_monotonic_ns) / 1_000_000),
        )
    started = datetime.fromisoformat(context.started_at.replace("Z", "+00:00"))
    finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    return max(0, int((finished - started).total_seconds() * 1000))


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _schema(schema_dir: Path, name: str) -> dict[str, Any]:
    path = schema_dir / name
    if not path.is_file():
        raise HostCreateRecordError(f"Missing Host Create schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def _schema_errors(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    return [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(schema).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]


def _session_id(project_id: str, created_at: str) -> str:
    return "HCS-" + sha256_json({"project_id": project_id, "created_at": created_at})[
        :16
    ].upper()


def _config_hash_payload(config: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(config)
    payload.pop("config_hash", None)
    return payload


def validate_host_create_session_data(
    data: dict[str, Any], schema_dir: Path
) -> tuple[str, ...]:
    """Validate one session independently of current external Source availability."""

    errors = _schema_errors(
        data,
        _schema(schema_dir, "host_create_session.schema.json"),
    )
    if errors:
        return tuple(errors)
    if data.get("session_id") != _session_id(
        str(data.get("project_id", "")), str(data.get("created_at", ""))
    ):
        errors.append("Host Create session identity mismatch")
    config = dict(data.get("config", {}))
    if config.get("config_hash") != "sha256:" + sha256_json(
        _config_hash_payload(config)
    ):
        errors.append("Host Create session config hash mismatch")
    sources = list(config.get("sources", []))
    paths = [str(item.get("path", "")) for item in sources]
    if paths != sorted(paths):
        errors.append("Host Create Source fingerprints must be sorted by path")
    if len(paths) != len(set(paths)):
        errors.append("Host Create session contains duplicate Source paths")
    try:
        created = datetime.fromisoformat(str(data["created_at"]).replace("Z", "+00:00"))
        updated = datetime.fromisoformat(str(data["updated_at"]).replace("Z", "+00:00"))
    except ValueError:
        errors.append("Host Create session timestamps are invalid")
    else:
        if updated < created:
            errors.append("Host Create session updated_at precedes created_at")
    if data.get("schema_version") == "0.2.0":
        calibration = data.get("calibration", {})
        state = calibration.get("state")
        if state == "idle" and any(
            calibration.get(field) is not None
            for field in (
                "sample_receipt",
                "authorization",
                "full_receipt",
                "whole_deck_decision",
            )
        ):
            errors.append("Idle Host Create calibration contains stale authority")
        if state in {
            "sample_rendered",
            "sample_office_available",
            "approved",
            "rework",
            "full_rendered",
            "full_office_available",
            "whole_deck_approved",
            "whole_deck_rework",
        } and calibration.get("sample_receipt") is None:
            errors.append("Host Create calibration state lacks sample receipt")
        if state in {
            "approved",
            "full_rendered",
            "full_office_available",
            "whole_deck_approved",
            "whole_deck_rework",
        } and calibration.get("authorization") is None:
            errors.append("Host Create calibrated state lacks authorization")
        if state in {
            "full_rendered",
            "full_office_available",
            "whole_deck_approved",
            "whole_deck_rework",
        } and calibration.get("full_receipt") is None:
            errors.append("Host Create full-deck state lacks full receipt")
        if state in {"whole_deck_approved", "whole_deck_rework"} and calibration.get(
            "whole_deck_decision"
        ) is None:
            errors.append("Host Create whole-deck state lacks decision")
    return tuple(errors)


def validate_host_create_operation_data(
    data: dict[str, Any], schema_dir: Path
) -> tuple[str, ...]:
    """Validate one started or terminal Host Create operation event."""

    errors = _schema_errors(
        data,
        _schema(schema_dir, "host_create_operation.schema.json"),
    )
    if errors:
        return tuple(errors)
    if data.get("event_kind") == "started" and data.get("occurred_at") != data.get(
        "started_at"
    ):
        errors.append("Host Create started event occurred_at must equal started_at")
    if data.get("event_kind") == "terminal":
        if data.get("status") not in TERMINAL_STATUSES:
            errors.append("Host Create terminal status is unknown")
        try:
            started = datetime.fromisoformat(
                str(data["started_at"]).replace("Z", "+00:00")
            )
            finished = datetime.fromisoformat(
                str(data["finished_at"]).replace("Z", "+00:00")
            )
        except ValueError:
            errors.append("Host Create operation timestamps are invalid")
        else:
            if finished < started:
                errors.append("Host Create terminal precedes its started event")
    return tuple(errors)


def provider_identity(provider: Any, *, include_mode: bool = False) -> dict[str, str] | None:
    """Return a bounded provider identity suitable for durable session config."""

    if provider is None:
        return None
    fields = ("name", "version", "mode") if include_mode else ("name", "version")
    identity = {field: str(getattr(provider, field, "")).strip() for field in fields}
    if any(not value or len(value) > 128 for value in identity.values()):
        raise HostCreateRecordError(
            "Host Create providers must declare bounded name/version"
            + ("/mode" if include_mode else "")
        )
    return identity


def visual_reviewer_identity(provider: Any) -> dict[str, Any]:
    if provider is None:
        return {
            "name": "unconfigured-visual-reviewer",
            "version": "0",
            "capabilities": ["unavailable"],
        }
    identity = provider_identity(provider)
    if identity is None:
        raise HostCreateRecordError("Host Create requires a visual review provider")
    capabilities = sorted(
        set(str(item) for item in getattr(provider, "capabilities", ()))
    )
    required = {"native_prototype", "semantic_preview", "office_pages", "whole_deck"}
    if not required.issubset(capabilities):
        raise HostCreateRecordError(
            "Host Create visual reviewer lacks required capabilities: "
            + ", ".join(sorted(required - set(capabilities)))
        )
    return {**identity, "capabilities": capabilities}


def fingerprint_sources(source_paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    """Fingerprint an explicit complete Source set before workspace mutation."""

    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for raw in source_paths:
        path = raw.expanduser().resolve()
        if path in seen:
            raise HostCreateConflictError(f"Duplicate Host Create Source path: {path}")
        seen.add(path)
        if not path.is_file():
            raise HostCreateConflictError(f"Host Create Source is not a readable file: {path}")
        rows.append(
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    rows.sort(key=lambda item: str(item["path"]))
    return rows


def build_host_create_config(
    *,
    title: str,
    source_fingerprints: list[dict[str, Any]],
    brief_hints: BriefCompletionHints,
    planning_limits: PlanningLimits,
    m2_limits: M2ApplicationLimits,
    allow_research_degraded: bool,
    approve_external_disclosure: bool,
    allow_high_risk_source_evidence: bool,
    planning_provider: Any,
    research_provider: Any,
    art_direction_provider: Any,
    visual_review_provider: Any = None,
) -> dict[str, Any]:
    """Build the complete canonical intent/config payload for one Create session."""

    normalized_title = " ".join(str(title).split()).strip()
    if not normalized_title or len(normalized_title) > 500:
        raise HostCreateRecordError("Host Create title must contain 1..500 characters")
    config: dict[str, Any] = {
        "config_hash": "",
        "title": normalized_title,
        "sources": copy.deepcopy(source_fingerprints),
        "brief_hints": _json_value(brief_hints),
        "planning_limits": _json_value(planning_limits),
        "m2_limits": _json_value(m2_limits),
        "allow_research_degraded": bool(allow_research_degraded),
        "approve_external_disclosure": bool(approve_external_disclosure),
        "allow_high_risk_source_evidence": bool(allow_high_risk_source_evidence),
        "planning_provider": provider_identity(planning_provider),
        "research_provider": provider_identity(research_provider),
        "art_direction_provider": provider_identity(
            art_direction_provider, include_mode=True
        ),
        "visual_review_provider": visual_reviewer_identity(visual_review_provider),
    }
    config["config_hash"] = "sha256:" + sha256_json(_config_hash_payload(config))
    return config


def session_path(workspace: Path) -> Path:
    return workspace.resolve() / SESSION_PATH


def load_host_create_session(
    workspace: Path, *, schema_dir: Path | None = None
) -> dict[str, Any] | None:
    """Load and validate the current Host Create session, if one exists."""

    path = session_path(workspace)
    if not path.is_file():
        return None
    data = read_json(path)
    if data.get("schema_version") == "0.1.0":
        raise HostCreateRecordError(
            "Host Create Session 0.1 cannot resume the quality-by-construction workflow; "
            "start a new workspace or perform an explicit session migration"
        )
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = validate_host_create_session_data(data, admitted)
    if errors:
        raise HostCreateRecordError("Invalid Host Create session: " + "; ".join(errors))
    state = read_json(workspace.resolve() / "project_state.json")
    if data.get("project_id") != state.get("project_id"):
        raise HostCreateRecordError("Host Create session project_id mismatch")
    return data


def create_host_create_session(
    workspace: Path,
    config: dict[str, Any],
    *,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    """Create the one canonical session for a workspace without overwriting history."""

    workspace = workspace.resolve()
    state = read_json(workspace / "project_state.json")
    now = _utc_now()
    session = {
        "schema_version": "0.2.0",
        "project_id": str(state["project_id"]),
        "session_id": _session_id(str(state["project_id"]), now),
        "session_revision": 1,
        "intent_revision": 1,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "config": copy.deepcopy(config),
        "pending_revision": None,
        "pending_request": None,
        "prepared_art_direction_seed": None,
        "m2_reports": {"orientation": None, "targeted": None},
        "last_planning_report": None,
        "last_terminal": None,
        "calibration": {
            "state": "idle",
            "sample_receipt": None,
            "authorization": None,
            "full_receipt": None,
            "whole_deck_decision": None,
        },
    }
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = validate_host_create_session_data(session, admitted)
    if errors:
        raise HostCreateRecordError("Invalid new Host Create session: " + "; ".join(errors))
    path = session_path(workspace)
    created = atomic_create_json(path, session)
    if not created:
        existing = load_host_create_session(workspace, schema_dir=admitted)
        if existing != session:
            raise HostCreateRecordError(
                "Host Create session already exists; resume or use an explicit revision"
            )
    return session


def save_host_create_session(
    workspace: Path,
    session: dict[str, Any],
    *,
    expected_revision: int,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    """Replace the mutable session using a caller-held workspace lease."""

    workspace = workspace.resolve()
    current = load_host_create_session(workspace, schema_dir=schema_dir)
    if current is None:
        raise HostCreateRecordError("Host Create session is missing")
    if int(current["session_revision"]) != int(expected_revision):
        raise HostCreateConflictError(
            "Host Create session changed concurrently; reload before continuing"
        )
    candidate = copy.deepcopy(session)
    if candidate.get("session_id") != current.get("session_id"):
        raise HostCreateRecordError("Host Create session identity cannot change")
    if candidate.get("created_at") != current.get("created_at"):
        raise HostCreateRecordError("Host Create session created_at cannot change")
    candidate["session_revision"] = expected_revision + 1
    candidate["updated_at"] = _utc_now()
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = validate_host_create_session_data(candidate, admitted)
    if errors:
        raise HostCreateRecordError("Invalid Host Create session update: " + "; ".join(errors))
    atomic_write_json(session_path(workspace), candidate)
    return candidate


def _brief_hints_from_payload(payload: dict[str, Any]) -> BriefCompletionHints:
    values = copy.deepcopy(payload)
    for field in ("audience_needs", "audience_objections", "output_formats"):
        values[field] = tuple(values.get(field, ()))
    return BriefCompletionHints(**values)


def resolve_session_config(
    session: dict[str, Any] | None,
    *,
    title: str | None,
    sources: tuple[Path, ...] | None,
    brief_hints: BriefCompletionHints | None,
    planning_limits: PlanningLimits | None,
    m2_limits: M2ApplicationLimits | None,
    allow_research_degraded: bool | None,
    approve_external_disclosure: bool | None,
    allow_high_risk_source_evidence: bool | None,
    planning_provider: Any,
    research_provider: Any,
    art_direction_provider: Any,
    visual_review_provider: Any = None,
) -> dict[str, Any]:
    """Create initial config or validate explicit resume arguments against it."""

    if session is None:
        from slidethus.services.m2_application import M2ApplicationLimits

        return build_host_create_config(
            title=title or "Slidethus Create",
            source_fingerprints=fingerprint_sources(sources or ()),
            brief_hints=brief_hints or BriefCompletionHints(),
            planning_limits=planning_limits or PlanningLimits(),
            m2_limits=m2_limits or M2ApplicationLimits(),
            allow_research_degraded=bool(allow_research_degraded),
            approve_external_disclosure=bool(approve_external_disclosure),
            allow_high_risk_source_evidence=bool(allow_high_risk_source_evidence),
            planning_provider=planning_provider,
            research_provider=research_provider,
            art_direction_provider=art_direction_provider,
            visual_review_provider=visual_review_provider,
        )

    canonical = copy.deepcopy(session["config"])
    candidate = build_host_create_config(
        title=title if title is not None else str(canonical["title"]),
        source_fingerprints=(
            fingerprint_sources(sources)
            if sources is not None
            else copy.deepcopy(canonical["sources"])
        ),
        brief_hints=(
            brief_hints
            if brief_hints is not None
            else _brief_hints_from_payload(canonical["brief_hints"])
        ),
        planning_limits=(
            planning_limits
            if planning_limits is not None
            else PlanningLimits(**copy.deepcopy(canonical["planning_limits"]))
        ),
        m2_limits=(
            m2_limits
            if m2_limits is not None
            else _m2_limits_from_payload(canonical["m2_limits"])
        ),
        allow_research_degraded=(
            allow_research_degraded
            if allow_research_degraded is not None
            else bool(canonical["allow_research_degraded"])
        ),
        approve_external_disclosure=(
            approve_external_disclosure
            if approve_external_disclosure is not None
            else bool(canonical["approve_external_disclosure"])
        ),
        allow_high_risk_source_evidence=(
            allow_high_risk_source_evidence
            if allow_high_risk_source_evidence is not None
            else bool(canonical["allow_high_risk_source_evidence"])
        ),
        planning_provider=planning_provider,
        research_provider=research_provider,
        art_direction_provider=art_direction_provider,
        visual_review_provider=visual_review_provider,
    )
    if candidate != canonical:
        fields = [
            key
            for key in sorted(candidate)
            if candidate.get(key) != canonical.get(key)
        ]
        raise HostCreateConflictError(
            "Host Create invocation conflicts with the persisted session in: "
            + ", ".join(fields)
            + ". Resume with omitted inputs or use an explicit Brief/Source revision."
        )
    verify_session_sources(canonical)
    return canonical


def _m2_limits_from_payload(payload: dict[str, Any]) -> M2ApplicationLimits:
    from slidethus.protocols import ResearchLimits, SourceParseLimits
    from slidethus.services.m2_application import M2ApplicationLimits

    return M2ApplicationLimits(
        max_sources=int(payload["max_sources"]),
        max_total_source_bytes=int(payload["max_total_source_bytes"]),
        source=SourceParseLimits(**copy.deepcopy(payload["source"])),
        research=ResearchLimits(**copy.deepcopy(payload["research"])),
    )


def config_brief_hints(config: dict[str, Any]) -> BriefCompletionHints:
    return _brief_hints_from_payload(config["brief_hints"])


def config_planning_limits(config: dict[str, Any]) -> PlanningLimits:
    return PlanningLimits(**copy.deepcopy(config["planning_limits"]))


def config_m2_limits(config: dict[str, Any]) -> M2ApplicationLimits:
    return _m2_limits_from_payload(config["m2_limits"])


def config_source_paths(config: dict[str, Any]) -> tuple[Path, ...]:
    return tuple(Path(str(item["path"])) for item in config["sources"])


def verify_session_sources(config: dict[str, Any]) -> None:
    """Reject missing or changed canonical Sources before artifact mutation."""

    failures: list[str] = []
    for row in config.get("sources", []):
        path = Path(str(row["path"]))
        if not path.is_file():
            failures.append(f"missing:{path}")
            continue
        if path.stat().st_size != int(row["size_bytes"]) or sha256_file(path) != row[
            "sha256"
        ]:
            failures.append(f"changed:{path}")
    if failures:
        raise HostCreateConflictError(
            "Persisted Host Create Sources changed outside an explicit Source revision: "
            + "; ".join(failures)
        )


def invocation_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + sha256_json(_json_value(payload))


def _state_ref(workspace: Path) -> dict[str, Any]:
    state = read_json(workspace.resolve() / "project_state.json")
    return {
        "revision": int(state["revision"]),
        "current_phase": str(state["current_phase"]),
        "status": str(state["status"]),
    }


def start_host_create_operation(
    workspace: Path,
    session: dict[str, Any],
    *,
    action: str,
    invocation_payload: dict[str, Any],
    schema_dir: Path | None = None,
) -> HostCreateOperationContext:
    """Persist the immutable started fact before running any production stage."""

    workspace = workspace.resolve()
    started_at = _utc_now()
    attempt_id = "HCO-" + uuid.uuid4().hex[:16].upper()
    state_before = _state_ref(workspace)
    digest = invocation_hash(invocation_payload)
    event = {
        "schema_version": "0.2.0",
        "project_id": str(session["project_id"]),
        "session_id": str(session["session_id"]),
        "attempt_id": attempt_id,
        "event_kind": "started",
        "status": "started",
        "action": action,
        "occurred_at": started_at,
        "started_at": started_at,
        "finished_at": None,
        "duration_ms": None,
        "config_hash": str(session["config"]["config_hash"]),
        "resulting_config_hash": None,
        "invocation_hash": digest,
        "state_before": state_before,
        "state_after": None,
        "pending_request": None,
        "result": None,
    }
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = validate_host_create_operation_data(event, admitted)
    if errors:
        raise HostCreateRecordError("Invalid Host Create started event: " + "; ".join(errors))
    path = workspace / OPERATIONS_ROOT / attempt_id / "started.json"
    if not atomic_create_json(path, event):
        raise HostCreateRecordError(f"Host Create attempt already exists: {attempt_id}")
    return HostCreateOperationContext(
        workspace=workspace,
        session_id=str(session["session_id"]),
        attempt_id=attempt_id,
        action=action,
        started_at=started_at,
        started_monotonic_ns=time.monotonic_ns(),
        config_hash=str(session["config"]["config_hash"]),
        invocation_hash=digest,
        state_before=state_before,
    )


def normalize_pending_request(
    workspace: Path, pending: dict[str, Any] | None
) -> dict[str, Any] | None:
    if pending is None:
        return None
    workspace = workspace.resolve()
    normalized = copy.deepcopy(pending)
    for field in ("request_path", "response_path"):
        raw = Path(str(normalized[field]))
        absolute = raw if raw.is_absolute() else workspace / raw
        safe = ensure_within(workspace, absolute)
        normalized[field] = safe.relative_to(workspace).as_posix()
    return normalized


def pending_request_for_output(
    workspace: Path, pending: dict[str, Any] | None
) -> dict[str, Any] | None:
    if pending is None:
        return None
    row = copy.deepcopy(pending)
    for field in ("request_path", "response_path"):
        row[field] = str(workspace.resolve() / str(row[field]))
    return row


def make_file_ref(workspace: Path, path: Path, *, kind: str) -> dict[str, str]:
    workspace = workspace.resolve()
    absolute = path.resolve()
    safe = ensure_within(workspace, absolute)
    if not safe.is_file():
        raise HostCreateRecordError(f"Host Create result reference is missing: {safe}")
    return {
        "kind": kind,
        "path": safe.relative_to(workspace).as_posix(),
        "sha256": sha256_file(safe),
    }


def finish_host_create_operation(
    context: HostCreateOperationContext,
    *,
    status: str,
    pending_request: dict[str, Any] | None,
    message: str,
    target_phase: str | None = None,
    issue_ids: tuple[str, ...] = (),
    allowed_next_actions: tuple[str, ...] = ("resume",),
    refs: tuple[dict[str, str], ...] = (),
    resulting_config_hash: str | None = None,
    schema_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Persist the one immutable terminal fact for an invocation."""

    if status not in TERMINAL_STATUSES:
        raise HostCreateRecordError(f"Unknown Host Create terminal status: {status}")
    finished_at = _utc_now()
    event = {
        "schema_version": "0.2.0",
        "project_id": str(read_json(context.workspace / "project_state.json")["project_id"]),
        "session_id": context.session_id,
        "attempt_id": context.attempt_id,
        "event_kind": "terminal",
        "status": status,
        "action": context.action,
        "occurred_at": finished_at,
        "started_at": context.started_at,
        "finished_at": finished_at,
        "duration_ms": _operation_duration_ms(context, finished_at),
        "config_hash": context.config_hash,
        "resulting_config_hash": resulting_config_hash or context.config_hash,
        "invocation_hash": context.invocation_hash,
        "state_before": context.state_before,
        "state_after": _state_ref(context.workspace),
        "pending_request": normalize_pending_request(
            context.workspace, pending_request
        ),
        "result": {
            "message": " ".join(str(message).split()).strip()[:4000]
            or "Host Create invocation ended.",
            "target_phase": target_phase,
            "issue_ids": sorted(set(str(item) for item in issue_ids)),
            "allowed_next_actions": list(dict.fromkeys(allowed_next_actions)),
            "refs": list(refs),
        },
    }
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = validate_host_create_operation_data(event, admitted)
    if errors:
        raise HostCreateRecordError("Invalid Host Create terminal event: " + "; ".join(errors))
    path = (
        context.workspace
        / OPERATIONS_ROOT
        / context.attempt_id
        / "terminal.json"
    )
    created = atomic_create_json(path, event)
    if not created and read_json(path) != event:
        raise HostCreateRecordError(
            f"Host Create attempt already has a different terminal event: {context.attempt_id}"
        )
    return path, event


def terminal_reference(workspace: Path, path: Path, event: dict[str, Any]) -> dict[str, str]:
    return {
        "attempt_id": str(event["attempt_id"]),
        "status": str(event["status"]),
        "path": path.resolve().relative_to(workspace.resolve()).as_posix(),
        "sha256": sha256_file(path),
    }


def recover_incomplete_host_create_operations(
    workspace: Path,
    session: dict[str, Any],
    *,
    schema_dir: Path | None = None,
) -> tuple[Path, ...]:
    """Close orphaned started facts after a later caller owns the workspace lease."""

    workspace = workspace.resolve()
    root = workspace / OPERATIONS_ROOT
    if not root.exists():
        return ()
    recovered: list[Path] = []
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    for attempt_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        started_path = attempt_dir / "started.json"
        terminal_path = attempt_dir / "terminal.json"
        if not started_path.is_file() or terminal_path.exists():
            continue
        started = read_json(started_path)
        errors = validate_host_create_operation_data(started, admitted)
        if errors:
            raise HostCreateRecordError(
                f"Cannot recover invalid Host Create start {started_path}: "
                + "; ".join(errors)
            )
        context = HostCreateOperationContext(
            workspace=workspace,
            session_id=str(started["session_id"]),
            attempt_id=str(started["attempt_id"]),
            action=str(started["action"]),
            started_at=str(started["started_at"]),
            started_monotonic_ns=None,
            config_hash=str(started["config_hash"]),
            invocation_hash=str(started["invocation_hash"]),
            state_before=copy.deepcopy(started["state_before"]),
        )
        path, _event = finish_host_create_operation(
            context,
            status="failed",
            pending_request=session.get("pending_request"),
            message="Recovered an interrupted Host Create invocation with no terminal fact.",
            allowed_next_actions=("resume", "inspect_report"),
            schema_dir=admitted,
        )
        recovered.append(path)
    return tuple(recovered)


def _safe_runtime_file(
    workspace: Path, raw_path: str, *, admitted_root: Path
) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute():
        raise HostCreateRecordError(f"Host Create runtime path must be relative: {relative}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / admitted_root)
    if path != root and root not in path.parents:
        raise HostCreateRecordError(
            f"Host Create runtime path is outside {admitted_root}: {relative}"
        )
    return path


def host_create_workspace_errors(
    workspace: Path, schema_dir: Path
) -> tuple[tuple[str, str], ...]:
    """Return structural/reference errors for durable Host Create runtime facts."""

    workspace = workspace.resolve()
    path = session_path(workspace)
    if not path.exists():
        return ()
    errors: list[tuple[str, str]] = []
    relative_session = path.relative_to(workspace).as_posix()
    try:
        session = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return ((relative_session, f"Host Create session cannot be read: {exc}"),)
    for message in validate_host_create_session_data(session, schema_dir):
        errors.append((relative_session, message))
    state = read_json(workspace / "project_state.json")
    if session.get("project_id") != state.get("project_id"):
        errors.append((relative_session, "Host Create session project_id mismatch"))

    pending = session.get("pending_request")
    if isinstance(pending, dict):
        for field, root in (
            ("request_path", Path(".slidethus/host-design/requests")),
            ("response_path", Path(".slidethus/host-design/responses")),
        ):
            try:
                target = _safe_runtime_file(
                    workspace, str(pending[field]), admitted_root=root
                )
            except Exception as exc:  # noqa: BLE001
                errors.append((relative_session, str(exc)))
                continue
            if field == "request_path" and not target.is_file():
                errors.append((relative_session, "Pending Host request file is missing"))

    for stage, ref in session.get("m2_reports", {}).items():
        if ref is None:
            continue
        try:
            target = _safe_runtime_file(
                workspace,
                str(ref["path"]),
                admitted_root=Path(".slidethus/m2/runs"),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append((relative_session, str(exc)))
            continue
        if not target.is_file() or sha256_file(target) != ref.get("sha256"):
            errors.append((relative_session, f"Host Create {stage} M2 report ref is invalid"))
        else:
            data = read_json(target)
            if data.get("report_id") != ref.get("report_id") or data.get(
                "status"
            ) != ref.get("status"):
                errors.append((relative_session, f"Host Create {stage} M2 report identity mismatch"))

    planning_ref = session.get("last_planning_report")
    if isinstance(planning_ref, dict):
        try:
            target = _safe_runtime_file(
                workspace,
                str(planning_ref["path"]),
                admitted_root=Path(".slidethus/m3/runs"),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append((relative_session, str(exc)))
        else:
            if not target.is_file() or sha256_file(target) != planning_ref.get("sha256"):
                errors.append((relative_session, "Host Create M3 report ref is invalid"))

    calibration = session.get("calibration", {})
    for field, root_path in (
        ("sample_receipt", Path("outputs/host-candidates")),
        ("full_receipt", Path("outputs/host-candidates")),
        ("whole_deck_decision", Path(".slidethus/visual-quality")),
    ):
        ref = calibration.get(field)
        if not isinstance(ref, dict):
            continue
        try:
            target = _safe_runtime_file(
                workspace, str(ref["path"]), admitted_root=root_path
            )
        except Exception as exc:  # noqa: BLE001
            errors.append((relative_session, str(exc)))
            continue
        if not target.is_file() or sha256_file(target) != ref.get("sha256"):
            errors.append(
                (relative_session, f"Host Create calibration {field} ref is invalid")
            )
    authorization = calibration.get("authorization")
    if isinstance(authorization, dict):
        for field in ("decision_path", "reference_set_path"):
            try:
                target = _safe_runtime_file(
                    workspace,
                    str(authorization[field]),
                    admitted_root=Path(".slidethus/visual-quality"),
                )
            except Exception as exc:  # noqa: BLE001
                errors.append((relative_session, str(exc)))
                continue
            if not target.is_file():
                errors.append(
                    (relative_session, f"Host Create calibration {field} is missing")
                )

    root = workspace / OPERATIONS_ROOT
    terminal_by_attempt: dict[str, tuple[Path, dict[str, Any]]] = {}
    if root.exists():
        for entry in sorted(root.iterdir()):
            relative = entry.relative_to(workspace).as_posix()
            if not entry.is_dir() or not entry.name.startswith("HCO-"):
                errors.append((relative, "Unexpected Host Create operations entry"))
                continue
            started_path = entry / "started.json"
            terminal_path = entry / "terminal.json"
            if not started_path.is_file():
                errors.append((relative, "Host Create attempt is missing started.json"))
                continue
            for candidate in (started_path, terminal_path):
                if not candidate.exists():
                    continue
                candidate_relative = candidate.relative_to(workspace).as_posix()
                try:
                    data = read_json(candidate)
                except Exception as exc:  # noqa: BLE001
                    errors.append((candidate_relative, f"Host Create event cannot be read: {exc}"))
                    continue
                for message in validate_host_create_operation_data(data, schema_dir):
                    errors.append((candidate_relative, message))
                if data.get("attempt_id") != entry.name:
                    errors.append((candidate_relative, "Host Create attempt directory mismatch"))
                if data.get("session_id") != session.get("session_id"):
                    errors.append((candidate_relative, "Host Create operation session mismatch"))
                if data.get("project_id") != session.get("project_id"):
                    errors.append((candidate_relative, "Host Create operation project mismatch"))
                if candidate == terminal_path:
                    terminal_by_attempt[str(data.get("attempt_id"))] = (candidate, data)
            if terminal_path.is_file():
                started = read_json(started_path)
                terminal = read_json(terminal_path)
                for field in (
                    "project_id",
                    "session_id",
                    "attempt_id",
                    "action",
                    "started_at",
                    "config_hash",
                    "invocation_hash",
                    "state_before",
                ):
                    if started.get(field) != terminal.get(field):
                        errors.append((relative, f"Host Create started/terminal mismatch: {field}"))
                for ref in terminal.get("result", {}).get("refs", []):
                    try:
                        target = _safe_runtime_file(
                            workspace, str(ref["path"]), admitted_root=Path(".")
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append((relative, str(exc)))
                        continue
                    if not target.is_file() or sha256_file(target) != ref.get("sha256"):
                        errors.append((relative, "Host Create terminal result ref is invalid"))

    last_terminal = session.get("last_terminal")
    if isinstance(last_terminal, dict):
        row = terminal_by_attempt.get(str(last_terminal["attempt_id"]))
        if row is None:
            errors.append((relative_session, "Host Create last terminal attempt is missing"))
        else:
            terminal_path, terminal = row
            if terminal.get("status") != last_terminal.get("status"):
                errors.append((relative_session, "Host Create last terminal status mismatch"))
            expected_path = terminal_path.relative_to(workspace).as_posix()
            if last_terminal.get("path") != expected_path or last_terminal.get(
                "sha256"
            ) != sha256_file(terminal_path):
                errors.append((relative_session, "Host Create last terminal ref mismatch"))
    return tuple(errors)
