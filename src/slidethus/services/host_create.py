"""One host-led Create entry with durable intent, resume, and terminal facts."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import (
    HostCreateConflictError,
    HostCreateError,
    RenderAttemptError,
    SlidethusError,
)
from slidethus.host_create_records import (
    build_host_create_config,
    config_brief_hints,
    config_m2_limits,
    config_planning_limits,
    config_source_paths,
    create_host_create_session,
    fingerprint_sources,
    finish_host_create_operation,
    load_host_create_session,
    make_file_ref,
    normalize_pending_request,
    pending_request_for_output,
    recover_incomplete_host_create_operations,
    resolve_session_config,
    save_host_create_session,
    start_host_create_operation,
    terminal_reference,
    verify_session_sources,
)
from slidethus.host_design import (
    HostArtDirectionProvider,
    HostDesignBridge,
    HostDesignRequired,
    HostPlanningProvider,
    HostVisualReviewProvider,
)
from slidethus.io_utils import ensure_within, read_json, sha256_file
from slidethus.protocols import (
    ArtDirectionLimits,
    BriefCompletionHints,
    PlanningLimits,
    ResearchProvider,
    VisualReviewProvider,
)
from slidethus.render_backends.artifact_tool import ArtifactToolRenderBackend
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.m2_application import M2ApplicationLimits
from slidethus.services.m3_application import (
    M3ApplicationService,
    evaluate_m3_workspace_gate,
)
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.render_preflight import RenderPreflightService
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.services.visual_calibration import VisualCalibrationService
from slidethus.services.visual_system import VisualSystemService
from slidethus.state_machine import FORWARD_SEQUENCE, Phase
from slidethus.workflow_operations import WorkflowLease
from slidethus.workspace import init_workspace

_PLANNING_TARGETS = {
    "BRIEF_READY": "P0",
    "EVIDENCE_READY": "P2",
    "NARRATIVE_READY": "P3",
    "OUTLINE_READY": "P4",
    "SLIDE_SPECS_READY": "P5A",
    "LAYOUT_READY": "P5B",
}

_PENDING_TARGETS = {
    "narrative_blueprint": "P3",
    "deck_outline": "P4",
    "art_direction_seed": "P6",
    "slide_specs": "P5A",
    "layout_plans": "P5B",
    "art_direction": "P6",
    "direction_review": "P4",
    "semantic_planning_review": "P5B",
    "calibration_office_evidence": "P7",
    "calibration_review": "P7",
    "whole_deck_review": "P8",
}


class HostCreateService:
    """Pause at missing host decisions; render only current, explicitly authored designs."""

    def __init__(
        self,
        workspace: Path,
        *,
        node: str | None = None,
        modules: Path | None = None,
        font_match: str | None = None,
        research_provider: ResearchProvider | None = None,
        visual_review_provider: VisualReviewProvider | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.bridge = HostDesignBridge(self.workspace)
        self.visual_review_provider = visual_review_provider or HostVisualReviewProvider(
            self.bridge
        )
        self.art_direction = HostArtDirectionProvider(
            self.bridge,
            require_taste_generated=True,
            visual_review_provider=self.visual_review_provider,
        )
        self.planning = HostPlanningProvider(
            self.bridge,
            art_direction_provider=self.art_direction,
        )
        self.research_provider = research_provider
        self.backend = ArtifactToolRenderBackend(node=node, modules=modules)
        self.font_match = font_match

    @staticmethod
    def _phase_index(value: str) -> int:
        return FORWARD_SEQUENCE.index(Phase(value))

    @staticmethod
    def _gate_is_current(state: dict[str, Any], gate_id: str) -> bool:
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
            return False
        current = {
            str(item["artifact_type"]): item for item in state.get("artifacts", [])
        }
        for reference in summary.get("artifact_versions", []):
            entry = current.get(str(reference.get("artifact_type")))
            if entry is None:
                return False
            if int(entry.get("version", 0)) != int(reference.get("version", -1)):
                return False
            if entry.get("sha256") != reference.get("sha256"):
                return False
        return True

    def _planning_is_reusable(self, runtime: ArtifactRuntime) -> bool:
        """Require current phase, registry, Gates, deterministic checks, and provider lineage."""

        state = runtime.show_artifact("project_state")
        if self._phase_index(str(state["current_phase"])) < self._phase_index(
            Phase.LAYOUT_READY.value
        ):
            return False
        planning_types = (
            "narrative_blueprint",
            "deck_outline",
            "slide_specs",
            "layout_plans",
        )
        if not all(
            self._gate_is_current(state, gate_id)
            for gate_id in ("G0", "G2", "G3", "G4", "G5A", "G5B")
        ):
            return False
        if evaluate_m3_workspace_gate(self.workspace)["status"] != "pass":
            return False
        provider = {"name": self.planning.name, "version": self.planning.version}
        return all(
            runtime.show_artifact(kind).get("planning_lineage", {}).get("provider")
            == provider
            for kind in planning_types
        )

    @staticmethod
    def _invocation_payload(
        *,
        sources: tuple[Path, ...] | None,
        title: str | None,
        hints: BriefCompletionHints | None,
        planning_limits: PlanningLimits | None,
        m2_limits: M2ApplicationLimits | None,
        allow_research_degraded: bool | None,
        approve_external_disclosure: bool | None,
        allow_high_risk_source_evidence: bool | None,
        render: bool,
        slide_ids: tuple[str, ...],
        revise_stage: str | None,
        revise_brief: bool,
        revise_sources: bool,
    ) -> dict[str, Any]:
        return {
            "sources": None if sources is None else [str(path.expanduser().resolve()) for path in sources],
            "title": title,
            "brief_hints": None if hints is None else asdict(hints),
            "planning_limits": None if planning_limits is None else asdict(planning_limits),
            "m2_limits": None if m2_limits is None else asdict(m2_limits),
            "allow_research_degraded": allow_research_degraded,
            "approve_external_disclosure": approve_external_disclosure,
            "allow_high_risk_source_evidence": allow_high_risk_source_evidence,
            "render": render,
            "slide_ids": list(slide_ids),
            "revise_stage": revise_stage,
            "revise_brief": revise_brief,
            "revise_sources": revise_sources,
        }

    @staticmethod
    def _action(
        *,
        session_exists: bool,
        render: bool,
        revise_stage: str | None,
        revise_brief: bool,
        revise_sources: bool,
    ) -> str:
        if revise_brief:
            return "revise_brief"
        if revise_sources:
            return "revise_sources"
        if revise_stage is not None:
            return "revise_stage"
        if render:
            return "render"
        return "resume" if session_exists else "start"

    @staticmethod
    def _merge_brief_hints(
        current: BriefCompletionHints,
        revision: BriefCompletionHints,
    ) -> BriefCompletionHints:
        """Overlay explicitly supplied Brief fields without erasing omitted facts."""

        values = asdict(current)
        updates = asdict(revision)
        if revision.request_text.strip():
            values["request_text"] = revision.request_text
        scalar_fields = (
            "purpose",
            "desired_outcome",
            "call_to_action",
            "delivery_context",
            "presentation_mode",
            "audience_role",
            "decision_power",
            "knowledge_level",
            "page_target",
            "duration_minutes",
            "editability_target",
            "approval_mode",
            "quality_profile",
        )
        for field in scalar_fields:
            if updates[field] is not None:
                values[field] = updates[field]
        for field in ("audience_needs", "audience_objections", "output_formats"):
            if updates[field]:
                values[field] = tuple(updates[field])
            else:
                values[field] = tuple(values[field])
        return BriefCompletionHints(**values)

    def _brief_revision_config(
        self,
        session: dict[str, Any],
        revision: BriefCompletionHints,
    ) -> dict[str, Any]:
        current = session["config"]
        verify_session_sources(current)
        merged = self._merge_brief_hints(config_brief_hints(current), revision)
        if merged == config_brief_hints(current):
            raise HostCreateConflictError(
                "Explicit Brief revision does not change any persisted Brief hint"
            )
        return build_host_create_config(
            title=str(current["title"]),
            source_fingerprints=copy.deepcopy(current["sources"]),
            brief_hints=merged,
            planning_limits=config_planning_limits(current),
            m2_limits=config_m2_limits(current),
            allow_research_degraded=bool(current["allow_research_degraded"]),
            approve_external_disclosure=bool(
                current["approve_external_disclosure"]
            ),
            allow_high_risk_source_evidence=bool(
                current["allow_high_risk_source_evidence"]
            ),
            planning_provider=self.planning,
            research_provider=self.research_provider,
            art_direction_provider=self.art_direction,
            visual_review_provider=self.visual_review_provider,
        )

    def _source_revision_config(
        self,
        session: dict[str, Any],
        additions_or_updates: tuple[Path, ...],
    ) -> dict[str, Any]:
        current = session["config"]
        paths = {
            Path(str(item["path"])).expanduser().resolve()
            for item in current["sources"]
        }
        paths.update(path.expanduser().resolve() for path in additions_or_updates)
        fingerprints = fingerprint_sources(tuple(sorted(paths, key=str)))
        candidate = build_host_create_config(
            title=str(current["title"]),
            source_fingerprints=fingerprints,
            brief_hints=config_brief_hints(current),
            planning_limits=config_planning_limits(current),
            m2_limits=config_m2_limits(current),
            allow_research_degraded=bool(current["allow_research_degraded"]),
            approve_external_disclosure=bool(
                current["approve_external_disclosure"]
            ),
            allow_high_risk_source_evidence=bool(
                current["allow_high_risk_source_evidence"]
            ),
            planning_provider=self.planning,
            research_provider=self.research_provider,
            art_direction_provider=self.art_direction,
            visual_review_provider=self.visual_review_provider,
        )
        if candidate == current:
            raise HostCreateConflictError(
                "Explicit Source revision does not change the persisted Source set or content"
            )
        return candidate

    def _replace_intent_config(
        self,
        session: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = copy.deepcopy(session)
        candidate["config"] = copy.deepcopy(config)
        candidate["intent_revision"] = int(session["intent_revision"]) + 1
        candidate["status"] = "active"
        candidate["pending_revision"] = None
        candidate["pending_request"] = None
        candidate["prepared_art_direction_seed"] = None
        candidate["m2_reports"] = {"orientation": None, "targeted": None}
        candidate["last_planning_report"] = None
        candidate["calibration"] = {
            "state": "idle",
            "sample_receipt": None,
            "authorization": None,
            "full_receipt": None,
            "whole_deck_decision": None,
        }
        return save_host_create_session(
            self.workspace,
            candidate,
            expected_revision=int(session["session_revision"]),
        )

    def _assert_revision_stage_available(self, stage: str) -> None:
        """Reject an impossible revision before persisting a pending transaction."""

        runtime = ArtifactRuntime(self.workspace)
        if stage == "art_direction_seed":
            try:
                specs = runtime.show_artifact("slide_specs")
            except SlidethusError as exc:
                raise HostCreateConflictError(
                    "Art Direction Seed revision requires existing Slide Specs"
                ) from exc
            if not isinstance(specs.get("art_direction_seed"), dict):
                raise HostCreateConflictError(
                    "Art Direction Seed revision requires an existing frozen Seed"
                )
            return
        graph = runtime.read_artifact_graph_snapshot(
            (stage,),
            optional_artifact_types=(stage,),
        )
        if stage not in graph:
            raise HostCreateConflictError(
                f"Host Create cannot revise missing stage: {stage}"
            )

    def _apply_revision_stage(self, stage: str) -> None:
        services = {
            "narrative_blueprint": NarrativePlanningService,
            "deck_outline": OutlinePlanningService,
            "slide_specs": SlideSpecPlanningService,
            "layout_plans": LayoutPlanningService,
        }
        if stage == "art_direction_seed":
            # A Seed revision can pause after the new Seed is admitted but before
            # the forced Slide Specs proposal arrives.  On cross-process resume,
            # the Session-restored prepared reference is authoritative: asking the
            # provider for another revision here would replay the old Host response
            # and recreate the Issue #3 overwrite path.
            if self.planning.prepared_art_direction_seed_reference is None:
                self.art_direction.request_seed_revision()
            SlideSpecPlanningService(
                self.workspace,
                provider=self.planning,
            ).generate(force=True)
            return
        service = services.get(stage)
        if service is None:
            raise HostCreateError(f"Unknown planning revision stage: {stage}")
        self.planning.request_revision(stage)
        service(
            self.workspace,
            provider=self.planning,
        ).generate(force=True)

    def _calibration_service(self) -> VisualCalibrationService:
        return VisualCalibrationService(
            self.workspace,
            backend=self.backend,
            reviewer=self.visual_review_provider,
            author_identities=(self.planning.name, self.art_direction.name),
        )

    def _receipt_ref(self, receipt_path: Path) -> dict[str, str]:
        path = ensure_within(self.workspace, receipt_path)
        return {
            "path": path.relative_to(self.workspace).as_posix(),
            "sha256": sha256_file(path),
        }

    def _register_office_evidence(
        self,
        receipt_path: Path,
        *,
        kind: str,
    ) -> dict[str, Any]:
        receipt = read_json(ensure_within(self.workspace, receipt_path))
        proposal = self.bridge.exchange(
            "calibration_office_evidence",
            {
                "kind": kind,
                "receipt": receipt,
                "required_slide_ids": list(receipt["slide_ids"]),
                "rules": {
                    "application": "Microsoft PowerPoint",
                    "real_office_export_required": True,
                    "artifact_tool_png_is_not_office_evidence": True,
                },
            },
            ArtDirectionLimits(),
        )
        required = {
            "application",
            "build",
            "profile",
            "export_parameters",
            "pages",
        }
        if set(proposal) != required or not isinstance(proposal.get("pages"), list):
            raise HostCreateError(
                "Office evidence proposal must contain exactly application, build, "
                "profile, export_parameters and pages"
            )
        pages = tuple(
            {
                "slide_id": str(item.get("slide_id", "")),
                "path": str(item.get("path", "")),
            }
            for item in proposal["pages"]
            if isinstance(item, dict)
        )
        return self.backend.record_office_evidence(
            self.workspace,
            receipt_path,
            pages=pages,
            application=str(proposal["application"]),
            build=str(proposal["build"]),
            profile=str(proposal["profile"]),
            export_parameters=copy.deepcopy(proposal["export_parameters"]),
        )

    def _resume_calibration(self, calibration: dict[str, Any]) -> dict[str, Any] | None:
        """Advance registered sample/full Office evidence before any new render."""

        state = str(calibration.get("state", "idle"))
        service = self._calibration_service()
        if state in {"sample_rendered", "sample_office_available"}:
            ref = calibration.get("sample_receipt")
            if not isinstance(ref, dict):
                raise HostCreateError("Calibration sample receipt is missing")
            receipt_path = self.workspace / str(ref["path"])
            receipt = read_json(receipt_path)
            if receipt.get("office", {}).get("status") != "available":
                registered = self._register_office_evidence(
                    receipt_path, kind="sample"
                )
                receipt_path = Path(str(registered["receipt_path"]))
            try:
                admitted = service.review_sample(receipt_path)
            except HostDesignRequired:
                update = copy.deepcopy(calibration)
                update.update(
                    {
                        "state": "sample_office_available",
                        "sample_receipt": self._receipt_ref(receipt_path),
                    }
                )
                return {
                    "status": "host_input_required",
                    "pending": self.bridge.pending,
                    "calibration_update": update,
                    "receipt_path": str(receipt_path),
                    "release_approved": False,
                }
            update = copy.deepcopy(calibration)
            approved = bool(admitted.decision["quality_approved"])
            update.update(
                {
                    "state": "approved" if approved else "rework",
                    "sample_receipt": self._receipt_ref(receipt_path),
                    "authorization": admitted.authorization,
                }
            )
            return {
                "status": "calibration_approved" if approved else "calibration_rework",
                "calibration_update": update,
                "receipt_path": str(receipt_path),
                "visual_review": str(admitted.review_path),
                "visual_decision": str(admitted.decision_path),
                **(
                    {"visual_reference_set": str(admitted.reference_set_path)}
                    if admitted.reference_set_path is not None
                    else {}
                ),
                "blockers": [
                    {"finding_id": item, "message": "sample visual blocker"}
                    for item in admitted.decision["open_finding_ids"]
                ],
                "release_approved": False,
            }
        if state in {"full_rendered", "full_office_available"}:
            ref = calibration.get("full_receipt")
            if not isinstance(ref, dict):
                raise HostCreateError("Full candidate receipt is missing")
            receipt_path = self.workspace / str(ref["path"])
            receipt = read_json(receipt_path)
            if receipt.get("office", {}).get("status") != "available":
                registered = self._register_office_evidence(
                    receipt_path, kind="full"
                )
                receipt_path = Path(str(registered["receipt_path"]))
            try:
                admitted = service.review_whole_deck(receipt_path)
            except HostDesignRequired:
                update = copy.deepcopy(calibration)
                update.update(
                    {
                        "state": "full_office_available",
                        "full_receipt": self._receipt_ref(receipt_path),
                    }
                )
                return {
                    "status": "host_input_required",
                    "pending": self.bridge.pending,
                    "calibration_update": update,
                    "receipt_path": str(receipt_path),
                    "release_approved": False,
                }
            update = copy.deepcopy(calibration)
            update.update(
                {
                    "state": (
                        "whole_deck_approved"
                        if admitted.decision["quality_approved"]
                        else "whole_deck_rework"
                    ),
                    "full_receipt": self._receipt_ref(receipt_path),
                    "whole_deck_decision": self._receipt_ref(
                        admitted.decision_path
                    ),
                }
            )
            return {
                "status": (
                    "whole_deck_approved"
                    if admitted.decision["quality_approved"]
                    else "whole_deck_rework"
                ),
                "calibration_update": update,
                "receipt_path": str(receipt_path),
                "visual_review": str(admitted.review_path),
                "visual_decision": str(admitted.decision_path),
                "blockers": [
                    {"finding_id": item, "message": "whole-deck visual blocker"}
                    for item in admitted.decision["open_finding_ids"]
                ],
                "release_approved": False,
            }
        return None

    def _advance(
        self,
        config: dict[str, Any],
        *,
        render: bool,
        slide_ids: tuple[str, ...],
        calibration: dict[str, Any],
        prepared_art_direction_seed: dict[str, Any] | None,
        revise_stage: str | None,
        reusable_m2_reports: dict[str, dict[str, Any] | None],
        on_revision_committed: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        self.bridge.pending = None
        revision_completed = False
        try:
            self.planning.restore_prepared_art_direction_seed(
                prepared_art_direction_seed
            )
            if revise_stage is not None:
                self._apply_revision_stage(revise_stage)
                revision_completed = True
                if on_revision_committed is not None:
                    on_revision_committed()

            runtime = ArtifactRuntime(self.workspace)
            if not self._planning_is_reusable(runtime):
                planning = M3ApplicationService(
                    self.workspace,
                    planning_provider=self.planning,
                    research_provider=self.research_provider,
                    visual_review_provider=self.visual_review_provider,
                    quality_by_construction=True,
                ).run(
                    config_source_paths(config),
                    brief_hints=config_brief_hints(config),
                    planning_limits=config_planning_limits(config),
                    m2_limits=config_m2_limits(config),
                    allow_research_degraded=bool(
                        config["allow_research_degraded"]
                    ),
                    approve_external_disclosure=bool(
                        config["approve_external_disclosure"]
                    ),
                    allow_high_risk_source_evidence=bool(
                        config["allow_high_risk_source_evidence"]
                    ),
                    auto_repair=False,
                    reusable_m2_reports=reusable_m2_reports,
                )
                if planning.report["status"] != "ready":
                    planning_status = str(planning.report["status"])
                    result_status = (
                        "host_input_required"
                        if self.bridge.pending is not None
                        else (
                            "rework_required"
                            if planning_status == "rework_required"
                            else "blocked"
                        )
                    )
                    return {
                        "status": result_status,
                        "pending": self.bridge.pending,
                        "prepared_art_direction_seed_update": (
                            self.planning.prepared_art_direction_seed_reference
                        ),
                        "planning_report": str(planning.path),
                        "blockers": planning.report["blockers"],
                        "release_approved": False,
                        "revision_completed": revision_completed,
                    }

            visual = VisualSystemService(
                self.workspace,
                art_direction_provider=self.art_direction,
            ).compile()
            state = runtime.show_artifact("project_state")
            if self._phase_index(str(state["current_phase"])) < self._phase_index(
                Phase.LAYOUT_READY.value
            ):
                raise HostCreateError(
                    "G6 cannot be evaluated before current accepted Layout planning"
                )
            if not self._gate_is_current(state, "G6"):
                g6 = runtime.record_gate(
                    "G6",
                    approved_by="host-create-admission",
                    target_phase=(
                        Phase.VISUAL_SYSTEM_READY
                        if state["current_phase"] == Phase.LAYOUT_READY.value
                        else None
                    ),
                )
                if not g6.passed:
                    return {
                        "status": "blocked",
                        "error": "G6 did not pass: " + "; ".join(g6.reasons),
                        "release_approved": False,
                        "revision_completed": revision_completed,
                    }
                state = runtime.show_artifact("project_state")
                if not self._gate_is_current(state, "G6"):
                    return {
                        "status": "blocked",
                        "error": "G6 was recorded but is not current for the admitted Visual System",
                        "release_approved": False,
                        "revision_completed": revision_completed,
                    }
            strict_quality = str(visual.get("schema_version", "")).startswith("0.2.")
            if strict_quality:
                resumed = self._resume_calibration(calibration)
                if resumed is not None:
                    resumed["revision_completed"] = revision_completed
                    return resumed
            if not render:
                return {
                    "status": "design_ready",
                    "theme_id": visual["theme_id"],
                    "host_submission": self.bridge.last_submission,
                    "release_approved": False,
                    "revision_completed": revision_completed,
                }

            preflight = RenderPreflightService(
                self.workspace,
                node=self.backend.node,
                artifact_tool_modules=self.backend.modules,
                font_match=self.font_match,
            ).run(("artifact-tool",), include_exports=False)
            if preflight.report["status"] != "pass":
                return {
                    "status": "blocked",
                    "preflight": str(preflight.path),
                    "checks": preflight.report["checks"],
                    "release_approved": False,
                    "revision_completed": revision_completed,
                }
            if strict_quality and slide_ids:
                raise HostCreateConflictError(
                    "Reviewed/critical calibration selects representative slides deterministically; "
                    "--slide-id cannot override it"
                )
            if strict_quality:
                service = self._calibration_service()
                calibration_state = str(calibration.get("state", "idle"))
                if calibration_state == "idle":
                    receipt = service.render_sample(preflight)
                    receipt_path = Path(str(receipt["receipt_path"]))
                    update = copy.deepcopy(calibration)
                    update.update(
                        {
                            "state": "sample_rendered",
                            "sample_receipt": self._receipt_ref(receipt_path),
                            "authorization": None,
                            "full_receipt": None,
                            "whole_deck_decision": None,
                        }
                    )
                    return {
                        **receipt,
                        "status": "calibration_office_evidence_pending",
                        "calibration_update": update,
                        "revision_completed": revision_completed,
                    }
                if calibration_state == "approved":
                    authorization = calibration.get("authorization")
                    if not isinstance(authorization, dict):
                        raise HostCreateError(
                            "Approved calibration state lacks full-render authorization"
                        )
                    receipt = service.render_full(preflight, authorization)
                    receipt_path = Path(str(receipt["receipt_path"]))
                    update = copy.deepcopy(calibration)
                    update.update(
                        {
                            "state": "full_rendered",
                            "full_receipt": self._receipt_ref(receipt_path),
                            "whole_deck_decision": None,
                        }
                    )
                    return {
                        **receipt,
                        "status": "full_office_evidence_pending",
                        "calibration_update": update,
                        "revision_completed": revision_completed,
                    }
                if calibration_state == "whole_deck_approved":
                    return {
                        "status": "whole_deck_approved",
                        "receipt_path": str(
                            self.workspace / str(calibration["full_receipt"]["path"])
                        ),
                        "release_approved": False,
                        "revision_completed": revision_completed,
                    }
                raise HostCreateConflictError(
                    f"Calibration state {calibration_state} must be resumed before rendering"
                )
            return {
                **self.backend.render(
                    self.workspace,
                    preflight,
                    slide_ids=slide_ids,
                    scope="full" if not slide_ids else "sample",
                ),
                "revision_completed": revision_completed,
            }
        except RenderAttemptError as exc:
            receipt = read_json(Path(exc.receipt_path))
            return {
                "status": str(receipt.get("status", "render_failed")),
                "pending": self.bridge.pending,
                "host_submission": self.bridge.last_submission,
                "error": str(exc),
                "receipt_path": exc.receipt_path,
                "release_approved": False,
                "revision_completed": revision_completed,
            }
        except SlidethusError as exc:
            return {
                "status": (
                    "host_input_required"
                    if self.bridge.pending is not None
                    else "blocked"
                ),
                "pending": self.bridge.pending,
                "prepared_art_direction_seed_update": (
                    self.planning.prepared_art_direction_seed_reference
                ),
                "host_submission": self.bridge.last_submission,
                "error": str(exc),
                "release_approved": False,
                "revision_completed": revision_completed,
            }

    def _planning_rework_details(
        self, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Resolve the exact Planning Review and its phase-correct open issues."""

        raw_report = result.get("planning_report")
        if not raw_report:
            return None
        try:
            report_path = ensure_within(self.workspace, Path(str(raw_report)))
            report = read_json(report_path)
            review_ref = report.get("outputs", {}).get("planning_review")
            if not isinstance(review_ref, dict):
                return None
            review_path = ensure_within(
                self.workspace,
                self.workspace / str(review_ref["path"]),
            )
            if (
                not review_path.is_file()
                or sha256_file(review_path) != review_ref.get("sha256")
            ):
                return None
            review = read_json(review_path)
        except (KeyError, OSError, ValueError):
            return None
        blocking = [
            item
            for item in review.get("issues", [])
            if item.get("status") == "open"
            and item.get("severity") in {"critical", "major"}
        ]
        target = _PLANNING_TARGETS.get(str(review.get("target_phase")))
        return {
            "target_phase": target,
            "review_report_id": str(review.get("report_id", "")),
            "review_path": str(review_path),
            "issue_ids": sorted(
                {str(item["issue_id"]) for item in blocking if item.get("issue_id")}
            ),
            "allowed_next_actions": ["inspect_report", "revise_stage", "resume"],
        }

    def _result_refs(self, result: dict[str, Any]) -> tuple[dict[str, str], ...]:
        refs: list[dict[str, str]] = []
        fields = (
            ("planning_report", "m3_report"),
            ("preflight", "preflight"),
            ("receipt_path", "render_receipt"),
            ("visual_review", "visual_review"),
            ("visual_decision", "visual_decision"),
            ("visual_reference_set", "visual_reference_set"),
        )
        for field, kind in fields:
            raw = result.get(field)
            if not raw:
                continue
            path = Path(str(raw))
            if path.is_file():
                refs.append(make_file_ref(self.workspace, path, kind=kind))
        rework = self._planning_rework_details(result)
        if rework is not None:
            review_path = Path(str(rework["review_path"]))
            refs.append(
                make_file_ref(self.workspace, review_path, kind="planning_review")
            )
        for output in result.get("outputs", []):
            if not isinstance(output, dict) or not output.get("path"):
                continue
            path = Path(str(output["path"]))
            if path.is_file():
                refs.append(make_file_ref(self.workspace, path, kind="candidate"))
        unique = {(item["kind"], item["path"]): item for item in refs}
        return tuple(unique[key] for key in sorted(unique))

    @staticmethod
    def _issue_ids(result: dict[str, Any]) -> tuple[str, ...]:
        return tuple(
            str(item["finding_id"])
            for item in result.get("blockers", [])
            if isinstance(item, dict) and item.get("finding_id")
        )

    def _terminal_contract(
        self, result: dict[str, Any]
    ) -> tuple[str, str | None, tuple[str, ...], tuple[str, ...], str]:
        status = str(result.get("status", "failed"))
        if status not in {
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
        }:
            status = "failed"
        pending = result.get("pending") or self.bridge.pending
        target = (
            _PENDING_TARGETS.get(str(pending.get("stage")))
            if isinstance(pending, dict)
            else None
        )
        issue_ids = self._issue_ids(result)
        rework = self._planning_rework_details(result)
        if status == "rework_required" and rework is not None:
            target = rework["target_phase"]
            issue_ids = tuple(rework["issue_ids"])
        if status == "host_input_required":
            actions = ("submit_host_response", "resume")
        elif status == "rework_required":
            actions = ("inspect_report", "revise_stage", "resume")
        elif status in {"render_failed", "render_timed_out"}:
            actions = ("inspect_report", "repair_capability", "resume")
        elif status == "blocked":
            actions = ("inspect_report", "resume", "revise_brief", "revise_sources")
        elif status == "design_ready":
            actions = ("render", "revise_stage")
        elif status == "candidate_office_review_pending":
            actions = ("review_candidate", "revise_stage")
        elif status == "calibration_office_evidence_pending":
            target = "P7"
            actions = ("register_office_evidence", "resume", "revise_stage")
        elif status == "calibration_review_pending":
            target = "P7"
            actions = ("review_sample", "resume", "revise_stage")
        elif status == "calibration_rework":
            target = "P7"
            actions = ("inspect_report", "revise_stage", "resume")
        elif status == "calibration_approved":
            target = "P7"
            actions = ("render_full", "revise_stage")
        elif status == "full_office_evidence_pending":
            target = "P8"
            actions = ("register_office_evidence", "resume", "revise_stage")
        elif status == "whole_deck_review_pending":
            target = "P8"
            actions = ("review_whole_deck", "resume", "revise_stage")
        elif status == "whole_deck_rework":
            target = "P8"
            actions = ("inspect_report", "revise_stage", "resume")
        elif status == "whole_deck_approved":
            target = "P8"
            actions = ("inspect_report", "revise_stage")
        else:
            actions = ("inspect_report", "resume")
        message = str(result.get("error") or "")
        if not message and result.get("blockers"):
            message = "; ".join(
                str(item.get("message", item))
                for item in result["blockers"]
                if isinstance(item, dict)
            )
        if not message:
            message = {
                "host_input_required": "A context-bound Host response is required.",
                "rework_required": "Planning review requires phase-correct rework.",
                "blocked": "Host Create is blocked; inspect the bound report.",
                "failed": "Host Create failed.",
                "design_ready": "Current design artifacts are admitted and ready to render.",
                "candidate_office_review_pending": "Candidate generated; real PowerPoint review remains pending.",
                "render_failed": "Renderer attempt failed; inspect its terminal receipt.",
                "render_timed_out": "Renderer attempt timed out; inspect its terminal receipt.",
                "calibration_office_evidence_pending": "Representative sample generated; register real PowerPoint page exports.",
                "calibration_review_pending": "Representative Office pages await independent visual review.",
                "calibration_rework": "Representative Office sample has unresolved visual blockers.",
                "calibration_approved": "Representative Office sample is approved for the identical full IR and producer.",
                "full_office_evidence_pending": "Full candidate generated; register real PowerPoint page exports.",
                "whole_deck_review_pending": "Full Office-rendered deck awaits whole-deck review.",
                "whole_deck_rework": "Whole-deck Office review has unresolved visual blockers.",
                "whole_deck_approved": "Whole-deck Office review is approved.",
            }[status]
        return status, target, issue_ids, actions, message

    def _update_session_from_result(
        self,
        session: dict[str, Any],
        result: dict[str, Any],
        *,
        terminal_path: Path,
        terminal: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = copy.deepcopy(session)
        pending = result.get("pending") or self.bridge.pending
        candidate["pending_request"] = normalize_pending_request(
            self.workspace,
            pending,
        )
        if bool(result.get("revision_completed")):
            candidate["pending_revision"] = None
        status = str(terminal["status"])
        candidate["status"] = (
            status
            if status
            in {
                "design_ready",
                "candidate_office_review_pending",
                "calibration_office_evidence_pending",
                "calibration_review_pending",
                "calibration_rework",
                "calibration_approved",
                "full_office_evidence_pending",
                "whole_deck_review_pending",
                "whole_deck_rework",
                "whole_deck_approved",
            }
            else "active"
        )
        if isinstance(result.get("calibration_update"), dict):
            candidate["calibration"] = copy.deepcopy(result["calibration_update"])
        if "prepared_art_direction_seed_update" in result:
            candidate["prepared_art_direction_seed"] = copy.deepcopy(
                result["prepared_art_direction_seed_update"]
            )
        candidate["last_terminal"] = terminal_reference(
            self.workspace,
            terminal_path,
            terminal,
        )
        planning_path = result.get("planning_report")
        if planning_path and Path(str(planning_path)).is_file():
            absolute = Path(str(planning_path)).resolve()
            candidate["last_planning_report"] = {
                "path": absolute.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(absolute),
            }
            planning_report = read_json(absolute)
            for ref in planning_report.get("outputs", {}).get("m2_reports", []):
                m2_path = self.workspace / str(ref["path"])
                if not m2_path.is_file():
                    continue
                m2_report = read_json(m2_path)
                stage = (
                    "targeted"
                    if m2_report.get("inputs", {})
                    .get("config", {})
                    .get("advance_existing_planning")
                    else "orientation"
                )
                if ref.get("status") in {"ready", "degraded"}:
                    candidate["m2_reports"][stage] = copy.deepcopy(ref)
        return candidate

    def run(
        self,
        sources: tuple[Path, ...] | None = None,
        *,
        title: str | None = None,
        hints: BriefCompletionHints | None = None,
        planning_limits: PlanningLimits | None = None,
        m2_limits: M2ApplicationLimits | None = None,
        allow_research_degraded: bool | None = None,
        approve_external_disclosure: bool | None = None,
        allow_high_risk_source_evidence: bool | None = None,
        render: bool = False,
        slide_ids: tuple[str, ...] = (),
        revise_stage: str | None = None,
        revise_brief: bool = False,
        revise_sources: bool = False,
    ) -> dict[str, Any]:
        """Advance or resume one durable Host Create session."""

        if slide_ids and not render:
            raise ValueError("--slide-id requires --render; planning always covers the full deck")
        revision_actions = sum(
            (revise_stage is not None, revise_brief, revise_sources)
        )
        if revision_actions > 1:
            raise ValueError(
                "Choose exactly one of --revise-stage, --revise-brief, or --revise-sources"
            )
        if revision_actions and (render or slide_ids):
            raise ValueError("A revision invocation cannot render in the same transaction")
        if revise_brief:
            if hints is None:
                raise ValueError("--revise-brief requires explicit Brief hints or --request")
            if sources is not None:
                raise ValueError("--revise-brief cannot also revise Sources")
            if any(
                value is not None
                for value in (
                    title,
                    planning_limits,
                    m2_limits,
                    allow_research_degraded,
                    approve_external_disclosure,
                    allow_high_risk_source_evidence,
                )
            ):
                raise ValueError(
                    "--revise-brief only accepts Brief hint fields; other config is immutable"
                )
        if revise_sources:
            if not sources:
                raise ValueError("--revise-sources requires at least one --source")
            if hints is not None or title is not None:
                raise ValueError("--revise-sources cannot also revise the Brief")
            if any(
                value is not None
                for value in (
                    planning_limits,
                    m2_limits,
                    allow_research_degraded,
                    approve_external_disclosure,
                    allow_high_risk_source_evidence,
                )
            ):
                raise ValueError(
                    "--revise-sources only accepts Source paths; other config is immutable"
                )
        invocation = self._invocation_payload(
            sources=sources,
            title=title,
            hints=hints,
            planning_limits=planning_limits,
            m2_limits=m2_limits,
            allow_research_degraded=allow_research_degraded,
            approve_external_disclosure=approve_external_disclosure,
            allow_high_risk_source_evidence=allow_high_risk_source_evidence,
            render=render,
            slide_ids=slide_ids,
            revise_stage=revise_stage,
            revise_brief=revise_brief,
            revise_sources=revise_sources,
        )

        with WorkflowLease(self.workspace):
            workspace_exists = (self.workspace / "project_state.json").is_file()
            session = (
                load_host_create_session(self.workspace) if workspace_exists else None
            )
            session_existed = session is not None
            if session is None:
                if workspace_exists:
                    raise HostCreateConflictError(
                        "Existing workspace has no canonical Host Create Session; "
                        "use a new workspace for designed Create or perform an explicit migration"
                    )
                if revision_actions:
                    raise HostCreateConflictError(
                        "Host Create revisions require an existing canonical session"
                    )
                config = resolve_session_config(
                    None,
                    title=title,
                    sources=sources,
                    brief_hints=hints,
                    planning_limits=planning_limits,
                    m2_limits=m2_limits,
                    allow_research_degraded=allow_research_degraded,
                    approve_external_disclosure=approve_external_disclosure,
                    allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                    planning_provider=self.planning,
                    research_provider=self.research_provider,
                    art_direction_provider=self.art_direction,
                    visual_review_provider=self.visual_review_provider,
                )
                if not workspace_exists:
                    init_workspace(self.workspace, title=str(config["title"]))
                session = create_host_create_session(self.workspace, config)
            else:
                recover_incomplete_host_create_operations(self.workspace, session)
                config = session["config"]

            action = self._action(
                session_exists=session_existed,
                render=render,
                revise_stage=revise_stage,
                revise_brief=revise_brief,
                revise_sources=revise_sources,
            )
            operation = start_host_create_operation(
                self.workspace,
                session,
                action=action,
                invocation_payload=invocation,
            )

            try:
                pending_revision = session.get("pending_revision")
                if pending_revision is not None and render:
                    raise HostCreateConflictError(
                        "Complete the pending stage revision before rendering"
                    )
                if (revise_brief or revise_sources) and pending_revision is not None:
                    raise HostCreateConflictError(
                        "Complete or cancel the pending stage revision before revising intent"
                    )
                if revise_brief:
                    config = self._brief_revision_config(session, hints)
                    session = self._replace_intent_config(session, config)
                elif revise_sources:
                    config = self._source_revision_config(session, sources)
                    session = self._replace_intent_config(session, config)
                else:
                    config = resolve_session_config(
                        session,
                        title=title,
                        sources=sources,
                        brief_hints=hints,
                        planning_limits=planning_limits,
                        m2_limits=m2_limits,
                        allow_research_degraded=allow_research_degraded,
                        approve_external_disclosure=approve_external_disclosure,
                        allow_high_risk_source_evidence=allow_high_risk_source_evidence,
                        planning_provider=self.planning,
                        research_provider=self.research_provider,
                        art_direction_provider=self.art_direction,
                        visual_review_provider=self.visual_review_provider,
                    )
                if revise_stage is not None:
                    if pending_revision is not None and pending_revision.get(
                        "stage"
                    ) != revise_stage:
                        raise HostCreateConflictError(
                            "A different Host Create stage revision is already pending"
                        )
                    if pending_revision is None:
                        if session.get("pending_request") is not None:
                            raise HostCreateConflictError(
                                "Complete the current Host request before starting a stage revision"
                            )
                        self._assert_revision_stage_available(revise_stage)
                        candidate = copy.deepcopy(session)
                        from slidethus.artifact_runtime import utc_now

                        candidate["pending_revision"] = {
                            "kind": "stage",
                            "stage": revise_stage,
                            "requested_at": utc_now(),
                        }
                        if revise_stage in {
                            "narrative_blueprint",
                            "deck_outline",
                            "art_direction_seed",
                        }:
                            candidate["prepared_art_direction_seed"] = None
                        session = save_host_create_session(
                            self.workspace,
                            candidate,
                            expected_revision=int(session["session_revision"]),
                        )
                effective_revision = (
                    revise_stage
                    or (
                        str(session["pending_revision"]["stage"])
                        if session.get("pending_revision") is not None
                        else None
                    )
                )
                def mark_revision_committed() -> None:
                    nonlocal session
                    candidate = copy.deepcopy(session)
                    candidate["pending_revision"] = None
                    candidate["pending_request"] = None
                    candidate["calibration"] = {
                        "state": "idle",
                        "sample_receipt": None,
                        "authorization": None,
                        "full_receipt": None,
                        "whole_deck_decision": None,
                    }
                    session = save_host_create_session(
                        self.workspace,
                        candidate,
                        expected_revision=int(session["session_revision"]),
                    )

                result = self._advance(
                    config,
                    render=render,
                    slide_ids=slide_ids,
                    calibration=copy.deepcopy(session["calibration"]),
                    prepared_art_direction_seed=copy.deepcopy(
                        session["prepared_art_direction_seed"]
                    ),
                    revise_stage=effective_revision,
                    reusable_m2_reports=copy.deepcopy(session["m2_reports"]),
                    on_revision_committed=(
                        mark_revision_committed
                        if effective_revision is not None
                        else None
                    ),
                )
            except HostCreateConflictError as exc:
                result = {
                    "status": "blocked",
                    "pending": pending_request_for_output(
                        self.workspace,
                        session.get("pending_request"),
                    ),
                    "error": str(exc),
                    "release_approved": False,
                    "revision_completed": False,
                }
            except Exception as exc:  # noqa: BLE001
                terminal_path, terminal = finish_host_create_operation(
                    operation,
                    status="failed",
                    pending_request=pending_request_for_output(
                        self.workspace,
                        session.get("pending_request"),
                    ),
                    message=str(exc) or type(exc).__name__,
                    allowed_next_actions=("inspect_report", "resume"),
                    resulting_config_hash=str(session["config"]["config_hash"]),
                )
                candidate = self._update_session_from_result(
                    session,
                    {"status": "failed", "revision_completed": False},
                    terminal_path=terminal_path,
                    terminal=terminal,
                )
                save_host_create_session(
                    self.workspace,
                    candidate,
                    expected_revision=int(session["session_revision"]),
                )
                raise

            status, target, issue_ids, actions, message = self._terminal_contract(result)
            rework = self._planning_rework_details(result)
            if status == "rework_required" and rework is not None:
                result["rework"] = rework
            refs = self._result_refs(result)
            terminal_path, terminal = finish_host_create_operation(
                operation,
                status=status,
                pending_request=result.get("pending") or self.bridge.pending,
                message=message,
                target_phase=target,
                issue_ids=issue_ids,
                allowed_next_actions=actions,
                refs=refs,
                resulting_config_hash=str(session["config"]["config_hash"]),
            )
            candidate = self._update_session_from_result(
                session,
                result,
                terminal_path=terminal_path,
                terminal=terminal,
            )
            session = save_host_create_session(
                self.workspace,
                candidate,
                expected_revision=int(session["session_revision"]),
            )
            result.pop("revision_completed", None)
            if result.get("pending") is None and session.get("pending_request") is not None:
                result["pending"] = pending_request_for_output(
                    self.workspace,
                    session["pending_request"],
                )
            result.update(
                {
                    "session_path": str(self.workspace / ".slidethus/host-create/session.json"),
                    "operation_path": str(terminal_path),
                    "attempt_id": terminal["attempt_id"],
                }
            )
            return result
