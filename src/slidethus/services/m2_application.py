from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import (
    EvidenceBindingError,
    EvidenceError,
    M2ApplicationError,
    M2CapabilityError,
    ResearchError,
    SlidethusError,
    SourceCapabilityError,
    SourceIngestionError,
    UnsupportedSourceError,
)
from slidethus.gates import GateResult, evaluate_gate
from slidethus.ingestion import validate_source_parse_limits
from slidethus.io_utils import atomic_create_json, read_json, sha256_file, sha256_json
from slidethus.m2_application_reports import (
    m2_finding_id,
    m2_report_file_key,
    m2_report_id,
    m2_report_reference_errors,
    validate_m2_report_data,
)
from slidethus.protocols import (
    ResearchLimits,
    ResearchProvider,
    SourceParseLimits,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.evidence import EvidenceEngine
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.research import (
    ResearchRuntime,
    plan_orientation_research,
    plan_targeted_research,
    validate_research_limits,
)
from slidethus.services.source_ingestion import SourceIngestionService
from slidethus.state_machine import FORWARD_SEQUENCE, Phase, can_transition
from slidethus.validation import validate_workspace

_GATE_TARGETS = {
    "G0": Phase.BRIEF_READY,
    "G1": Phase.SOURCES_READY,
    "G2": Phase.EVIDENCE_READY,
    "G3": Phase.NARRATIVE_READY,
    "G4": Phase.OUTLINE_READY,
    "G5A": Phase.SLIDE_SPECS_READY,
}
_GATE_ACTION_STAGES = {
    "G0": "brief",
    "G1": "sources",
    "G2": "g2",
    "G3": "planning_revalidation",
    "G4": "planning_revalidation",
    "G5A": "g5a",
}


@dataclass(frozen=True)
class M2ApplicationLimits:
    """Bound application-level Source and Research expansion."""

    max_sources: int = 64
    max_total_source_bytes: int = 1024 * 1024 * 1024
    source: SourceParseLimits = field(default_factory=SourceParseLimits)
    research: ResearchLimits = field(default_factory=ResearchLimits)


@dataclass(frozen=True)
class M2ApplicationRunResult:
    """One persisted M2 application run report."""

    report: dict[str, Any]
    path: Path
    changed: bool


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()


def _phase_index(phase: Phase) -> int:
    return FORWARD_SEQUENCE.index(phase)


class M2ApplicationService:
    """Single application orchestrator for the completed M2 production services."""

    def __init__(
        self,
        workspace: Path,
        *,
        research_provider: ResearchProvider | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.research_provider = research_provider
        self.report_dir = self.workspace / ".slidethus/m2/runs"

    @staticmethod
    def _add_action(
        actions: list[dict[str, Any]],
        *,
        stage: str,
        status: str,
        detail: str,
        refs: tuple[str, ...] = (),
    ) -> None:
        actions.append(
            {
                "action_id": f"M2A-{len(actions) + 1:03d}",
                "stage": stage,
                "status": status,
                "detail": _normalized(detail)[:4000],
                "refs": sorted(set(str(item) for item in refs)),
            }
        )

    @staticmethod
    def _upsert_capability(
        capabilities: list[dict[str, str]],
        *,
        capability: str,
        status: str,
        detail: str,
    ) -> None:
        existing = next(
            (item for item in capabilities if item.get("capability") == capability),
            None,
        )
        payload = {
            "capability": capability,
            "status": status,
            "detail": _normalized(detail)[:4000],
        }
        if existing is None:
            capabilities.append(payload)
        else:
            existing.update(payload)

    @staticmethod
    def _add_finding(
        findings: list[dict[str, str]],
        *,
        kind: str,
        code: str,
        message: str,
    ) -> None:
        normalized = _normalized(message)[:4000]
        finding = {
            "finding_id": m2_finding_id(kind, code, normalized),
            "code": code,
            "message": normalized,
        }
        if finding["finding_id"] not in {item["finding_id"] for item in findings}:
            findings.append(finding)

    def _current_gate_summary(self, gate_id: str) -> dict[str, Any] | None:
        state = self.runtime.show_artifact("project_state")
        summary = next(
            (
                item
                for item in state.get("completed_gates", [])
                if item.get("gate_id") == gate_id
                and item.get("status") in {"pass", "waived"}
            ),
            None,
        )
        if summary is None:
            return None
        current_entries = {
            str(item["artifact_type"]): item for item in state.get("artifacts", [])
        }
        for reference in summary.get("artifact_versions", []):
            current = current_entries.get(str(reference.get("artifact_type")))
            if current is None:
                return None
            if (
                int(current.get("version", 0)) != int(reference.get("version", -1))
                or current.get("sha256") != reference.get("sha256")
            ):
                return None
        return summary

    def _ensure_gate(
        self,
        gate_id: str,
        *,
        actions: list[dict[str, Any]],
        blockers: list[dict[str, str]],
    ) -> bool:
        current_summary = self._current_gate_summary(gate_id)
        if current_summary is not None:
            self._add_action(
                actions,
                stage=_GATE_ACTION_STAGES[gate_id],
                status="complete",
                detail=f"{gate_id} is current and accepted.",
            )
            return True

        result = evaluate_gate(self.workspace, gate_id)
        if not result.passed:
            self._add_action(
                actions,
                stage=_GATE_ACTION_STAGES[gate_id],
                status="blocked",
                detail=f"{gate_id} did not pass: {'; '.join(result.reasons)}",
            )
            self._add_finding(
                blockers,
                kind="blocker",
                code=f"{gate_id.lower()}_not_ready",
                message=f"{gate_id} did not pass: {'; '.join(result.reasons)}",
            )
            return False

        target = _GATE_TARGETS[gate_id]
        state = self.runtime.show_artifact("project_state")
        current = Phase(state["current_phase"])
        target_phase: Phase | None = None
        if _phase_index(current) < _phase_index(target):
            if not can_transition(current, target):
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="gate_transition_not_admitted",
                    message=f"Cannot advance {gate_id}: {current.value} -> {target.value} is not admitted.",
                )
                return False
            target_phase = target
        self.runtime.record_gate(
            gate_id,
            approved_by="m2-application-service",
            target_phase=target_phase,
        )
        self._add_action(
            actions,
            stage=_GATE_ACTION_STAGES[gate_id],
            status="complete",
            detail=f"{gate_id} is current and accepted.",
        )
        return True

    def _preflight_sources(
        self,
        source_paths: tuple[Path, ...],
        limits: M2ApplicationLimits,
        blockers: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        unique_paths: list[Path] = []
        seen: set[Path] = set()
        for raw_path in source_paths:
            path = raw_path.expanduser().resolve()
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)
        unique_paths.sort(key=lambda item: str(item))
        if len(unique_paths) > limits.max_sources:
            self._add_finding(
                blockers,
                kind="blocker",
                code="source_count_limit_exceeded",
                message=(
                    f"Requested {len(unique_paths)} unique sources, exceeding "
                    f"max_sources={limits.max_sources}."
                ),
            )
            return []
        fingerprints: list[dict[str, Any]] = []
        total_bytes = 0
        for path in unique_paths:
            if not path.is_file():
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="source_path_unavailable",
                    message=f"Requested source is not a readable file: {path}",
                )
                continue
            size_bytes = path.stat().st_size
            total_bytes += size_bytes
            fingerprints.append(
                {
                    "path": str(path),
                    "size_bytes": size_bytes,
                    "sha256": sha256_file(path),
                }
            )
        if total_bytes > limits.max_total_source_bytes:
            self._add_finding(
                blockers,
                kind="blocker",
                code="source_total_bytes_exceeded",
                message=(
                    f"Requested sources total {total_bytes} bytes, exceeding "
                    f"max_total_source_bytes={limits.max_total_source_bytes}."
                ),
            )
        return fingerprints

    def _high_risk_source_counts(self) -> dict[str, int]:
        """Return high-severity risk counts for every current ingested Source."""

        ledger = self.runtime.show_artifact("source_ledger")
        service = SourceIngestionService(self.workspace)
        counts: dict[str, int] = {}
        for source in ledger.get("sources", []):
            source_id = str(source["source_id"])
            if not source.get("ingestion"):
                continue
            loaded = service.load(source_id)
            count = sum(
                1 for item in loaded.risks if item.get("severity") == "high"
            )
            if count:
                counts[source_id] = count
        return counts

    @staticmethod
    def _usable_claims(
        evidence: dict[str, Any],
        *,
        excluded_source_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        excluded = excluded_source_ids or set()
        output = []
        for item in evidence.get("claims", []):
            if (
                item.get("support_status") not in {"verified", "provisional"}
                or item.get("use_policy") == "do_not_use"
            ):
                continue
            refs = list(item.get("source_refs", []))
            if not refs:
                continue
            if all(str(ref.get("source_id")) in excluded for ref in refs):
                continue
            output.append(item)
        return output

    @staticmethod
    def _planning_evidence_ids(graph: dict[str, dict[str, Any]]) -> set[str]:
        evidence_ids = {
            str(evidence_id)
            for slide in graph.get("deck_outline", {}).get("data", {}).get("slides", [])
            if slide.get("status") != "excluded"
            for evidence_id in slide.get("evidence_ids", [])
        }
        evidence_ids.update(
            str(evidence_id)
            for slide in graph.get("slide_specs", {}).get("data", {}).get("slides", [])
            for block in slide.get("content_blocks", [])
            for evidence_id in block.get("evidence_ids", [])
        )
        return evidence_ids

    @staticmethod
    def _evidence_ids_exclusively_backed_by_sources(
        evidence: dict[str, Any],
        source_ids: set[str],
    ) -> set[str]:
        blocked: set[str] = set()
        for claim in evidence.get("claims", []):
            refs = list(claim.get("source_refs", []))
            if refs and all(str(ref.get("source_id")) in source_ids for ref in refs):
                blocked.add(str(claim["evidence_id"]))
        return blocked

    def _complete_orientation_from_user_materials(
        self,
        *,
        waiver_reason: str | None,
        excluded_source_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "source_ledger", "evidence_ledger")
        )
        brief = graph["project_brief"]["data"]
        sources = graph["source_ledger"]["data"]
        evidence = graph["evidence_ledger"]["data"]
        evidence_version = int(graph["evidence_ledger"]["version"])
        usable = self._usable_claims(
            evidence,
            excluded_source_ids=excluded_source_ids,
        )
        if brief.get("source_policy", {}).get("citation_required") and not usable:
            raise M2CapabilityError(
                "Citation policy requires usable Evidence before orientation completion"
            )
        excluded = excluded_source_ids or set()
        source_ids = sorted(
            {
                str(ref["source_id"])
                for claim in usable
                for ref in claim.get("source_refs", [])
                if str(ref["source_id"]) not in excluded
            }
        )
        source_map = {
            str(item["source_id"]): item for item in sources.get("sources", [])
        }
        web_sources = [
            source_id
            for source_id in source_ids
            if source_map.get(source_id, {}).get("kind") == "web"
        ]
        if web_sources:
            raise M2CapabilityError(
                "User-material orientation completion cannot absorb Web Source lineage: "
                + ", ".join(web_sources)
            )

        cycles = copy.deepcopy(evidence.get("research_cycles", []))
        orientation = next(
            (item for item in cycles if item.get("kind") == "orientation"),
            None,
        )
        if orientation is None:
            numbers = [
                int(str(item["cycle_id"]).split("-")[-1])
                for item in cycles
                if str(item.get("cycle_id", "")).startswith("RSC-")
            ]
            next_number = max(numbers, default=0) + 1
            if next_number > 999:
                raise M2ApplicationError("Research cycle ID space is exhausted")
            orientation = {
                "cycle_id": f"RSC-{next_number:03d}",
                "kind": "orientation",
                "status": "pending",
                "basis": "none_required",
                "outline_version": None,
                "source_ids": [],
                "run_ids": [],
                "query_count": 0,
                "waiver_reason": None,
                "notes": [],
            }
            cycles.append(orientation)
        updated = copy.deepcopy(orientation)
        if updated.get("run_ids"):
            raise M2CapabilityError(
                "Existing orientation Research Run lineage must complete through EvidenceEngine"
            )
        semantic_update = {
            "status": "waived" if waiver_reason else "complete",
            "basis": "user_materials" if source_ids else "none_required",
            "outline_version": None,
            "source_ids": source_ids,
            "run_ids": [],
            "query_count": 0,
            "waiver_reason": waiver_reason,
        }
        def equivalent_cycle_value(key: str, value: Any) -> bool:
            current = updated.get(key)
            if key in {"source_ids", "run_ids"}:
                return list(current or []) == list(value or [])
            return current == value

        if all(
            equivalent_cycle_value(key, value)
            for key, value in semantic_update.items()
        ):
            return copy.deepcopy(evidence)
        updated.update(semantic_update)
        note = (
            "Orientation review completed from current user-material Evidence."
            if waiver_reason is None
            else f"External orientation research waived for this run: {waiver_reason}"
        )
        notes = list(updated.get("notes", []))
        if note not in notes:
            notes.append(note)
        updated["notes"] = notes
        candidate = copy.deepcopy(evidence)
        candidate["research_cycles"] = sorted(
            [
                updated if item.get("cycle_id") == updated["cycle_id"] else item
                for item in cycles
            ],
            key=lambda item: int(str(item["cycle_id"]).split("-")[-1]),
        )
        if candidate != evidence:
            self.runtime.write_artifact(
                "evidence_ledger",
                candidate,
                expected_version=evidence_version,
                status="approved",
                created_by="m2-application-service",
            )
            return self.runtime.show_artifact("evidence_ledger")
        return copy.deepcopy(evidence)

    def _run_research_plan(
        self,
        plan: Any,
        *,
        freshness_cutoff: str | None,
        allow_high_risk_source_evidence: bool,
        observed_run_ids: set[str],
    ) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        if self.research_provider is None:
            raise M2CapabilityError("No ResearchProvider is available")
        runtime = ResearchRuntime(self.workspace, self.research_provider)
        run = runtime.execute(plan)
        observed_run_ids.add(str(run["run_id"]))
        if run.get("status") != "complete":
            raise M2CapabilityError(
                f"Research Run did not complete: {run.get('run_id')} status={run.get('status')}"
            )
        materialized, published = EvidenceEngine(self.workspace).materialize_and_adjudicate_research(
            str(run["run_id"]),
            freshness_cutoff=freshness_cutoff,
            complete_cycle=True,
            allow_high_risk_source_evidence=allow_high_risk_source_evidence,
        )
        return (
            str(run["run_id"]),
            tuple(materialized.source_ids),
            tuple(published.evidence_ids),
        )

    def _planning_artifacts(self) -> set[str]:
        return {
            str(item["artifact_type"])
            for item in self.runtime.list_artifacts()
            if item.get("artifact_type")
            in {"narrative_blueprint", "deck_outline", "slide_specs"}
        }

    def _revalidate_planning_gates(
        self,
        *,
        actions: list[dict[str, Any]],
        blockers: list[dict[str, str]],
    ) -> bool:
        present = self._planning_artifacts()
        if "deck_outline" in present and "narrative_blueprint" not in present:
            self._add_finding(
                blockers,
                kind="blocker",
                code="outline_without_narrative",
                message="A Deck Outline is registered without a Narrative Blueprint.",
            )
            return False
        if "slide_specs" in present and "deck_outline" not in present:
            self._add_finding(
                blockers,
                kind="blocker",
                code="specs_without_outline",
                message="Slide Specs are registered without a Deck Outline.",
            )
            return False
        if "narrative_blueprint" not in present:
            self._add_action(
                actions,
                stage="planning_revalidation",
                status="skipped",
                detail="No Production planning artifacts are registered; M2 stops at EVIDENCE_READY.",
            )
            return True
        if not self._ensure_gate("G3", actions=actions, blockers=blockers):
            return False
        if "deck_outline" not in present:
            self._add_action(
                actions,
                stage="planning_revalidation",
                status="complete",
                detail="Narrative was revalidated; no Deck Outline is registered.",
            )
            return True
        if not self._ensure_gate("G4", actions=actions, blockers=blockers):
            return False
        self._add_action(
            actions,
            stage="planning_revalidation",
            status="complete",
            detail="Existing Narrative and Deck Outline are current against M2 Evidence.",
        )
        return True

    def _check_research_run_budgets(
        self,
        run_ids: set[str],
        limits: ResearchLimits,
        blockers: list[dict[str, str]],
    ) -> None:
        """Apply this application run's Research policy to all referenced Runs."""

        admitted = asdict(limits)
        for run_id in sorted(run_ids):
            run_path = self.workspace / ".slidethus/research/runs" / f"{run_id}.json"
            if not run_path.is_file():
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="referenced_research_run_missing",
                    message=f"Referenced Research Run is missing: {run_id}",
                )
                continue
            run = read_json(run_path)
            run_limits = dict(run.get("limits", {}))
            wider = sorted(
                name
                for name, admitted_value in admitted.items()
                if int(run_limits.get(name, admitted_value)) > int(admitted_value)
            )
            if wider:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="research_run_policy_exceeds_application_limits",
                    message=(
                        f"Research Run {run_id} was created with broader limits than this "
                        "application run: "
                        + ", ".join(wider)
                    ),
                )
            tasks = list(run.get("tasks", []))
            total_results = sum(int(item.get("result_count", 0)) for item in tasks)
            if len(tasks) > limits.max_queries:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="research_run_query_budget_exceeded",
                    message=(
                        f"Research Run {run_id} contains {len(tasks)} queries, exceeding "
                        f"max_queries={limits.max_queries}."
                    ),
                )
            if total_results > limits.max_total_results:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="research_run_result_budget_exceeded",
                    message=(
                        f"Research Run {run_id} contains {total_results} results, exceeding "
                        f"max_total_results={limits.max_total_results}."
                    ),
                )
            if any(
                int(item.get("result_count", 0)) > limits.max_results_per_query
                for item in tasks
            ):
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="research_run_per_query_budget_exceeded",
                    message=(
                        f"Research Run {run_id} exceeds max_results_per_query="
                        f"{limits.max_results_per_query}."
                    ),
                )
            if any(len(str(item.get("query", ""))) > limits.max_query_chars for item in tasks):
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="research_run_query_length_exceeded",
                    message=(
                        f"Research Run {run_id} contains a query above max_query_chars="
                        f"{limits.max_query_chars}."
                    ),
                )

    def _snapshot_research_runs(
        self,
        run_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Publish immutable Research Run snapshots for historical M2 report lineage."""

        snapshot_dir = self.workspace / ".slidethus/m2/research-runs"
        refs: list[dict[str, Any]] = []
        for run_id in sorted(run_ids):
            run_path = self.workspace / ".slidethus/research/runs" / f"{run_id}.json"
            if not run_path.is_file():
                raise M2ApplicationError(f"Research Run is missing before report snapshot: {run_id}")
            run = read_json(run_path)
            if run.get("run_id") != run_id:
                raise M2ApplicationError(f"Research Run identity mismatch: {run_id}")
            digest = sha256_json(run)
            snapshot_path = snapshot_dir / f"{digest}.json"
            created = atomic_create_json(snapshot_path, run)
            if not created and read_json(snapshot_path) != run:
                raise M2ApplicationError(
                    f"Immutable Research Run snapshot path contains different content: {snapshot_path}"
                )
            refs.append(
                {
                    "run_id": run_id,
                    "snapshot_path": snapshot_path.relative_to(self.workspace).as_posix(),
                    "snapshot_sha256": sha256_file(snapshot_path),
                    "status": str(run["status"]),
                    "cycle_id": str(run["cycle_id"]),
                }
            )
        return refs

    def _collect_artifact_refs(self) -> list[dict[str, Any]]:
        admitted = {
            "project_brief",
            "source_ledger",
            "evidence_ledger",
            "narrative_blueprint",
            "deck_outline",
            "slide_specs",
            "gate_results",
            "decision_log",
            "project_state",
        }
        return [
            {
                "artifact_type": str(item["artifact_type"]),
                "version": int(item["version"]),
                "content_hash": str(item["content_hash"]),
            }
            for item in self.runtime.list_artifacts()
            if item.get("artifact_type") in admitted
        ]

    def _generated_at(
        self,
        artifact_refs: list[dict[str, Any]],
        research_run_refs: list[dict[str, Any]],
        gap_report_path: str | None,
    ) -> str:
        metadata = {
            str(item["artifact_type"]): item for item in self.runtime.list_artifacts()
        }
        values = [
            str(metadata[ref["artifact_type"]].get("updated_at"))
            for ref in artifact_refs
            if metadata.get(ref["artifact_type"], {}).get("updated_at")
        ]
        for run_ref in research_run_refs:
            run = read_json(self.workspace / str(run_ref["snapshot_path"]))
            if run.get("updated_at"):
                values.append(str(run["updated_at"]))
        if gap_report_path is not None:
            gap = read_json(self.workspace / gap_report_path)
            if gap.get("generated_at"):
                values.append(str(gap["generated_at"]))
        return max(values) if values else "1970-01-01T00:00:00Z"

    def _persist_report(self, report: dict[str, Any]) -> M2ApplicationRunResult:
        report["report_id"] = m2_report_id(report)
        errors = validate_m2_report_data(report, self.schemas.schema_dir)
        if errors:
            raise M2ApplicationError("Invalid M2 Application Report: " + "; ".join(errors))
        key = m2_report_file_key(report)
        path = self.report_dir / f"{key}.json"
        created = atomic_create_json(path, report)
        if not created:
            from slidethus.io_utils import read_json

            if read_json(path) != report:
                raise M2ApplicationError(
                    f"Immutable M2 Application Report path contains different content: {path}"
                )
        reference_errors = m2_report_reference_errors(
            self.workspace,
            path,
            self.schemas.schema_dir,
        )
        if reference_errors:
            if created and path.exists():
                path.unlink()
            raise M2ApplicationError(
                "M2 Application Report references are invalid: "
                + "; ".join(reference_errors)
            )
        return M2ApplicationRunResult(report=copy.deepcopy(report), path=path, changed=created)

    def run(
        self,
        source_paths: tuple[Path, ...] = (),
        *,
        limits: M2ApplicationLimits | None = None,
        allow_research_degraded: bool = False,
        approve_external_disclosure: bool = False,
        allow_high_risk_source_evidence: bool = False,
        advance_existing_planning: bool = True,
    ) -> M2ApplicationRunResult:
        """Run/resume M2 through G2 and, for existing planning artifacts, current G5A."""

        admitted_limits = limits or M2ApplicationLimits()
        if admitted_limits.max_sources < 1 or admitted_limits.max_total_source_bytes < 1:
            raise M2ApplicationError("M2 application limits must be positive")
        validate_source_parse_limits(admitted_limits.source)
        validate_research_limits(admitted_limits.research)

        initial = self.runtime.read_artifact_graph_snapshot(
            ("project_state", "project_brief")
        )
        brief = initial["project_brief"]["data"]
        brief_ref = _artifact_ref(initial["project_brief"], "project_brief")
        external_required = bool(brief.get("source_policy", {}).get("external_research"))
        freshness_requirement = _normalized(
            brief.get("source_policy", {}).get("freshness_requirement")
        ) or None
        provider_present = self.research_provider is not None
        provider_name = _normalized(getattr(self.research_provider, "name", ""))
        provider_version = _normalized(getattr(self.research_provider, "version", ""))
        provider_identity_valid = (
            provider_present
            and 1 <= len(provider_name) <= 128
            and 1 <= len(provider_version) <= 128
        )
        provider_available = bool(provider_identity_valid)
        provider_identity = (
            {"name": provider_name, "version": provider_version}
            if provider_identity_valid
            else None
        )

        actions: list[dict[str, Any]] = []
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if provider_present and not provider_identity_valid:
            self._add_finding(
                blockers,
                kind="blocker",
                code="research_provider_identity_invalid",
                message=(
                    "Injected ResearchProvider must declare non-empty name/version values no "
                    "longer than 128 characters."
                ),
            )
        capabilities = [
            {
                "capability": "source_ingestion",
                "status": "available",
                "detail": "Parser Registry and bounded Source ingestion are available.",
            },
            {
                "capability": "evidence_adjudication",
                "status": "available",
                "detail": "Deterministic Evidence materialization and policy adjudication are available.",
            },
            {
                "capability": "block_evidence_gap_analysis",
                "status": "available",
                "detail": "Current-version Outline/Block Evidence binding analysis is available.",
            },
            {
                "capability": "external_research_provider",
                "status": "available" if provider_available else "missing",
                "detail": (
                    f"Provider {provider_name}@{provider_version} is injected."
                    if provider_available
                    else "No online ResearchProvider is injected; CLI remains provider-neutral."
                ),
            },
            {
                "capability": "external_disclosure",
                "status": (
                    "available"
                    if approve_external_disclosure or not external_required
                    else ("missing" if provider_available else "degraded")
                ),
                "detail": (
                    "External disclosure is explicitly approved for this run."
                    if approve_external_disclosure
                    else (
                        "External disclosure is not required by the Project Brief."
                        if not external_required
                        else "No external disclosure approval is recorded for this run."
                    )
                ),
            },
        ]

        if external_required and provider_available and approve_external_disclosure:
            mode = "full"
        elif external_required:
            mode = "offline_degraded"
        else:
            mode = "user_materials"

        requested_sources = self._preflight_sources(source_paths, admitted_limits, blockers)
        config_payload = {
            "limits": asdict(admitted_limits),
            "allow_research_degraded": allow_research_degraded,
            "approve_external_disclosure": approve_external_disclosure,
            "allow_high_risk_source_evidence": allow_high_risk_source_evidence,
            "advance_existing_planning": advance_existing_planning,
            "provider": provider_identity,
        }
        config_hash = f"sha256:{sha256_json(config_payload)}"

        source_ids: set[str] = set()
        evidence_ids: set[str] = set()
        research_run_ids: set[str] = set()
        excluded_source_ids: set[str] = set()
        high_risk_count = 0
        gap_report_path: str | None = None
        gap_report_sha256: str | None = None
        rework_required = False

        if not blockers:
            try:
                reconciled = EvidenceEngine(self.workspace).reconcile_current_evidence(
                    freshness_cutoff=freshness_requirement,
                )
            except EvidenceError as exc:
                self._add_action(
                    actions,
                    stage="evidence",
                    status="blocked",
                    detail=f"Current Evidence reconciliation failed: {exc}",
                )
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="current_evidence_reconciliation_failed",
                    message=str(exc),
                )
            else:
                if reconciled.changed:
                    evidence_ids.update(reconciled.evidence_ids)
                    self._add_action(
                        actions,
                        stage="evidence",
                        status="complete",
                        detail=(
                            "Current Production Evidence was reconciled against current Source "
                            "lineage, risk and freshness policy."
                        ),
                        refs=tuple(reconciled.evidence_ids),
                    )

        if not blockers and self._ensure_gate("G0", actions=actions, blockers=blockers):
            source_service = SourceIngestionService(self.workspace)
            for fingerprint in requested_sources:
                try:
                    result = source_service.ingest(
                        Path(str(fingerprint["path"])),
                        limits=admitted_limits.source,
                    )
                    source_ids.add(result.source_id)
                    actual_sha256 = str(result.source_record.get("content_hash", "")).removeprefix(
                        "sha256:"
                    )
                    actual_size = int(result.source_record.get("size_bytes") or 0)
                    if (
                        actual_sha256 != fingerprint["sha256"]
                        or actual_size != fingerprint["size_bytes"]
                    ):
                        self._add_finding(
                            warnings,
                            kind="warning",
                            code="source_changed_after_preflight",
                            message=(
                                f"{fingerprint['path']} changed after application preflight; "
                                "the report was rebound to the safely ingested bytes."
                            ),
                        )
                        fingerprint["sha256"] = actual_sha256
                        fingerprint["size_bytes"] = actual_size
                except SourceCapabilityError as exc:
                    suffix = Path(str(fingerprint["path"])).suffix.lower() or "<extensionless>"
                    self._upsert_capability(
                        capabilities,
                        capability=f"source_adapter:{suffix}",
                        status="missing",
                        detail=str(exc),
                    )
                    self._add_finding(
                        blockers,
                        kind="blocker",
                        code="source_adapter_capability_missing",
                        message=f"{fingerprint['path']}: {exc}",
                    )
                except UnsupportedSourceError as exc:
                    suffix = Path(str(fingerprint["path"])).suffix.lower() or "<extensionless>"
                    self._upsert_capability(
                        capabilities,
                        capability=f"source_adapter:{suffix}",
                        status="missing",
                        detail=str(exc),
                    )
                    self._add_finding(
                        blockers,
                        kind="blocker",
                        code="source_format_unsupported",
                        message=f"{fingerprint['path']}: {exc}",
                    )
                except (SourceIngestionError, FileNotFoundError) as exc:
                    self._add_finding(
                        blockers,
                        kind="blocker",
                        code="source_ingestion_failed",
                        message=str(exc),
                    )
            current_source_ledger = self.runtime.show_artifact("source_ledger")
            current_sources = list(current_source_ledger.get("sources", []))
            source_ids.update(str(item["source_id"]) for item in current_sources)
            if len(current_sources) > admitted_limits.max_sources:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="workspace_source_count_limit_exceeded",
                    message=(
                        f"Current Source Ledger contains {len(current_sources)} sources, exceeding "
                        f"max_sources={admitted_limits.max_sources}."
                    ),
                )
            current_total_bytes = sum(
                int(item.get("size_bytes") or 0) for item in current_sources
            )
            if current_total_bytes > admitted_limits.max_total_source_bytes:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="workspace_source_bytes_limit_exceeded",
                    message=(
                        f"Current Source Ledger represents {current_total_bytes} bytes, exceeding "
                        f"max_total_source_bytes={admitted_limits.max_total_source_bytes}."
                    ),
                )
            self._add_action(
                actions,
                stage="sources",
                status="blocked" if blockers else "complete",
                detail=(
                    f"Current Source Ledger contains {len(source_ids)} source(s)."
                    if not blockers
                    else "One or more requested Sources could not be ingested safely."
                ),
                refs=tuple(sorted(source_ids)),
            )

        if not blockers and self._ensure_gate("G1", actions=actions, blockers=blockers):
            evidence_engine = EvidenceEngine(self.workspace)
            source_ledger = self.runtime.show_artifact("source_ledger")
            try:
                risk_counts = self._high_risk_source_counts()
            except SlidethusError as exc:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="source_snapshot_unavailable",
                    message=str(exc),
                )
                risk_counts = {}
            high_risk_count = sum(risk_counts.values())
            if not allow_high_risk_source_evidence:
                for source_id, count in sorted(risk_counts.items()):
                    excluded_source_ids.add(source_id)
                    self._add_finding(
                        warnings,
                        kind="warning",
                        code="high_risk_source_excluded",
                        message=(
                            f"{source_id} contains {count} high-severity Source risk finding(s) "
                            "and was excluded from automatic Evidence promotion."
                        ),
                    )
            for source in source_ledger.get("sources", []):
                source_id = str(source["source_id"])
                if not source.get("ingestion") or source.get("kind") == "web":
                    continue
                if source_id in excluded_source_ids:
                    continue
                try:
                    published = evidence_engine.adjudicate(
                        evidence_engine.candidates_from_source(source_id),
                        freshness_cutoff=freshness_requirement,
                        allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                    )
                    evidence_ids.update(published.evidence_ids)
                except EvidenceError as exc:
                    self._add_finding(
                        blockers,
                        kind="blocker",
                        code="source_evidence_adjudication_failed",
                        message=f"{source_id}: {exc}",
                    )
            current_evidence = self.runtime.show_artifact("evidence_ledger")
            evidence_ids.update(
                str(item["evidence_id"])
                for item in current_evidence.get("claims", [])
            )
            self._add_action(
                actions,
                stage="evidence",
                status="blocked" if blockers else "complete",
                detail=(
                    f"Current Evidence Ledger contains {len(evidence_ids)} claim(s)."
                    if not blockers
                    else "Source-backed Evidence adjudication encountered a blocking failure."
                ),
                refs=tuple(sorted(evidence_ids)),
            )

        if not blockers:
            try:
                if external_required:
                    if provider_available and approve_external_disclosure:
                        plan = plan_orientation_research(
                            self.workspace,
                            limits=admitted_limits.research,
                        )
                        run_id, new_sources, new_evidence = self._run_research_plan(
                            plan,
                            freshness_cutoff=freshness_requirement,
                            allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                            observed_run_ids=research_run_ids,
                        )
                        research_run_ids.add(run_id)
                        source_ids.update(new_sources)
                        evidence_ids.update(new_evidence)
                        detail = "External orientation Research completed with approved disclosure."
                    elif allow_research_degraded and freshness_requirement is None:
                        reason = "No ResearchProvider/disclosure approval; explicit D3 degradation accepted."
                        self._complete_orientation_from_user_materials(
                            waiver_reason=reason,
                            excluded_source_ids=excluded_source_ids,
                        )
                        self._add_finding(
                            warnings,
                            kind="warning",
                            code="external_research_waived",
                            message=reason,
                        )
                        detail = "Orientation Research was explicitly waived for D3 user-material delivery."
                    elif provider_available and not approve_external_disclosure:
                        raise M2CapabilityError(
                            "External research is required but disclosure approval is absent"
                        )
                    elif freshness_requirement is not None:
                        raise M2CapabilityError(
                            "External research is required for a freshness-constrained project, but no provider is available"
                        )
                    else:
                        raise M2CapabilityError(
                            "External research is required but no ResearchProvider is available; explicit D3 degradation was not approved"
                        )
                else:
                    self._complete_orientation_from_user_materials(
                        waiver_reason=None,
                        excluded_source_ids=excluded_source_ids,
                    )
                    detail = "Orientation Evidence was completed from current user materials."
                self._add_action(
                    actions,
                    stage="orientation_research",
                    status="complete",
                    detail=detail,
                    refs=tuple(sorted(research_run_ids)),
                )
            except (M2ApplicationError, ResearchError, EvidenceError) as exc:
                self._add_action(
                    actions,
                    stage="orientation_research",
                    status="blocked",
                    detail=str(exc),
                )
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="orientation_research_unavailable",
                    message=str(exc),
                )

        try:
            final_risk_counts = self._high_risk_source_counts()
        except SlidethusError as exc:
            self._add_finding(
                blockers,
                kind="blocker",
                code="final_source_risk_inventory_failed",
                message=str(exc),
            )
        else:
            high_risk_count = sum(final_risk_counts.values())
            if not allow_high_risk_source_evidence:
                for source_id, count in sorted(final_risk_counts.items()):
                    excluded_source_ids.add(source_id)
                    self._add_finding(
                        warnings,
                        kind="warning",
                        code="high_risk_source_excluded",
                        message=(
                            f"{source_id} contains {count} high-severity Source risk finding(s) "
                            "and was excluded from automatic Evidence promotion."
                        ),
                    )

        if not blockers:
            if self._ensure_gate("G1", actions=actions, blockers=blockers):
                self._ensure_gate("G2", actions=actions, blockers=blockers)

        if not blockers and freshness_requirement is not None:
            evidence = self.runtime.show_artifact("evidence_ledger")
            unresolved_freshness = [
                item
                for item in evidence.get("claims", [])
                if item.get("use_policy") != "do_not_use"
                and item.get("freshness_decision", {}).get("status")
                in {"unknown", "stale"}
            ]
            if unresolved_freshness:
                self._add_finding(
                    warnings,
                    kind="warning",
                    code="freshness_requires_qualification",
                    message=(
                        f"{len(unresolved_freshness)} usable Evidence claim(s) remain stale or "
                        "deterministically unknown under the Brief freshness requirement."
                    ),
                )

        if (
            not blockers
            and advance_existing_planning
            and excluded_source_ids
            and not allow_high_risk_source_evidence
        ):
            present = self._planning_artifacts()
            graph_types = ["evidence_ledger"]
            if "deck_outline" in present:
                graph_types.append("deck_outline")
            if "slide_specs" in present:
                graph_types.append("slide_specs")
            planning_graph = self.runtime.read_artifact_graph_snapshot(tuple(graph_types))
            blocked_evidence_ids = self._evidence_ids_exclusively_backed_by_sources(
                planning_graph["evidence_ledger"]["data"],
                excluded_source_ids,
            )
            affected = sorted(
                blocked_evidence_ids & self._planning_evidence_ids(planning_graph)
            )
            if affected:
                self._add_action(
                    actions,
                    stage="planning_revalidation",
                    status="blocked",
                    detail=(
                        "Existing planning binds Evidence backed only by high-risk Sources: "
                        + ", ".join(affected)
                    ),
                    refs=tuple(affected),
                )
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="high_risk_evidence_binding_requires_override",
                    message=(
                        "Existing Outline/Slide Specs bind Evidence backed only by high-risk "
                        "Sources; rerun with explicit approval or replace the Evidence: "
                        + ", ".join(affected)
                    ),
                )

        if not blockers and advance_existing_planning:
            if self._revalidate_planning_gates(actions=actions, blockers=blockers):
                present = self._planning_artifacts()
                if "slide_specs" in present:
                    binding = EvidenceBindingService(self.workspace)
                    preliminary = binding.analyze(
                        persist=True,
                        require_targeted_cycle=False,
                    )
                    if preliminary.path is not None:
                        gap_report_path = preliminary.path.relative_to(self.workspace).as_posix()
                        gap_report_sha256 = sha256_file(preliminary.path)
                    binding_blockers = [
                        item
                        for item in preliminary.report.get("issues", [])
                        if item.get("severity") in {"critical", "major"}
                    ]
                    try:
                        if binding_blockers:
                            if (
                                mode == "full"
                                and provider_available
                                and preliminary.report.get("query_suggestions")
                            ):
                                targeted_plan = binding.build_targeted_plan(
                                    limits=admitted_limits.research
                                )
                                run_id, new_sources, new_evidence = self._run_research_plan(
                                    targeted_plan,
                                    freshness_cutoff=freshness_requirement,
                                    allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                                    observed_run_ids=research_run_ids,
                                )
                                research_run_ids.add(run_id)
                                source_ids.update(new_sources)
                                evidence_ids.update(new_evidence)
                                self._add_action(
                                    actions,
                                    stage="targeted_research",
                                    status="complete",
                                    detail=(
                                        "Targeted Research executed for current Evidence gap suggestions; "
                                        "new Evidence still requires explicit Outline/Block binding."
                                    ),
                                    refs=(run_id,),
                                )
                                if self._ensure_gate("G1", actions=actions, blockers=blockers):
                                    self._ensure_gate("G2", actions=actions, blockers=blockers)
                                if not blockers:
                                    self._revalidate_planning_gates(
                                        actions=actions,
                                        blockers=blockers,
                                    )
                            if not any(
                                item.get("stage") == "targeted_research" for item in actions
                            ):
                                self._add_action(
                                    actions,
                                    stage="targeted_research",
                                    status="blocked",
                                    detail=(
                                        "Blocking Evidence gaps exist, but no admitted provider execution "
                                        "can resolve them in this run."
                                    ),
                                )
                            if not blockers:
                                state = binding.route_rework(
                                    reason=(
                                        "M2 application found unresolved current Outline/Block Evidence gaps."
                                    )
                                )
                                rework_required = True
                                self._add_finding(
                                    blockers,
                                    kind="blocker",
                                    code="evidence_rework_required",
                                    message=(
                                        "Current Outline/Slide Specs contain unresolved Evidence gaps; "
                                        f"workflow routed to {state['current_phase']}."
                                    ),
                                )
                        else:
                            current_gap = binding.analyze(
                                persist=False,
                                require_targeted_cycle=True,
                            )
                            targeted_missing = any(
                                item.get("code") == "targeted_cycle_incomplete"
                                and item.get("severity") in {"critical", "major"}
                                for item in current_gap.report.get("issues", [])
                            )
                            if targeted_missing:
                                if mode == "full" and provider_available:
                                    try:
                                        targeted_plan = plan_targeted_research(
                                            self.workspace,
                                            limits=admitted_limits.research,
                                        )
                                    except ResearchError:
                                        binding.complete_user_material_targeted_cycle()
                                        self._add_action(
                                            actions,
                                            stage="targeted_research",
                                            status="complete",
                                            detail=(
                                                "No external targeted query was required; current user-material "
                                                "bindings completed the targeted review."
                                            ),
                                        )
                                    else:
                                        run_id, new_sources, new_evidence = self._run_research_plan(
                                            targeted_plan,
                                            freshness_cutoff=freshness_requirement,
                                            allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                                            observed_run_ids=research_run_ids,
                                        )
                                        research_run_ids.add(run_id)
                                        source_ids.update(new_sources)
                                        evidence_ids.update(new_evidence)
                                        self._add_action(
                                            actions,
                                            stage="targeted_research",
                                            status="complete",
                                            detail="Current-outline targeted Research completed.",
                                            refs=(run_id,),
                                        )
                                else:
                                    binding.complete_user_material_targeted_cycle()
                                    self._add_action(
                                        actions,
                                        stage="targeted_research",
                                        status="complete",
                                        detail=(
                                            "Current-outline targeted review completed from user-material "
                                            "Evidence without network execution."
                                        ),
                                    )
                                if self._ensure_gate("G1", actions=actions, blockers=blockers):
                                    self._ensure_gate("G2", actions=actions, blockers=blockers)
                                if not blockers:
                                    self._revalidate_planning_gates(
                                        actions=actions,
                                        blockers=blockers,
                                    )
                            if not blockers:
                                final_gap = binding.analyze(
                                    persist=True,
                                    require_targeted_cycle=True,
                                )
                                if final_gap.path is not None:
                                    gap_report_path = final_gap.path.relative_to(
                                        self.workspace
                                    ).as_posix()
                                    gap_report_sha256 = sha256_file(final_gap.path)
                                if final_gap.report.get("requires_rework"):
                                    binding.route_rework(
                                        reason="M2 application final Evidence binding check requires P2 rework."
                                    )
                                    rework_required = True
                                    self._add_finding(
                                        blockers,
                                        kind="blocker",
                                        code="evidence_rework_required",
                                        message="Final current-version Evidence Gap Report requires P2 rework.",
                                    )
                                else:
                                    self._ensure_gate(
                                        "G5A",
                                        actions=actions,
                                        blockers=blockers,
                                    )
                            elif not any(
                                item.get("stage") == "targeted_research" for item in actions
                            ):
                                self._add_action(
                                    actions,
                                    stage="targeted_research",
                                    status="complete",
                                    detail="The current-outline targeted cycle was already complete.",
                                )
                    except (EvidenceBindingError, EvidenceError, ResearchError) as exc:
                        if not any(
                            item.get("stage") == "targeted_research" for item in actions
                        ):
                            self._add_action(
                                actions,
                                stage="targeted_research",
                                status="blocked",
                                detail=str(exc),
                            )
                        self._add_finding(
                            blockers,
                            kind="blocker",
                            code="targeted_evidence_integration_failed",
                            message=str(exc),
                        )
                    self._add_action(
                        actions,
                        stage="gap_analysis",
                        status="blocked" if blockers else "complete",
                        detail=(
                            "Current Outline/Block Evidence bindings are ready for G5A."
                            if not blockers
                            else "Current Outline/Block Evidence requires additional work."
                        ),
                        refs=((gap_report_path,) if gap_report_path else ()),
                    )
                else:
                    self._add_action(
                        actions,
                        stage="gap_analysis",
                        status="skipped",
                        detail="No Slide Specs are registered; block-level G5A is not applicable.",
                    )
        elif not advance_existing_planning:
            self._add_action(
                actions,
                stage="planning_revalidation",
                status="skipped",
                detail="Existing planning revalidation was disabled for this application run.",
            )

        if provider_present:
            final_provider_identity = {
                "name": _normalized(getattr(self.research_provider, "name", "")),
                "version": _normalized(getattr(self.research_provider, "version", "")),
            }
            if final_provider_identity != provider_identity:
                self._add_action(
                    actions,
                    stage="orientation_research",
                    status="blocked",
                    detail="ResearchProvider identity changed during the M2 application run.",
                )
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="research_provider_identity_changed",
                    message=(
                        "ResearchProvider name/version changed during execution; persisted Run and "
                        "application configuration cannot share one stable provider identity."
                    ),
                )

        final_graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "source_ledger", "evidence_ledger")
        )
        current_brief_ref = _artifact_ref(final_graph["project_brief"], "project_brief")
        if current_brief_ref != brief_ref:
            self._add_action(
                actions,
                stage="brief",
                status="blocked",
                detail=(
                    "Project Brief changed during the M2 application run; the run result is "
                    "not valid for the new policy version."
                ),
            )
            self._add_finding(
                blockers,
                kind="blocker",
                code="brief_changed_during_application_run",
                message=(
                    f"Project Brief changed from v{brief_ref['version']} to "
                    f"v{current_brief_ref['version']} during the application run."
                ),
            )

        final_sources = list(final_graph["source_ledger"]["data"].get("sources", []))
        source_ids.update(str(item["source_id"]) for item in final_sources)
        final_source_bytes = sum(int(item.get("size_bytes") or 0) for item in final_sources)
        if len(final_sources) > admitted_limits.max_sources:
            self._add_finding(
                blockers,
                kind="blocker",
                code="final_source_count_limit_exceeded",
                message=(
                    f"Final Source Ledger contains {len(final_sources)} sources, exceeding "
                    f"max_sources={admitted_limits.max_sources}."
                ),
            )
        if final_source_bytes > admitted_limits.max_total_source_bytes:
            self._add_finding(
                blockers,
                kind="blocker",
                code="final_source_bytes_limit_exceeded",
                message=(
                    f"Final Source Ledger represents {final_source_bytes} bytes, exceeding "
                    f"max_total_source_bytes={admitted_limits.max_total_source_bytes}."
                ),
            )
        oversized_final_sources = sorted(
            str(item["source_id"])
            for item in final_sources
            if int(item.get("size_bytes") or 0)
            > admitted_limits.source.max_source_bytes
        )
        if oversized_final_sources:
            self._add_finding(
                blockers,
                kind="blocker",
                code="final_source_size_limit_exceeded",
                message=(
                    "Final Source Ledger contains Source(s) above max_source_bytes="
                    f"{admitted_limits.source.max_source_bytes}: "
                    + ", ".join(oversized_final_sources)
                ),
            )

        final_evidence = final_graph["evidence_ledger"]["data"]
        evidence_ids.update(
            str(item["evidence_id"]) for item in final_evidence.get("claims", [])
        )
        research_run_ids.update(
            str(run_id)
            for cycle in final_evidence.get("research_cycles", [])
            for run_id in cycle.get("run_ids", [])
        )
        for action in actions:
            detail = str(action.get("detail", ""))
            if detail.startswith("Current Source Ledger contains"):
                action["detail"] = (
                    f"Final Source Ledger contains {len(source_ids)} source(s)."
                )
                action["refs"] = sorted(source_ids)
            elif detail.startswith("Current Evidence Ledger contains"):
                action["detail"] = (
                    f"Final Evidence Ledger contains {len(evidence_ids)} claim(s)."
                )
                action["refs"] = sorted(evidence_ids)

        state = self.runtime.show_artifact("project_state")
        final_phase = str(state["current_phase"])
        gate_ids = ["G0", "G1", "G2"]
        present = self._planning_artifacts()
        if "narrative_blueprint" in present:
            gate_ids.append("G3")
        if "deck_outline" in present:
            gate_ids.append("G4")
        if "slide_specs" in present:
            gate_ids.append("G5A")
        gates: list[dict[str, Any]] = []
        for gate_id in gate_ids:
            result = evaluate_gate(self.workspace, gate_id)
            gates.append(
                {
                    "gate_id": gate_id,
                    "status": result.status,
                    "reasons": list(result.reasons),
                }
            )

        self._check_research_run_budgets(
            research_run_ids,
            admitted_limits.research,
            blockers,
        )
        research_run_refs = self._snapshot_research_runs(research_run_ids)

        if blockers:
            rework_only = rework_required and all(
                item.get("code") == "evidence_rework_required" for item in blockers
            )
            status = "rework_required" if rework_only else "blocked"
            delivery_level = "D4" if rework_only else "D5"
        elif mode == "offline_degraded":
            status = "degraded"
            delivery_level = "D3"
        else:
            status = "ready"
            delivery_level = "D0" if mode == "full" else "D3"

        artifact_refs = self._collect_artifact_refs()
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(brief["project_id"]),
            "report_id": "",
            "generated_at": self._generated_at(
                artifact_refs,
                research_run_refs,
                gap_report_path,
            ),
            "status": status,
            "delivery_level": delivery_level,
            "mode": mode,
            "inputs": {
                "project_brief": brief_ref,
                "requested_sources": requested_sources,
                "config": config_payload,
                "config_hash": config_hash,
            },
            "capabilities": sorted(
                capabilities, key=lambda item: str(item["capability"])
            ),
            "actions": actions,
            "blockers": sorted(blockers, key=lambda item: item["finding_id"]),
            "warnings": sorted(warnings, key=lambda item: item["finding_id"]),
            "security": {
                "external_disclosure_approved": approve_external_disclosure,
                "high_risk_source_evidence_allowed": allow_high_risk_source_evidence,
                "excluded_source_ids": sorted(excluded_source_ids),
                "high_risk_finding_count": high_risk_count,
            },
            "outputs": {
                "source_ids": sorted(source_ids),
                "evidence_ids": sorted(evidence_ids),
                "research_run_ids": sorted(research_run_ids),
                "research_runs": research_run_refs,
                "gap_report_path": gap_report_path,
                "gap_report_sha256": gap_report_sha256,
                "artifact_refs": sorted(
                    artifact_refs,
                    key=lambda item: (str(item["artifact_type"]), int(item["version"])),
                ),
                "final_phase": final_phase,
                "gates": gates,
            },
        }
        self._add_action(
            report["actions"],
            stage="report",
            status="complete",
            detail=f"M2 application report finalized with status={status}, delivery_level={delivery_level}.",
        )
        return self._persist_report(report)


def evaluate_m2_workspace_gate(workspace: Path) -> dict[str, Any]:
    """Evaluate the current workspace M2 Gate without mutating state."""

    workspace = workspace.resolve()
    validation = validate_workspace(workspace, check_hashes=True)
    if not validation.ok:
        return {
            "status": "fail",
            "reasons": [
                f"validation:{item.code}:{item.path}"
                for item in validation.issues
                if item.severity == "error"
            ],
            "gates": [],
        }
    runtime = ArtifactRuntime(workspace)
    present = {
        str(item["artifact_type"]) for item in runtime.list_artifacts()
    }
    gate_ids = ["G1", "G2"]
    if {"deck_outline", "slide_specs"}.issubset(present):
        gate_ids.append("G5A")
    results: list[dict[str, Any]] = []
    reasons: list[str] = []
    for gate_id in gate_ids:
        result: GateResult = evaluate_gate(workspace, gate_id)
        results.append(
            {
                "gate_id": gate_id,
                "status": result.status,
                "reasons": list(result.reasons),
            }
        )
        if not result.passed:
            reasons.extend(f"{gate_id}:{reason}" for reason in result.reasons)
    return {
        "status": "pass" if not reasons else "fail",
        "reasons": reasons,
        "gates": results,
    }
