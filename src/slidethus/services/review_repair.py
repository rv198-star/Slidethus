from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ReviewRepairError, WorkspaceError
from slidethus.io_utils import atomic_create_json, ensure_within, read_json, sha256_file
from slidethus.review_repairs import (
    repair_action_id,
    repair_file_key,
    repair_plan_id,
    repair_plan_reference_errors,
    repair_report_id,
    target_phase_for_repair_issues,
    validate_repair_plan_data,
    validate_repair_report_data,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.deterministic_review import (
    DeterministicReviewResult,
    DeterministicReviewService,
)
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.semantic_review import SemanticReviewResult
from slidethus.services.visual_review import VisualReviewResult

_CURRENT_INPUTS = (
    "asset_manifest",
    "deck_outline",
    "evidence_ledger",
    "layout_plans",
    "narrative_blueprint",
    "project_brief",
    "render_manifest",
    "slide_specs",
    "source_ledger",
    "visual_system",
)
_PHASE_ORDER = {phase: index for index, phase in enumerate(("P0", "P1", "P2", "P3", "P4", "P5A", "P5B", "P6", "P7"))}
_INVALIDATIONS = {
    "P0": ["project_brief", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P1": ["source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P2": ["evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P3": ["narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P4": ["deck_outline", "slide_specs", "layout_plans", "visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P5A": ["slide_specs", "layout_plans", "visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P5B": ["layout_plans", "visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P6": ["visual_system", "render_manifest", "quality_report", "delivery_manifest"],
    "P7": ["render_manifest", "quality_report", "delivery_manifest"],
}


@dataclass(frozen=True)
class RepairPlanResult:
    path: Path
    plan: dict[str, Any]
    changed: bool


@dataclass(frozen=True)
class RepairExecutionResult:
    path: Path
    report: dict[str, Any]
    changed: bool


def _artifact_refs(runtime: ArtifactRuntime) -> list[dict[str, Any]]:
    state = runtime.show_artifact("project_state")
    entries = {str(item.get("artifact_type")): item for item in state.get("artifacts", [])}
    refs: list[dict[str, Any]] = []
    for artifact_type in _CURRENT_INPUTS:
        entry = entries.get(artifact_type)
        if entry is None:
            raise ReviewRepairError(f"Repair planning requires current artifact: {artifact_type}")
        refs.append(
            {
                "artifact_type": artifact_type,
                "version": int(entry["version"]),
                "content_hash": str(entry["content_hash"]),
            }
        )
    return sorted(refs, key=lambda item: item["artifact_type"])


def _report_ref(
    workspace: Path,
    source_type: str,
    path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    report_id = report.get("review_id") if source_type == "deterministic" else report.get("report_id")
    return {
        "source_type": source_type,
        "report_id": str(report_id),
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "status": str(report["status"]),
    }


def _action(
    *,
    operation: str,
    phase: str,
    automatic: bool,
    source_ids: list[str],
    slide_ids: list[str],
    detail: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "action_id": "",
        "operation": operation,
        "phase": phase,
        "automatic": automatic,
        "source_ids": sorted(set(source_ids)),
        "slide_ids": sorted(set(slide_ids)),
        "detail": detail,
    }
    item["action_id"] = repair_action_id(item)
    return item


def _safe_missing_output_refs(workspace: Path, refs: list[str]) -> tuple[bool, list[str]]:
    admitted = ensure_within(workspace, workspace / "outputs")
    missing: list[str] = []
    for raw in refs:
        try:
            relative = Path(raw)
            if relative.is_absolute():
                return False, []
            path = ensure_within(workspace, workspace / relative)
        except (WorkspaceError, OSError, ValueError):
            return False, []
        if admitted != path and admitted not in path.parents:
            return False, []
        if path.exists():
            return False, []
        missing.append(relative.as_posix())
    return bool(missing), missing


class ReviewRepairPlanService:
    """Select root review blockers and publish a minimal-impact Repair Plan before mutation."""

    def __init__(
        self,
        workspace: Path,
        *,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.plan_dir = self.workspace / ".slidethus/review/repairs/plans"

    def plan(
        self,
        deterministic: DeterministicReviewResult,
        semantic: SemanticReviewResult | None = None,
        visual: VisualReviewResult | None = None,
        *,
        persist: bool = True,
    ) -> RepairPlanResult:
        state = self.runtime.show_artifact("project_state")
        source_reports = [_report_ref(self.workspace, "deterministic", deterministic.path, deterministic.report)]
        if semantic is not None:
            source_reports.append(_report_ref(self.workspace, "semantic", semantic.path, semantic.report))
        if visual is not None:
            source_reports.append(_report_ref(self.workspace, "visual", visual.path, visual.report))
        source_reports.sort(key=lambda item: item["source_type"])

        selected: list[dict[str, Any]] = []
        failed_checks = [item for item in deterministic.report.get("checks", []) if item.get("status") == "fail"]
        signature = next((item for item in failed_checks if item.get("code") == "real_output_signatures"), None)
        if signature is not None:
            safe_auto, missing = _safe_missing_output_refs(
                self.workspace,
                [str(item) for item in signature.get("refs", [])],
            )
            selected.append(
                {
                    "source_type": "deterministic",
                    "source_id": str(signature["check_id"]),
                    "code": str(signature["code"]),
                    "severity": str(signature["severity"]),
                    "earliest_phase": "P7",
                    "repairability": "automatic" if safe_auto else "assisted",
                    "slide_ids": [],
                    "refs": missing if safe_auto else sorted(set(str(item) for item in signature.get("refs", []))),
                    "finding": str(signature["finding"]),
                }
            )
        elif failed_checks:
            root = min(
                failed_checks,
                key=lambda item: _PHASE_ORDER.get(str(item.get("earliest_phase")), 99),
            )
            selected.append(
                {
                    "source_type": "deterministic",
                    "source_id": str(root["check_id"]),
                    "code": str(root["code"]),
                    "severity": str(root["severity"]),
                    "earliest_phase": str(root["earliest_phase"]),
                    "repairability": "assisted",
                    "slide_ids": [],
                    "refs": sorted(set(str(item) for item in root.get("refs", []))),
                    "finding": str(root["finding"]),
                }
            )

        if not failed_checks:
            if semantic is not None:
                for issue in semantic.report.get("issues", []):
                    if issue.get("status") == "open" and issue.get("severity") in {"critical", "major"}:
                        selected.append(
                            {
                                "source_type": "semantic",
                                "source_id": str(issue["issue_id"]),
                                "code": str(issue["code"]),
                                "severity": str(issue["severity"]),
                                "earliest_phase": str(issue["earliest_phase"]),
                                "repairability": str(issue["repairability"]),
                                "slide_ids": [str(issue["slide_id"])] if issue.get("slide_id") else [],
                                "refs": [str(item) for item in issue.get("evidence_ids", [])],
                                "finding": str(issue["finding"]),
                            }
                        )
            if visual is not None:
                for issue in visual.report.get("issues", []):
                    if issue.get("status") == "open" and issue.get("severity") in {"critical", "major"}:
                        slide_ids = sorted(
                            set(
                                [str(item) for item in issue.get("related_slide_ids", [])]
                                + ([str(issue["slide_id"])] if issue.get("slide_id") else [])
                            )
                        )
                        selected.append(
                            {
                                "source_type": "visual",
                                "source_id": str(issue["issue_id"]),
                                "code": str(issue["code"]),
                                "severity": str(issue["severity"]),
                                "earliest_phase": str(issue["earliest_phase"]),
                                "repairability": str(issue["repairability"]),
                                "slide_ids": slide_ids,
                                "refs": [str(issue["region_id"])] if issue.get("region_id") else [],
                                "finding": str(issue["finding"]),
                            }
                        )
        selected.sort(key=lambda item: (_PHASE_ORDER[item["earliest_phase"]], item["source_id"]))

        actions: list[dict[str, Any]] = []
        automatic_p7 = [
            item for item in selected
            if item["repairability"] == "automatic" and item["earliest_phase"] == "P7"
        ]
        if automatic_p7:
            actions.append(
                _action(
                    operation="rerender_missing_outputs",
                    phase="P7",
                    automatic=True,
                    source_ids=[str(item["source_id"]) for item in automatic_p7],
                    slide_ids=[],
                    detail="Re-run the frozen M4 rendering boundary to recreate missing generated outputs from current Renderer IR; do not patch output bytes manually.",
                )
            )
        for issue in selected:
            if issue in automatic_p7:
                continue
            operation = "route_manual" if issue["repairability"] == "manual" else "route_assisted"
            actions.append(
                _action(
                    operation=operation,
                    phase=str(issue["earliest_phase"]),
                    automatic=False,
                    source_ids=[str(issue["source_id"])],
                    slide_ids=list(issue["slide_ids"]),
                    detail=(
                        f"Route {issue['source_id']} to {issue['earliest_phase']} for root-cause repair before any downstream regeneration."
                    ),
                )
            )
        target = target_phase_for_repair_issues(selected)
        earliest = min((str(item["earliest_phase"]) for item in selected), key=lambda phase: _PHASE_ORDER[phase]) if selected else None
        expected_invalidations = _INVALIDATIONS[earliest] if earliest else []
        plan: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(state["project_id"]),
            "plan_id": "",
            "inputs": _artifact_refs(self.runtime),
            "source_reports": source_reports,
            "issues": selected,
            "target_phase": target,
            "actions": actions,
            "expected_invalidations": expected_invalidations,
            "verification": [
                "Re-run M5 deterministic review after any automatic execution.",
                "Re-run the responsible upstream Gate and every invalidated downstream Gate.",
                "Run local changed-scope and full-deck regression before G8 aggregation.",
            ],
            "status": "planned" if selected else "not_required",
        }
        plan["plan_id"] = repair_plan_id(plan)
        errors = validate_repair_plan_data(plan, self.schemas.schema_dir)
        if errors:
            raise ReviewRepairError("Invalid Review Repair Plan: " + "; ".join(errors))
        path = self.plan_dir / f"{repair_file_key(plan)}.json"
        if not persist:
            return RepairPlanResult(path=path, plan=plan, changed=False)
        changed = atomic_create_json(path, plan)
        if not changed and read_json(path) != plan:
            raise ReviewRepairError(f"Immutable Review Repair Plan contains different content: {path}")
        return RepairPlanResult(path=path, plan=plan, changed=changed)


class ReviewRepairExecutionService:
    """Execute only admitted automatic M5 repair operations and checkpoint all other routes."""

    def __init__(
        self,
        workspace: Path,
        *,
        renderer_root: Path | None = None,
        node: str | None = None,
        font_match: str | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.renderer_root = renderer_root
        self.node = node
        self.font_match = font_match
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.report_dir = self.workspace / ".slidethus/review/repairs/reports"

    def execute(self, plan_result: RepairPlanResult, *, persist: bool = True) -> RepairExecutionResult:
        plan = plan_result.plan
        errors = repair_plan_reference_errors(self.workspace, plan_result.path, self.schemas.schema_dir)
        if errors:
            raise ReviewRepairError("Repair execution requires a valid current plan: " + "; ".join(errors))
        before = _artifact_refs(self.runtime)
        source_ids = [str(item["source_id"]) for item in plan.get("issues", [])]
        actions: list[dict[str, Any]] = []
        result_deterministic: dict[str, Any] | None = None
        rerendered = False
        if plan.get("status") == "not_required":
            status = "not_required"
            remaining: list[str] = []
        elif not plan.get("actions") or any(not bool(item.get("automatic")) for item in plan.get("actions", [])):
            status = "blocked"
            remaining = source_ids
            for item in plan.get("actions", []):
                actions.append(
                    {
                        "operation": str(item["operation"]),
                        "status": "blocked" if not item.get("automatic") else "skipped",
                        "detail": str(item["detail"]),
                    }
                )
        else:
            unsupported = [item for item in plan.get("actions", []) if item.get("operation") != "rerender_missing_outputs"]
            if unsupported:
                raise ReviewRepairError("Repair Plan contains an unimplemented automatic operation")
            run = M4ApplicationService(
                self.workspace,
                renderer_root=self.renderer_root,
                node=self.node,
                font_match=self.font_match,
            ).run()
            rerendered = True
            actions.append(
                {
                    "operation": "rerender_missing_outputs",
                    "status": "complete" if run.report.get("status") == "ready" else "failed",
                    "detail": f"M4 re-render completed with status={run.report.get('status')}.",
                }
            )
            deterministic = DeterministicReviewService(self.workspace).analyze()
            result_deterministic = {
                "review_id": str(deterministic.report["review_id"]),
                "path": deterministic.path.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(deterministic.path),
                "status": str(deterministic.report["status"]),
            }
            status = "applied" if run.report.get("status") == "ready" and deterministic.report.get("status") == "pass" else "failed"
            remaining = [] if status == "applied" else source_ids
        after = _artifact_refs(self.runtime)
        before_map = {item["artifact_type"]: item for item in before}
        after_map = {item["artifact_type"]: item for item in after}
        changed_artifacts = sorted(
            artifact_type
            for artifact_type in after_map
            if after_map[artifact_type] != before_map.get(artifact_type)
        )
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(self.runtime.show_artifact("project_state")["project_id"]),
            "repair_id": "",
            "plan": {
                "plan_id": str(plan["plan_id"]),
                "path": plan_result.path.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(plan_result.path),
                "status": str(plan["status"]),
            },
            "before_inputs": before,
            "after_inputs": after,
            "actions": actions,
            "result_deterministic": result_deterministic,
            "changed_artifacts": changed_artifacts,
            "changed_slides": [],
            "remaining_source_ids": sorted(set(remaining)),
            "rerendered": rerendered,
            "status": status,
        }
        report["repair_id"] = repair_report_id(report)
        errors = validate_repair_report_data(report, self.schemas.schema_dir)
        if errors:
            raise ReviewRepairError("Invalid Review Repair Report: " + "; ".join(errors))
        path = self.report_dir / f"{repair_file_key(report)}.json"
        if not persist:
            return RepairExecutionResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise ReviewRepairError(f"Immutable Review Repair Report contains different content: {path}")
        return RepairExecutionResult(path=path, report=report, changed=changed)
