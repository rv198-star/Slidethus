from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from slidethus.art_direction_seed import (
    validate_seed_fulfillment,
    validate_seed_reference_for_graph,
)
from slidethus.brief_completion import is_unresolved
from slidethus.errors import ArtifactError, WorkspaceError
from slidethus.io_utils import ensure_within, sha256_file, sha256_json
from slidethus.planning_lineage import planning_lineage_reference_errors
from slidethus.text_capacity import estimated_text_height


def usable_evidence_map(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return Evidence claims admitted for planning use."""

    return {
        str(item["evidence_id"]): item
        for item in evidence.get("claims", [])
        if item.get("support_status") not in {"unsupported", "disputed"}
        and item.get("use_policy") != "do_not_use"
    }


def evidence_requires_qualification(claim: dict[str, Any]) -> bool:
    """Return whether one Evidence claim must be visibly qualified in a factual block."""

    return (
        claim.get("support_status") in {"provisional", "inference", "assumption"}
        or claim.get("use_policy") in {"allowed_with_qualification", "internal_only"}
        or claim.get("freshness_decision", {}).get("status") in {"stale", "unknown"}
    )


def evidence_qualification_text(claim: dict[str, Any]) -> str | None:
    """Return a deterministic user-visible qualification for one usable Evidence claim."""

    reasons: list[str] = []
    support = str(claim.get("support_status", ""))
    freshness = str(claim.get("freshness_decision", {}).get("status", ""))
    policy = str(claim.get("use_policy", ""))
    if support == "provisional":
        reasons.append("间接或部分来源，未独立核验完整正文")
    elif support == "inference":
        reasons.append("解释性推断")
    elif support == "assumption":
        reasons.append("待验证假设")
    if freshness == "stale":
        reasons.append("来源时间早于 freshness 要求")
    elif freshness == "unknown":
        reasons.append("时效无法由确定性核心确认")
    if policy == "internal_only":
        reasons.append("仅限内部使用")
    if policy == "allowed_with_qualification" and not reasons:
        reasons.append("需限定来源能力和适用范围")
    return "；".join(reasons) if reasons else None


def slide_spec_content_hash(slide: dict[str, Any]) -> str:
    """Hash one page specification while excluding review/repair bookkeeping."""

    semantic_fields = {
        key: slide.get(key)
        for key in (
            "slide_id",
            "section_id",
            "slide_type",
            "outline_slide_ref",
            "audience_question",
            "core_message",
            "content_blocks",
            "visual_intent",
            "speaker_notes",
            "density_budget",
            "editability_intent",
        )
    }
    return "sha256:" + sha256_json(semantic_fields)


def _regions_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return not (
        float(first["x"]) + float(first["w"]) <= float(second["x"])
        or float(second["x"]) + float(second["w"]) <= float(first["x"])
        or float(first["y"]) + float(first["h"]) <= float(second["y"])
        or float(second["y"]) + float(second["h"]) <= float(first["y"])
    )


def layout_gate_reasons(
    workspace: Path,
    *,
    brief: dict[str, Any],
    outline: dict[str, Any],
    slide_specs: dict[str, Any],
    layout_plans: dict[str, Any],
    graph: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    """Return deterministic G5B reasons for Production Layout Plans and wireframes."""

    reasons: list[str] = []
    if layout_plans.get("status") not in {"approved", "frozen"}:
        reasons.append("layout plans are not approved")
    canvas = layout_plans.get("canvas", {})
    width = float(canvas.get("width", 0))
    height = float(canvas.get("height", 0))
    if width != 1280 or height != 720:
        reasons.append("Production planning canvas must be 1280×720")
    safe = layout_plans.get("safe_area", {})
    left = float(safe.get("left", 0))
    right = float(safe.get("right", 0))
    top = float(safe.get("top", 0))
    bottom = float(safe.get("bottom", 0))
    if left + right >= width or top + bottom >= height:
        reasons.append("layout safe area leaves no usable canvas")

    specs = list(slide_specs.get("slides", []))
    specs_by_id = {str(item["slide_id"]): item for item in specs}
    plans = list(layout_plans.get("plans", []))
    spec_ids = [str(item["slide_id"]) for item in specs]
    plan_ids = [str(item.get("slide_id", "")) for item in plans]
    if plan_ids != spec_ids:
        reasons.append("Layout Plan order/coverage disagrees with Slide Specs")
    for plan in plans:
        slide_id = str(plan.get("slide_id", ""))
        spec = specs_by_id.get(slide_id)
        if spec is None:
            reasons.append(f"Layout Plan references unknown Slide Spec {slide_id}")
            continue
        if plan.get("status") not in {"approved", "frozen"}:
            reasons.append(f"Layout Plan {slide_id} is not approved")
        spec_ref = plan.get("slide_spec_ref", {})
        if spec_ref.get("slide_id") != slide_id or spec_ref.get(
            "content_hash"
        ) != slide_spec_content_hash(spec):
            reasons.append(f"Layout Plan {slide_id} has stale Slide Spec binding")
        families = set(spec.get("visual_intent", {}).get("suggested_layout_families", []))
        if plan.get("layout_family") not in families and plan.get("layout_family") != "custom":
            reasons.append(f"Layout Plan {slide_id} ignores declared layout-family intent")
        blocks = {str(item["block_id"]): item for item in spec.get("content_blocks", [])}
        regions = list(plan.get("regions", []))
        region_ids = [str(item.get("region_id", "")) for item in regions]
        block_ids = [str(item.get("block_id", "")) for item in regions]
        if len(region_ids) != len(set(region_ids)):
            reasons.append(f"Layout Plan {slide_id} contains duplicate Region IDs")
        if len(block_ids) != len(set(block_ids)) or set(block_ids) != set(blocks):
            reasons.append(f"Layout Plan {slide_id} does not map every Block exactly once")
        if list(plan.get("reading_order", [])) != region_ids:
            reasons.append(f"Layout Plan {slide_id} reading_order must match Region order")
        expected_prefix = f"REG-{slide_id.replace('-', '')}-"
        if any(not region_id.startswith(expected_prefix) for region_id in region_ids):
            reasons.append(f"Layout Plan {slide_id} has non-slide-scoped Region IDs")
        for index, region in enumerate(regions):
            block = blocks.get(str(region.get("block_id", "")))
            if block is None:
                continue
            if region.get("source_block_hash") != block.get("content_hash"):
                reasons.append(
                    f"Region {region.get('region_id')} has stale Block content binding"
                )
            x = float(region.get("x", 0))
            y = float(region.get("y", 0))
            region_width = float(region.get("w", 0))
            region_height = float(region.get("h", 0))
            if (
                x < left
                or y < top
                or x + region_width > width - right
                or y + region_height > height - bottom
            ):
                reasons.append(f"Region {region.get('region_id')} exceeds safe area")
            content_units = planning_content_units(block.get("content"))
            if content_units > int(region.get("content_capacity_units", 0)):
                reasons.append(f"Region {region.get('region_id')} lacks content capacity")
            role = str(block.get("semantic_role", "body"))
            minimum = float(spec.get("density_budget", {}).get("min_body_pt", 8))
            admitted_floor = 12.0 if role in {"caption", "footer", "label"} else minimum
            if float(region.get("min_font_pt", 0)) < admitted_floor:
                reasons.append(f"Region {region.get('region_id')} violates font floor")
            required_height = estimated_text_height(
                block.get("content"),
                str(block.get("content_type")),
                width=region_width,
                font_size=admitted_floor,
                line_height=1.18 if role == "headline" else 1.28,
                qualification=block.get("evidence_qualification"),
            )
            if required_height > region_height:
                reasons.append(
                    f"Region {region.get('region_id')} cannot fit its Block at font floor"
                )
            for other in regions[index + 1 :]:
                if _regions_overlap(region, other):
                    reasons.append(
                        f"Layout Plan {slide_id} contains collision: "
                        f"{region.get('region_id')} / {other.get('region_id')}"
                    )
        diagnostics = plan.get("diagnostics", {})
        if int(diagnostics.get("block_count", -1)) != len(blocks):
            reasons.append(f"Layout Plan {slide_id} diagnostic block count mismatch")
        if int(diagnostics.get("region_count", -1)) != len(regions):
            reasons.append(f"Layout Plan {slide_id} diagnostic region count mismatch")
        expected_units = sum(
            planning_content_units(item.get("content")) for item in blocks.values()
        )
        expected_capacity = sum(
            int(item.get("content_capacity_units", 0)) for item in regions
        )
        if int(diagnostics.get("content_units", -1)) != expected_units:
            reasons.append(f"Layout Plan {slide_id} diagnostic content units mismatch")
        if int(diagnostics.get("capacity_units", -1)) != expected_capacity:
            reasons.append(f"Layout Plan {slide_id} diagnostic capacity mismatch")

    wireframes = list(layout_plans.get("wireframes", []))
    wireframe_ids = [str(item.get("slide_id", "")) for item in wireframes]
    if wireframe_ids != plan_ids:
        reasons.append("Layout wireframe coverage/order disagrees with Layout Plans")
    admitted_root = workspace / ".slidethus/planning/wireframes"
    for reference in wireframes:
        raw_path = Path(str(reference.get("path", "")))
        try:
            if raw_path.is_absolute():
                raise WorkspaceError("absolute wireframe path is not allowed")
            path = ensure_within(workspace, workspace / raw_path)
            if path.parent != ensure_within(workspace, admitted_root):
                raise WorkspaceError(
                    "wireframe must be stored directly under the immutable planning directory"
                )
        except (OSError, ValueError, WorkspaceError) as exc:
            reasons.append(f"Wireframe path is unsafe: {reference.get('slide_id')}: {exc}")
            continue
        if not path.is_file():
            reasons.append(f"Wireframe is missing: {reference.get('slide_id')}")
        elif sha256_file(path) != reference.get("sha256"):
            reasons.append(f"Wireframe hash mismatch: {reference.get('slide_id')}")
    lineage = layout_plans.get("planning_lineage")
    if lineage is None:
        reasons.append("Production Layout Plans planning lineage is missing")
    else:
        reasons.extend(
            planning_lineage_reference_errors(
                lineage,
                graph,
                required_inputs=("deck_outline", "project_brief", "slide_specs"),
            )
        )
    return tuple(dict.fromkeys(reasons))


def outline_slide_content_hash(slide: dict[str, Any]) -> str:
    """Hash the page task semantics while excluding order and operation bookkeeping."""

    semantic_fields = {
        key: slide.get(key)
        for key in (
            "slide_id",
            "section_id",
            "narrative_section_ref",
            "slide_type",
            "headline",
            "takeaway",
            "purpose",
            "audience_question",
            "content_scope",
            "evidence_ids",
            "evidence_requirement",
            "evidence_qualification",
            "estimated_minutes",
        )
    }
    return "sha256:" + sha256_json(semantic_fields)


def block_content_hash(block: dict[str, Any]) -> str:
    """Hash one semantic content block independent of ID and repair metadata."""

    semantic_fields = {
        key: block.get(key)
        for key in (
            "semantic_role",
            "content_type",
            "priority",
            "content",
            "evidence_ids",
            "evidence_requirement",
            "evidence_qualification",
            "claim_mode",
            "asset_refs",
        )
    }
    return "sha256:" + sha256_json(semantic_fields)


def planning_content_units(value: Any) -> int:
    """Estimate cross-language reading units for deterministic density checks."""

    if isinstance(value, dict):
        return sum(planning_content_units(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(planning_content_units(item) for item in value)
    text = str(value or "")
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    western = len(re.findall(r"[A-Za-z0-9]+(?:[./%:+-][A-Za-z0-9]+)*", text))
    return math.ceil(cjk / 2) + western


def slide_specs_gate_reasons(
    *,
    brief: dict[str, Any],
    evidence: dict[str, Any],
    outline: dict[str, Any],
    slide_specs: dict[str, Any],
    graph: dict[str, dict[str, Any]],
    workspace: Path | None = None,
) -> tuple[str, ...]:
    """Return deterministic intrinsic G5A reasons for Production Slide Specs."""

    reasons: list[str] = []
    if slide_specs.get("status") not in {"approved", "frozen"}:
        reasons.append("slide specs are not approved")
    active_outline = sorted(
        (item for item in outline.get("slides", []) if item.get("status") != "excluded"),
        key=lambda item: int(item.get("ordinal", 0)),
    )
    outline_by_id = {str(item["slide_id"]): item for item in active_outline}
    specs = list(slide_specs.get("slides", []))
    spec_ids = [str(item.get("slide_id", "")) for item in specs]
    outline_ids = [str(item["slide_id"]) for item in active_outline]
    if spec_ids != outline_ids:
        reasons.append("Slide Specs order/coverage disagrees with active Deck Outline")
    usable = usable_evidence_map(evidence)
    max_words = 0
    for spec in specs:
        slide_id = str(spec.get("slide_id", ""))
        outline_slide = outline_by_id.get(slide_id)
        if outline_slide is None:
            reasons.append(f"Slide Spec references unknown active slide {slide_id}")
            continue
        if spec.get("section_id") != outline_slide.get("section_id"):
            reasons.append(f"Slide Spec {slide_id} section_id disagrees with Outline")
        if spec.get("slide_type") != outline_slide.get("slide_type"):
            reasons.append(f"Slide Spec {slide_id} slide_type disagrees with Outline")
        if spec.get("core_message") != outline_slide.get("takeaway"):
            reasons.append(f"Slide Spec {slide_id} changes the approved Outline takeaway")
        if spec.get("audience_question") != outline_slide.get("audience_question"):
            reasons.append(f"Slide Spec {slide_id} changes the approved audience question")
        reference = spec.get("outline_slide_ref", {})
        if reference.get("slide_id") != slide_id or reference.get(
            "content_hash"
        ) != outline_slide_content_hash(outline_slide):
            reasons.append(f"Slide Spec {slide_id} has stale Outline slide binding")
        if spec.get("status") not in {"approved", "frozen"}:
            reasons.append(f"Slide Spec {slide_id} is not approved")
        blocks = list(spec.get("content_blocks", []))
        block_ids = [str(item.get("block_id", "")) for item in blocks]
        expected_prefix = f"BLK-{slide_id.replace('-', '')}-"
        if len(block_ids) != len(set(block_ids)) or any(
            not block_id.startswith(expected_prefix) for block_id in block_ids
        ):
            reasons.append(f"Slide Spec {slide_id} block IDs must be unique and slide-scoped")
        budget = spec.get("density_budget", {})
        if len(blocks) > int(budget.get("max_blocks", 0)):
            reasons.append(f"Slide Spec {slide_id} exceeds max_blocks")
        units = sum(planning_content_units(item.get("content")) for item in blocks)
        max_words = max(max_words, units)
        if units > int(budget.get("max_words", 0)):
            reasons.append(f"Slide Spec {slide_id} exceeds max_words")
        if not spec.get("visual_intent", {}).get("suggested_layout_families"):
            reasons.append(f"Slide Spec {slide_id} has no layout-family intent")
        outline_evidence = set(str(item) for item in outline_slide.get("evidence_ids", []))
        block_evidence: set[str] = set()
        for block in blocks:
            if block.get("content_hash") != block_content_hash(block):
                reasons.append(
                    f"Block {block.get('block_id')} content_hash disagrees with block semantics"
                )
            evidence_ids = [str(item) for item in block.get("evidence_ids", [])]
            block_evidence.update(evidence_ids)
            unknown = sorted(set(evidence_ids) - set(usable))
            if unknown:
                reasons.append(
                    f"Block {block.get('block_id')} references unusable Evidence: "
                    + ", ".join(unknown)
                )
            if not set(evidence_ids).issubset(outline_evidence):
                reasons.append(
                    f"Block {block.get('block_id')} uses Evidence not declared by Outline"
                )
            requirement = block.get("evidence_requirement")
            claim_mode = block.get("claim_mode")
            if claim_mode == "fact" and not evidence_ids:
                reasons.append(f"Factual block {block.get('block_id')} has no Evidence")
            if requirement == "required" and not evidence_ids:
                reasons.append(f"Required block {block.get('block_id')} has no Evidence")
            if requirement == "none" and evidence_ids:
                reasons.append(
                    f"Block {block.get('block_id')} declares no Evidence but references it"
                )
            if evidence_ids and any(
                evidence_requires_qualification(usable[item]) for item in evidence_ids
            ) and not str(block.get("evidence_qualification") or "").strip():
                reasons.append(
                    f"Block {block.get('block_id')} lacks required Evidence qualification"
                )
        if outline_slide.get("evidence_requirement") == "required" and not set(
            outline_slide.get("evidence_ids", [])
        ).issubset(block_evidence):
            reasons.append(f"Slide Spec {slide_id} does not carry all required slide Evidence")
    if max_words > int(brief.get("constraints", {}).get("page_count", {}).get("max", 9999)) * 100:
        reasons.append("Slide Specs contain implausible aggregate density")
    seed_ref = slide_specs.get("art_direction_seed")
    if seed_ref is not None:
        if workspace is None:
            reasons.append("Slide Specs Art Direction Seed cannot be verified without workspace")
        else:
            try:
                seed = validate_seed_reference_for_graph(workspace, seed_ref, graph)
                validate_seed_fulfillment(seed, slide_specs, None)
            except ArtifactError as exc:
                reasons.append(f"Slide Specs Art Direction Seed is invalid: {exc}")
    lineage = slide_specs.get("planning_lineage")
    if lineage is None:
        reasons.append("Production Slide Specs planning lineage is missing")
    else:
        reasons.extend(
            planning_lineage_reference_errors(
                lineage,
                graph,
                required_inputs=("deck_outline", "evidence_ledger", "project_brief"),
            )
        )
    return tuple(dict.fromkeys(reasons))


def outline_gate_reasons(
    *,
    brief: dict[str, Any],
    evidence: dict[str, Any],
    narrative: dict[str, Any],
    outline: dict[str, Any],
    graph: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    """Return deterministic G4 reasons for a current Production Deck Outline."""

    reasons: list[str] = []
    if outline.get("status") not in {"approved", "frozen"}:
        reasons.append("deck outline is not approved")
    all_slides = list(outline.get("slides", []))
    active = [item for item in all_slides if item.get("status") != "excluded"]
    if not active:
        reasons.append("deck outline has no active slides")
        return tuple(reasons)
    slide_ids = [str(item.get("slide_id", "")) for item in all_slides]
    if len(slide_ids) != len(set(slide_ids)):
        reasons.append("deck outline contains duplicate slide IDs")
    ordinals = [item.get("ordinal") for item in active]
    if ordinals != list(range(1, len(active) + 1)):
        reasons.append("active slide ordinals must be contiguous from 1")
    if int(outline.get("target_page_count", 0)) != len(active):
        reasons.append("outline target_page_count disagrees with active slide count")
    page_contract = brief.get("constraints", {}).get("page_count", {})
    minimum = int(page_contract.get("min", 1))
    maximum = int(page_contract.get("max", len(active)))
    if not minimum <= len(active) <= maximum:
        reasons.append("active slide count is outside the Brief page range")
    if active[0].get("slide_type") != "cover":
        reasons.append("first active slide must be a cover")
    if active[-1].get("slide_type") not in {"action", "summary"}:
        reasons.append("last active slide must close with action or summary")
    takeaways = [str(item.get("takeaway", "")).strip().casefold() for item in active]
    if len(takeaways) != len(set(takeaways)):
        reasons.append("deck outline contains duplicate slide takeaways")
    if any(
        not str(item.get(field) or "").strip()
        for item in active
        for field in ("headline", "takeaway", "purpose")
    ):
        reasons.append("every active slide requires headline, takeaway, and purpose")

    narrative_sections = {
        str(item["section_id"])
        for item in narrative.get("sections", [])
        if item.get("status") != "excluded"
    }
    covered_sections: set[str] = set()
    usable = usable_evidence_map(evidence)
    for index, slide in enumerate(active):
        section_id = str(
            slide.get("narrative_section_ref") or slide.get("section_id") or ""
        )
        if section_id not in narrative_sections:
            reasons.append(
                f"slide {slide.get('slide_id')} references unknown Narrative section {section_id}"
            )
        else:
            covered_sections.add(section_id)
        evidence_ids = [str(item) for item in slide.get("evidence_ids", [])]
        unknown = sorted(set(evidence_ids) - set(usable))
        if unknown:
            reasons.append(
                f"slide {slide.get('slide_id')} references unusable Evidence: "
                + ", ".join(unknown)
            )
        requirement = slide.get("evidence_requirement")
        if requirement == "required" and not evidence_ids:
            reasons.append(f"slide {slide.get('slide_id')} requires Evidence but has none")
        if requirement == "none" and evidence_ids:
            reasons.append(
                f"slide {slide.get('slide_id')} declares no Evidence but references Evidence"
            )
        if evidence_ids and any(
            evidence_requires_qualification(usable[item]) for item in evidence_ids
        ) and not str(slide.get("evidence_qualification") or "").strip():
            reasons.append(
                f"slide {slide.get('slide_id')} uses qualified Evidence without qualification"
            )
        if index == 0 and slide.get("transition_from") is not None:
            reasons.append("cover transition_from must be null")
        if index > 0 and not str(slide.get("transition_from") or "").strip():
            reasons.append(f"slide {slide.get('slide_id')} lacks transition_from")
        if index == len(active) - 1 and slide.get("transition_to") is not None:
            reasons.append("last slide transition_to must be null")
        if index < len(active) - 1 and not str(slide.get("transition_to") or "").strip():
            reasons.append(f"slide {slide.get('slide_id')} lacks transition_to")
    missing_sections = sorted(narrative_sections - covered_sections)
    if missing_sections:
        reasons.append(
            "deck outline does not cover Narrative sections: " + ", ".join(missing_sections)
        )

    lineage = outline.get("planning_lineage")
    if lineage is None:
        reasons.append("Production deck outline planning lineage is missing")
    else:
        reasons.extend(
            planning_lineage_reference_errors(
                lineage,
                graph,
                required_inputs=(
                    "evidence_ledger",
                    "narrative_blueprint",
                    "project_brief",
                ),
            )
        )
    return tuple(dict.fromkeys(reasons))


def narrative_gate_reasons(
    *,
    brief: dict[str, Any],
    evidence: dict[str, Any],
    narrative: dict[str, Any],
    graph: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    """Return deterministic G3 reasons for a current Production Narrative."""

    reasons: list[str] = []
    if is_unresolved(narrative.get("central_thesis")):
        reasons.append("narrative central thesis is unresolved")
    if not str(narrative.get("story_rationale") or "").strip():
        reasons.append("narrative story rationale is missing")
    if not str(narrative.get("proof_strategy") or "").strip():
        reasons.append("narrative proof strategy is missing")
    if narrative.get("status") not in {"approved", "frozen"}:
        reasons.append("narrative is not approved")

    journey = [str(item).strip() for item in narrative.get("audience_journey", [])]
    if len(journey) < 3:
        reasons.append("narrative audience journey has fewer than three stages")
    if len(journey) != len(set(journey)):
        reasons.append("narrative audience journey contains duplicate stages")

    sections = [item for item in narrative.get("sections", []) if item.get("status") != "excluded"]
    if len(sections) < 2:
        reasons.append("narrative requires at least two active sections")
    section_ids = [str(item.get("section_id", "")) for item in sections]
    expected_ids = [f"SEC-{index:02d}" for index in range(1, len(sections) + 1)]
    if section_ids != expected_ids:
        reasons.append("narrative section IDs must be contiguous from SEC-01")
    ordinals = [item.get("ordinal") for item in sections]
    if ordinals != list(range(1, len(sections) + 1)):
        reasons.append("narrative section ordinals must be contiguous from 1")
    titles = [str(item.get("title", "")).strip().casefold() for item in sections]
    purposes = [str(item.get("purpose", "")).strip().casefold() for item in sections]
    if len(titles) != len(set(titles)):
        reasons.append("narrative contains duplicate section titles")
    if len(purposes) != len(set(purposes)):
        reasons.append("narrative contains duplicate section purposes")
    if any(not item.get("key_questions") for item in sections):
        reasons.append("every narrative section requires a key question")
    if any(not str(item.get("transition") or "").strip() for item in sections[:-1]):
        reasons.append("narrative section transition is missing")
    if any(int(item.get("slide_budget", 0)) < 1 for item in sections):
        reasons.append("narrative section slide budgets must be positive")
    target = int(brief.get("constraints", {}).get("page_count", {}).get("target", 0) or 0)
    budget_total = sum(int(item.get("slide_budget", 0)) for item in sections)
    if target and not max(1, target - 4) <= budget_total <= target:
        reasons.append("narrative section budgets do not fit the Brief page target")

    usable = usable_evidence_map(evidence)
    referenced = {
        str(evidence_id)
        for section in sections
        for evidence_id in section.get("evidence_ids", [])
    }
    referenced.update(
        str(evidence_id)
        for objection in narrative.get("objections", [])
        for evidence_id in objection.get("evidence_ids", [])
    )
    unknown = sorted(referenced - set(usable))
    if unknown:
        reasons.append("narrative references unusable Evidence: " + ", ".join(unknown))
    if brief.get("source_policy", {}).get("citation_required") and usable and not referenced:
        reasons.append("citation-required narrative contains no Evidence strategy")

    objections = narrative.get("objections", [])
    objection_ids = [str(item.get("objection_id", "")) for item in objections]
    if objection_ids and objection_ids != [
        f"OBJ-{index:03d}" for index in range(1, len(objections) + 1)
    ]:
        reasons.append("narrative objection IDs must be contiguous from OBJ-001")
    if any(not str(item.get("response_strategy") or "").strip() for item in objections):
        reasons.append("narrative objection response strategy is missing")

    lineage = narrative.get("planning_lineage")
    if lineage is None:
        reasons.append("Production narrative planning lineage is missing")
    else:
        reasons.extend(
            planning_lineage_reference_errors(
                lineage,
                graph,
                required_inputs=("evidence_ledger", "project_brief"),
            )
        )
    return tuple(dict.fromkeys(reasons))
