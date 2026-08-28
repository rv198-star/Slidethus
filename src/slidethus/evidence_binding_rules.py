from __future__ import annotations

from typing import Any

NON_FACTUAL_SLIDE_TYPES = frozenset({"cover", "agenda", "section"})
FACTUAL_SLIDE_TYPES = frozenset(
    {"evidence", "comparison", "timeline", "matrix", "chart", "case", "quote"}
)
FACTUAL_BLOCK_ROLES = frozenset({"metric", "evidence", "quote", "chart", "table"})
FACTUAL_CONTENT_TYPES = frozenset({"metric", "quote", "chart", "table"})
QUALIFIED_STATUSES = frozenset({"provisional", "inference", "assumption"})


def evidence_requirement(explicit: Any, *, default: str) -> str:
    """Resolve one optional evidence requirement with a deterministic default."""

    value = str(explicit or "")
    return value if value in {"required", "optional", "none"} else default


def slide_evidence_requirement(slide: dict[str, Any]) -> str:
    """Return the conservative requirement for one Outline slide."""

    slide_type = str(slide.get("slide_type", ""))
    if slide_type in NON_FACTUAL_SLIDE_TYPES:
        default = "none"
    elif slide_type in FACTUAL_SLIDE_TYPES:
        default = "required"
    else:
        default = "optional"
    return evidence_requirement(slide.get("evidence_requirement"), default=default)


def block_evidence_requirement(block: dict[str, Any]) -> str:
    """Return the conservative requirement for one Slide Spec content block."""

    default = (
        "required"
        if block.get("semantic_role") in FACTUAL_BLOCK_ROLES
        or block.get("content_type") in FACTUAL_CONTENT_TYPES
        else "optional"
    )
    if block.get("priority") == "decorative" or block.get("content_type") == "spacer":
        default = "none"
    return evidence_requirement(block.get("evidence_requirement"), default=default)


def evidence_usable(claim: dict[str, Any]) -> bool:
    """Return whether one Evidence claim may be used at all."""

    return claim.get("support_status") not in {"unsupported", "disputed"} and claim.get(
        "use_policy"
    ) != "do_not_use"


def evidence_requires_qualification(claim: dict[str, Any]) -> bool:
    """Return whether a factual block needs an explicit visible/notes qualification."""

    return (
        claim.get("support_status") in QUALIFIED_STATUSES
        or claim.get("use_policy") == "allowed_with_qualification"
        or claim.get("freshness_decision", {}).get("status") in {"stale", "unknown"}
    )


def binding_gate_reasons(
    *,
    evidence: dict[str, Any],
    outline: dict[str, Any],
    slide_specs: dict[str, Any] | None,
    outline_version: int | None,
) -> tuple[str, ...]:
    """Recompute blocking G5A binding reasons from current semantic artifacts."""

    reasons: list[str] = []
    evidence_map = {
        str(item["evidence_id"]): item for item in evidence.get("claims", [])
    }
    targeted_complete = any(
        cycle.get("kind") == "targeted"
        and cycle.get("status") in {"complete", "waived"}
        and cycle.get("outline_version") == outline_version
        for cycle in evidence.get("research_cycles", [])
    )
    if not targeted_complete:
        reasons.append(f"targeted research is incomplete for outline version {outline_version}")
    if slide_specs is None:
        reasons.append("slide specs are missing")
        return tuple(dict.fromkeys(reasons))

    spec_map = {
        str(item["slide_id"]): item for item in slide_specs.get("slides", [])
    }
    for slide in outline.get("slides", []):
        if slide.get("status") == "excluded":
            continue
        slide_id = str(slide.get("slide_id", ""))
        requirement = slide_evidence_requirement(slide)
        slide_ids = list(dict.fromkeys(str(item) for item in slide.get("evidence_ids", [])))
        if requirement == "required" and not slide_ids:
            reasons.append(f"required slide evidence is missing: {slide_id}")
        for evidence_id in slide_ids:
            claim = evidence_map.get(evidence_id)
            if claim is None:
                reasons.append(f"outline references unknown evidence: {slide_id}:{evidence_id}")
            elif not evidence_usable(claim):
                reasons.append(f"outline uses blocked evidence: {slide_id}:{evidence_id}")

        spec = spec_map.get(slide_id)
        if spec is None:
            reasons.append(f"slide spec coverage is missing: {slide_id}")
            continue
        bound_evidence_ids: set[str] = set()
        for block in spec.get("content_blocks", []):
            block_id = str(block.get("block_id", ""))
            block_requirement = block_evidence_requirement(block)
            evidence_ids = list(
                dict.fromkeys(str(item) for item in block.get("evidence_ids", []))
            )
            bound_evidence_ids.update(evidence_ids)
            if block_requirement == "required" and not evidence_ids:
                reasons.append(f"required block evidence is missing: {block_id}")
            if (
                block_requirement == "required"
                and set(evidence_ids) - set(slide_ids)
            ):
                reasons.append(
                    f"required block evidence is not declared in outline: {block_id}:"
                    + ",".join(sorted(set(evidence_ids) - set(slide_ids)))
                )
            qualified: list[str] = []
            for evidence_id in evidence_ids:
                claim = evidence_map.get(evidence_id)
                if claim is None:
                    reasons.append(f"block references unknown evidence: {block_id}:{evidence_id}")
                elif not evidence_usable(claim):
                    reasons.append(f"block uses blocked evidence: {block_id}:{evidence_id}")
                elif evidence_requires_qualification(claim):
                    qualified.append(evidence_id)
            if (
                qualified
                and (block_requirement == "required" or requirement == "required")
                and not " ".join(str(block.get("evidence_qualification") or "").split())
            ):
                reasons.append(
                    f"required block lacks evidence qualification: {block_id}:{','.join(qualified)}"
                )
        if requirement == "required" and set(slide_ids) - bound_evidence_ids:
            reasons.append(
                f"required slide evidence is not bound to a block: {slide_id}:"
                + ",".join(sorted(set(slide_ids) - bound_evidence_ids))
            )
    return tuple(dict.fromkeys(reasons))
