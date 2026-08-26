from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slidethus.errors import WorkspaceError
from slidethus.gate_contracts import GATE_REQUIRED_PATHS
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.schema_registry import SchemaRegistry


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    severity: str = "error"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def add(self, code: str, message: str, path: str = "", severity: str = "error") -> None:
        self.issues.append(ValidationIssue(code, message, path, severity))

    def extend(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues.extend(issues)


PHASE_REQUIRED_ARTIFACTS: dict[str, set[str]] = {
    "CREATED": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "asset_manifest"},
    "BRIEF_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "asset_manifest"},
    "SOURCES_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "asset_manifest"},
    "EVIDENCE_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "asset_manifest"},
    "NARRATIVE_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "asset_manifest"},
    "OUTLINE_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "asset_manifest"},
    "SLIDE_SPECS_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "asset_manifest"},
    "LAYOUT_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "asset_manifest"},
    "VISUAL_SYSTEM_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "asset_manifest"},
    "DRAFT_RENDERED": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "asset_manifest", "render_manifest"},
    "REVIEWED": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "asset_manifest", "render_manifest", "quality_report"},
    "DELIVERY_READY": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "asset_manifest", "render_manifest", "quality_report", "delivery_manifest"},
    "COMPLETED": {"project_state", "project_brief", "source_ledger", "evidence_ledger", "narrative_blueprint", "deck_outline", "slide_specs", "layout_plans", "visual_system", "asset_manifest", "render_manifest", "quality_report", "delivery_manifest"},
}


PHASE_REQUIRED_GATES: dict[str, tuple[str, ...]] = {
    "CREATED": (),
    "BRIEF_READY": ("G0",),
    "SOURCES_READY": ("G0", "G1"),
    "EVIDENCE_READY": ("G0", "G1", "G2"),
    "NARRATIVE_READY": ("G0", "G1", "G2", "G3"),
    "OUTLINE_READY": ("G0", "G1", "G2", "G3", "G4"),
    "SLIDE_SPECS_READY": ("G0", "G1", "G2", "G3", "G4", "G5A"),
    "LAYOUT_READY": ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B"),
    "VISUAL_SYSTEM_READY": ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6"),
    "DRAFT_RENDERED": ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7"),
    "REVIEWED": ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7", "G8"),
    "DELIVERY_READY": ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7", "G8", "G9"),
    "COMPLETED": ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7", "G8", "G9"),
}

RUNTIME_ARTIFACTS = {"gate_results", "decision_log", "assumption_log"}
for _required_artifacts in PHASE_REQUIRED_ARTIFACTS.values():
    _required_artifacts.update(RUNTIME_ARTIFACTS)

EDITABILITY_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}


def _json_path(parts: Iterable[Any]) -> str:
    return "/".join(str(part) for part in parts)


