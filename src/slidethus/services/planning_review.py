from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import PlanningReviewError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import atomic_create_json, read_json
from slidethus.planning_reviews import (
    planning_issue_id,
    planning_review_file_key,
    planning_review_id,
    target_phase_for_issues,
    validate_planning_review_data,
)
from slidethus.planning_rules import planning_content_units
from slidethus.schema_registry import SchemaRegistry

_DIMENSIONS = (
    "brief",
    "narrative",
    "outline",
    "slide_specs",
    "layout",
    "evidence",
    "rhythm",
    "recovery",
)
_PHASE_BY_GATE = {
    "G0": ("project_brief", "P0"),
    "G3": ("narrative_blueprint", "P3"),
    "G4": ("deck_outline", "P4"),
    "G5A": ("slide_specs", "P5A"),
    "G5B": ("layout_plans", "P5B"),
}
_DIMENSION_BY_ARTIFACT = {
    "project_brief": "brief",
    "evidence_ledger": "evidence",
    "narrative_blueprint": "narrative",
    "deck_outline": "outline",
    "slide_specs": "slide_specs",
    "layout_plans": "layout",
}


@dataclass(frozen=True)
class PlanningReviewResult:
    """One persisted deterministic Planning Review."""

    report: dict[str, Any]
    path: Path
    changed: bool


def _text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _similarity_tokens(value: Any) -> set[str]:
    text = _text(value, limit=1000).casefold()
    western = set(re.findall(r"[a-z0-9]+", text))
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", text))
    bigrams = {cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))}
    return western | bigrams


def _jaccard(first: Any, second: Any) -> float:
    left = _similarity_tokens(first)
    right = _similarity_tokens(second)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _claim_clauses(value: Any) -> list[str]:
    return [
        item.strip(" ，,：:。；;!?！？")
        for item in re.split(
            r"[。！？!?；;]+|(?<!\d)\.(?!\d)|\s+(?=\d+[.、)]\s*)",
            _text(value, limit=4000),
        )
        if item.strip(" ，,：:。；;!?！？")
    ]


def _semantic_key(value: Any) -> str:
    text = _text(value, limit=1000).casefold()
    text = re.sub(
        r"^(?:决策请求|行动请求|decision request|request|decision)\s*[:：-]?\s*",
        "",
        text,
    )
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text)


def _content_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item, limit=1000) for item in value if _text(item, limit=1000)]
    if isinstance(value, dict):
        return [
            _text(f"{key}: {item}", limit=1000)
            for key, item in value.items()
            if _text(item, limit=1000)
        ]
    text = _text(value, limit=1000)
    return [text] if text else []


def _issue(
    *,
    code: str,
    severity: str,
    artifact_type: str,
    earliest_phase: str,
    message: str,
    suggested_action: str,
    repairability: str,
    slide_id: str | None = None,
    block_id: str | None = None,
    region_id: str | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "issue_id": "",
        "code": code,
        "severity": severity,
        "status": "open",
        "artifact_type": artifact_type,
        "slide_id": slide_id,
        "block_id": block_id,
        "region_id": region_id,
        "earliest_phase": earliest_phase,
        "message": _text(message),
        "evidence_ids": sorted(set(evidence_ids)),
        "suggested_action": _text(suggested_action),
        "repairability": repairability,
    }
    item["issue_id"] = planning_issue_id(item)
    return item


def _layout_topology_signature(plan: dict[str, Any]) -> tuple[Any, ...]:
    body = [
        item for item in plan.get("regions", [])
        if str(item.get("role", "")) != "headline"
    ]
    if not body:
        return ("headline_only",)
    if len(body) == 1:
        return ("single_support",)
    xs = {round(float(item.get("x", 0.0)) / 40.0) for item in body}
    ys = {round(float(item.get("y", 0.0)) / 40.0) for item in body}
    if len(ys) == 1 and len(xs) == len(body):
        return ("row", len(body))
    if len(xs) == 1:
        return ("column", len(body))
    return ("grid", len(xs), len(ys), len(body))


