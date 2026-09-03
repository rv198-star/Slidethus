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
    HostPlanningProvider,
)
from slidethus.io_utils import ensure_within, read_json, sha256_file
from slidethus.protocols import BriefCompletionHints, PlanningLimits, ResearchProvider
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
    ) -> None:
        self.workspace = workspace.resolve()
        self.bridge = HostDesignBridge(self.workspace)
        self.art_direction = HostArtDirectionProvider(
            self.bridge,
            require_taste_generated=True,
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
        candidate["m2_reports"] = {"orientation": None, "targeted": None}
        candidate["last_planning_report"] = None
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

    def _advance(
        self,
        config: dict[str, Any],
        *,
        render: bool,
        slide_ids: tuple[str, ...],
        revise_stage: str | None,
        reusable_m2_reports: dict[str, dict[str, Any] | None],
        on_revision_committed: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        self.bridge.pending = None
        revision_completed = False
        try:
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
            return {
                **self.backend.render(
                    self.workspace,
                    preflight,
                    slide_ids=slide_ids,
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
            if status in {"design_ready", "candidate_office_review_pending"}
            else "active"
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
                    session = save_host_create_session(
                        self.workspace,
                        candidate,
                        expected_revision=int(session["session_revision"]),
                    )

                result = self._advance(
                    config,
                    render=render,
                    slide_ids=slide_ids,
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