def _unique_ids(report: ValidationReport, values: list[str], path: str, kind: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            report.add("duplicate_id", f"Duplicate {kind} ID: {value}", path)
        seen.add(value)


def _safe_workspace_path(
    report: ValidationReport,
    workspace: Path,
    raw_path: Any,
    *,
    issue_path: str,
) -> Path | None:
    try:
        relative = Path(str(raw_path))
        if relative.is_absolute():
            raise WorkspaceError(f"Absolute paths are not allowed: {relative}")
        return ensure_within(workspace, workspace / relative)
    except (WorkspaceError, OSError, ValueError) as exc:
        report.add("unsafe_workspace_path", str(exc), issue_path)
        return None


def validate_workspace(workspace: Path, registry: SchemaRegistry | None = None, *, check_hashes: bool = False) -> ValidationReport:
    """Validate all present artifacts plus phase-required artifacts and cross references."""

    workspace = workspace.resolve()
    report = ValidationReport()
    registry = registry or SchemaRegistry()

    state_path = workspace / "project_state.json"
    if not state_path.exists():
        report.add("missing_project_state", "Missing project_state.json", "project_state.json")
        return report

    try:
        state = read_json(state_path)
    except Exception as exc:  # noqa: BLE001 - convert parse error into report
        report.add("invalid_json", str(exc), "project_state.json")
        return report

    current_phase = state.get("current_phase", "CREATED")
    required = PHASE_REQUIRED_ARTIFACTS.get(current_phase, {"project_state", "project_brief"})
    loaded: dict[str, Any] = {}

    for artifact_type, entry in registry.entries.items():
        artifact_path = workspace / entry.default_path
        if not artifact_path.exists():
            if artifact_type in required:
                report.add("missing_artifact", f"Required artifact is missing for phase {current_phase}", entry.default_path.as_posix())
            continue
        try:
            data = read_json(artifact_path)
            loaded[artifact_type] = data
        except Exception as exc:  # noqa: BLE001
            report.add("invalid_json", str(exc), entry.default_path.as_posix())
            continue
        for error in sorted(registry.validator(artifact_type).iter_errors(data), key=lambda item: list(item.path)):
            path = f"{entry.default_path.as_posix()}#{_json_path(error.absolute_path)}"
            report.add("schema_error", error.message, path)

    _validate_cross_references(report, workspace, state, loaded, registry, check_hashes=check_hashes)
    return report


def _validate_cross_references(
    report: ValidationReport,
    workspace: Path,
    state: dict[str, Any],
    loaded: dict[str, Any],
    registry: SchemaRegistry,
    *,
    check_hashes: bool,
) -> None:
    project_id = state.get("project_id")
    open_blockers = [item for item in state.get("blockers", []) if item.get("status") == "open"]
    state_status = state.get("status")
    current_phase = state.get("current_phase")
    if open_blockers and state_status not in {"blocked", "failed"}:
        report.add("state_blocker_mismatch", "Open blockers require project status blocked or failed", "project_state.json")
    if state_status == "blocked" and not open_blockers:
        report.add("state_blocker_mismatch", "Blocked project must record at least one open blocker", "project_state.json")
    if (current_phase == "COMPLETED") != (state_status == "completed"):
        report.add("state_completion_mismatch", "COMPLETED phase and completed status must be set together", "project_state.json")

    blocker_ids = [str(item.get("blocker_id", "")) for item in state.get("blockers", [])]
    decision_ids = [str(item.get("decision_id", "")) for item in state.get("decisions", [])]
    _unique_ids(report, blocker_ids, "project_state.json", "blocker")
    _unique_ids(report, decision_ids, "project_state.json", "decision")

    brief = loaded.get("project_brief", {})
    _unique_ids(
        report,
        [str(item.get("audience_id", "")) for item in brief.get("audiences", [])],
        "brief/project_brief.json",
        "audience",
    )
    _unique_ids(
        report,
        [str(item.get("assumption_id", "")) for item in brief.get("assumptions", [])],
        "brief/project_brief.json",
        "assumption",
    )
    _unique_ids(
        report,
        [str(item.get("question_id", "")) for item in brief.get("open_questions", [])],
        "brief/project_brief.json",
        "question",
    )
    page_count = brief.get("constraints", {}).get("page_count", {})
    minimum = page_count.get("min")
    target = page_count.get("target")
    maximum = page_count.get("max")
    if all(isinstance(value, int) for value in (minimum, target, maximum)) and not minimum <= target <= maximum:
        report.add(
            "invalid_page_count_range",
            f"Page-count contract must satisfy min <= target <= max, got {minimum} <= {target} <= {maximum}",
            "brief/project_brief.json",
        )

    completed_gates = state.get("completed_gates", [])
    gate_ids = [str(item.get("gate_id", "")) for item in completed_gates]
    _unique_ids(report, gate_ids, "project_state.json", "gate")
    gates_by_id = {item.get("gate_id"): item for item in completed_gates}
    for gate_id in PHASE_REQUIRED_GATES.get(str(current_phase), ()):
        gate = gates_by_id.get(gate_id)
        if gate is None:
            report.add("missing_phase_gate", f"Phase {current_phase} requires {gate_id}", "project_state.json")
        elif gate.get("status") not in {"pass", "waived"}:
            report.add("failed_phase_gate", f"Phase {current_phase} requires {gate_id} to pass or be waived", "project_state.json")

    gate_records = loaded.get("gate_results", {}).get("records", [])
    gate_record_ids = [str(item.get("gate_record_id", "")) for item in gate_records]
    _unique_ids(report, gate_record_ids, "gates/gate_results.json", "gate result")
    gate_records_by_id = {item.get("gate_record_id"): item for item in gate_records}
    for summary in completed_gates:
        record = gate_records_by_id.get(summary.get("gate_record_id"))
        if record is None:
            report.add(
                "missing_gate_record",
                f"Gate summary {summary.get('gate_id')} has no persisted record",
                "project_state.json",
            )
            continue
        if record.get("gate_id") != summary.get("gate_id") or record.get("status") != summary.get("status"):
            report.add("gate_record_mismatch", "Gate summary and persisted record disagree", "project_state.json")
        if record.get("artifact_versions") != summary.get("artifact_versions"):
            report.add("gate_record_mismatch", "Gate artifact versions disagree", "project_state.json")
        hashes = [item.get("sha256") for item in summary.get("artifact_versions", [])]
        if summary.get("artifact_hashes") != hashes:
            report.add("gate_hash_summary_mismatch", "Gate hashes must derive from artifact_versions", "project_state.json")

    for artifact_type, data in loaded.items():
        if data.get("project_id") and data.get("project_id") != project_id:
            report.add("project_id_mismatch", f"{artifact_type} project_id does not match state", registry.entry(artifact_type).default_path.as_posix())

    sources = loaded.get("source_ledger", {}).get("sources", [])
    source_ids = [item["source_id"] for item in sources if "source_id" in item]
    _unique_ids(report, source_ids, "sources/source_ledger.json", "source")
    source_set = set(source_ids)
    source_status = {
        item.get("source_id"): (item.get("parse_status"), item.get("allowed_use"))
        for item in sources
    }

    evidence_ledger = loaded.get("evidence_ledger", {})
    research_cycles = evidence_ledger.get("research_cycles", [])
    cycle_ids = [item["cycle_id"] for item in research_cycles if "cycle_id" in item]
    _unique_ids(report, cycle_ids, "evidence/evidence_ledger.json", "research cycle")
    for cycle in research_cycles:
        for source_id in cycle.get("source_ids", []):
            if source_id not in source_set:
                report.add(
                    "missing_source_ref",
                    f"Research cycle {cycle.get('cycle_id')} references unknown source {source_id}",
                    "evidence/evidence_ledger.json",
                )

    claims = evidence_ledger.get("claims", [])
    evidence_ids = [item["evidence_id"] for item in claims if "evidence_id" in item]
    _unique_ids(report, evidence_ids, "evidence/evidence_ledger.json", "evidence")
    evidence_set = set(evidence_ids)
    evidence_status = {item.get("evidence_id"): (item.get("support_status"), item.get("use_policy")) for item in claims}

    assets = loaded.get("asset_manifest", {}).get("assets", [])
    asset_ids = [item["asset_id"] for item in assets if "asset_id" in item]
    _unique_ids(report, asset_ids, "assets/asset_manifest.json", "asset")
    asset_set = set(asset_ids)
    asset_status = {item.get("asset_id"): (item.get("status"), item.get("allowed_use")) for item in assets}

    decision_log = loaded.get("decision_log", {}).get("decisions", [])
    assumption_log = loaded.get("assumption_log", {}).get("assumptions", [])
    _unique_ids(report, [str(item.get("decision_id", "")) for item in decision_log], "decisions/decision_log.json", "decision log")
    _unique_ids(report, [str(item.get("assumption_id", "")) for item in assumption_log], "decisions/assumption_log.json", "assumption log")

    for claim in claims:
        for ref in claim.get("source_refs", []):
            source_id = ref.get("source_id")
            if source_id not in source_set:
                report.add("missing_source_ref", f"Evidence {claim.get('evidence_id')} references unknown source {source_id}", "evidence/evidence_ledger.json")
            else:
                _parse_status, allowed_use = source_status.get(source_id, (None, None))
                if allowed_use == "do_not_use":
                    report.add(
                        "unusable_source",
                        f"Evidence {claim.get('evidence_id')} references source {source_id} marked do_not_use",
                        "evidence/evidence_ledger.json",
                    )

    narrative = loaded.get("narrative_blueprint", {})
    narrative_sections = narrative.get("sections", [])
    section_ids = [str(section.get("section_id", "")) for section in narrative_sections]
    _unique_ids(report, section_ids, "narrative/narrative_blueprint.json", "section")
    section_set = set(section_ids)
    for section in narrative_sections:
        for evidence_id in section.get("evidence_ids", []):
            if evidence_id not in evidence_set:
                report.add("missing_evidence_ref", f"Narrative section references unknown evidence {evidence_id}", "narrative/narrative_blueprint.json")
            else:
                status, policy = evidence_status.get(evidence_id, (None, None))
                if status in {"unsupported", "disputed"} or policy == "do_not_use":
                    report.add("unusable_evidence", f"Narrative section uses {evidence_id} with status={status}, policy={policy}", "narrative/narrative_blueprint.json")
    for objection in narrative.get("objections", []):
        for evidence_id in objection.get("evidence_ids", []):
            if evidence_id not in evidence_set:
                report.add(
                    "missing_evidence_ref",
                    f"Narrative objection references unknown evidence {evidence_id}",
                    "narrative/narrative_blueprint.json",
                )
            else:
                status, policy = evidence_status.get(evidence_id, (None, None))
                if status in {"unsupported", "disputed"} or policy == "do_not_use":
                    report.add(
                        "unusable_evidence",
                        f"Narrative objection uses {evidence_id} with status={status}, policy={policy}",
                        "narrative/narrative_blueprint.json",
                    )

    outline = loaded.get("deck_outline", {})
    deck_ids = {
        artifact_type: data.get("deck_id")
        for artifact_type, data in loaded.items()
        if artifact_type in {"deck_outline", "slide_specs", "layout_plans", "visual_system", "render_manifest"} and data.get("deck_id")
    }
    if len(set(deck_ids.values())) > 1:
        report.add("deck_id_mismatch", f"Deck IDs are inconsistent: {deck_ids}", "project_state.json")

    active_outline_slides = [slide for slide in outline.get("slides", []) if slide.get("status") != "excluded"]
    slide_ids = [slide["slide_id"] for slide in active_outline_slides if "slide_id" in slide]
    _unique_ids(report, slide_ids, "outline/deck_outline.json", "slide")
    ordinals = [slide.get("ordinal") for slide in active_outline_slides]
    if ordinals and sorted(ordinals) != list(range(1, len(ordinals) + 1)):
        report.add("invalid_ordinals", "Active slide ordinals must be contiguous from 1", "outline/deck_outline.json")
    if outline and outline.get("target_page_count") != len(active_outline_slides):
        report.add("page_count_mismatch", "target_page_count does not equal active slide count", "outline/deck_outline.json")
    for slide in active_outline_slides:
        section_id = slide.get("section_id")
        if section_id not in section_set:
            report.add(
                "missing_section_ref",
                f"Slide {slide.get('slide_id')} references unknown narrative section {section_id}",
                "outline/deck_outline.json",
            )
        for evidence_id in slide.get("evidence_ids", []):
            if evidence_id not in evidence_set:
                report.add("missing_evidence_ref", f"Slide {slide.get('slide_id')} references unknown evidence {evidence_id}", "outline/deck_outline.json")
            else:
                status, policy = evidence_status.get(evidence_id, (None, None))
                if status in {"unsupported", "disputed"} or policy == "do_not_use":
                    report.add("unusable_evidence", f"Slide {slide.get('slide_id')} uses {evidence_id} with status={status}, policy={policy}", "outline/deck_outline.json")

    specs = loaded.get("slide_specs", {}).get("slides", [])
    spec_ids = [slide["slide_id"] for slide in specs if "slide_id" in slide]
    if slide_ids and set(spec_ids) != set(slide_ids):
        report.add("slide_coverage_mismatch", f"Slide Specs IDs {sorted(spec_ids)} do not match Outline IDs {sorted(slide_ids)}", "slides/slide_specs.json")
    _unique_ids(report, spec_ids, "slides/slide_specs.json", "slide spec")
    block_map: dict[str, set[str]] = {}
    all_block_ids: list[str] = []
    for slide in specs:
        blocks = slide.get("content_blocks", [])
        block_ids = [block["block_id"] for block in blocks if "block_id" in block]
        slide_id = str(slide.get("slide_id", ""))
        block_map[slide_id] = set(block_ids)
        all_block_ids.extend(block_ids)
        expected_prefix = f"BLK-{slide_id.replace('-', '')}-"
        for block_id in block_ids:
            if not block_id.startswith(expected_prefix):
                report.add(
                    "block_slide_mismatch",
                    f"Block {block_id} is nested under {slide_id} but its ID encodes another slide",
                    "slides/slide_specs.json",
                )
        budget = slide.get("density_budget", {})
        if len(blocks) > budget.get("max_blocks", len(blocks)):
            report.add("density_budget_exceeded", f"{slide.get('slide_id')} has {len(blocks)} blocks but max_blocks={budget.get('max_blocks')}", "slides/slide_specs.json", "warning")
        for block in blocks:
            for evidence_id in block.get("evidence_ids", []):
                if evidence_id not in evidence_set:
                    report.add("missing_evidence_ref", f"Block {block.get('block_id')} references unknown evidence {evidence_id}", "slides/slide_specs.json")
                else:
                    status, policy = evidence_status.get(evidence_id, (None, None))
                    if status in {"unsupported", "disputed"} or policy == "do_not_use":
                        report.add("unusable_evidence", f"Block {block.get('block_id')} uses {evidence_id} with status={status}, policy={policy}", "slides/slide_specs.json")
            for asset_id in block.get("asset_refs", []):
                if asset_id not in asset_set:
                    report.add("missing_asset_ref", f"Block {block.get('block_id')} references unknown asset {asset_id}", "slides/slide_specs.json")
                else:
                    status, policy = asset_status.get(asset_id, (None, None))
                    if status != "available" or policy == "do_not_use":
                        report.add("unusable_asset", f"Block {block.get('block_id')} uses {asset_id} with status={status}, policy={policy}", "slides/slide_specs.json")
    _unique_ids(report, all_block_ids, "slides/slide_specs.json", "block")

    layout = loaded.get("layout_plans", {})
    plans = layout.get("plans", [])
    plan_ids = [plan["slide_id"] for plan in plans if "slide_id" in plan]
    if slide_ids and set(plan_ids) != set(slide_ids):
        report.add("layout_coverage_mismatch", f"Layout IDs {sorted(plan_ids)} do not match Outline IDs {sorted(slide_ids)}", "layout/layout_plans.json")
    _unique_ids(report, plan_ids, "layout/layout_plans.json", "layout plan")
    canvas = layout.get("canvas", {})
    width, height = canvas.get("width", 0), canvas.get("height", 0)
    safe_area = layout.get("safe_area", {})
    if layout and (safe_area.get("left", 0) + safe_area.get("right", 0) >= width or safe_area.get("top", 0) + safe_area.get("bottom", 0) >= height):
        report.add("invalid_safe_area", "Safe-area margins must leave a positive drawable region", "layout/layout_plans.json")
    aspect_ratio = brief.get("constraints", {}).get("aspect_ratio")
    if layout and width and height and aspect_ratio in {"16:9", "4:3"}:
        expected = 16 / 9 if aspect_ratio == "16:9" else 4 / 3
        if abs(width / height - expected) > 0.01:
            report.add(
                "aspect_ratio_mismatch",
                f"Layout canvas {width}x{height} does not match brief aspect ratio {aspect_ratio}",
                "layout/layout_plans.json",
            )
    all_region_ids: list[str] = []
    for plan in plans:
        regions = plan.get("regions", [])
        region_ids = [region["region_id"] for region in regions if "region_id" in region]
        all_region_ids.extend(region_ids)
        reading_order = plan.get("reading_order", [])
        if set(reading_order) != set(region_ids) or len(reading_order) != len(region_ids):
            report.add("reading_order_mismatch", f"{plan.get('slide_id')} reading_order must contain every region exactly once", "layout/layout_plans.json")
        slide_id = str(plan.get("slide_id", ""))
        expected_region_prefix = f"REG-{slide_id.replace('-', '')}-"
        for region_id in region_ids:
            if not region_id.startswith(expected_region_prefix):
                report.add(
                    "region_slide_mismatch",
                    f"Region {region_id} is nested under {slide_id} but its ID encodes another slide",
                    "layout/layout_plans.json",
                )
        placed_blocks = [str(region.get("block_id", "")) for region in regions]
        expected_blocks = block_map.get(slide_id, set())
        if set(placed_blocks) != expected_blocks or len(placed_blocks) != len(expected_blocks):
            report.add(
                "block_coverage_mismatch",
                f"{slide_id} layout must place every content block exactly once",
                "layout/layout_plans.json",
            )
        for region in regions:
            slide_id = plan.get("slide_id", "")
            block_id = region.get("block_id")
            if block_id not in block_map.get(slide_id, set()):
                report.add("missing_block_ref", f"Region {region.get('region_id')} references unknown block {block_id} for {slide_id}", "layout/layout_plans.json")
            if region.get("x", 0) + region.get("w", 0) > width or region.get("y", 0) + region.get("h", 0) > height:
                report.add("region_out_of_canvas", f"Region {region.get('region_id')} exceeds {width}x{height} canvas", "layout/layout_plans.json")
            if plan.get("layout_family") != "full-bleed":
                if (
                    region.get("x", 0) < safe_area.get("left", 0)
                    or region.get("y", 0) < safe_area.get("top", 0)
                    or region.get("x", 0) + region.get("w", 0) > width - safe_area.get("right", 0)
                    or region.get("y", 0) + region.get("h", 0) > height - safe_area.get("bottom", 0)
                ):
                    report.add("region_outside_safe_area", f"Region {region.get('region_id')} exceeds the declared safe area", "layout/layout_plans.json")
    _unique_ids(report, all_region_ids, "layout/layout_plans.json", "region")

    if brief and outline:
        page_count = brief.get("constraints", {}).get("page_count", {})
        target = outline.get("target_page_count")
        if target is not None and not (page_count.get("min", target) <= target <= page_count.get("max", target)):
            report.add("page_count_outside_brief", f"Outline target {target} is outside brief range", "outline/deck_outline.json")

    visual = loaded.get("visual_system", {})
    for asset_id in visual.get("brand_assets", []):
        if asset_id not in asset_set:
            report.add("missing_asset_ref", f"Visual System references unknown brand asset {asset_id}", "design/visual_system.json")
        else:
            status, policy = asset_status.get(asset_id, (None, None))
            if status != "available" or policy == "do_not_use":
                report.add("unusable_asset", f"Visual System uses {asset_id} with status={status}, policy={policy}", "design/visual_system.json")

    state_artifacts = state.get("artifacts", [])
    registry_paths = [str(item.get("path", "")) for item in state_artifacts]
    registry_types = [str(item.get("artifact_type", "")) for item in state_artifacts]
    _unique_ids(report, registry_paths, "project_state.json", "registered artifact path")
    _unique_ids(report, registry_types, "project_state.json", "registered artifact type")
    registered_by_path = {item.get("path"): item for item in state_artifacts}

    def artifact_version_exists(reference: dict[str, Any]) -> bool:
        registered = registered_by_path.get(reference.get("path"))
        if registered is None or registered.get("artifact_type") != reference.get("artifact_type"):
            return False
        version = reference.get("version")
        current_version = registered.get("version")
        if version == current_version:
            return registered.get("sha256") == reference.get("sha256")
        if not isinstance(version, int) or not isinstance(current_version, int) or version >= current_version:
            return False
        history_path = workspace / ".slidethus" / "history" / str(reference.get("artifact_type")) / f"{version:06d}.json"
        return history_path.exists() and sha256_file(history_path) == reference.get("sha256")

    valid_issue_ids = {item.get("issue_id") for item in loaded.get("quality_report", {}).get("issues", [])}
    for record in gate_records:
        for reference in record.get("artifact_versions", []):
            if not artifact_version_exists(reference):
                report.add(
                    "invalid_gate_artifact_version",
                    f"Gate {record.get('gate_record_id')} references an unavailable artifact version",
                    "gates/gate_results.json",
                )
        for issue_ref in record.get("issue_refs", []):
            if issue_ref not in valid_issue_ids:
                report.add(
                    "invalid_gate_issue_ref",
                    f"Gate {record.get('gate_record_id')} references unknown issue {issue_ref}",
                    "gates/gate_results.json",
                )
        critical_checks = [item for item in record.get("check_results", []) if item.get("severity") == "critical"]
        if record.get("status") == "waived" and critical_checks:
            report.add("critical_gate_waiver", "Critical Gate checks cannot be waived", "gates/gate_results.json")
        if record.get("status") == "waived" and (not record.get("approved_by") or not record.get("waiver_reason")):
            report.add("invalid_gate_waiver", "A waiver requires approver and reason", "gates/gate_results.json")

    for required_gate_id in PHASE_REQUIRED_GATES.get(str(current_phase), ()):
        summary = gates_by_id.get(required_gate_id, {})
        refs_by_path = {
            item.get("path"): item for item in summary.get("artifact_versions", [])
        }
        for required_path in GATE_REQUIRED_PATHS.get(required_gate_id, ()):
            registered = registered_by_path.get(required_path)
            reference = refs_by_path.get(required_path)
            if registered is None or reference is None or (
                reference.get("version") != registered.get("version")
                or reference.get("sha256") != registered.get("sha256")
            ):
                report.add(
                    "stale_phase_gate",
                    f"Phase {current_phase} requires {required_gate_id} against current {required_path}",
                    "project_state.json",
                )

    if current_phase in {
        "SLIDE_SPECS_READY",
        "LAYOUT_READY",
        "VISUAL_SYSTEM_READY",
        "DRAFT_RENDERED",
        "REVIEWED",
        "DELIVERY_READY",
        "COMPLETED",
    }:
        outline_entry = registered_by_path.get("outline/deck_outline.json", {})
        outline_version = outline_entry.get("version")
        targeted_complete = any(
            cycle.get("kind") == "targeted"
            and cycle.get("status") in {"complete", "waived"}
            and cycle.get("outline_version") == outline_version
            for cycle in research_cycles
        )
        if not targeted_complete:
            report.add(
                "targeted_evidence_incomplete",
                f"Phase {current_phase} requires a complete or waived targeted research cycle for outline version {outline_version}",
                "evidence/evidence_ledger.json",
            )

    for artifact_type in loaded:
        if artifact_type == "project_state":
            continue
        expected_path = registry.entry(artifact_type).default_path.as_posix()
        if expected_path not in registered_by_path:
            report.add("unregistered_artifact", f"Present artifact is not registered: {expected_path}", "project_state.json")

    render = loaded.get("render_manifest", {})
    for input_artifact in render.get("input_artifacts", []):
        relative = input_artifact.get("path")
        registered = registered_by_path.get(relative)
        artifact_path = _safe_workspace_path(report, workspace, relative, issue_path="renders/render_manifest.json")
        if artifact_path is None:
            continue
        if registered is None or not artifact_path.exists():
            report.add("invalid_render_input", f"Render input is not a registered existing artifact: {relative}", "renders/render_manifest.json")
        elif input_artifact.get("version") != registered.get("version"):
            report.add("render_input_version_mismatch", f"Render input version mismatch: {relative}", "renders/render_manifest.json")
        elif input_artifact.get("sha256") != sha256_file(artifact_path):
            report.add("render_input_hash_mismatch", f"Render input hash mismatch: {relative}", "renders/render_manifest.json")
    render_outputs = render.get("outputs", [])
    if render.get("status") == "success" and render.get("editability_level") == "not_measured":
        report.add(
            "unmeasured_render_editability",
            "Successful render must record actual measured editability",
            "renders/render_manifest.json",
        )
    if render.get("status") == "success":
        actual = render.get("editability_level")
        target_level = render.get("target_editability_level")
        if actual in EDITABILITY_ORDER and target_level in EDITABILITY_ORDER and EDITABILITY_ORDER[actual] < EDITABILITY_ORDER[target_level]:
            report.add(
                "editability_below_target",
                f"Successful render measured {actual}, below target {target_level}",
                "renders/render_manifest.json",
            )
    if render.get("status") == "success" and not render_outputs:
        report.add("missing_render_output", "Successful render must record at least one output", "renders/render_manifest.json")
    for output in render_outputs:
        output_path = _safe_workspace_path(report, workspace, output.get("path"), issue_path="renders/render_manifest.json")
        if output_path is None:
            continue
        if not output_path.exists():
            report.add("missing_render_output", f"Render output does not exist: {output.get('path')}", "renders/render_manifest.json")
        elif output.get("sha256") != sha256_file(output_path):
            report.add("render_output_hash_mismatch", f"Render output hash mismatch: {output.get('path')}", "renders/render_manifest.json")

    delivery = loaded.get("delivery_manifest", {})
    for artifact_version in delivery.get("artifact_versions", []):
        relative = artifact_version.get("path")
        registered = registered_by_path.get(relative)
        artifact_path = _safe_workspace_path(report, workspace, relative, issue_path="delivery/delivery_manifest.json")
        if artifact_path is None:
            continue
        if registered is None or not artifact_path.exists():
            report.add("invalid_delivery_artifact", f"Delivery references an unregistered artifact: {relative}", "delivery/delivery_manifest.json")
        elif artifact_version.get("artifact_type") != registered.get("artifact_type") or artifact_version.get("version") != registered.get("version"):
            report.add("delivery_artifact_version_mismatch", f"Delivery artifact version mismatch: {relative}", "delivery/delivery_manifest.json")
        elif artifact_version.get("sha256") != sha256_file(artifact_path):
            report.add("delivery_artifact_hash_mismatch", f"Delivery artifact hash mismatch: {relative}", "delivery/delivery_manifest.json")
    delivery_outputs = delivery.get("outputs", [])
    if delivery.get("status") in {"ready", "delivered"} and delivery.get("editability_level") == "not_measured":
        report.add(
            "unmeasured_delivery_editability",
            "Ready or delivered manifest must record actual measured editability",
            "delivery/delivery_manifest.json",
        )
    if delivery.get("status") in {"ready", "delivered"}:
        actual = delivery.get("editability_level")
        target_level = delivery.get("target_editability_level")
        if actual in EDITABILITY_ORDER and target_level in EDITABILITY_ORDER and EDITABILITY_ORDER[actual] < EDITABILITY_ORDER[target_level]:
            report.add(
                "editability_below_target",
                f"Ready delivery measured {actual}, below target {target_level}",
                "delivery/delivery_manifest.json",
            )
    if delivery.get("status") in {"ready", "delivered"} and not delivery_outputs:
        report.add("missing_delivery_output", "Ready or delivered manifest must record at least one output", "delivery/delivery_manifest.json")
    for output in delivery_outputs:
        output_path = _safe_workspace_path(report, workspace, output.get("path"), issue_path="delivery/delivery_manifest.json")
        if output_path is None:
            continue
        if not output_path.exists():
            report.add("missing_delivery_output", f"Delivery output does not exist: {output.get('path')}", "delivery/delivery_manifest.json")
        elif output.get("sha256") != sha256_file(output_path):
            report.add("delivery_output_hash_mismatch", f"Delivery output hash mismatch: {output.get('path')}", "delivery/delivery_manifest.json")

    quality = loaded.get("quality_report", {})
    valid_slide_ids = set(slide_ids)
    valid_block_ids = set(all_block_ids)
    valid_region_ids = set(all_region_ids)
    blocking_quality_issues = []
    for issue in quality.get("issues", []):
        if issue.get("slide_id") and issue["slide_id"] not in valid_slide_ids:
            report.add("invalid_issue_ref", f"Issue {issue.get('issue_id')} references unknown slide", "review/quality_report.json")
        if issue.get("block_id") and issue["block_id"] not in valid_block_ids:
            report.add("invalid_issue_ref", f"Issue {issue.get('issue_id')} references unknown block", "review/quality_report.json")
        if issue.get("region_id") and issue["region_id"] not in valid_region_ids:
            report.add("invalid_issue_ref", f"Issue {issue.get('issue_id')} references unknown region", "review/quality_report.json")
        if issue.get("status") == "open" and issue.get("severity") in {"critical", "major"}:
            blocking_quality_issues.append(issue)
    if quality:
        gate_status = quality.get("gate_result", {}).get("status")
        if (quality.get("status") == "pass") != (gate_status == "pass"):
            report.add("quality_gate_mismatch", "Quality status pass and gate_result pass must agree", "review/quality_report.json")
        if quality.get("status") == "pass" and blocking_quality_issues:
            report.add("quality_blocker_mismatch", "Passing Quality Report cannot contain open Critical/Major issues", "review/quality_report.json")

    if current_phase in {"DRAFT_RENDERED", "REVIEWED", "DELIVERY_READY", "COMPLETED"} and render.get("status") != "success":
        report.add("phase_render_mismatch", f"Phase {current_phase} requires a successful render", "project_state.json")
    if current_phase in {"REVIEWED", "DELIVERY_READY", "COMPLETED"}:
        quality_gate = quality.get("gate_result", {})
        if quality.get("status") != "pass" or quality_gate.get("gate_id") != "G8" or quality_gate.get("status") != "pass":
            report.add(
                "phase_review_mismatch",
                f"Phase {current_phase} requires a passing Quality Report for G8",
                "project_state.json",
            )
    if current_phase in {"DELIVERY_READY", "COMPLETED"} and delivery.get("status") not in {"ready", "delivered"}:
        report.add("phase_delivery_mismatch", f"Phase {current_phase} requires a ready or delivered manifest", "project_state.json")
    if current_phase in {"DELIVERY_READY", "COMPLETED"}:
        declared_waivers = "\n".join(delivery.get("waivers", []))
        for record in gate_records:
            if record.get("status") == "waived" and record.get("gate_record_id") not in declared_waivers:
                report.add(
                    "missing_delivery_waiver",
                    f"Delivery Manifest must disclose waived Gate record {record.get('gate_record_id')}",
                    "delivery/delivery_manifest.json",
                )

    for artifact in state_artifacts:
        raw_relative = artifact.get("path", "")
        relative = Path(str(raw_relative))
        artifact_path = _safe_workspace_path(report, workspace, raw_relative, issue_path="project_state.json")
        if artifact_path is None:
            continue
        if not artifact_path.exists():
            report.add("registry_missing_file", f"Registered artifact does not exist: {relative}", "project_state.json")
            continue
        expected_type = registry.artifact_type_for_path(relative)
        if expected_type is None:
            report.add("registry_unknown_path", f"Registered path is not in the schema catalog: {relative}", "project_state.json")
            continue
        if expected_type != artifact.get("artifact_type"):
            report.add("registry_type_mismatch", f"{relative} is cataloged as {expected_type}, state says {artifact.get('artifact_type')}", "project_state.json")
        expected_schema = registry.entry(expected_type).schema_path.name
        if artifact.get("schema") != expected_schema:
            report.add("registry_schema_mismatch", f"{relative} should use {expected_schema}, state says {artifact.get('schema')}", "project_state.json")
        if artifact.get("project_id") != project_id:
            report.add("registry_project_mismatch", f"{relative} registry project_id does not match state", "project_state.json")
        artifact_data = loaded.get(expected_type)
        if artifact_data is not None:
            if artifact.get("schema_version") != artifact_data.get("schema_version"):
                report.add("registry_schema_version_mismatch", f"{relative} schema_version does not match content", "project_state.json")
            if artifact.get("content_hash") != f"sha256:{sha256_json(artifact_data)}":
                report.add("artifact_content_hash_mismatch", f"Content hash mismatch for {relative}", "project_state.json")
        if check_hashes and artifact.get("sha256") and artifact["sha256"] != sha256_file(artifact_path):
            report.add("artifact_hash_mismatch", f"Hash mismatch for {relative}", "project_state.json")


def format_report(report: ValidationReport) -> str:
    if not report.issues:
        return "PASS: no validation issues"
    lines = []
    for issue in report.issues:
        location = f" [{issue.path}]" if issue.path else ""
        lines.append(f"{issue.severity.upper()} {issue.code}{location}: {issue.message}")
    lines.append(f"RESULT: {'PASS' if report.ok else 'FAIL'} ({len(report.issues)} issue(s))")
    return "\n".join(lines)
