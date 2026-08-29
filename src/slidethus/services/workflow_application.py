from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import SlidethusError, WorkflowApplicationError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import (
    atomic_create_json,
    canonical_json_bytes,
    read_json,
    sha256_file,
    sha256_json,
)
from slidethus.protocols import (
    BriefCompletionHints,
    PlanningProvider,
    ResearchProvider,
    SemanticReviewProvider,
    VisualReviewProvider,
    WorkflowCostMeter,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.m5_application import M5ApplicationService
from slidethus.services.outline_changes import OutlineChangeService
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.services.style_extraction import extract_pptx_style_candidate
from slidethus.state_machine import FORWARD_SEQUENCE, Phase, can_transition
from slidethus.workflow_application_reports import (
    validate_workflow_report_data,
    workflow_report_file_key,
    workflow_report_id,
    workflow_request_hash,
)
from slidethus.workflow_operations import (
    WorkflowLease,
    WorkflowOperationalLimits,
    find_cached_workflow_result,
    persist_workflow_event,
    persist_workflow_operation,
    recover_incomplete_workflow_attempts,
    utc_now,
    workflow_attempt_id,
    workflow_event_workspace_errors,
    workflow_operation_workspace_errors,
)
from slidethus.workspace import init_workspace

_WORKFLOW_POLICY = {
    "create": "create_workspace",
    "rebuild": "rebuild_workspace",
    "improve": "admitted_repair",
    "audit": "review_only",
    "revise": "target_scoped_change",
    "extract_style": "style_candidate",
}
_TRACKED = (
    "asset_manifest",
    "deck_outline",
    "evidence_ledger",
    "layout_plans",
    "narrative_blueprint",
    "project_brief",
    "quality_report",
    "render_manifest",
    "slide_specs",
    "source_ledger",
    "visual_system",
)
_FROZEN_TRUTH = tuple(item for item in _TRACKED if item != "quality_report")
_REBUILD_SUFFIXES = {".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class WorkflowRequest:
    workflow: str
    title: str = "Slidethus Workflow"
    source_paths: tuple[Path, ...] = ()
    brief_hints: BriefCompletionHints | None = None
    auto_repair: bool = True
    slide_updates: dict[str, dict[str, Any]] | None = None
    reason: str = ""


@dataclass(frozen=True)
class WorkflowApplicationResult:
    report: dict[str, Any]
    path: Path
    changed: bool


def _artifact_refs(workspace: Path, artifact_types: tuple[str, ...]) -> list[dict[str, Any]]:
    state = read_json(workspace / "project_state.json")
    entries = {str(item.get("artifact_type")): item for item in state.get("artifacts", [])}
    refs = []
    for artifact_type in artifact_types:
        entry = entries.get(artifact_type)
        if entry is None:
            continue
        refs.append(
            {
                "artifact_type": artifact_type,
                "version": int(entry["version"]),
                "content_hash": str(entry["content_hash"]),
            }
        )
    return sorted(refs, key=lambda item: item["artifact_type"])


def _changed(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    def values(rows: list[dict[str, Any]]) -> dict[str, tuple[int, str]]:
        return {
            str(item["artifact_type"]): (int(item["version"]), str(item["content_hash"]))
            for item in rows
        }

    left = values(before)
    right = values(after)
    return sorted(name for name in set(left) | set(right) if left.get(name) != right.get(name))


def _output_ref(workspace: Path, kind: str, ref_id: str, path: Path) -> dict[str, Any]:
    return {
        "kind": kind,
        "ref_id": ref_id,
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
    }


class WorkflowApplicationService:
    """Single M6 dispatcher above the frozen M2-M5 Production boundaries."""

    def __init__(
        self,
        workspace: Path,
        *,
        planning_provider: PlanningProvider | None = None,
        research_provider: ResearchProvider | None = None,
        semantic_provider: SemanticReviewProvider | None = None,
        visual_provider: VisualReviewProvider | None = None,
        renderer_root: Path | None = None,
        node: str | None = None,
        font_match: str | None = None,
        operational_limits: WorkflowOperationalLimits | None = None,
        cost_meter: WorkflowCostMeter | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.planning_provider = planning_provider
        self.research_provider = research_provider
        self.semantic_provider = semantic_provider
        self.visual_provider = visual_provider
        self.renderer_root = renderer_root
        self.node = node
        self.font_match = font_match
        self.operational_limits = operational_limits or WorkflowOperationalLimits()
        self.operational_limits.validate()
        self.cost_meter = cost_meter
        self.schemas = schema_registry or SchemaRegistry()
        self.report_dir = self.workspace / ".slidethus/workflows/runs"
        self._deadline_ns: int | None = None
        self._active_workflow: str | None = None
        self._cost_start_usd: float | None = None

    def _uses_external_provider(self, workflow: str) -> bool:
        if workflow == "extract_style":
            return False
        return any(
            provider is not None
            for provider in (
                self.planning_provider,
                self.research_provider,
                self.semantic_provider,
                self.visual_provider,
            )
        )

    def _meter_value(self) -> float:
        if self.cost_meter is None:
            raise WorkflowApplicationError("Workflow cost meter is unavailable")
        value = float(self.cost_meter.current_cost_usd())
        if not math.isfinite(value) or value < 0:
            raise WorkflowApplicationError("Workflow cost meter returned an invalid USD value")
        return value

    def _provider_cost_snapshot(self, workflow: str) -> tuple[float | None, str]:
        if not self._uses_external_provider(workflow):
            return 0.0, "not_applicable"
        if self.cost_meter is None:
            return None, "not_measured"
        current = self._meter_value()
        baseline = self._cost_start_usd if self._cost_start_usd is not None else current
        return max(0.0, current - baseline), "measured"

    def _operation_cost_fields(self, workflow: str) -> dict[str, Any]:
        cost, status = self._provider_cost_snapshot(workflow)
        return {"provider_cost_usd": cost, "provider_cost_status": status}

    def _check_deadline(self, stage: str) -> None:
        if self._deadline_ns is not None and time.monotonic_ns() > self._deadline_ns:
            raise WorkflowApplicationError(
                f"Workflow wall-time budget exceeded before/after stage: {stage}"
            )
        workflow = self._active_workflow
        limit = self.operational_limits.max_provider_cost_usd
        if workflow is not None and limit is not None and self._uses_external_provider(workflow):
            if self.cost_meter is None:
                raise WorkflowApplicationError(
                    "Workflow provider-cost budget requires an injected WorkflowCostMeter"
                )
            current, _status = self._provider_cost_snapshot(workflow)
            if current is not None and current > limit:
                raise WorkflowApplicationError(
                    f"Workflow provider cost ${current:.6f} exceeds max_provider_cost_usd=${limit:.6f} at {stage}"
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
                "action_id": f"WFA-{len(actions) + 1:03d}",
                "stage": stage,
                "status": status,
                "detail": " ".join(detail.split()).strip(),
                "refs": sorted(set(str(item) for item in refs)),
            }
        )

    def _capabilities(self, workflow: str) -> list[dict[str, str]]:
        implemented = workflow in _WORKFLOW_POLICY
        rows = [
            {
                "capability": "semantic_review",
                "status": "available" if self.semantic_provider is not None else "missing",
                "detail": "Injected SemanticReviewProvider is available."
                if self.semantic_provider is not None
                else "No SemanticReviewProvider was injected.",
            },
            {
                "capability": "visual_review",
                "status": "available" if self.visual_provider is not None else "missing",
                "detail": "Injected VisualReviewProvider is available."
                if self.visual_provider is not None
                else "No VisualReviewProvider was injected.",
            },
            {
                "capability": "workflow_implementation",
                "status": "available" if implemented else "missing",
                "detail": (
                    f"{workflow} is implemented in the current M6.1 dispatcher."
                    if implemented
                    else f"{workflow} is not yet implemented in the current M6.1 increment."
                ),
            },
        ]
        return sorted(rows, key=lambda item: item["capability"])

    def _request_payload(self, request: WorkflowRequest) -> dict[str, Any]:
        source_rows = []
        for path in request.source_paths:
            admitted = path.resolve()
            if not admitted.is_file():
                raise WorkflowApplicationError(f"Workflow source does not exist: {admitted}")
            source_rows.append(
                {
                    "name": admitted.name,
                    "suffix": admitted.suffix.lower(),
                    "sha256": sha256_file(admitted),
                }
            )
        hints = asdict(request.brief_hints) if request.brief_hints is not None else None
        slide_updates = request.slide_updates or {}
        return {
            "workflow": request.workflow,
            "title": request.title.strip(),
            "sources": sorted(source_rows, key=lambda item: (item["name"], item["sha256"])),
            "brief_hints": hints,
            "auto_repair": bool(request.auto_repair),
            "slide_updates": {key: slide_updates[key] for key in sorted(slide_updates)},
            "reason": " ".join(request.reason.split()).strip(),
        }

    def _execution_signature(self) -> str:
        def identity(provider: Any | None) -> dict[str, str]:
            if provider is None:
                return {"name": "missing", "version": "missing"}
            return {
                "name": str(getattr(provider, "name", "unknown")),
                "version": str(getattr(provider, "version", "unknown")),
            }

        repository = Path(__file__).resolve().parents[3]
        renderer = (self.renderer_root or (repository / "renderers/pptxgenjs")).resolve()
        lock = renderer / "package-lock.json"
        payload = {
            "planning_provider": identity(self.planning_provider),
            "research_provider": identity(self.research_provider),
            "semantic_provider": identity(self.semantic_provider),
            "visual_provider": identity(self.visual_provider),
            "cost_meter": identity(self.cost_meter),
            "operational_limits": asdict(self.operational_limits),
            "renderer_lock_sha256": sha256_file(lock) if lock.is_file() else "missing",
            "node": self.node or "auto",
            "font_match": self.font_match or "auto",
        }
        return f"sha256:{sha256_json(payload)}"

    @staticmethod
    def _input_bytes(
        request: WorkflowRequest,
        request_payload: dict[str, Any],
    ) -> int:
        file_bytes = sum(path.resolve().stat().st_size for path in request.source_paths)
        return file_bytes + len(canonical_json_bytes(request_payload))

    def _budget_block(
        self,
        request: WorkflowRequest,
        *,
        request_hash: str,
        code: str,
        message: str,
    ) -> WorkflowApplicationResult:
        workflow = request.workflow.strip().lower()
        normalized = WorkflowRequest(**{**request.__dict__, "workflow": workflow})
        self._ensure_workspace(normalized)
        before = _artifact_refs(self.workspace, _TRACKED)
        actions: list[dict[str, Any]] = []
        self._add_action(
            actions,
            stage="operational_budget",
            status="blocked",
            detail=message,
        )
        return self._persist(
            workflow=workflow,
            request_hash=request_hash,
            status="blocked",
            capabilities=self._capabilities(workflow),
            actions=actions,
            artifacts_before=before,
            artifacts_after=before,
            outputs=[],
            gate_result={"gate_id": None, "status": "not_run", "reasons": [message]},
            blockers=[{"code": code, "message": message}],
        )

    def _persist_operation_terminal(
        self,
        *,
        project_id: str,
        attempt_id: str,
        workflow: str,
        request_hash: str,
        execution_signature: str,
        status: str,
        cache_status: str,
        started_at: str,
        started_ns: int,
        input_bytes: int,
        slide_updates: int,
        workflow_result: WorkflowApplicationResult | None,
        blockers: list[dict[str, str]],
        event_type: str,
        event_detail: str,
    ) -> Path:
        operation_path = persist_workflow_operation(
            self.workspace,
            schema_dir=self.schemas.schema_dir,
            project_id=project_id,
            attempt_id=attempt_id,
            workflow=workflow,
            request_hash=request_hash,
            execution_signature=execution_signature,
            status=status,
            cache_status=cache_status,
            started_at=started_at,
            started_monotonic_ns=started_ns,
            limits=self.operational_limits,
            input_bytes=input_bytes,
            slide_updates=slide_updates,
            workflow_result=workflow_result,
            blockers=blockers,
            **self._operation_cost_fields(workflow),
        )
        operation = read_json(operation_path)
        persist_workflow_event(
            self.workspace,
            schema_dir=self.schemas.schema_dir,
            project_id=project_id,
            attempt_id=attempt_id,
            workflow=workflow,
            request_hash=request_hash,
            execution_signature=execution_signature,
            event_type=event_type,
            sequence=2,
            detail=event_detail,
            operation_id=str(operation["operation_id"]),
        )
        return operation_path

    def _ensure_workspace(
        self,
        request: WorkflowRequest,
        *,
        allow_resume: bool = False,
    ) -> None:
        state = self.workspace / "project_state.json"
        if request.workflow in {"create", "rebuild"}:
            if state.is_file():
                current = read_json(state)
                if current.get("current_phase") != "CREATED" and not allow_resume:
                    raise WorkflowApplicationError(
                        f"{request.workflow} requires a new/stage-0 workspace; current phase={current.get('current_phase')}"
                    )
                return
            init_workspace(self.workspace, title=request.title)
            return
        if request.workflow == "extract_style" and not state.is_file():
            init_workspace(self.workspace, title=request.title)
            return
        if not state.is_file():
            raise WorkflowApplicationError(f"{request.workflow} requires an existing workspace")

    def _persist(
        self,
        *,
        workflow: str,
        request_hash: str,
        status: str,
        capabilities: list[dict[str, str]],
        actions: list[dict[str, Any]],
        artifacts_before: list[dict[str, Any]],
        artifacts_after: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        gate_result: dict[str, Any],
        blockers: list[dict[str, str]],
    ) -> WorkflowApplicationResult:
        state = read_json(self.workspace / "project_state.json")
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(state["project_id"]),
            "report_id": "",
            "workflow": workflow,
            "request_hash": request_hash,
            "mutation_policy": _WORKFLOW_POLICY[workflow],
            "status": status,
            "capabilities": capabilities,
            "actions": actions,
            "artifacts_before": artifacts_before,
            "artifacts_after": artifacts_after,
            "changed_artifacts": _changed(artifacts_before, artifacts_after),
            "outputs": outputs,
            "final_phase": str(state["current_phase"]),
            "gate_result": gate_result,
            "blockers": blockers,
        }
        report["report_id"] = workflow_report_id(report)
        errors = validate_workflow_report_data(report, self.schemas.schema_dir)
        if errors:
            raise WorkflowApplicationError(
                "Invalid Workflow Application Report: " + "; ".join(errors)
            )
        path = self.report_dir / f"{workflow_report_file_key(report)}.json"
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise WorkflowApplicationError(
                f"Immutable Workflow Application Report contains different content: {path}"
            )
        return WorkflowApplicationResult(report=report, path=path, changed=changed)

    def _run_m3_m4_m5(
        self,
        request: WorkflowRequest,
        actions: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
        blockers: list[dict[str, str]] = []
        self._check_deadline("m3")
        m3 = M3ApplicationService(
            self.workspace,
            planning_provider=self.planning_provider,
            research_provider=self.research_provider,
        ).run(request.source_paths, brief_hints=request.brief_hints)
        outputs.append(_output_ref(self.workspace, "m3_application", str(m3.report["report_id"]), m3.path))
        self._add_action(
            actions,
            stage="planning",
            status="complete" if m3.report["status"] == "ready" else "blocked",
            detail=f"M3 application status={m3.report['status']}.",
            refs=(str(m3.report["report_id"]),),
        )
        if m3.report["status"] != "ready":
            blockers.append({"code": "m3_not_ready", "message": "Workflow planning did not reach M3 ready."})
            return "blocked", {"gate_id": None, "status": "not_run", "reasons": ["M3 not ready"]}, blockers

        self._check_deadline("m3")
        self._check_deadline("m4")
        m4 = M4ApplicationService(
            self.workspace,
            renderer_root=self.renderer_root,
            node=self.node,
            font_match=self.font_match,
        ).run()
        outputs.append(_output_ref(self.workspace, "m4_application", str(m4.report["report_id"]), m4.path))
        self._add_action(
            actions,
            stage="render",
            status="complete" if m4.report["status"] == "ready" else "blocked",
            detail=f"M4 application status={m4.report['status']}.",
            refs=(str(m4.report["report_id"]),),
        )
        if m4.report["status"] != "ready":
            blockers.append({"code": "m4_not_ready", "message": "Workflow rendering did not reach M4 ready."})
            return "blocked", {"gate_id": "G7", "status": "fail", "reasons": ["M4 not ready"]}, blockers

        self._check_deadline("m4")
        self._check_deadline("m5")
        m5 = M5ApplicationService(
            self.workspace,
            semantic_provider=self.semantic_provider,
            visual_provider=self.visual_provider,
            renderer_root=self.renderer_root,
            node=self.node,
            font_match=self.font_match,
        ).run(auto_repair=request.auto_repair)
        outputs.append(_output_ref(self.workspace, "m5_application", str(m5.report["report_id"]), m5.path))
        self._add_action(
            actions,
            stage="review",
            status="complete" if m5.report["status"] == "ready" else "blocked",
            detail=f"M5 application status={m5.report['status']}.",
            refs=(str(m5.report["report_id"]),),
        )
        self._check_deadline("m5")
        if m5.report["status"] != "ready":
            blockers.extend(
                {"code": str(item["code"]), "message": str(item["message"])}
                for item in m5.report.get("blockers", [])
            )
            return "blocked", {
                "gate_id": "G8",
                "status": "blocked" if m5.report["status"] == "blocked" else "fail",
                "reasons": list(m5.report.get("g8", {}).get("reasons", [])),
            }, blockers
        return "ready", {"gate_id": "G8", "status": "pass", "reasons": []}, blockers

    def _record_gate(self, gate_id: str, target: Phase) -> None:
        result = evaluate_gate(self.workspace, gate_id)
        if not result.passed:
            raise WorkflowApplicationError(
                f"Workflow cannot record {gate_id}: " + "; ".join(result.reasons)
            )
        runtime = ArtifactRuntime(self.workspace)
        current = Phase(str(runtime.show_artifact("project_state")["current_phase"]))
        target_phase: Phase | None = None
        if FORWARD_SEQUENCE.index(current) < FORWARD_SEQUENCE.index(target):
            if not can_transition(current, target):
                raise WorkflowApplicationError(
                    f"Workflow cannot advance {gate_id}: {current.value} -> {target.value}"
                )
            target_phase = target
        runtime.record_gate(
            gate_id,
            approved_by="workflow-application-service",
            target_phase=target_phase,
        )

    def _m5(self, *, auto_repair: bool):
        return M5ApplicationService(
            self.workspace,
            semantic_provider=self.semantic_provider,
            visual_provider=self.visual_provider,
            renderer_root=self.renderer_root,
            node=self.node,
            font_match=self.font_match,
        ).run(auto_repair=auto_repair)

    def _run_improve(
        self,
        request: WorkflowRequest,
        actions: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any], list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
        before = _artifact_refs(self.workspace, _TRACKED)
        self._check_deadline("improve_audit")
        audit = self._m5(auto_repair=False)
        self._check_deadline("improve_audit")
        outputs.append(_output_ref(self.workspace, "m5_audit", str(audit.report["report_id"]), audit.path))
        self._add_action(
            actions,
            stage="improve_audit",
            status="complete" if audit.report["status"] == "ready" else "blocked",
            detail=f"Improve audit status={audit.report['status']} with automatic repair disabled.",
            refs=(str(audit.report["report_id"]),),
        )
        final = audit
        if audit.report["status"] != "ready" and request.auto_repair:
            self._check_deadline("improve_repair")
            final = self._m5(auto_repair=True)
            self._check_deadline("improve_repair")
            if final.path != audit.path:
                outputs.append(
                    _output_ref(
                        self.workspace,
                        "m5_improve",
                        str(final.report["report_id"]),
                        final.path,
                    )
                )
            self._add_action(
                actions,
                stage="improve_repair",
                status="complete" if final.report["status"] == "ready" else "blocked",
                detail=f"Improve admitted repair status={final.report['status']}.",
                refs=(str(final.report["report_id"]),),
            )
        after = _artifact_refs(self.workspace, _TRACKED)
        blockers = [
            {"code": str(item["code"]), "message": str(item["message"])}
            for item in final.report.get("blockers", [])
        ]
        status = "ready" if final.report["status"] == "ready" else "blocked"
        gate = {
            "gate_id": "G8",
            "status": "pass" if final.report.get("g8", {}).get("status") == "pass" else "blocked",
            "reasons": list(final.report.get("g8", {}).get("reasons", [])),
        }
        return status, gate, blockers, before, after

    def _run_revise(
        self,
        request: WorkflowRequest,
        actions: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any], list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
        updates = request.slide_updates or {}
        if not updates:
            raise WorkflowApplicationError("revise requires at least one structured slide update")
        reason = " ".join(request.reason.split()).strip() or "M6 Revise Slide workflow"
        before = _artifact_refs(self.workspace, _TRACKED)
        change_service = OutlineChangeService(self.workspace)
        for slide_id in sorted(updates):
            change = change_service.update(
                slide_id,
                updates[slide_id],
                reason=reason,
                idempotency_key=f"workflow-revise:{workflow_request_hash({'slide_id': slide_id, 'changes': updates[slide_id], 'reason': reason})}",
            )
            self._add_action(
                actions,
                stage="revise_outline",
                status="complete",
                detail=f"Updated admitted Outline fields for {slide_id}.",
                refs=(slide_id, str(change.report["change_id"])),
            )

        self._record_gate("G4", Phase.OUTLINE_READY)
        SlideSpecPlanningService(
            self.workspace,
            provider=self.planning_provider,
        ).generate(force=True, created_by="workflow-revise")
        self._add_action(
            actions,
            stage="revise_slide_specs",
            status="complete",
            detail="Regenerated Slide Specs from the revised Outline.",
            refs=tuple(sorted(updates)),
        )
        EvidenceBindingService(self.workspace).complete_user_material_targeted_cycle()
        for gate_id, target in (
            ("G2", Phase.EVIDENCE_READY),
            ("G3", Phase.NARRATIVE_READY),
            ("G4", Phase.OUTLINE_READY),
            ("G5A", Phase.SLIDE_SPECS_READY),
        ):
            self._record_gate(gate_id, target)
        LayoutPlanningService(
            self.workspace,
            provider=self.planning_provider,
        ).generate(force=True, created_by="workflow-revise")
        self._record_gate("G5B", Phase.LAYOUT_READY)
        self._add_action(
            actions,
            stage="revise_layout",
            status="complete",
            detail="Regenerated Layout Plans and wireframes after the target-scoped revision.",
            refs=tuple(sorted(updates)),
        )

        self._check_deadline("revise_render")
        m4 = M4ApplicationService(
            self.workspace,
            renderer_root=self.renderer_root,
            node=self.node,
            font_match=self.font_match,
        ).run()
        outputs.append(_output_ref(self.workspace, "m4_application", str(m4.report["report_id"]), m4.path))
        if m4.report["status"] != "ready":
            after = _artifact_refs(self.workspace, _TRACKED)
            return (
                "blocked",
                {"gate_id": "G7", "status": "fail", "reasons": ["M4 not ready after revision"]},
                [{"code": "m4_not_ready", "message": "Revision rendering did not reach M4 ready."}],
                before,
                after,
            )
        self._add_action(
            actions,
            stage="revise_render",
            status="complete",
            detail="Rendered the revised current graph through M4.",
            refs=(str(m4.report["report_id"]),),
        )
        self._check_deadline("revise_render")
        self._check_deadline("revise_review")
        m5 = self._m5(auto_repair=request.auto_repair)
        self._check_deadline("revise_review")
        outputs.append(_output_ref(self.workspace, "m5_application", str(m5.report["report_id"]), m5.path))
        self._add_action(
            actions,
            stage="revise_regression",
            status="complete" if m5.report["status"] == "ready" else "blocked",
            detail=f"Revision M5 regression status={m5.report['status']}.",
            refs=(str(m5.report["report_id"]),),
        )
        after = _artifact_refs(self.workspace, _TRACKED)
        blockers = [
            {"code": str(item["code"]), "message": str(item["message"])}
            for item in m5.report.get("blockers", [])
        ]
        return (
            "ready" if m5.report["status"] == "ready" else "blocked",
            {
                "gate_id": "G8",
                "status": "pass" if m5.report.get("g8", {}).get("status") == "pass" else "blocked",
                "reasons": list(m5.report.get("g8", {}).get("reasons", [])),
            },
            blockers,
            before,
            after,
        )

    def _run_extract_style(
        self,
        request: WorkflowRequest,
        actions: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any], list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
        if len(request.source_paths) != 1 or request.source_paths[0].suffix.lower() != ".pptx":
            raise WorkflowApplicationError("extract_style requires exactly one PPTX reference")
        source = request.source_paths[0].resolve()
        original = sha256_file(source)
        before = _artifact_refs(self.workspace, _TRACKED)
        self._check_deadline("extract_style")
        result = extract_pptx_style_candidate(self.workspace, source)
        self._check_deadline("extract_style")
        outputs.append(
            _output_ref(
                self.workspace,
                "visual_system_candidate",
                str(result.candidate["theme_id"]),
                result.path,
            )
        )
        if sha256_file(source) != original:
            raise WorkflowApplicationError("Extract Style modified the reference PPTX")
        self._add_action(
            actions,
            stage="extract_style",
            status="complete",
            detail=(
                "Extracted schema-valid reusable PPTX style tokens; font/media bytes were not copied."
            ),
            refs=(str(result.candidate["theme_id"]),),
        )
        after = _artifact_refs(self.workspace, _TRACKED)
        return (
            "ready",
            {"gate_id": None, "status": "not_run", "reasons": []},
            [],
            before,
            after,
        )

    def _run_once(
        self,
        request: WorkflowRequest,
        *,
        allow_resume: bool = False,
    ) -> WorkflowApplicationResult:
        workflow = request.workflow.strip().lower()
        if workflow not in _WORKFLOW_POLICY:
            raise WorkflowApplicationError(f"Unknown workflow: {workflow}")
        if not request.title.strip():
            raise WorkflowApplicationError("Workflow title must not be blank")
        if workflow in {"create", "rebuild"} and not request.source_paths:
            raise WorkflowApplicationError(f"{workflow} requires at least one source")
        if workflow == "rebuild" and any(
            path.suffix.lower() not in _REBUILD_SUFFIXES for path in request.source_paths
        ):
            raise WorkflowApplicationError(
                "rebuild sources must be PPTX, PDF, or image references"
            )
        if workflow == "extract_style" and (
            len(request.source_paths) != 1 or request.source_paths[0].suffix.lower() != ".pptx"
        ):
            raise WorkflowApplicationError("extract_style requires exactly one PPTX reference")
        if workflow == "revise" and not (request.slide_updates or {}):
            raise WorkflowApplicationError("revise requires at least one structured slide update")

        request_payload = self._request_payload(request)
        request_hash = workflow_request_hash(request_payload)
        self._ensure_workspace(
            WorkflowRequest(**{**request.__dict__, "workflow": workflow}),
            allow_resume=allow_resume,
        )
        capabilities = self._capabilities(workflow)
        actions: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []

        if workflow == "audit":
            before = _artifact_refs(self.workspace, _FROZEN_TRUTH)
            self._check_deadline("audit")
            m5 = M5ApplicationService(
                self.workspace,
                semantic_provider=self.semantic_provider,
                visual_provider=self.visual_provider,
                renderer_root=self.renderer_root,
                node=self.node,
                font_match=self.font_match,
            ).run(auto_repair=False)
            self._check_deadline("audit")
            outputs.append(_output_ref(self.workspace, "m5_application", str(m5.report["report_id"]), m5.path))
            after = _artifact_refs(self.workspace, _FROZEN_TRUTH)
            if before != after:
                raise WorkflowApplicationError("Audit changed frozen semantic/render artifact truth")
            self._add_action(
                actions,
                stage="audit",
                status="complete" if m5.report["status"] == "ready" else "blocked",
                detail=f"M5 review-only audit status={m5.report['status']}; frozen truth unchanged.",
                refs=(str(m5.report["report_id"]),),
            )
            blockers = [
                {"code": str(item["code"]), "message": str(item["message"])}
                for item in m5.report.get("blockers", [])
            ]
            return self._persist(
                workflow=workflow,
                request_hash=request_hash,
                status="ready" if m5.report["status"] == "ready" else "blocked",
                capabilities=capabilities,
                actions=actions,
                artifacts_before=before,
                artifacts_after=after,
                outputs=outputs,
                gate_result={
                    "gate_id": "G8",
                    "status": "pass" if m5.report.get("g8", {}).get("status") == "pass" else "blocked",
                    "reasons": list(m5.report.get("g8", {}).get("reasons", [])),
                },
                blockers=blockers,
            )

        if workflow in {"improve", "revise", "extract_style"}:
            initial_before = _artifact_refs(self.workspace, _TRACKED)
            try:
                if workflow == "improve":
                    status, gate_result, blockers, before, after = self._run_improve(
                        request, actions, outputs
                    )
                elif workflow == "revise":
                    status, gate_result, blockers, before, after = self._run_revise(
                        request, actions, outputs
                    )
                else:
                    status, gate_result, blockers, before, after = self._run_extract_style(
                        request, actions, outputs
                    )
            except SlidethusError as exc:
                before = initial_before
                self._add_action(actions, stage="workflow", status="failed", detail=str(exc))
                after = _artifact_refs(self.workspace, _TRACKED)
                status = "failed"
                gate_result = {"gate_id": None, "status": "fail", "reasons": [str(exc)]}
                blockers = [{"code": "workflow_execution_failed", "message": str(exc)}]
            return self._persist(
                workflow=workflow,
                request_hash=request_hash,
                status=status,
                capabilities=capabilities,
                actions=actions,
                artifacts_before=before,
                artifacts_after=after,
                outputs=outputs,
                gate_result=gate_result,
                blockers=blockers,
            )

        original_hashes = {
            path.resolve(): sha256_file(path.resolve()) for path in request.source_paths
        }
        before: list[dict[str, Any]] = []
        try:
            status, gate_result, blockers = self._run_m3_m4_m5(request, actions, outputs)
        except SlidethusError as exc:
            self._add_action(actions, stage="workflow", status="failed", detail=str(exc))
            status = "failed"
            gate_result = {"gate_id": None, "status": "fail", "reasons": [str(exc)]}
            blockers = [{"code": "workflow_execution_failed", "message": str(exc)}]
        after = _artifact_refs(self.workspace, _TRACKED)
        if workflow == "rebuild":
            changed_sources = [
                path for path, digest in original_hashes.items() if sha256_file(path) != digest
            ]
            if changed_sources:
                raise WorkflowApplicationError(
                    "Rebuild modified original source bytes: "
                    + ", ".join(path.name for path in changed_sources)
                )
            self._add_action(
                actions,
                stage="source_preservation",
                status="complete",
                detail="Rebuild source files remained byte-identical and were not overwritten.",
            )
        return self._persist(
            workflow=workflow,
            request_hash=request_hash,
            status=status,
            capabilities=capabilities,
            actions=actions,
            artifacts_before=before,
            artifacts_after=after,
            outputs=outputs,
            gate_result=gate_result,
            blockers=blockers,
        )

    def run(self, request: WorkflowRequest) -> WorkflowApplicationResult:
        """Run one workflow under M6 operational cache, budget and lease controls."""

        workflow = request.workflow.strip().lower()
        if workflow not in _WORKFLOW_POLICY:
            raise WorkflowApplicationError(f"Unknown workflow: {workflow}")
        normalized = WorkflowRequest(**{**request.__dict__, "workflow": workflow})
        request_payload = self._request_payload(normalized)
        request_hash = workflow_request_hash(request_payload)
        execution_signature = self._execution_signature()
        input_bytes = self._input_bytes(normalized, request_payload)
        slide_updates = len(normalized.slide_updates or {})
        started_at = utc_now()
        started_ns = time.monotonic_ns()
        self._active_workflow = workflow
        self._cost_start_usd = (
            self._meter_value()
            if self._uses_external_provider(workflow) and self.cost_meter is not None
            else None
        )

        with WorkflowLease(self.workspace):
            state_path = self.workspace / "project_state.json"
            if not state_path.is_file():
                self._ensure_workspace(normalized)
            project_id = str(read_json(state_path)["project_id"])
            recovered_attempts = recover_incomplete_workflow_attempts(
                self.workspace,
                schema_dir=self.schemas.schema_dir,
            )
            history_errors = [
                *workflow_operation_workspace_errors(
                    self.workspace,
                    self.schemas.schema_dir,
                ),
                *workflow_event_workspace_errors(
                    self.workspace,
                    self.schemas.schema_dir,
                ),
            ]
            if history_errors:
                raise WorkflowApplicationError(
                    "Workflow operational history is invalid: "
                    + "; ".join(f"{path}: {message}" for path, message in history_errors[:12])
                )
            allow_resume = any(
                item["workflow"] == workflow
                and item["request_hash"] == request_hash
                and item["execution_signature"] == execution_signature
                for item in recovered_attempts
            )
            attempt_id = workflow_attempt_id(
                project_id,
                workflow,
                request_hash,
                execution_signature,
                started_at,
            )
            persist_workflow_event(
                self.workspace,
                schema_dir=self.schemas.schema_dir,
                project_id=project_id,
                attempt_id=attempt_id,
                workflow=workflow,
                request_hash=request_hash,
                execution_signature=execution_signature,
                event_type="started",
                sequence=1,
                detail="Workflow attempt admitted after acquiring the exclusive workspace lease.",
            )

            cached = find_cached_workflow_result(
                self.workspace,
                schema_dir=self.schemas.schema_dir,
                request_hash=request_hash,
                execution_signature=execution_signature,
                max_age_seconds=self.operational_limits.max_cache_age_seconds,
            )
            if cached is not None:
                path, report = cached
                result = WorkflowApplicationResult(report=report, path=path, changed=False)
                self._persist_operation_terminal(
                    project_id=project_id,
                    attempt_id=attempt_id,
                    workflow=workflow,
                    request_hash=request_hash,
                    execution_signature=execution_signature,
                    status=str(report["status"]),
                    cache_status="hit",
                    started_at=started_at,
                    started_ns=started_ns,
                    input_bytes=input_bytes,
                    slide_updates=slide_updates,
                    workflow_result=result,
                    blockers=list(report.get("blockers", [])),
                    event_type="cache_hit",
                    event_detail="Reused a current Workflow Application Report within the admitted cache age.",
                )
                return result

            budget: tuple[str, str] | None = None
            if (
                self.operational_limits.max_provider_cost_usd is not None
                and self._uses_external_provider(workflow)
                and self.cost_meter is None
            ):
                budget = (
                    "workflow_cost_meter_missing",
                    "A provider-cost budget was requested, but no WorkflowCostMeter was injected.",
                )
            elif input_bytes > self.operational_limits.max_input_bytes:
                budget = (
                    "workflow_input_budget_exceeded",
                    f"Workflow input bytes {input_bytes} exceed max_input_bytes={self.operational_limits.max_input_bytes}.",
                )
            elif slide_updates > self.operational_limits.max_slide_updates:
                budget = (
                    "workflow_slide_update_budget_exceeded",
                    f"Workflow slide updates {slide_updates} exceed max_slide_updates={self.operational_limits.max_slide_updates}.",
                )
            if budget is not None:
                code, message = budget
                result = self._budget_block(
                    normalized,
                    request_hash=request_hash,
                    code=code,
                    message=message,
                )
                self._persist_operation_terminal(
                    project_id=project_id,
                    attempt_id=attempt_id,
                    workflow=workflow,
                    request_hash=request_hash,
                    execution_signature=execution_signature,
                    status="blocked",
                    cache_status="miss",
                    started_at=started_at,
                    started_ns=started_ns,
                    input_bytes=input_bytes,
                    slide_updates=slide_updates,
                    workflow_result=result,
                    blockers=list(result.report["blockers"]),
                    event_type="blocked",
                    event_detail=message,
                )
                return result

            self._deadline_ns = started_ns + self.operational_limits.max_wall_seconds * 1_000_000_000
            try:
                result = self._run_once(normalized, allow_resume=allow_resume)
            except WorkflowApplicationError as exc:
                message = str(exc)
                budget_code = None
                if message.startswith("Workflow wall-time budget exceeded"):
                    budget_code = "workflow_wall_time_budget_exceeded"
                elif message.startswith("Workflow provider cost"):
                    budget_code = "workflow_provider_cost_budget_exceeded"
                elif message.startswith("Workflow provider-cost budget requires"):
                    budget_code = "workflow_cost_meter_missing"
                if budget_code is not None:
                    result = self._budget_block(
                        normalized,
                        request_hash=request_hash,
                        code=budget_code,
                        message=message,
                    )
                    self._persist_operation_terminal(
                        project_id=project_id,
                        attempt_id=attempt_id,
                        workflow=workflow,
                        request_hash=request_hash,
                        execution_signature=execution_signature,
                        status="blocked",
                        cache_status="miss",
                        started_at=started_at,
                        started_ns=started_ns,
                        input_bytes=input_bytes,
                        slide_updates=slide_updates,
                        workflow_result=result,
                        blockers=list(result.report["blockers"]),
                        event_type="blocked",
                        event_detail=message,
                    )
                    return result
                blockers = [{"code": "workflow_operation_failed", "message": message}]
                self._persist_operation_terminal(
                    project_id=project_id,
                    attempt_id=attempt_id,
                    workflow=workflow,
                    request_hash=request_hash,
                    execution_signature=execution_signature,
                    status="failed",
                    cache_status="miss",
                    started_at=started_at,
                    started_ns=started_ns,
                    input_bytes=input_bytes,
                    slide_updates=slide_updates,
                    workflow_result=None,
                    blockers=blockers,
                    event_type="failed",
                    event_detail=message,
                )
                raise
            except Exception as exc:
                message = str(exc)
                blockers = [{"code": "workflow_operation_failed", "message": message}]
                self._persist_operation_terminal(
                    project_id=project_id,
                    attempt_id=attempt_id,
                    workflow=workflow,
                    request_hash=request_hash,
                    execution_signature=execution_signature,
                    status="failed",
                    cache_status="miss",
                    started_at=started_at,
                    started_ns=started_ns,
                    input_bytes=input_bytes,
                    slide_updates=slide_updates,
                    workflow_result=None,
                    blockers=blockers,
                    event_type="failed",
                    event_detail=message or type(exc).__name__,
                )
                raise
            finally:
                self._deadline_ns = None

            status = str(result.report["status"])
            event_type = {"ready": "completed", "blocked": "blocked", "failed": "failed"}[status]
            self._persist_operation_terminal(
                project_id=project_id,
                attempt_id=attempt_id,
                workflow=workflow,
                request_hash=request_hash,
                execution_signature=execution_signature,
                status=status,
                cache_status="miss",
                started_at=started_at,
                started_ns=started_ns,
                input_bytes=input_bytes,
                slide_updates=slide_updates,
                workflow_result=result,
                blockers=list(result.report.get("blockers", [])),
                event_type=event_type,
                event_detail=f"Workflow attempt finished with status={status}.",
            )
            return result