def _generated_at(graph: dict[str, dict[str, Any]]) -> str:
    values = [
        str(item.get("updated_at") or "")
        for item in graph.values()
        if item.get("updated_at")
    ]
    return max(values) if values else utc_now()


class PlanningReviewService:
    """Audit the full M3 planning stack before final visual design."""

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
        self.report_dir = self.workspace / ".slidethus/planning/reviews"

    def _gate_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for gate_id, (artifact_type, phase) in _PHASE_BY_GATE.items():
            result = evaluate_gate(self.workspace, gate_id)
            for reason in result.reasons:
                issues.append(
                    _issue(
                        code=f"{gate_id.lower()}_contract_failure",
                        severity="major",
                        artifact_type=artifact_type,
                        earliest_phase=phase,
                        message=f"{gate_id}: {reason}",
                        suggested_action=(
                            f"Repair the earliest {phase} contract and re-run {gate_id}; "
                            "do not compensate in a later rendering stage."
                        ),
                        repairability="assisted",
                    )
                )
        return issues

    def _narrative_issues(
        self,
        narrative: dict[str, Any],
        brief: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        objections = list(narrative.get("objections", []))
        primary = (brief.get("audiences") or [{}])[0]
        brief_signature = " ".join(
            _text(brief.get("intent", {}).get(key))
            for key in ("purpose", "desired_outcome", "call_to_action")
        )
        thesis = _text(narrative.get("central_thesis"))
        if thesis and _jaccard(thesis, brief_signature) >= 0.75:
            issues.append(
                _issue(
                    code="narrative_thesis_restates_brief",
                    severity="major",
                    artifact_type="narrative_blueprint",
                    earliest_phase="P3",
                    message="Narrative central thesis mostly restates Brief intent/outcome instead of a substantive presentation argument.",
                    suggested_action="Derive the thesis from admitted source/evidence semantics while preserving the Brief as purpose and action constraints.",
                    repairability="assisted",
                )
            )
        if primary.get("decision_power") in {"decision_maker", "mixed"} and not objections:
            issues.append(
                _issue(
                    code="decision_narrative_has_no_objections",
                    severity="major",
                    artifact_type="narrative_blueprint",
                    earliest_phase="P3",
                    message="Decision-oriented Narrative does not model any audience objection.",
                    suggested_action="Add the highest-impact objections and an evidence-backed response strategy.",
                    repairability="assisted",
                )
            )
        sections = [
            item
            for item in narrative.get("sections", [])
            if item.get("status") != "excluded"
        ]
        total_budget = sum(int(item.get("slide_budget", 0)) for item in sections)
        evidence_sections = [
            section for section in sections if section.get("evidence_ids")
        ]
        generic_section_theses = sum(
            bool(_text(section.get("thesis")))
            and _jaccard(section.get("thesis"), section.get("purpose")) >= 0.9
            for section in evidence_sections
        )
        if evidence_sections and generic_section_theses >= max(
            2, (len(evidence_sections) + 1) // 2
        ):
            issues.append(
                _issue(
                    code="narrative_section_theses_are_structural_labels",
                    severity="major",
                    artifact_type="narrative_blueprint",
                    earliest_phase="P3",
                    message=(
                        f"{generic_section_theses} Narrative section theses merely restate their structural purpose."
                    ),
                    suggested_action="Give each section a substantive claim or question resolution grounded in its admitted evidence rather than copying the section template purpose.",
                    repairability="assisted",
                )
            )
        for section in sections:
            if total_budget and int(section.get("slide_budget", 0)) / total_budget > 0.55:
                issues.append(
                    _issue(
                        code="narrative_section_dominates_deck",
                        severity="minor",
                        artifact_type="narrative_blueprint",
                        earliest_phase="P3",
                        message=(
                            f"Section {section.get('section_id')} consumes more than 55% of the Narrative slide budget."
                        ),
                        suggested_action="Split the section or rebalance proof and action pages across the story arc.",
                        repairability="assisted",
                    )
                )
        if not _text(narrative.get("call_to_action")):
            issues.append(
                _issue(
                    code="narrative_call_to_action_missing",
                    severity="major",
                    artifact_type="narrative_blueprint",
                    earliest_phase="P3",
                    message="Narrative does not close with a call to action.",
                    suggested_action="Define the specific decision or action expected after the deck.",
                    repairability="assisted",
                )
            )
        return issues

    def _outline_issues(
        self,
        outline: dict[str, Any],
        brief: dict[str, Any],
        evidence: dict[str, Any],
        narrative: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        claims_by_id = {
            str(item["evidence_id"]): item
            for item in evidence.get("claims", [])
        }
        sections_by_id = {
            str(item["section_id"]): item
            for item in narrative.get("sections", [])
        }
        slides = sorted(
            (item for item in outline.get("slides", []) if item.get("status") != "excluded"),
            key=lambda item: int(item.get("ordinal", 0)),
        )
        for slide in slides:
            headline = slide.get("headline")
            takeaway = slide.get("takeaway")
            if (
                slide.get("slide_type") not in {"cover", "agenda", "section", "action"}
                and planning_content_units(headline) >= 18
                and _jaccard(headline, takeaway) >= 0.78
            ):
                issues.append(
                    _issue(
                        code="headline_takeaway_role_collapse",
                        severity="major",
                        artifact_type="deck_outline",
                        earliest_phase="P4",
                        slide_id=str(slide["slide_id"]),
                        message="Headline and takeaway are near-duplicate, so proposition and support responsibilities have collapsed.",
                        suggested_action="Synthesize a concise page proposition for the headline and keep supporting explanation/evidence semantically distinct.",
                        repairability="assisted",
                    )
                )
            if planning_content_units(headline) > 42:
                issues.append(
                    _issue(
                        code="headline_too_long",
                        severity="minor",
                        artifact_type="deck_outline",
                        earliest_phase="P4",
                        slide_id=str(slide["slide_id"]),
                        message=f"Headline is too long for a clear sticky-note proposition: {slide['headline']}",
                        suggested_action="Shorten the headline while preserving the approved takeaway and audience question.",
                        repairability="automatic",
                    )
                )
            if slide.get("slide_type") not in {"cover", "agenda", "section", "action"}:
                headline_key = _semantic_key(headline)
                copied_from = next(
                    (
                        (evidence_id, claim)
                        for evidence_id in slide.get("evidence_ids", [])
                        if (claim := claims_by_id.get(str(evidence_id))) is not None
                        and any(
                            headline_key
                            and headline_key == _semantic_key(clause)
                            and (
                                len(_claim_clauses(claim.get("claim"))) > 1
                                or _semantic_key(claim.get("claim")) != headline_key
                            )
                            for clause in _claim_clauses(claim.get("claim"))
                        )
                    ),
                    None,
                )
                if copied_from is not None:
                    issues.append(
                        _issue(
                            code="headline_reuses_source_clause",
                            severity="major",
                            artifact_type="deck_outline",
                            earliest_phase="P4",
                            slide_id=str(slide["slide_id"]),
                            evidence_ids=(str(copied_from[0]),),
                            message=(
                                "Headline selects one Evidence clause verbatim instead of "
                                "expressing the full page job as an audience-facing proposition."
                            ),
                            suggested_action=(
                                "Synthesize the proposition from the audience question, page role, "
                                "and all assigned semantics; keep source clauses in support blocks."
                            ),
                            repairability="assisted",
                        )
                    )
            if slide.get("slide_type") == "section":
                section = sections_by_id.get(str(slide.get("narrative_section_ref")), {})
                thesis = section.get("thesis")
                orchestration_values = [
                    section.get("purpose"),
                    section.get("transition"),
                    section.get("audience_shift"),
                    *section.get("key_questions", []),
                ]
                if (
                    _jaccard(takeaway, thesis) < 0.7
                    and any(
                        _jaccard(takeaway, item) >= 0.78
                        for item in orchestration_values
                        if _text(item)
                    )
                ):
                    issues.append(
                        _issue(
                            code="structural_slide_exposes_orchestration_copy",
                            severity="major",
                            artifact_type="deck_outline",
                            earliest_phase="P4",
                            slide_id=str(slide["slide_id"]),
                            message=(
                                "Structural slide visible copy serializes planning purpose, "
                                "transition, or audience-question metadata."
                            ),
                            suggested_action=(
                                "Use audience-facing section framing or intentional headline-only "
                                "minimalism while preserving orchestration facts outside visible blocks."
                            ),
                            repairability="assisted",
                        )
                    )
        transition_types = {"cover", "agenda", "section", "action"}
        for index, first in enumerate(slides):
            for second in slides[index + 1 :]:
                if (
                    first.get("slide_type") in transition_types
                    or second.get("slide_type") in transition_types
                    or first.get("slide_type") != second.get("slide_type")
                ):
                    continue
                takeaway_similarity = _jaccard(first.get("takeaway"), second.get("takeaway"))
                if takeaway_similarity >= 0.88:
                    issues.append(
                        _issue(
                            code="near_duplicate_takeaway",
                            severity="major",
                            artifact_type="deck_outline",
                            earliest_phase="P4",
                            slide_id=str(second["slide_id"]),
                            message=(
                                f"Slides {first['slide_id']} and {second['slide_id']} have near-duplicate takeaways "
                                f"(similarity={takeaway_similarity:.2f})."
                            ),
                            suggested_action="Merge the pages or assign distinct audience questions and proof responsibilities.",
                            repairability="assisted",
                        )
                    )
        type_run: list[dict[str, Any]] = []
        for slide in slides:
            if not type_run or type_run[-1]["slide_type"] == slide["slide_type"]:
                type_run.append(slide)
            else:
                if len(type_run) >= 3:
                    issues.append(
                        _issue(
                            code="repetitive_slide_type_rhythm",
                            severity="minor" if len(type_run) <= 4 else "major",
                            artifact_type="deck_outline",
                            earliest_phase="P4",
                            slide_id=str(type_run[-1]["slide_id"]),
                            message=(
                                f"{len(type_run)} consecutive slides use type {type_run[0]['slide_type']}."
                            ),
                            suggested_action="Reconsider page responsibilities or introduce a different evidence/relationship pattern.",
                            repairability="assisted",
                        )
                    )
                type_run = [slide]
        if len(type_run) >= 3:
            issues.append(
                _issue(
                    code="repetitive_slide_type_rhythm",
                    severity="minor" if len(type_run) <= 4 else "major",
                    artifact_type="deck_outline",
                    earliest_phase="P4",
                    slide_id=str(type_run[-1]["slide_id"]),
                    message=f"{len(type_run)} consecutive slides use type {type_run[0]['slide_type']}.",
                    suggested_action="Reconsider page responsibilities or introduce a different relationship pattern.",
                    repairability="assisted",
                )
            )
        duration = brief.get("constraints", {}).get("duration_minutes")
        estimated = sum(float(item.get("estimated_minutes") or 0) for item in slides)
        if isinstance(duration, (int, float)) and duration > 0 and estimated:
            delta = abs(estimated - float(duration)) / float(duration)
            if delta > 0.2:
                issues.append(
                    _issue(
                        code="outline_timing_mismatch",
                        severity="major",
                        artifact_type="deck_outline",
                        earliest_phase="P4",
                        message=(
                            f"Estimated slide time {estimated:.1f} min differs from Brief duration {duration} min."
                        ),
                        suggested_action="Rebalance page count or estimated minutes before page design.",
                        repairability="assisted",
                    )
                )
        return issues

    def _spec_issues(
        self,
        specs: dict[str, Any],
        outline: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        outline_by_id = {
            str(item["slide_id"]): item
            for item in outline.get("slides", [])
            if item.get("status") != "excluded"
        }
        for slide in specs.get("slides", []):
            blocks = list(slide.get("content_blocks", []))
            units = sum(planning_content_units(item.get("content")) for item in blocks)
            maximum = int(slide.get("density_budget", {}).get("max_words", 1))
            ratio = units / max(1, maximum)
            if ratio >= 0.9:
                issues.append(
                    _issue(
                        code="slide_density_near_limit",
                        severity="major" if ratio >= 0.98 else "minor",
                        artifact_type="slide_specs",
                        earliest_phase="P5A",
                        slide_id=str(slide["slide_id"]),
                        message=(
                            f"Slide {slide['slide_id']} uses {ratio:.0%} of its content-density budget."
                        ),
                        suggested_action="Reduce or split content; do not compensate by shrinking all text.",
                        repairability="assisted",
                    )
                )
            headline_blocks = [
                item for item in blocks if item.get("semantic_role") == "headline"
            ]
            if headline_blocks:
                headline_content = headline_blocks[0].get("content")
                duplicated_support = next(
                    (
                        item
                        for item in blocks
                        if item.get("semantic_role") != "headline"
                        and planning_content_units(item.get("content")) >= 18
                        and _jaccard(headline_content, item.get("content")) >= 0.82
                    ),
                    None,
                )
                if duplicated_support is not None:
                    issues.append(
                        _issue(
                            code="content_role_duplication",
                            severity="major",
                            artifact_type="slide_specs",
                            earliest_phase="P5A",
                            slide_id=str(slide["slide_id"]),
                            block_id=str(duplicated_support["block_id"]),
                            message="A supporting content block substantially duplicates the headline instead of carrying distinct proof or structure.",
                            suggested_action="Decompose the page into non-duplicative semantic roles before assigning geometry.",
                            repairability="assisted",
                        )
                    )
            primary_blocks = [
                item for item in blocks if item.get("priority") == "primary"
            ]
            if len(primary_blocks) > 2:
                issues.append(
                    _issue(
                        code="too_many_primary_blocks",
                        severity="major",
                        artifact_type="slide_specs",
                        earliest_phase="P5A",
                        slide_id=str(slide["slide_id"]),
                        message=f"Slide {slide['slide_id']} has {len(primary_blocks)} primary blocks.",
                        suggested_action="Choose one dominant message and demote or split competing blocks.",
                        repairability="assisted",
                    )
                )
            if outline_by_id.get(str(slide["slide_id"]), {}).get("slide_type") == "action":
                seen: dict[str, dict[str, Any]] = {}
                duplicate: dict[str, Any] | None = None
                for block in blocks:
                    if block.get("semantic_role") == "headline":
                        continue
                    for item in _content_items(block.get("content")):
                        key = _semantic_key(item)
                        if not key:
                            continue
                        if key in seen:
                            duplicate = block
                            break
                        seen[key] = block
                    if duplicate is not None:
                        break
                if duplicate is not None:
                    issues.append(
                        _issue(
                            code="action_block_responsibility_duplication",
                            severity="major",
                            artifact_type="slide_specs",
                            earliest_phase="P5A",
                            slide_id=str(slide["slide_id"]),
                            block_id=str(duplicate["block_id"]),
                            message=(
                                "Action slide repeats one responsibility across multiple blocks "
                                "instead of separating decision, owner, timing, and checkpoint duties."
                            ),
                            suggested_action=(
                                "Keep the primary decision once and assign each supporting block a "
                                "distinct execution responsibility."
                            ),
                            repairability="assisted",
                        )
                    )
        return issues

    def _layout_issues(
        self,
        layout: dict[str, Any],
        specs: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        plans = list(layout.get("plans", []))
        relationship_by_slide = {
            str(item["slide_id"]): str(item.get("visual_intent", {}).get("relationship", ""))
            for item in specs.get("slides", [])
        }
        slide_type_by_slide = {
            str(item["slide_id"]): str(item.get("slide_type", ""))
            for item in specs.get("slides", [])
        }
        topology_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for plan in plans:
            slide_type = slide_type_by_slide.get(str(plan.get("slide_id")), "")
            if slide_type in {"cover", "agenda", "section", "action", "summary", "appendix"}:
                continue
            topology_groups.setdefault(_layout_topology_signature(plan), []).append(plan)
        for signature, grouped in topology_groups.items():
            relationships = {
                relationship_by_slide.get(str(item.get("slide_id")), "")
                for item in grouped
            }
            relationships.discard("")
            if len(grouped) < 3 or len(relationships) < 2:
                continue
            ratio = len(grouped) / max(1, len(plans))
            issues.append(
                _issue(
                    code="layout_relationship_topology_collapse",
                    severity="major" if ratio >= 0.6 else "minor",
                    artifact_type="layout_plans",
                    earliest_phase="P5B",
                    slide_id=str(grouped[-1]["slide_id"]),
                    message=(
                        f"{len(grouped)} pages with {len(relationships)} different declared relationships share the same coarse topology {signature}."
                    ),
                    suggested_action="Make region topology express the information relationship; do not treat a family label as sufficient differentiation.",
                    repairability="assisted",
                )
            )
        families = [str(item.get("layout_family", "")) for item in plans]
        families = [str(item.get("layout_family", "")) for item in plans]
        if plans and families.count("bento") / len(plans) > 0.4:
            issues.append(
                _issue(
                    code="bento_overuse",
                    severity="minor",
                    artifact_type="layout_plans",
                    earliest_phase="P5B",
                    message="Bento is used on more than 40% of pages.",
                    suggested_action="Select layout families from page relationships instead of defaulting to cards.",
                    repairability="assisted",
                )
            )
        run_start = 0
        while run_start < len(families):
            run_end = run_start + 1
            while run_end < len(families) and families[run_end] == families[run_start]:
                run_end += 1
            run_length = run_end - run_start
            if run_length >= 3:
                issues.append(
                    _issue(
                        code="repetitive_layout_rhythm",
                        severity="minor" if run_length <= 4 else "major",
                        artifact_type="layout_plans",
                        earliest_phase="P5B",
                        slide_id=str(plans[run_end - 1]["slide_id"]),
                        message=(
                            f"{run_length} consecutive pages use layout family {families[run_start]}."
                        ),
                        suggested_action="Vary the spatial relationship only where page semantics support it.",
                        repairability="assisted",
                    )
                )
            run_start = run_end
        for plan in plans:
            diagnostics = plan.get("diagnostics", {})
            ratio = int(diagnostics.get("content_units", 0)) / max(
                1, int(diagnostics.get("capacity_units", 1))
            )
            if ratio >= 0.8:
                issues.append(
                    _issue(
                        code="layout_capacity_near_limit",
                        severity="major" if ratio >= 0.95 else "minor",
                        artifact_type="layout_plans",
                        earliest_phase="P5B",
                        slide_id=str(plan["slide_id"]),
                        message=(
                            f"Layout {plan['slide_id']} uses {ratio:.0%} of estimated region capacity."
                        ),
                        suggested_action="Reallocate space or return to P5A to reduce content.",
                        repairability="assisted",
                    )
                )
        return issues

    @staticmethod
    def _dimensions(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output = []
        for dimension in _DIMENSIONS:
            dimension_issues = [
                item
                for item in issues
                if (
                    _DIMENSION_BY_ARTIFACT.get(str(item["artifact_type"])) == dimension
                    or (
                        dimension == "rhythm"
                        and item["code"]
                        in {
                            "repetitive_slide_type_rhythm",
                            "repetitive_layout_rhythm",
                            "near_duplicate_takeaway",
                        }
                    )
                )
            ]
            penalty = sum(
                {"critical": 3, "major": 2, "minor": 1}[str(item["severity"])]
                for item in dimension_issues
                if item.get("status") == "open"
            )
            score = max(0, 5 - penalty)
            output.append(
                {
                    "dimension": dimension,
                    "score": score,
                    "rationale": (
                        "No deterministic issue found in this dimension."
                        if not dimension_issues
                        else f"{len(dimension_issues)} deterministic issue(s) affect this dimension."
                    ),
                    "issue_ids": [str(item["issue_id"]) for item in dimension_issues],
                }
            )
        return output

    def analyze(
        self,
        *,
        persist: bool = True,
        review_mode: str = "deterministic",
    ) -> PlanningReviewResult:
        """Review current M3 artifacts and optionally persist a content-addressed report."""

        if review_mode not in {"deterministic", "open_issue", "scorecard"}:
            raise PlanningReviewError(f"Unsupported review_mode: {review_mode}")
        graph = self.runtime.read_artifact_graph_snapshot(
            (
                "project_brief",
                "evidence_ledger",
                "narrative_blueprint",
                "deck_outline",
                "slide_specs",
                "layout_plans",
            )
        )
        brief = graph["project_brief"]["data"]
        narrative = graph["narrative_blueprint"]["data"]
        outline = graph["deck_outline"]["data"]
        specs = graph["slide_specs"]["data"]
        layout = graph["layout_plans"]["data"]
        issues = [
            *self._gate_issues(),
            *self._narrative_issues(narrative, brief),
            *self._outline_issues(
                outline,
                brief,
                graph["evidence_ledger"]["data"],
                narrative,
            ),
            *self._spec_issues(specs, outline),
            *self._layout_issues(layout, specs),
        ]
        issues_by_id: dict[str, dict[str, Any]] = {}
        for issue in issues:
            issues_by_id.setdefault(str(issue["issue_id"]), issue)
        issues = sorted(
            issues_by_id.values(),
            key=lambda item: (
                {"critical": 0, "major": 1, "minor": 2}[str(item["severity"])],
                str(item["artifact_type"]),
                str(item.get("slide_id") or ""),
                str(item["code"]),
            ),
        )
        dimensions = self._dimensions(issues)
        open_issues = [item for item in issues if item.get("status") == "open"]
        target_phase = target_phase_for_issues(open_issues)
        scores = [int(item["score"]) for item in dimensions]
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(brief["project_id"]),
            "report_id": "",
            "generated_at": _generated_at(graph),
            "status": "issues" if open_issues else "pass",
            "review_mode": review_mode,
            "inputs": [
                {
                    "artifact_type": artifact_type,
                    "version": int(snapshot["version"]),
                    "content_hash": str(snapshot["content_hash"]),
                }
                for artifact_type, snapshot in sorted(graph.items())
            ],
            "issues": issues,
            "dimensions": dimensions,
            "summary": {
                "critical_count": sum(
                    item["severity"] == "critical" for item in open_issues
                ),
                "major_count": sum(item["severity"] == "major" for item in open_issues),
                "minor_count": sum(item["severity"] == "minor" for item in open_issues),
                "open_count": len(open_issues),
                "overall_score": round(sum(scores) / len(scores), 2),
            },
            "requires_rework": target_phase is not None,
            "target_phase": target_phase,
        }
        report["report_id"] = planning_review_id(report)
        errors = validate_planning_review_data(report, self.schemas.schema_dir)
        if errors:
            raise PlanningReviewError(
                "Planning Review Report is invalid: " + "; ".join(errors)
            )
        path = self.report_dir / f"{planning_review_file_key(report)}.json"
        changed = False
        if persist:
            changed = atomic_create_json(path, report)
            if not changed and read_json(path) != report:
                raise PlanningReviewError(
                    f"Immutable Planning Review path contains different content: {path}"
                )
        return PlanningReviewResult(
            report=copy.deepcopy(report),
            path=path,
            changed=changed,
        )
