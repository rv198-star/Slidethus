from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import PlanningReviewError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import atomic_create_json, sha256_file
from slidethus.planning_limits import validate_planning_limits
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.planning_repairs import (
    find_planning_repair_report,
    planning_repair_file_key,
    planning_repair_id,
    planning_repair_reference_errors,
    planning_repair_request_hash,
    target_phase_for_selected_issues,
    validate_planning_repair_data,
)
from slidethus.planning_reviews import find_planning_review_report
from slidethus.planning_rules import planning_content_units
from slidethus.protocols import PlanningLimits, PlanningProvider
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.outline_changes import OutlineChangeService
from slidethus.services.planning_review import PlanningReviewService
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.state_machine import FORWARD_SEQUENCE, Phase, can_transition

_AUTOMATIC_CODES = {"headline_too_long"}
_GATE_SEQUENCE = (
    ("G2", Phase.EVIDENCE_READY),
    ("G3", Phase.NARRATIVE_READY),
    ("G4", Phase.OUTLINE_READY),
    ("G5A", Phase.SLIDE_SPECS_READY),
)


@dataclass(frozen=True)
class PlanningRepairResult:
    """One persisted local repair attempt and its resulting planning facts."""

    report: dict[str, Any]
    path: Path
    changed: bool


def _text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _shorten_to_units(text: str, max_units: int = 42) -> str:
    normalized = _text(text, limit=2000)
    if planning_content_units(normalized) <= max_units:
        return normalized
    for size in range(1, len(normalized) // 2 + 1):
        unit = normalized[:size]
        repeats, remainder = divmod(len(normalized), size)
        if (
            repeats >= 2
            and remainder == 0
            and unit * repeats == normalized
            and planning_content_units(unit) <= max_units
        ):
            return unit
    candidate = normalized
    while candidate and planning_content_units(candidate + "…") > max_units:
        candidate = candidate[:-1].rstrip("，,。.;；:： ")
    if not candidate:
        raise PlanningReviewError("Headline cannot be shortened within the admitted unit limit")
    return candidate + "…"


class PlanningRepairService:
    """Apply bounded automatic planning repairs and rebuild only dependent stages."""

    def __init__(
        self,
        workspace: Path,
        *,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
        provider: PlanningProvider | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.provider = provider or DeterministicPlanningProvider()
        self.provider_name = _text(getattr(self.provider, "name", ""))[:128]
        self.provider_version = _text(getattr(self.provider, "version", ""))[:128]
        if not self.provider_name or not self.provider_version:
            raise PlanningReviewError(
                "Planning repair provider must declare bounded name and version"
            )
        self.provider_identity = {
            "name": self.provider_name,
            "version": self.provider_version,
        }
        self.report_dir = self.workspace / ".slidethus/planning/repairs"

    def _assert_provider_identity(self) -> None:
        current = {
            "name": _text(getattr(self.provider, "name", ""))[:128],
            "version": _text(getattr(self.provider, "version", ""))[:128],
        }
        if current != self.provider_identity:
            raise PlanningReviewError(
                "Planning repair provider identity changed during execution"
            )

    def _artifact_ref(self, artifact_type: str) -> dict[str, Any] | None:
        graph = self.runtime.read_artifact_graph_snapshot(
            (artifact_type,),
            optional_artifact_types=(artifact_type,),
        )
        snapshot = graph.get(artifact_type)
        if snapshot is None:
            return None
        return {
            "artifact_type": artifact_type,
            "version": int(snapshot["version"]),
            "content_hash": str(snapshot["content_hash"]),
        }

    @staticmethod
    def _add_action(
        actions: list[dict[str, Any]],
        *,
        operation: str,
        artifact_type: str,
        detail: str,
        slide_id: str | None = None,
        before_ref: dict[str, Any] | None = None,
        after_ref: dict[str, Any] | None = None,
        change_report_id: str | None = None,
    ) -> None:
        actions.append(
            {
                "action_id": f"PRA-{len(actions) + 1:03d}",
                "operation": operation,
                "artifact_type": artifact_type,
                "slide_id": slide_id,
                "before_ref": before_ref,
                "after_ref": after_ref,
                "change_report_id": change_report_id,
                "detail": _text(detail),
            }
        )

    def _review_ref(self, path: Path, report: dict[str, Any]) -> dict[str, Any]:
        return {
            "report_id": str(report["report_id"]),
            "path": path.relative_to(self.workspace).as_posix(),
            "sha256": sha256_file(path),
        }

    def _review_is_current(self, report: dict[str, Any]) -> bool:
        current = {
            str(item["artifact_type"]): item for item in self.runtime.list_artifacts()
        }
        for reference in report.get("inputs", []):
            entry = current.get(str(reference.get("artifact_type")))
            if entry is None:
                return False
            if (
                int(entry.get("version", 0)) != int(reference.get("version", -1))
                or entry.get("content_hash") != reference.get("content_hash")
            ):
                return False
        return True

    def _user_material_targeted_admitted(self) -> bool:
        source_ledger = self.runtime.show_artifact("source_ledger")
        if any(item.get("kind") == "web" for item in source_ledger.get("sources", [])):
            return False
        evidence = self.runtime.show_artifact("evidence_ledger")
        return not any(
            cycle.get("run_ids")
            for cycle in evidence.get("research_cycles", [])
            if cycle.get("kind") == "targeted"
        )

    def _record_gate_action(
        self,
        actions: list[dict[str, Any]],
        gate_id: str,
        target: Phase,
    ) -> None:
        result = evaluate_gate(self.workspace, gate_id)
        if not result.passed:
            raise PlanningReviewError(
                f"Repair cannot record {gate_id}: " + "; ".join(result.reasons)
            )
        before = self._artifact_ref("gate_results")
        state = self.runtime.show_artifact("project_state")
        current = Phase(str(state["current_phase"]))
        target_phase: Phase | None = None
        if FORWARD_SEQUENCE.index(current) < FORWARD_SEQUENCE.index(target):
            if not can_transition(current, target):
                raise PlanningReviewError(
                    f"Repair cannot advance {gate_id}: {current.value} -> {target.value}"
                )
            target_phase = target
        self.runtime.record_gate(
            gate_id,
            approved_by="planning-repair-service",
            target_phase=target_phase,
        )
        after = self._artifact_ref("gate_results")
        self._add_action(
            actions,
            operation="record_gate",
            artifact_type="gate_results",
            before_ref=before,
            after_ref=after,
            detail=f"Revalidated and recorded {gate_id} after local planning repair.",
        )

    def _persist(self, report: dict[str, Any]) -> PlanningRepairResult:
        errors = validate_planning_repair_data(report, self.schemas.schema_dir)
        if errors:
            raise PlanningReviewError(
                "Planning Repair Report is invalid: " + "; ".join(errors)
            )
        path = self.report_dir / f"{planning_repair_file_key(report)}.json"
        changed = atomic_create_json(path, report)
        if not changed:
            from slidethus.io_utils import read_json

            if read_json(path) != report:
                raise PlanningReviewError(
                    f"Immutable Planning Repair path contains different content: {path}"
                )
        reference_errors = planning_repair_reference_errors(
            self.workspace,
            path,
            self.schemas.schema_dir,
        )
        if reference_errors:
            if changed and path.exists():
                path.unlink()
            raise PlanningReviewError(
                "Planning Repair references are invalid: "
                + "; ".join(reference_errors)
            )
        return PlanningRepairResult(
            report=copy.deepcopy(report),
            path=path,
            changed=changed,
        )

    def apply(
        self,
        review_id: str,
        *,
        issue_ids: tuple[str, ...] | None = None,
        reason: str,
        limits: PlanningLimits | None = None,
    ) -> PlanningRepairResult:
        """Apply selected automatic issues or return an explicit assisted/manual block."""

        normalized_reason = _text(reason)
        if not normalized_reason:
            raise PlanningReviewError("Planning repair requires a reason")
        admitted_limits = limits or PlanningLimits()
        validate_planning_limits(admitted_limits)
        found = find_planning_review_report(
            self.workspace,
            review_id,
            schema_dir=self.schemas.schema_dir,
        )
        if found is None:
            raise PlanningReviewError(f"Unknown Planning Review Report: {review_id}")
        source_path, source_review = found
        issue_map = {
            str(item["issue_id"]): item
            for item in source_review.get("issues", [])
            if item.get("status") == "open"
        }
        selected_ids = (
            tuple(sorted(set(issue_ids)))
            if issue_ids is not None
            else tuple(
                sorted(
                    issue_id
                    for issue_id, issue in issue_map.items()
                    if issue.get("repairability") == "automatic"
                )
            )
        )
        if not selected_ids:
            raise PlanningReviewError(
                "Planning Review has no selected automatic open issues"
            )
        unknown = sorted(set(selected_ids) - set(issue_map))
        if unknown:
            raise PlanningReviewError(
                "Repair references unknown/non-open issues: " + ", ".join(unknown)
            )
        selected = [issue_map[issue_id] for issue_id in selected_ids]
        state = self.runtime.show_artifact("project_state")
        request_hash = planning_repair_request_hash(
            str(state["project_id"]),
            review_id,
            selected_ids,
            normalized_reason,
            admitted_limits,
            self.provider_identity,
        )
        repair_id = planning_repair_id(request_hash)
        existing = find_planning_repair_report(
            self.workspace,
            repair_id,
            schema_dir=self.schemas.schema_dir,
        )
        if existing is not None:
            path, report = existing
            return PlanningRepairResult(
                report=report,
                path=path,
                changed=False,
            )
        target_phase = target_phase_for_selected_issues(selected)
        source_ref = self._review_ref(source_path, source_review)
        automatic = all(
            issue.get("repairability") == "automatic"
            and issue.get("code") in _AUTOMATIC_CODES
            for issue in selected
        )
        if not automatic:
            actions: list[dict[str, Any]] = []
            first = selected[0]
            self._add_action(
                actions,
                operation="route_manual",
                artifact_type=str(first["artifact_type"]),
                slide_id=first.get("slide_id"),
                detail=(
                    "Selected issue requires assisted/manual planning judgment; no semantic "
                    "artifact was changed automatically."
                ),
            )
            report = {
                "schema_version": SCHEMA_VERSION,
                "project_id": str(state["project_id"]),
                "repair_id": repair_id,
                "generated_at": utc_now(),
                "status": "blocked",
                "reason": normalized_reason,
                "planning_limits": asdict(admitted_limits),
                "planning_provider": self.provider_identity,
                "source_review": source_ref,
                "result_review": None,
                "issue_ids": list(selected_ids),
                "target_phase": target_phase,
                "actions": actions,
                "downstream_invalidated": [],
                "remaining_issue_ids": list(selected_ids),
                "result_summary": (
                    "No automatic repair was applied; route the selected issue to "
                    f"{target_phase} with explicit user/provider judgment."
                ),
            }
            return self._persist(report)
        if not self._review_is_current(source_review):
            raise PlanningReviewError(
                "Planning Review is stale; create a current review before applying a new repair"
            )
        if not self._user_material_targeted_admitted():
            raise PlanningReviewError(
                "Automatic local repair cannot rebind external targeted research without an injected ResearchProvider"
            )

        self._assert_provider_identity()
        actions: list[dict[str, Any]] = []
        invalidated: list[str] = []
        change_service = OutlineChangeService(self.workspace)
        for issue in selected:
            if issue["code"] != "headline_too_long":
                raise PlanningReviewError(
                    f"Automatic repair is not implemented for {issue['code']}"
                )
            slide_id = str(issue.get("slide_id") or "")
            outline = self.runtime.show_artifact("deck_outline")
            slide = next(
                (
                    item
                    for item in outline.get("slides", [])
                    if item.get("slide_id") == slide_id
                    and item.get("status") != "excluded"
                ),
                None,
            )
            if slide is None:
                raise PlanningReviewError(
                    f"Automatic repair target slide is unavailable: {slide_id}"
                )
            shortened = _shorten_to_units(str(slide["headline"]))
            before = self._artifact_ref("deck_outline")
            change = change_service.update(
                slide_id,
                {"headline": shortened},
                reason=f"{repair_id}: {normalized_reason}",
                idempotency_key=f"{repair_id}:{issue['issue_id']}",
                limits=admitted_limits,
            )
            after = self._artifact_ref("deck_outline")
            invalidated.extend(change.report.get("downstream_invalidated", []))
            self._add_action(
                actions,
                operation="outline_update",
                artifact_type="deck_outline",
                slide_id=slide_id,
                before_ref=before,
                after_ref=after,
                change_report_id=str(change.report["change_id"]),
                detail=f"Shortened {slide_id} headline to the admitted planning-unit limit.",
            )

        self._record_gate_action(actions, "G4", Phase.OUTLINE_READY)

        before_specs = self._artifact_ref("slide_specs")
        spec_result = SlideSpecPlanningService(
            self.workspace,
            provider=self.provider,
        ).generate(limits=admitted_limits)
        self._assert_provider_identity()
        after_specs = self._artifact_ref("slide_specs")
        self._add_action(
            actions,
            operation="regenerate_slide_specs",
            artifact_type="slide_specs",
            before_ref=before_specs,
            after_ref=after_specs,
            detail=(
                "Regenerated current Slide Specs; stable Block IDs were retained for "
                "unchanged semantic blocks."
            ),
        )

        before_evidence = self._artifact_ref("evidence_ledger")
        EvidenceBindingService(self.workspace).complete_user_material_targeted_cycle()
        after_evidence = self._artifact_ref("evidence_ledger")
        self._add_action(
            actions,
            operation="complete_targeted_cycle",
            artifact_type="evidence_ledger",
            before_ref=before_evidence,
            after_ref=after_evidence,
            detail="Rebound the gap-free user-material targeted cycle to the current Outline version.",
        )
        for gate_id, target in _GATE_SEQUENCE:
            self._record_gate_action(actions, gate_id, target)

        before_layout = self._artifact_ref("layout_plans")
        layout_result = LayoutPlanningService(
            self.workspace,
            provider=self.provider,
        ).generate(limits=admitted_limits)
        self._assert_provider_identity()
        after_layout = self._artifact_ref("layout_plans")
        self._add_action(
            actions,
            operation="regenerate_layout",
            artifact_type="layout_plans",
            before_ref=before_layout,
            after_ref=after_layout,
            detail=(
                "Regenerated Layout Plans and immutable wireframes after the local Slide Spec update."
            ),
        )
        self._record_gate_action(actions, "G5B", Phase.LAYOUT_READY)

        result_review = PlanningReviewService(self.workspace).analyze()
        self._add_action(
            actions,
            operation="planning_review",
            artifact_type="planning_review_report",
            detail="Re-ran the full Planning Review after local regeneration.",
        )
        remaining = [
            str(item["issue_id"])
            for item in result_review.report.get("issues", [])
            if item.get("status") == "open"
        ]
        result_ref = self._review_ref(result_review.path, result_review.report)
        report = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(state["project_id"]),
            "repair_id": repair_id,
            "generated_at": str(result_review.report["generated_at"]),
            "status": "applied",
            "reason": normalized_reason,
            "planning_limits": asdict(admitted_limits),
            "planning_provider": self.provider_identity,
            "source_review": source_ref,
            "result_review": result_ref,
            "issue_ids": list(selected_ids),
            "target_phase": target_phase,
            "actions": actions,
            "downstream_invalidated": list(dict.fromkeys(invalidated)),
            "remaining_issue_ids": remaining,
            "result_summary": (
                f"Applied {len(selected_ids)} local automatic repair(s); "
                f"Slide Specs changed={spec_result.changed}, Layout changed={layout_result.changed}; "
                f"{len(remaining)} issue(s) remain in the result review."
            ),
        }
        return self._persist(report)
