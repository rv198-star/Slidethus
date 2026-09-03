from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import (
    M3ApplicationError,
    SlidethusError,
    SourceIngestionError,
)
from slidethus.gates import evaluate_gate
from slidethus.ingestion import validate_source_parse_limits
from slidethus.io_utils import atomic_create_json, read_json, sha256_file, sha256_json
from slidethus.m2_application_reports import m2_report_reference_errors
from slidethus.m3_application_reports import (
    m3_finding_id,
    m3_report_file_key,
    m3_report_id,
    m3_report_reference_errors,
    validate_m3_report_data,
)
from slidethus.planning_limits import validate_planning_limits
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.planning_reviews import find_planning_review_report
from slidethus.protocols import (
    BriefCompletionHints,
    PlanningLimits,
    PlanningProvider,
    ResearchProvider,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.brief_completion import (
    BriefCompletionService,
    validate_brief_completion_hints,
)
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.m2_application import (
    M2ApplicationLimits,
    M2ApplicationService,
)
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.planning_repair import PlanningRepairService
from slidethus.services.planning_review import PlanningReviewService
from slidethus.services.research import validate_research_limits
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.services.source_ingestion import SourceIngestionService
from slidethus.state_machine import FORWARD_SEQUENCE, Phase, can_transition

_GATE_TARGETS = {
    "G0": Phase.BRIEF_READY,
    "G2": Phase.EVIDENCE_READY,
    "G3": Phase.NARRATIVE_READY,
    "G4": Phase.OUTLINE_READY,
    "G5A": Phase.SLIDE_SPECS_READY,
    "G5B": Phase.LAYOUT_READY,
}
_PHASE_LEVEL = {
    Phase.CREATED: "P0",
    Phase.BRIEF_READY: "P0",
    Phase.SOURCES_READY: "P2",
    Phase.EVIDENCE_READY: "P2",
    Phase.NARRATIVE_READY: "P3",
    Phase.OUTLINE_READY: "P4",
    Phase.SLIDE_SPECS_READY: "P5A",
    Phase.LAYOUT_READY: "P5B",
    Phase.VISUAL_SYSTEM_READY: "P5B",
    Phase.DRAFT_RENDERED: "P5B",
    Phase.REVIEWED: "P5B",
    Phase.DELIVERY_READY: "P5B",
    Phase.COMPLETED: "P5B",
}
_REWORK_LEVEL = {
    "BRIEF_READY": "P0",
    "EVIDENCE_READY": "P2",
    "NARRATIVE_READY": "P3",
    "OUTLINE_READY": "P4",
    "SLIDE_SPECS_READY": "P5A",
    "LAYOUT_READY": "P5B",
}
_LEVEL_CURRENT_ARTIFACTS = {
    "P0": {"project_state", "project_brief", "gate_results", "decision_log"},
    "P2": {
        "project_state", "project_brief", "source_ledger", "evidence_ledger",
        "gate_results", "decision_log",
    },
    "P3": {
        "project_state", "project_brief", "source_ledger", "evidence_ledger",
        "narrative_blueprint", "gate_results", "decision_log",
    },
    "P4": {
        "project_state", "project_brief", "source_ledger", "evidence_ledger",
        "narrative_blueprint", "deck_outline", "gate_results", "decision_log",
    },
    "P5A": {
        "project_state", "project_brief", "source_ledger", "evidence_ledger",
        "narrative_blueprint", "deck_outline", "slide_specs", "gate_results",
        "decision_log",
    },
    "P5B": {
        "project_state", "project_brief", "source_ledger", "evidence_ledger",
        "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans",
        "gate_results", "decision_log",
    },
}


@dataclass(frozen=True)
class M3ApplicationRunResult:
    """One persisted integrated M3 application result."""

    report: dict[str, Any]
    path: Path
    changed: bool


def _text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _phase_index(phase: Phase) -> int:
    return FORWARD_SEQUENCE.index(phase)


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


def _provider_identity(provider: Any, *, required: bool) -> dict[str, str] | None:
    if provider is None:
        if required:
            raise M3ApplicationError("PlanningProvider is required")
        return None
    name = _text(getattr(provider, "name", ""), limit=128)
    version = _text(getattr(provider, "version", ""), limit=128)
    if not name or not version:
        raise M3ApplicationError("Provider must declare bounded name and version")
    return {"name": name, "version": version}


def _hints_payload(hints: BriefCompletionHints) -> dict[str, Any]:
    payload = asdict(hints)
    payload["audience_needs"] = list(hints.audience_needs)
    payload["audience_objections"] = list(hints.audience_objections)
    payload["output_formats"] = list(hints.output_formats)
    return payload


class M3ApplicationService:
    """Single M3 orchestrator from conservative Brief completion through G5B review."""

    def __init__(
        self,
        workspace: Path,
        *,
        planning_provider: PlanningProvider | None = None,
        research_provider: ResearchProvider | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.planning_provider = planning_provider or DeterministicPlanningProvider()
        self.research_provider = research_provider
        self.planning_provider_identity = _provider_identity(
            self.planning_provider,
            required=True,
        )
        self.research_provider_identity = _provider_identity(
            self.research_provider,
            required=False,
        )
        self.report_dir = self.workspace / ".slidethus/m3/runs"

    def _assert_planning_provider_identity(self) -> None:
        actual = _provider_identity(self.planning_provider, required=True)
        if actual != self.planning_provider_identity:
            raise M3ApplicationError(
                "PlanningProvider identity changed during the M3 application run"
            )

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
                "action_id": f"M3A-{len(actions) + 1:03d}",
                "stage": stage,
                "status": status,
                "detail": _text(detail),
                "refs": sorted(set(str(item) for item in refs)),
            }
        )

    @staticmethod
    def _add_finding(
        findings: list[dict[str, str]],
        *,
        kind: str,
        code: str,
        message: str,
    ) -> None:
        normalized = _text(message)
        payload = {
            "finding_id": m3_finding_id(kind, code, normalized),
            "code": code,
            "message": normalized,
        }
        if payload["finding_id"] not in {item["finding_id"] for item in findings}:
            findings.append(payload)

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
        stage: str,
    ) -> bool:
        if self._current_gate_summary(gate_id) is not None:
            self._add_action(
                actions,
                stage=stage,
                status="complete",
                detail=f"{gate_id} is current and accepted.",
            )
            return True
        result = evaluate_gate(self.workspace, gate_id)
        if not result.passed:
            self._add_action(
                actions,
                stage=stage,
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
        current = Phase(str(state["current_phase"]))
        target_phase: Phase | None = None
        if _phase_index(current) < _phase_index(target):
            if not can_transition(current, target):
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="gate_transition_not_admitted",
                    message=(
                        f"Cannot advance {gate_id}: {current.value} -> {target.value} is not admitted."
                    ),
                )
                return False
            target_phase = target
        self.runtime.record_gate(
            gate_id,
            approved_by="m3-application-service",
            target_phase=target_phase,
        )
        self._add_action(
            actions,
            stage=stage,
            status="complete",
            detail=f"{gate_id} passed and was recorded.",
        )
        return True

    def _source_fingerprints(
        self,
        source_paths: tuple[Path, ...],
        limits: M2ApplicationLimits,
        blockers: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        fingerprints: list[dict[str, Any]] = []
        seen: set[Path] = set()
        unique_paths: list[Path] = []
        for raw in source_paths:
            path = raw.expanduser().resolve()
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)
        if len(unique_paths) > limits.max_sources:
            self._add_finding(
                blockers,
                kind="blocker",
                code="source_count_limit_exceeded",
                message=(
                    f"Requested {len(unique_paths)} Sources, exceeding max_sources={limits.max_sources}."
                ),
            )
        total_bytes = 0
        for path in unique_paths:
            if not path.is_file():
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="source_path_unavailable",
                    message=f"Requested Source is not a readable file: {path}",
                )
                continue
            size_bytes = path.stat().st_size
            total_bytes += size_bytes
            if size_bytes > limits.source.max_source_bytes:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="source_size_limit_exceeded",
                    message=(
                        f"Requested Source {path} is {size_bytes} bytes, exceeding "
                        f"max_source_bytes={limits.source.max_source_bytes}."
                    ),
                )
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
                    f"Requested Sources total {total_bytes} bytes, exceeding "
                    f"max_total_source_bytes={limits.max_total_source_bytes}."
                ),
            )
        fingerprints.sort(key=lambda item: str(item["path"]))
        return fingerprints

    def _m2_ref(self, result: Any) -> dict[str, Any]:
        return {
            "report_id": str(result.report["report_id"]),
            "path": result.path.relative_to(self.workspace).as_posix(),
            "sha256": sha256_file(result.path),
            "status": str(result.report["status"]),
        }

    def _reusable_m2_report(
        self,
        reference: dict[str, Any] | None,
        *,
        stage: str,
        requested_sources: list[dict[str, Any]],
        limits: M2ApplicationLimits,
        allow_research_degraded: bool,
        approve_external_disclosure: bool,
        allow_high_risk_source_evidence: bool,
    ) -> dict[str, Any] | None:
        """Return an exact current M2 fact; historical validity alone is insufficient."""

        if not isinstance(reference, dict) or stage not in {"orientation", "targeted"}:
            return None
        relative = Path(str(reference.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            return None
        path = (self.workspace / relative).resolve()
        report_root = (self.workspace / ".slidethus/m2/runs").resolve()
        if path.parent != report_root or not path.is_file():
            return None
        if sha256_file(path) != reference.get("sha256"):
            return None
        if m2_report_reference_errors(self.workspace, path, self.schemas.schema_dir):
            return None
        report = read_json(path)
        if (
            report.get("report_id") != reference.get("report_id")
            or report.get("status") != reference.get("status")
            or report.get("status") not in {"ready", "degraded"}
        ):
            return None
        targeted = stage == "targeted"
        expected_config = {
            "limits": asdict(limits),
            "allow_research_degraded": allow_research_degraded,
            "approve_external_disclosure": approve_external_disclosure,
            "allow_high_risk_source_evidence": allow_high_risk_source_evidence,
            "advance_existing_planning": targeted,
            "provider": self.research_provider_identity,
        }
        inputs = report.get("inputs", {})
        if inputs.get("config") != expected_config:
            return None
        expected_sources = [] if targeted else requested_sources
        if inputs.get("requested_sources") != expected_sources:
            return None

        state = self.runtime.show_artifact("project_state")
        phase = Phase(str(state["current_phase"]))
        minimum = Phase.SLIDE_SPECS_READY if targeted else Phase.EVIDENCE_READY
        if _phase_index(phase) < _phase_index(minimum):
            return None
        required_gates = ("G2", "G4", "G5A") if targeted else ("G2",)
        if any(self._current_gate_summary(gate_id) is None for gate_id in required_gates):
            return None
        required_types = {"project_brief", "source_ledger", "evidence_ledger"}
        if targeted:
            required_types.update({"deck_outline", "slide_specs"})
        refs = {
            str(item.get("artifact_type")): item
            for item in report.get("outputs", {}).get("artifact_refs", [])
        }
        current = {
            str(item.get("artifact_type")): item
            for item in state.get("artifacts", [])
        }
        for artifact_type in required_types:
            ref = refs.get(artifact_type)
            entry = current.get(artifact_type)
            if ref is None or entry is None:
                return None
            exact = (
                int(entry.get("version", 0)) == int(ref.get("version", -1))
                and entry.get("content_hash") == ref.get("content_hash")
            )
            if exact:
                continue
            if artifact_type != "evidence_ledger":
                return None
            prior_version = int(ref.get("version", 0))
            current_version = int(entry.get("version", 0))
            if prior_version == current_version:
                prior_path = self.workspace / str(entry["path"])
            elif 1 <= prior_version < current_version:
                prior_path = (
                    self.workspace
                    / ".slidethus/history/evidence_ledger"
                    / f"{prior_version:06d}.json"
                )
            else:
                return None
            current_path = self.workspace / str(entry["path"])
            if not prior_path.is_file() or not current_path.is_file():
                return None
            if sha256_json(read_json(prior_path).get("claims", [])) != sha256_json(
                read_json(current_path).get("claims", [])
            ):
                return None
        return report

    def _review_ref(self, result: Any) -> dict[str, Any]:
        summary = result.report["summary"]
        return {
            "report_id": str(result.report["report_id"]),
            "path": result.path.relative_to(self.workspace).as_posix(),
            "sha256": sha256_file(result.path),
            "critical_count": int(summary["critical_count"]),
            "major_count": int(summary["major_count"]),
            "minor_count": int(summary["minor_count"]),
        }

    def _repair_ref(self, result: Any) -> dict[str, Any]:
        return {
            "repair_id": str(result.report["repair_id"]),
            "path": result.path.relative_to(self.workspace).as_posix(),
            "sha256": sha256_file(result.path),
            "status": str(result.report["status"]),
        }

    def _collect_artifact_refs(self, planning_level: str) -> list[dict[str, Any]]:
        admitted = _LEVEL_CURRENT_ARTIFACTS[planning_level]
        return [
            {
                "artifact_type": str(item["artifact_type"]),
                "version": int(item["version"]),
                "content_hash": str(item["content_hash"]),
            }
            for item in self.runtime.list_artifacts()
            if item.get("artifact_type") in admitted
        ]

    def _generated_at(self, artifact_refs: list[dict[str, Any]]) -> str:
        metadata = {
            str(item["artifact_type"]): item for item in self.runtime.list_artifacts()
        }
        values = [
            str(metadata[ref["artifact_type"]].get("updated_at"))
            for ref in artifact_refs
            if metadata.get(ref["artifact_type"], {}).get("updated_at")
        ]
        return max(values) if values else "1970-01-01T00:00:00Z"

    def _wireframe_refs(self) -> list[dict[str, Any]]:
        graph = self.runtime.read_artifact_graph_snapshot(
            ("layout_plans",),
            optional_artifact_types=("layout_plans",),
        )
        snapshot = graph.get("layout_plans")
        if snapshot is None:
            return []
        return [
            {
                "slide_id": str(item["slide_id"]),
                "path": str(item["path"]),
                "sha256": str(item["sha256"]),
            }
            for item in snapshot["data"].get("wireframes", [])
        ]

    def _gate_rows(self) -> list[dict[str, Any]]:
        state = self.runtime.show_artifact("project_state")
        accepted = {
            str(item.get("gate_id")): str(item.get("status"))
            for item in state.get("completed_gates", [])
        }
        rows: list[dict[str, Any]] = []
        for gate_id in ("G0", "G2", "G3", "G4", "G5A", "G5B"):
            result = evaluate_gate(self.workspace, gate_id)
            if result.passed and accepted.get(gate_id) not in {"pass", "waived"}:
                rows.append(
                    {
                        "gate_id": gate_id,
                        "status": "not_applicable",
                        "reasons": [
                            "Deterministic checks pass, but this Gate is not accepted by the bound Project State."
                        ],
                    }
                )
            else:
                rows.append(
                    {
                        "gate_id": gate_id,
                        "status": result.status,
                        "reasons": list(result.reasons),
                    }
                )
        return rows

    def _persist_report(self, report: dict[str, Any]) -> M3ApplicationRunResult:
        report["report_id"] = m3_report_id(report)
        errors = validate_m3_report_data(report, self.schemas.schema_dir)
        if errors:
            raise M3ApplicationError("Invalid M3 Application Report: " + "; ".join(errors))
        path = self.report_dir / f"{m3_report_file_key(report)}.json"
        created = atomic_create_json(path, report)
        if not created and read_json(path) != report:
            raise M3ApplicationError(
                f"Immutable M3 Application Report path contains different content: {path}"
            )
        reference_errors = m3_report_reference_errors(
            self.workspace,
            path,
            self.schemas.schema_dir,
        )
        if reference_errors:
            if created and path.exists():
                path.unlink()
            raise M3ApplicationError(
                "M3 Application Report references are invalid: "
                + "; ".join(reference_errors)
            )
        return M3ApplicationRunResult(
            report=copy.deepcopy(report),
            path=path,
            changed=created,
        )

    def _finalize(
        self,
        *,
        initial_brief_ref: dict[str, Any],
        requested_sources: list[dict[str, Any]],
        config: dict[str, Any],
        actions: list[dict[str, Any]],
        blockers: list[dict[str, str]],
        warnings: list[dict[str, str]],
        m2_reports: list[dict[str, Any]],
        planning_review: dict[str, Any] | None,
        planning_repairs: list[dict[str, Any]],
        status: str,
        planning_level: str | None = None,
    ) -> M3ApplicationRunResult:
        state = self.runtime.show_artifact("project_state")
        actual_level = planning_level or _PHASE_LEVEL[Phase(str(state["current_phase"]))]
        artifact_refs = sorted(
            self._collect_artifact_refs(actual_level),
            key=lambda item: (str(item["artifact_type"]), int(item["version"])),
        )
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(state["project_id"]),
            "report_id": "",
            "generated_at": self._generated_at(artifact_refs),
            "status": status,
            "planning_level": actual_level,
            "inputs": {
                "project_brief": initial_brief_ref,
                "requested_sources": requested_sources,
                "config": config,
                "config_hash": f"sha256:{sha256_json(config)}",
            },
            "capabilities": [
                {
                    "capability": "brief_completion",
                    "status": "available",
                    "detail": "Deterministic minimum-question Brief completion is available.",
                },
                {
                    "capability": "planning_provider",
                    "status": "available",
                    "detail": (
                        f"Planning provider {self.planning_provider_identity['name']}@"
                        f"{self.planning_provider_identity['version']} is admitted."
                    ),
                },
                {
                    "capability": "research_provider",
                    "status": "available" if self.research_provider_identity else "missing",
                    "detail": (
                        f"Research provider {self.research_provider_identity['name']}@"
                        f"{self.research_provider_identity['version']} is admitted."
                        if self.research_provider_identity
                        else "No external ResearchProvider is injected."
                    ),
                },
                {
                    "capability": "planning_review_and_repair",
                    "status": "available",
                    "detail": "Deterministic Planning Review and bounded local repair are available.",
                },
                {
                    "capability": "wireframe_generation",
                    "status": "available",
                    "detail": "Content-addressed deterministic SVG planning wireframes are available.",
                },
            ],
            "actions": actions,
            "blockers": sorted(blockers, key=lambda item: item["finding_id"]),
            "warnings": sorted(warnings, key=lambda item: item["finding_id"]),
            "outputs": {
                "artifact_refs": artifact_refs,
                "m2_reports": sorted(
                    {item["report_id"]: item for item in m2_reports}.values(),
                    key=lambda item: str(item["report_id"]),
                ),
                "planning_review": planning_review,
                "planning_repairs": sorted(
                    {item["repair_id"]: item for item in planning_repairs}.values(),
                    key=lambda item: str(item["repair_id"]),
                ),
                "wireframes": self._wireframe_refs() if actual_level == "P5B" else [],
                "final_phase": str(state["current_phase"]),
                "gates": self._gate_rows(),
            },
        }
        self._add_action(
            report["actions"],
            stage="report",
            status="complete",
            detail=(
                f"M3 application report finalized with status={status}, "
                f"planning_level={actual_level}."
            ),
        )
        return self._persist_report(report)

    def run(
        self,
        source_paths: tuple[Path, ...] = (),
        *,
        brief_hints: BriefCompletionHints | None = None,
        planning_limits: PlanningLimits | None = None,
        m2_limits: M2ApplicationLimits | None = None,
        allow_research_degraded: bool = False,
        approve_external_disclosure: bool = False,
        allow_high_risk_source_evidence: bool = False,
        auto_repair: bool = True,
        max_repair_passes: int = 2,
        reusable_m2_reports: dict[str, dict[str, Any] | None] | None = None,
    ) -> M3ApplicationRunResult:
        """Run/resume M3 from Brief completion through reviewed Layout Plans."""

        if not 0 <= max_repair_passes <= 10:
            raise M3ApplicationError("max_repair_passes must be between 0 and 10")
        hints = brief_hints or BriefCompletionHints()
        limits = planning_limits or PlanningLimits()
        admitted_m2_limits = m2_limits or M2ApplicationLimits()
        validate_planning_limits(limits)
        validate_brief_completion_hints(hints, limits)
        if (
            admitted_m2_limits.max_sources < 1
            or admitted_m2_limits.max_total_source_bytes < 1
        ):
            raise M3ApplicationError("M2 application limits must be positive")
        validate_source_parse_limits(admitted_m2_limits.source)
        validate_research_limits(admitted_m2_limits.research)
        initial = self.runtime.read_artifact_graph_snapshot(
            ("project_state", "project_brief")
        )
        initial_brief_ref = _artifact_ref(initial["project_brief"], "project_brief")
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        actions: list[dict[str, Any]] = []
        m2_reports: list[dict[str, Any]] = []
        repair_refs: list[dict[str, Any]] = []
        review_ref: dict[str, Any] | None = None
        requested_sources = self._source_fingerprints(
            source_paths,
            admitted_m2_limits,
            blockers,
        )
        config = {
            "brief_hints": _hints_payload(hints),
            "planning_limits": asdict(limits),
            "m2_limits": asdict(admitted_m2_limits),
            "allow_research_degraded": allow_research_degraded,
            "approve_external_disclosure": approve_external_disclosure,
            "allow_high_risk_source_evidence": allow_high_risk_source_evidence,
            "auto_repair": auto_repair,
            "max_repair_passes": max_repair_passes,
            "planning_provider": self.planning_provider_identity,
            "research_provider": self.research_provider_identity,
        }
        if blockers:
            self._add_action(
                actions,
                stage="brief",
                status="blocked",
                detail="One or more requested Source paths are unavailable.",
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status="blocked",
                planning_level="P0",
            )

        if requested_sources:
            source_service = SourceIngestionService(self.workspace)
            try:
                for fingerprint in requested_sources:
                    source_service.ingest(
                        Path(str(fingerprint["path"])),
                        limits=admitted_m2_limits.source,
                    )
            except SourceIngestionError as exc:
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="source_preinspection_failed",
                    message=str(exc),
                )
                self._add_action(
                    actions,
                    stage="brief",
                    status="blocked",
                    detail=(
                        "Source pre-inspection failed before Brief completion: " + str(exc)
                    ),
                )
                return self._finalize(
                    initial_brief_ref=initial_brief_ref,
                    requested_sources=requested_sources,
                    config=config,
                    actions=actions,
                    blockers=blockers,
                    warnings=warnings,
                    m2_reports=m2_reports,
                    planning_review=None,
                    planning_repairs=repair_refs,
                    status="blocked",
                    planning_level="P0",
                )
            self._add_action(
                actions,
                stage="brief",
                status="complete",
                detail=(
                    f"Safely pre-inspected {len(requested_sources)} Source(s) before material Brief questions."
                ),
            )

        try:
            brief_result = BriefCompletionService(self.workspace).complete(
                hints,
                limits=limits,
            )
        except SlidethusError as exc:
            self._add_finding(
                blockers,
                kind="blocker",
                code="brief_completion_failed",
                message=str(exc),
            )
            self._add_action(
                actions,
                stage="brief",
                status="failed",
                detail=str(exc),
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status="failed",
                planning_level="P0",
            )
        current_brief_graph = self.runtime.read_artifact_graph_snapshot(("project_brief",))
        initial_brief_ref = _artifact_ref(
            current_brief_graph["project_brief"],
            "project_brief",
        )
        self._add_action(
            actions,
            stage="brief",
            status="complete" if brief_result.status == "resolved" else "blocked",
            detail=(
                "Project Brief is resolved with bounded assumptions/questions."
                if brief_result.status == "resolved"
                else f"Project Brief requires {len(brief_result.blocking_questions)} material answer(s)."
            ),
            refs=tuple(item["question_id"] for item in brief_result.blocking_questions),
        )
        if brief_result.status != "resolved":
            self._add_finding(
                blockers,
                kind="blocker",
                code="brief_needs_input",
                message=(
                    "Project Brief has unresolved material questions: "
                    + ", ".join(item["question_id"] for item in brief_result.blocking_questions)
                ),
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status="needs_input",
                planning_level="P0",
            )

        if not self._ensure_gate(
            "G0",
            actions=actions,
            blockers=blockers,
            stage="brief",
        ):
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status="blocked",
                planning_level="P0",
            )

        reusable_orientation_ref = (reusable_m2_reports or {}).get("orientation")
        orientation_report = self._reusable_m2_report(
            reusable_orientation_ref,
            stage="orientation",
            requested_sources=requested_sources,
            limits=admitted_m2_limits,
            allow_research_degraded=allow_research_degraded,
            approve_external_disclosure=approve_external_disclosure,
            allow_high_risk_source_evidence=allow_high_risk_source_evidence,
        )
        if orientation_report is not None:
            m2_reports.append(copy.deepcopy(reusable_orientation_ref))
            requested_sources = list(
                orientation_report["inputs"]["requested_sources"]
            )
            self._add_action(
                actions,
                stage="m2_orientation",
                status="complete",
                detail=(
                    "Reused the exact current M2 orientation report bound to "
                    "the current Brief/Source/Evidence facts."
                ),
                refs=(str(orientation_report["report_id"]),),
            )
        else:
            try:
                orientation = M2ApplicationService(
                    self.workspace,
                    research_provider=self.research_provider,
                ).run(
                    source_paths,
                    limits=admitted_m2_limits,
                    allow_research_degraded=allow_research_degraded,
                    approve_external_disclosure=approve_external_disclosure,
                    allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                    advance_existing_planning=False,
                )
            except SlidethusError as exc:
                self._add_action(
                    actions,
                    stage="m2_orientation",
                    status="failed",
                    detail=str(exc),
                )
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="m2_orientation_failed",
                    message=str(exc),
                )
                return self._finalize(
                    initial_brief_ref=initial_brief_ref,
                    requested_sources=requested_sources,
                    config=config,
                    actions=actions,
                    blockers=blockers,
                    warnings=warnings,
                    m2_reports=m2_reports,
                    planning_review=None,
                    planning_repairs=repair_refs,
                    status="failed",
                )
            orientation_report = orientation.report
            m2_reports.append(self._m2_ref(orientation))
            requested_sources = list(
                orientation_report["inputs"]["requested_sources"]
            )
            self._add_action(
                actions,
                stage="m2_orientation",
                status=(
                    "complete"
                    if orientation_report["status"] in {"ready", "degraded"}
                    else "blocked"
                ),
                detail=(
                    "M2 orientation completed with "
                    f"status={orientation_report['status']}."
                ),
                refs=(str(orientation_report["report_id"]),),
            )
        if orientation_report["status"] not in {"ready", "degraded"}:
            self._add_finding(
                blockers,
                kind="blocker",
                code="m2_orientation_not_ready",
                message=(
                    "M2 orientation cannot support planning: "
                    f"{orientation_report['status']}"
                ),
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status="blocked",
                planning_level="P2",
            )
        if orientation_report["status"] == "degraded":
            self._add_finding(
                warnings,
                kind="warning",
                code="m2_research_degraded",
                message="M3 is using an explicitly degraded M2 research boundary.",
            )

        try:
            self._assert_planning_provider_identity()
            narrative = NarrativePlanningService(
                self.workspace,
                provider=self.planning_provider,
            ).generate(limits=limits)
            self._assert_planning_provider_identity()
            self._add_action(
                actions,
                stage="narrative",
                status="complete",
                detail=f"Production Narrative version {narrative.version} is current.",
            )
            if not self._ensure_gate(
                "G3",
                actions=actions,
                blockers=blockers,
                stage="narrative",
            ):
                raise M3ApplicationError("G3 did not pass after Narrative generation")

            self._assert_planning_provider_identity()
            outline = OutlinePlanningService(
                self.workspace,
                provider=self.planning_provider,
            ).generate(limits=limits)
            self._assert_planning_provider_identity()
            self._add_action(
                actions,
                stage="outline",
                status="complete",
                detail=f"Production Deck Outline version {outline.version} is current.",
            )
            if not self._ensure_gate(
                "G4",
                actions=actions,
                blockers=blockers,
                stage="outline",
            ):
                raise M3ApplicationError("G4 did not pass after Outline generation")

            self._assert_planning_provider_identity()
            specs = SlideSpecPlanningService(
                self.workspace,
                provider=self.planning_provider,
            ).generate(limits=limits)
            self._assert_planning_provider_identity()
            self._add_action(
                actions,
                stage="slide_specs",
                status="complete",
                detail=f"Production Slide Specs version {specs.version} are current.",
            )
        except SlidethusError as exc:
            self._add_finding(
                blockers,
                kind="blocker",
                code="planning_generation_failed",
                message=str(exc),
            )
            self._add_action(
                actions,
                stage="rework",
                status="failed",
                detail=str(exc),
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status="failed",
            )

        reusable_targeted_ref = (reusable_m2_reports or {}).get("targeted")
        targeted_report = self._reusable_m2_report(
            reusable_targeted_ref,
            stage="targeted",
            requested_sources=requested_sources,
            limits=admitted_m2_limits,
            allow_research_degraded=allow_research_degraded,
            approve_external_disclosure=approve_external_disclosure,
            allow_high_risk_source_evidence=allow_high_risk_source_evidence,
        )
        if targeted_report is not None:
            m2_reports.append(copy.deepcopy(reusable_targeted_ref))
            self._add_action(
                actions,
                stage="m2_targeted",
                status="complete",
                detail=(
                    "Reused the exact current targeted M2 report bound to the "
                    "current Outline/Slide Specs/Evidence facts."
                ),
                refs=(str(targeted_report["report_id"]),),
            )
        else:
            try:
                targeted = M2ApplicationService(
                    self.workspace,
                    research_provider=self.research_provider,
                ).run(
                    (),
                    limits=admitted_m2_limits,
                    allow_research_degraded=allow_research_degraded,
                    approve_external_disclosure=approve_external_disclosure,
                    allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                    advance_existing_planning=True,
                )
            except SlidethusError as exc:
                self._add_action(
                    actions,
                    stage="m2_targeted",
                    status="failed",
                    detail=str(exc),
                )
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="m2_targeted_failed",
                    message=str(exc),
                )
                return self._finalize(
                    initial_brief_ref=initial_brief_ref,
                    requested_sources=requested_sources,
                    config=config,
                    actions=actions,
                    blockers=blockers,
                    warnings=warnings,
                    m2_reports=m2_reports,
                    planning_review=None,
                    planning_repairs=repair_refs,
                    status="failed",
                )
            targeted_report = targeted.report
            m2_reports.append(self._m2_ref(targeted))
            self._add_action(
                actions,
                stage="m2_targeted",
                status=(
                    "complete"
                    if targeted_report["status"] in {"ready", "degraded"}
                    else "blocked"
                ),
                detail=(
                    "M2 targeted Evidence integration ended with "
                    f"status={targeted_report['status']}."
                ),
                refs=(str(targeted_report["report_id"]),),
            )
        if targeted_report["status"] not in {"ready", "degraded"}:
            self._add_finding(
                blockers,
                kind="blocker",
                code="m2_targeted_not_ready",
                message=(
                    "Targeted Evidence integration requires rework: "
                    f"{targeted_report['status']}"
                ),
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status=(
                    "rework_required"
                    if targeted_report["status"] == "rework_required"
                    else "blocked"
                ),
            )

        try:
            self._assert_planning_provider_identity()
            layout = LayoutPlanningService(
                self.workspace,
                provider=self.planning_provider,
            ).generate(limits=limits)
            self._assert_planning_provider_identity()
            self._add_action(
                actions,
                stage="layout",
                status="complete",
                detail=(
                    f"Production Layout Plans version {layout.version} and "
                    f"{len(layout.wireframe_paths)} wireframes are current."
                ),
            )
            if not self._ensure_gate(
                "G5B",
                actions=actions,
                blockers=blockers,
                stage="layout",
            ):
                raise M3ApplicationError("G5B did not pass after Layout generation")
            review = PlanningReviewService(self.workspace).analyze()
        except SlidethusError as exc:
            self._add_finding(
                blockers,
                kind="blocker",
                code="layout_or_review_failed",
                message=str(exc),
            )
            self._add_action(
                actions,
                stage="planning_review",
                status="failed",
                detail=str(exc),
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=None,
                planning_repairs=repair_refs,
                status="failed",
            )

        review_ref = self._review_ref(review)
        self._add_action(
            actions,
            stage="planning_review",
            status="complete",
            detail=(
                f"Planning Review found {review.report['summary']['critical_count']} Critical, "
                f"{review.report['summary']['major_count']} Major and "
                f"{review.report['summary']['minor_count']} Minor issue(s)."
            ),
            refs=(review.report["report_id"],),
        )

        for pass_index in range(max_repair_passes if auto_repair else 0):
            automatic_ids = tuple(
                str(item["issue_id"])
                for item in review.report.get("issues", [])
                if item.get("status") == "open"
                and item.get("repairability") == "automatic"
            )
            if not automatic_ids:
                break
            self._assert_planning_provider_identity()
            try:
                repair = PlanningRepairService(
                    self.workspace,
                    provider=self.planning_provider,
                ).apply(
                    review.report["report_id"],
                    issue_ids=automatic_ids,
                    reason=f"M3 application automatic repair pass {pass_index + 1}",
                    limits=limits,
                )
            except SlidethusError as exc:
                self._add_action(
                    actions,
                    stage="planning_repair",
                    status="failed",
                    detail=(
                        f"Automatic repair pass {pass_index + 1} failed after safe "
                        f"checkpointing: {exc}"
                    ),
                )
                self._add_finding(
                    blockers,
                    kind="blocker",
                    code="planning_repair_failed",
                    message=str(exc),
                )
                return self._finalize(
                    initial_brief_ref=initial_brief_ref,
                    requested_sources=requested_sources,
                    config=config,
                    actions=actions,
                    blockers=blockers,
                    warnings=warnings,
                    m2_reports=m2_reports,
                    planning_review=review_ref,
                    planning_repairs=repair_refs,
                    status="failed",
                )
            self._assert_planning_provider_identity()
            repair_refs.append(self._repair_ref(repair))
            self._add_action(
                actions,
                stage="planning_repair",
                status="complete" if repair.report["status"] == "applied" else "blocked",
                detail=(
                    f"Automatic repair pass {pass_index + 1} ended with "
                    f"status={repair.report['status']}."
                ),
                refs=(repair.report["repair_id"],),
            )
            if repair.report["status"] != "applied" or repair.report.get("result_review") is None:
                break
            result_review_id = str(repair.report["result_review"]["report_id"])
            found = find_planning_review_report(
                self.workspace,
                result_review_id,
                schema_dir=self.schemas.schema_dir,
            )
            if found is None:
                raise M3ApplicationError(
                    f"Planning Repair result review is missing: {result_review_id}"
                )
            path, data = found
            review = type("PlanningReviewProxy", (), {"path": path, "report": data})()
            review_ref = self._review_ref(review)

        summary = review.report["summary"]
        blocking_count = int(summary["critical_count"]) + int(summary["major_count"])
        if blocking_count:
            target = review.report.get("target_phase")
            if target is not None:
                target_phase = Phase(str(target))
                current = Phase(
                    str(self.runtime.show_artifact("project_state")["current_phase"])
                )
                if _phase_index(current) > _phase_index(target_phase):
                    self.runtime.route_rework(
                        target_phase,
                        reason=(
                            f"Planning Review {review.report['report_id']} retains "
                            f"{blocking_count} Critical/Major issue(s)."
                        ),
                    )
                    self._add_action(
                        actions,
                        stage="rework",
                        status="complete",
                        detail=f"Workflow routed to {target_phase.value} from Planning Review.",
                        refs=(review.report["report_id"],),
                    )
            self._add_finding(
                blockers,
                kind="blocker",
                code="planning_review_requires_rework",
                message=(
                    f"Planning Review retains {blocking_count} Critical/Major issue(s)."
                ),
            )
            return self._finalize(
                initial_brief_ref=initial_brief_ref,
                requested_sources=requested_sources,
                config=config,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                m2_reports=m2_reports,
                planning_review=review_ref,
                planning_repairs=repair_refs,
                status="rework_required",
                planning_level=(
                    _REWORK_LEVEL.get(str(target))
                    if target is not None
                    else None
                ),
            )
        if int(summary["minor_count"]):
            self._add_finding(
                warnings,
                kind="warning",
                code="planning_minor_issues_remain",
                message=(
                    f"Planning Review retains {summary['minor_count']} non-blocking Minor issue(s)."
                ),
            )
        return self._finalize(
            initial_brief_ref=initial_brief_ref,
            requested_sources=requested_sources,
            config=config,
            actions=actions,
            blockers=blockers,
            warnings=warnings,
            m2_reports=m2_reports,
            planning_review=review_ref,
            planning_repairs=repair_refs,
            status="ready",
            planning_level="P5B",
        )


def evaluate_m3_workspace_gate(workspace: Path) -> dict[str, Any]:
    """Evaluate current M3 planning readiness without mutating the workspace."""

    workspace = workspace.resolve()
    gates: list[dict[str, Any]] = []
    reasons: list[str] = []
    for gate_id in ("G0", "G2", "G3", "G4", "G5A", "G5B"):
        result = evaluate_gate(workspace, gate_id)
        gates.append(
            {
                "gate_id": gate_id,
                "status": result.status,
                "reasons": list(result.reasons),
            }
        )
        if not result.passed:
            reasons.extend(f"{gate_id}:{reason}" for reason in result.reasons)
    review = None
    if not reasons:
        try:
            review_result = PlanningReviewService(workspace).analyze(persist=False)
        except SlidethusError as exc:
            reasons.append(f"planning_review:{exc}")
        else:
            review = {
                "report_id": review_result.report["report_id"],
                "summary": review_result.report["summary"],
            }
            if int(review_result.report["summary"]["critical_count"]) or int(
                review_result.report["summary"]["major_count"]
            ):
                reasons.append("planning_review:Critical/Major issues remain")
    return {
        "status": "pass" if not reasons else "fail",
        "reasons": reasons,
        "gates": gates,
        "planning_review": review,
    }
