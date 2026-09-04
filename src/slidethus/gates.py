from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from slidethus.evidence_binding_rules import binding_gate_reasons
from slidethus.gate_contracts import GATE_REQUIRED_PATHS
from slidethus.io_utils import read_json
from slidethus.planning_lineage import workspace_planning_graph
from slidethus.planning_rules import (
    layout_gate_reasons,
    narrative_gate_reasons,
    outline_gate_reasons,
    slide_specs_gate_reasons,
)
from slidethus.quality_reviews import production_quality_gate_reasons
from slidethus.rendering_rules import (
    production_render_gate_reasons,
    visual_system_gate_reasons,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.validation import EDITABILITY_ORDER, ValidationIssue, validate_workspace

_GATE_STAGE = {
    "G0": 0,
    "G1": 1,
    "G2": 2,
    "G3": 3,
    "G4": 4,
    "G5A": 5,
    "G5B": 6,
    "G6": 7,
    "G7": 8,
    "G8": 9,
    "G9": 10,
}
_VALIDATION_PATH_STAGE = (
    ("brief/", 0),
    ("sources/", 1),
    ("evidence/", 2),
    ("narrative/", 3),
    ("outline/", 4),
    ("slides/", 5),
    ("layout/", 6),
    ("design/", 7),
    ("assets/", 7),
    ("renders/", 8),
    ("outputs/", 8),
    (".slidethus/render/", 8),
    ("review/", 9),
    (".slidethus/review/", 9),
    ("delivery/", 10),
)


def _validation_issue_stage(issue: ValidationIssue) -> int:
    path = issue.path.replace("\\", "/")
    for prefix, stage in _VALIDATION_PATH_STAGE:
        if path.startswith(prefix):
            return stage
    if issue.code.startswith(("render_", "invalid_m4", "invalid_renderer", "invalid_render_")):
        return 8
    if issue.code.startswith(("invalid_deterministic_review", "invalid_semantic_review", "invalid_visual_review")):
        return 9
    if issue.code.startswith("delivery_"):
        return 10
    return 0


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
    blocking_validation = [
        issue
        for issue in validation.issues
        if issue.severity == "error" and _validation_issue_stage(issue) <= _GATE_STAGE[gate_id]
    ]
    if blocking_validation:
        return GateResult(
            gate_id,
            "fail",
            tuple(f"validation:{issue.code}" for issue in blocking_validation),
        )

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
        completion = brief.get("completion")
        if completion:
            if brief.get("intent", {}).get("delivery_context") in placeholders:
                reasons.append("delivery context is not resolved")
            audiences = brief.get("audiences", [])
            if not audiences or audiences[0].get("role") in placeholders:
                reasons.append("primary audience is not resolved")
        page_count = brief.get("constraints", {}).get("page_count", {})
        minimum = page_count.get("min")
        target = page_count.get("target")
        maximum = page_count.get("max")
        if not (
            isinstance(minimum, int)
            and isinstance(target, int)
            and isinstance(maximum, int)
            and minimum <= target <= maximum
        ):
            reasons.append("page-count contract is invalid")
        if completion and completion.get("status") != "resolved":
            reasons.append("brief completion still needs input")
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
        lineage_issue_codes = {
            "unusable_source",
            "invalid_evidence_locator",
            "stale_evidence_source_binding",
            "stale_evidence_source_content",
            "invalid_verified_evidence",
        }
        if any(issue.code in lineage_issue_codes for issue in validation.issues):
            reasons.append("evidence lineage is invalidated by current sources")
        orientation_complete = any(
            cycle.get("kind") == "orientation" and cycle.get("status") in {"complete", "waived"}
            for cycle in evidence.get("research_cycles", [])
        )
        if not orientation_complete:
            reasons.append("orientation research cycle is not complete or waived")
        if brief.get("source_policy", {}).get("citation_required"):
            if not claims:
                reasons.append("citation policy requires evidence but ledger is empty")
            elif not any(
                item.get("source_refs")
                and item.get("support_status") in {"verified", "provisional"}
                and item.get("use_policy") != "do_not_use"
                for item in claims
            ):
                reasons.append(
                    "citation policy requires at least one usable source-backed claim"
                )
        if brief.get("source_policy", {}).get("citation_required") and claims and not any(
            item.get("use_policy") != "do_not_use"
            and item.get("support_status") not in {"unsupported", "disputed"}
            for item in claims
        ):
            reasons.append("citation policy requires at least one usable evidence claim")
        if any(item.get("support_status") in {"unsupported", "disputed"} and item.get("use_policy") != "do_not_use" for item in claims):
            reasons.append("unresolved unsupported or disputed claims")
    elif gate_id == "G3":
        path = workspace / "narrative/narrative_blueprint.json"
        if not path.exists():
            reasons.append("narrative blueprint is missing")
        else:
            narrative = read_json(path)
            if narrative.get("planning_lineage"):
                graph = workspace_planning_graph(
                    workspace,
                    ("project_brief", "evidence_ledger", "narrative_blueprint"),
                )
                reasons.extend(
                    narrative_gate_reasons(
                        brief=graph["project_brief"]["data"],
                        evidence=graph["evidence_ledger"]["data"],
                        narrative=narrative,
                        graph=graph,
                    )
                )
            elif not narrative.get("central_thesis") or not narrative.get("sections"):
                reasons.append("narrative is incomplete")
    elif gate_id == "G4":
        path = workspace / "outline/deck_outline.json"
        if not path.exists():
            reasons.append("deck outline is missing")
        else:
            outline = read_json(path)
            if outline.get("planning_lineage"):
                graph = workspace_planning_graph(
                    workspace,
                    (
                        "project_brief",
                        "evidence_ledger",
                        "narrative_blueprint",
                        "deck_outline",
                    ),
                )
                reasons.extend(
                    outline_gate_reasons(
                        brief=graph["project_brief"]["data"],
                        evidence=graph["evidence_ledger"]["data"],
                        narrative=graph["narrative_blueprint"]["data"],
                        outline=outline,
                        graph=graph,
                    )
                )
            else:
                slides = [
                    item
                    for item in outline.get("slides", [])
                    if item.get("status") != "excluded"
                ]
                takeaways = [item.get("takeaway", "").strip() for item in slides]
                if not slides:
                    reasons.append("outline has no active slides")
                if len(set(takeaways)) != len(takeaways):
                    reasons.append("duplicate slide takeaways")
    elif gate_id == "G5A":
        g2 = evaluate_gate(workspace, "G2")
        if not g2.passed:
            reasons.append("G2 does not pass for the current Evidence lineage")
        evidence = read_json(workspace / "evidence/evidence_ledger.json")
        outline = read_json(workspace / "outline/deck_outline.json")
        specs_path = workspace / "slides/slide_specs.json"
        slide_specs = read_json(specs_path) if specs_path.exists() else None
        if slide_specs is not None and slide_specs.get("planning_lineage"):
            graph = workspace_planning_graph(
                workspace,
                ("project_brief", "evidence_ledger", "deck_outline", "slide_specs"),
            )
            reasons.extend(
                slide_specs_gate_reasons(
                    brief=graph["project_brief"]["data"],
                    evidence=graph["evidence_ledger"]["data"],
                    outline=graph["deck_outline"]["data"],
                    slide_specs=slide_specs,
                    graph=graph,
                    workspace=workspace,
                )
            )
        from slidethus.visual_quality import quality_path_required

        if quality_path_required(workspace) and not str(
            (slide_specs or {}).get("schema_version", "")
        ).startswith("0.2."):
            reasons.append(
                "reviewed/critical G5A requires representation-aware Slide Specs 0.2"
            )
        state = read_json(workspace / "project_state.json")
        artifacts_by_type = {
            str(item.get("artifact_type")): item for item in state.get("artifacts", [])
        }
        outline_entry = artifacts_by_type.get("deck_outline", {})
        reasons.extend(
            binding_gate_reasons(
                evidence=evidence,
                outline=outline,
                slide_specs=slide_specs,
                outline_version=outline_entry.get("version"),
            )
        )
    elif gate_id == "G5B":
        path = workspace / "layout/layout_plans.json"
        if not path.exists():
            reasons.append("layout plans are missing")
        else:
            layout_plans = read_json(path)
            if layout_plans.get("planning_lineage"):
                graph = workspace_planning_graph(
                    workspace,
                    ("project_brief", "deck_outline", "slide_specs", "layout_plans"),
                )
                reasons.extend(
                    layout_gate_reasons(
                        workspace,
                        brief=graph["project_brief"]["data"],
                        outline=graph["deck_outline"]["data"],
                        slide_specs=graph["slide_specs"]["data"],
                        layout_plans=layout_plans,
                        graph=graph,
                    )
                )
                if str(layout_plans.get("schema_version", "")).startswith("0.2."):
                    # Imported lazily because visual-quality persistence uses
                    # ArtifactRuntime, whose evaluator imports this module.
                    from slidethus.visual_quality import planning_admission_errors

                    reasons.extend(planning_admission_errors(workspace))
    elif gate_id == "G6":
        g5b = evaluate_gate(workspace, "G5B")
        if not g5b.passed:
            reasons.append("G5B does not pass for the current semantic planning lineage")
        state = read_json(workspace / "project_state.json")
        path = workspace / "design/visual_system.json"
        visual = read_json(path) if path.exists() else None
        reasons.extend(
            visual_system_gate_reasons(
                state=state,
                visual_system=visual,
                workspace=workspace,
            )
        )
        from slidethus.visual_quality import quality_path_required

        if quality_path_required(workspace) and not str(
            (visual or {}).get("schema_version", "")
        ).startswith("0.2."):
            reasons.append(
                "reviewed/critical G6 requires a closed-grammar Visual System 0.2"
            )
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
            if render.get("pipeline_mode") == "production_multi_backend":
                reasons.extend(production_render_gate_reasons(workspace, render))
            elif render.get("pipeline_mode") == "complete_mvp":
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
        elif render.get("pipeline_mode") == "production_multi_backend":
            reasons.extend(
                production_quality_gate_reasons(
                    workspace,
                    report,
                    SchemaRegistry().schema_dir,
                )
            )
        from slidethus.visual_quality import whole_deck_admission_errors

        reasons.extend(whole_deck_admission_errors(workspace))
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
