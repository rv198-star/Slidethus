"""One host-led Create entry; baseline automation is not a design substitute."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import SlidethusError
from slidethus.host_design import HostArtDirectionProvider, HostDesignBridge, HostPlanningProvider
from slidethus.protocols import BriefCompletionHints
from slidethus.render_backends.artifact_tool import ArtifactToolRenderBackend
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.m3_application import M3ApplicationService, evaluate_m3_workspace_gate
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.render_preflight import RenderPreflightService
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.services.visual_system import VisualSystemService
from slidethus.state_machine import Phase
from slidethus.workspace import init_workspace


class HostCreateService:
    """Pause at missing host decisions; render only current, explicitly authored designs."""

    def __init__(
        self, workspace: Path, *, node: str | None = None, modules: Path | None = None,
        font_match: str | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.bridge = HostDesignBridge(self.workspace)
        self.planning = HostPlanningProvider(self.bridge)
        self.backend = ArtifactToolRenderBackend(node=node, modules=modules)
        self.font_match = font_match

    def run(
        self, sources: tuple[Path, ...] = (), *, title: str = "Slidethus Create",
        hints: BriefCompletionHints | None = None, render: bool = False,
        slide_ids: tuple[str, ...] = (), revise_stage: str | None = None,
    ) -> dict[str, Any]:
        """Advance to the next missing stage or generate a sample/full candidate."""

        if slide_ids and not render:
            raise ValueError("--slide-id requires --render; planning always covers the full deck")
        if not (self.workspace / "project_state.json").exists():
            init_workspace(self.workspace, title=title)
        self.bridge.pending = None
        try:
            if revise_stage is not None:
                services = {
                    "narrative_blueprint": NarrativePlanningService,
                    "deck_outline": OutlinePlanningService,
                    "slide_specs": SlideSpecPlanningService,
                    "layout_plans": LayoutPlanningService,
                }
                if revise_stage not in services:
                    raise ValueError("Unknown planning revision stage")
                services[revise_stage](self.workspace, provider=self.planning).generate(force=True)
            runtime = ArtifactRuntime(self.workspace)
            # Rendering a current design must not re-run intake with empty/default hints.
            current_planning = evaluate_m3_workspace_gate(self.workspace)
            reuse = not sources and hints is None and current_planning["status"] == "pass"
            if reuse:
                reuse = all(
                    runtime.show_artifact(kind).get("planning_lineage", {}).get("provider")
                    == {"name": self.planning.name, "version": self.planning.version}
                    for kind in ("narrative_blueprint", "deck_outline", "slide_specs", "layout_plans")
                )
            if not reuse:
                planning = M3ApplicationService(self.workspace, planning_provider=self.planning).run(
                    sources, brief_hints=hints, auto_repair=False,
                )
                if planning.report["status"] != "ready":
                    return {
                        "status": "host_input_required" if self.bridge.pending else "blocked",
                        "pending": self.bridge.pending,
                        "planning_report": str(planning.path),
                        "blockers": planning.report["blockers"],
                        "release_approved": False,
                    }
            visual = VisualSystemService(
                self.workspace, art_direction_provider=HostArtDirectionProvider(self.bridge)
            ).compile()
            state = runtime.show_artifact("project_state")
            runtime.record_gate(
                "G6", approved_by="host-create-admission",
                target_phase=Phase.VISUAL_SYSTEM_READY if state["current_phase"] == "LAYOUT_READY" else None,
            )
            if not render:
                return {"status": "design_ready", "theme_id": visual["theme_id"], "release_approved": False}
            self.backend.check_available()
            preflight = RenderPreflightService(self.workspace, font_match=self.font_match).run(
                ("artifact-tool",), include_exports=False,
            )
            if preflight.report["status"] != "pass":
                return {"status": "blocked", "preflight": str(preflight.path), "checks": preflight.report["checks"], "release_approved": False}
            return self.backend.render(self.workspace, preflight, slide_ids=slide_ids)
        except SlidethusError as exc:
            return {
                "status": "host_input_required" if self.bridge.pending else "blocked",
                "pending": self.bridge.pending, "error": str(exc), "release_approved": False,
            }
