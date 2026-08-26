from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from slidethus.gate_contracts import GATE_REQUIRED_PATHS
from slidethus.io_utils import read_json
from slidethus.validation import EDITABILITY_ORDER, validate_workspace


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    reasons: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def evaluate_gate(workspace: Path, gate_id: str) -> GateResult:
    """Evaluate a deterministic subset of Slidethus gates."""

    workspace = workspace.resolve()
    gate_id = gate_id.upper()
    if gate_id not in GATE_REQUIRED_PATHS:
        return GateResult(gate_id, "blocked", ("unknown gate",))

    validation = validate_workspace(workspace, check_hashes=True)
    if not validation.ok:
        return GateResult(gate_id, "fail", tuple(f"validation:{issue.code}" for issue in validation.issues if issue.severity == "error"))

    reasons = [
        f"required artifact is missing: {relative}"
        for relative in GATE_REQUIRED_PATHS[gate_id]
        if not (workspace / relative).exists()
    ]
    if reasons:
        return GateResult(gate_id, "fail", tuple(reasons))
    if gate_id == "G0":
        brief = read_json(workspace / "brief/project_brief.json")
        blocking = [q for q in brief.get("open_questions", []) if q.get("blocking") and q.get("status") == "open"]
        placeholders = {"待补充", "TBD", "TODO", ""}
        if blocking:
            reasons.append("blocking questions remain open")
        if brief.get("intent", {}).get("purpose") in placeholders:
            reasons.append("purpose is not resolved")
        if brief.get("intent", {}).get("desired_outcome") in placeholders:
            reasons.append("desired outcome is not resolved")
        if reasons:
            return GateResult(gate_id, "blocked", tuple(reasons))
    elif gate_id == "G1":
        sources = read_json(workspace / "sources/source_ledger.json").get("sources", [])
        if not sources:
            reasons.append("no sources are inventoried")
        if any(item.get("parse_status") in {"pending", "unreadable"} for item in sources):
            reasons.append("source parsing is incomplete")
    elif gate_id == "G2":
        brief = read_json(workspace / "brief/project_brief.json")
        evidence = read_json(workspace / "evidence/evidence_ledger.json")
        claims = evidence.get("claims", [])
        orientation_complete = any(
            cycle.get("kind") == "orientation" and cycle.get("status") in {"complete", "waived"}
            for cycle in evidence.get("research_cycles", [])
        )
        if not orientation_complete:
            reasons.append("orientation research cycle is not complete or waived")
        if brief.get("source_policy", {}).get("citation_required") and not claims:
            reasons.append("citation policy requires evidence but ledger is empty")
        if any(item.get("support_status") in {"unsupported", "disputed"} and item.get("use_policy") != "do_not_use" for item in claims):
            reasons.append("unresolved unsupported or disputed claims")
    elif gate_id == "G3":
        path = workspace / "narrative/narrative_blueprint.json"
        if not path.exists():
            reasons.append("narrative blueprint is missing")
        else:
            narrative = read_json(path)
            if not narrative.get("central_thesis") or not narrative.get("sections"):
                reasons.append("narrative is incomplete")
    elif gate_id == "G4":
        path = workspace / "outline/deck_outline.json"
        if not path.exists():
            reasons.append("deck outline is missing")
        else:
            slides = [item for item in read_json(path).get("slides", []) if item.get("status") != "excluded"]
            takeaways = [item.get("takeaway", "").strip() for item in slides]
            if not slides:
                reasons.append("outline has no active slides")
            if len(set(takeaways)) != len(takeaways):
                reasons.append("duplicate slide takeaways")
    elif gate_id == "G5A":
        if not (workspace / "slides/slide_specs.json").exists():
            reasons.append("slide specs are missing")
        evidence = read_json(workspace / "evidence/evidence_ledger.json")
        state = read_json(workspace / "project_state.json")
        outline_entry = next(
            (item for item in state.get("artifacts", []) if item.get("artifact_type") == "deck_outline"),
            {},
        )
        outline_version = outline_entry.get("version")
        targeted_complete = any(
            cycle.get("kind") == "targeted"
            and cycle.get("status") in {"complete", "waived"}
            and cycle.get("outline_version") == outline_version
            for cycle in evidence.get("research_cycles", [])
        )
        if not targeted_complete:
            reasons.append(f"targeted research is incomplete for outline version {outline_version}")
    elif gate_id == "G5B":
        if not (workspace / "layout/layout_plans.json").exists():
            reasons.append("layout plans are missing")
    elif gate_id == "G6":
        if not (workspace / "design/visual_system.json").exists():
            reasons.append("visual system is missing")
    elif gate_id == "G7":
        path = workspace / "renders/render_manifest.json"
        if not path.exists():
            reasons.append("render manifest is missing")
        else:
            render = read_json(path)
            if render.get("status") != "success":
                reasons.append("render did not complete successfully")
            elif render.get("editability_level") == "not_measured":
                reasons.append("successful render must record measured editability")
            else:
                actual = render.get("editability_level")
                target = render.get("target_editability_level")
                if actual in EDITABILITY_ORDER and target in EDITABILITY_ORDER and EDITABILITY_ORDER[actual] < EDITABILITY_ORDER[target]:
                    reasons.append(f"actual editability {actual} is below target {target}")
            if render.get("pipeline_mode") == "complete_mvp":
                required_stages = {
                    "planning",
                    "diagnostics",
                    "debug_render",
                    "debug_preview",
                    "design_compile",
                    "final_render",
                    "final_preview",
                }
                stages = {item.get("stage_id"): item for item in render.get("pipeline_stages", [])}
                missing_stages = sorted(required_stages - set(stages))
                if missing_stages:
                    reasons.append(f"complete MVP is missing stages: {missing_stages}")
                required_render_stages = {
                    "planning",
                    "diagnostics",
                    "debug_render",
                    "design_compile",
                    "final_render",
                }
                failed_render_stages = sorted(
                    stage_id
                    for stage_id in required_render_stages
                    if stages.get(stage_id, {}).get("status") != "success"
                )
                if failed_render_stages:
                    reasons.append(
                        f"complete MVP render stages did not succeed: {failed_render_stages}"
                    )
                output_roles = {item.get("role") for item in render.get("outputs", [])}
                required_roles = {
                    "planning_wireframe",
                    "layout_diagnostics",
                    "debug_pptx",
                    "design_preview",
                    "final_pptx",
                }
                missing_roles = sorted(required_roles - output_roles)
                if missing_roles:
                    reasons.append(f"complete MVP is missing outputs: {missing_roles}")
                diagnostics_output = next(
                    (
                        item
                        for item in render.get("outputs", [])
                        if item.get("role") == "layout_diagnostics"
                    ),
                    None,
                )
                if diagnostics_output:
                    diagnostics = read_json(workspace / diagnostics_output["path"])
                    if diagnostics.get("status") != "pass":
                        reasons.append("layout diagnostics did not pass")
    elif gate_id == "G8":
        render = read_json(workspace / "renders/render_manifest.json")
        if render.get("status") != "success":
            reasons.append("render gate has not passed")
        path = workspace / "review/quality_report.json"
        report = read_json(path)
        open_blockers = [issue for issue in report.get("issues", []) if issue.get("status") == "open" and issue.get("severity") in {"critical", "major"}]
        if open_blockers:
            reasons.append("critical or major issues remain open")
        quality_gate = report.get("gate_result", {})
        if report.get("status") != "pass":
            reasons.append("quality report status is not pass")
        if quality_gate.get("gate_id") != "G8" or quality_gate.get("status") != "pass":
            reasons.append("quality report does not record a passing G8 review")
        if render.get("pipeline_mode") == "complete_mvp":
            roles = [item.get("role") for item in render.get("outputs", [])]
            if "debug_preview" not in roles:
                reasons.append("debug PPTX has no independent preview")
            if "final_preview" not in roles:
                reasons.append("final PPTX has no independent preview")
    elif gate_id == "G9":
        render = read_json(workspace / "renders/render_manifest.json")
        quality = read_json(workspace / "review/quality_report.json")
        delivery = read_json(workspace / "delivery/delivery_manifest.json")
        if render.get("status") != "success":
            reasons.append("render gate has not passed")
        quality_gate = quality.get("gate_result", {})
        if quality.get("status") != "pass" or quality_gate.get("gate_id") != "G8" or quality_gate.get("status") != "pass":
            reasons.append("review gate has not passed")
        if delivery.get("status") not in {"ready", "delivered"}:
            reasons.append("delivery is not ready")
        if delivery.get("status") in {"ready", "delivered"} and delivery.get("editability_level") == "not_measured":
            reasons.append("ready delivery must record measured editability")
        if not delivery.get("outputs"):
            reasons.append("delivery has no outputs")
        if any(not item.get("validated") for item in delivery.get("outputs", [])):
            reasons.append("one or more outputs are not validated")

    return GateResult(gate_id, "pass" if not reasons else "fail", tuple(reasons))
