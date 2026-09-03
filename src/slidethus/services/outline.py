from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import OutlinePlanningError, PlanningError
from slidethus.gates import evaluate_gate
from slidethus.planning_limits import (
    admit_planning_proposal,
    validate_planning_limits,
)
from slidethus.planning_lineage import (
    accepted_gate_current,
    build_planning_lineage,
    planning_artifact_reusable,
    reuse_semantically_current_lineage,
)
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.planning_rules import (
    evidence_qualification_text,
    evidence_requires_qualification,
    outline_gate_reasons,
    usable_evidence_map,
)
from slidethus.protocols import PlanningLimits, PlanningProvider


@dataclass(frozen=True)
class OutlinePlanningResult:
    """One versioned Production Deck Outline result."""

    outline: dict[str, Any]
    changed: bool
    version: int
    gate_reasons: tuple[str, ...]


def _text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _signature(slide: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(slide.get("narrative_section_ref") or slide.get("section_id") or ""),
        str(slide.get("slide_type") or ""),
        _text(slide.get("headline"), limit=300).casefold(),
        _text(slide.get("purpose"), limit=500).casefold(),
    )


def _next_slide_number(slides: list[dict[str, Any]]) -> int:
    numbers = [
        int(str(item["slide_id"]).split("-")[-1])
        for item in slides
        if str(item.get("slide_id", "")).startswith("S-")
    ]
    return max(numbers, default=0) + 1


def _generated_at(graph: dict[str, dict[str, Any]]) -> str:
    values = [
        str(item.get("updated_at") or "")
        for item in graph.values()
        if item.get("updated_at")
    ]
    return max(values) if values else utc_now()


class OutlinePlanningService:
    """Generate a stable digital-sticky-note Deck Outline from current Narrative."""

    def __init__(
        self,
        workspace,
        *,
        provider: PlanningProvider | None = None,
        runtime: ArtifactRuntime | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.provider = provider or DeterministicPlanningProvider()
        self.provider_name = _text(getattr(self.provider, "name", ""), limit=128)
        self.provider_version = _text(
            getattr(self.provider, "version", ""), limit=128
        )
        if not self.provider_name or not self.provider_version:
            raise OutlinePlanningError(
                "Planning provider must declare bounded name and version"
            )

    def _proposal(self, context: dict[str, Any], limits: PlanningLimits):
        try:
            proposal = self.provider.propose("deck_outline", context, limits)
        except PlanningError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OutlinePlanningError(f"Planning provider failed: {exc}") from exc
        if _text(getattr(self.provider, "name", ""), limit=128) != self.provider_name or _text(
            getattr(self.provider, "version", ""), limit=128
        ) != self.provider_version:
            raise OutlinePlanningError(
                "Planning provider identity changed during Outline generation"
            )
        return admit_planning_proposal(
            proposal,
            artifact_type="deck_outline",
            limits=limits,
        )

    def _admit(
        self,
        proposal_content: dict[str, Any],
        *,
        graph: dict[str, dict[str, Any]],
        warnings: tuple[str, ...],
        assumptions: tuple[str, ...],
        limits: PlanningLimits,
    ) -> dict[str, Any]:
        brief = graph["project_brief"]["data"]
        narrative = graph["narrative_blueprint"]["data"]
        evidence = graph["evidence_ledger"]["data"]
        usable = usable_evidence_map(evidence)
        narrative_sections = [
            item
            for item in narrative.get("sections", [])
            if item.get("status") != "excluded"
        ]
        if not narrative_sections:
            raise OutlinePlanningError("Narrative has no active sections")
        raw_slides = list(proposal_content.get("slides", []))[: limits.max_slides]
        if len(raw_slides) < 3:
            raise OutlinePlanningError("Production Outline proposal requires at least three slides")

        existing_snapshot = graph.get("deck_outline")
        existing = (
            copy.deepcopy(existing_snapshot["data"])
            if existing_snapshot is not None
            else None
        )
        existing_slides = list(existing.get("slides", [])) if existing else []
        if existing and existing.get("status") == "frozen":
            raise OutlinePlanningError(
                "Frozen Deck Outline requires explicit sticky-note operations, not regeneration"
            )
        frozen = [
            item
            for item in existing_slides
            if item.get("status") == "frozen" or "all" in item.get("locked_fields", [])
        ]
        signature_to_existing: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        duplicate_signatures: set[tuple[str, str, str, str]] = set()
        for item in existing_slides:
            if item.get("status") == "excluded":
                continue
            signature = _signature(item)
            if signature in signature_to_existing:
                duplicate_signatures.add(signature)
            else:
                signature_to_existing[signature] = item
        for signature in duplicate_signatures:
            signature_to_existing.pop(signature, None)

        next_number = _next_slide_number(existing_slides)
        used_ids: set[str] = set()
        slides: list[dict[str, Any]] = []
        duration = brief.get("constraints", {}).get("duration_minutes")
        per_slide_minutes = (
            round(float(duration) / len(raw_slides), 2)
            if isinstance(duration, (int, float)) and duration > 0
            else None
        )
        for ordinal, raw in enumerate(raw_slides, start=1):
            raw_section_index = int(raw.get("section_index", 0) or 0)
            section_index = min(max(0, raw_section_index), len(narrative_sections) - 1)
            section = narrative_sections[section_index]
            evidence_ids = list(
                dict.fromkeys(
                    str(item)
                    for item in raw.get("evidence_ids", [])
                    if str(item) in usable
                )
            )
            requirement = str(
                raw.get("evidence_requirement")
                or ("required" if evidence_ids else "none")
            )
            if requirement not in {"required", "optional", "none"}:
                raise OutlinePlanningError(
                    f"Invalid evidence requirement at proposed slide {ordinal}"
                )
            if requirement == "required" and not evidence_ids:
                raise OutlinePlanningError(
                    f"Proposed slide {ordinal} requires Evidence but has no usable Evidence"
                )
            if requirement == "none":
                evidence_ids = []
            qualification_parts = [
                evidence_qualification_text(usable[evidence_id])
                for evidence_id in evidence_ids
                if evidence_requires_qualification(usable[evidence_id])
            ]
            qualification = "；".join(
                dict.fromkeys(item for item in qualification_parts if item)
            ) or None
            candidate_stub = {
                "section_id": str(section["section_id"]),
                "narrative_section_ref": str(section["section_id"]),
                "slide_type": str(raw.get("slide_type", "statement")),
                "headline": _text(raw.get("headline"), limit=180),
                "purpose": _text(raw.get("purpose"), limit=600),
            }
            signature = _signature(candidate_stub)
            matched = signature_to_existing.get(signature)
            if matched is not None and str(matched["slide_id"]) not in used_ids:
                slide_id = str(matched["slide_id"])
            else:
                if next_number > 999:
                    raise OutlinePlanningError("Slide ID space is exhausted")
                slide_id = f"S-{next_number:03d}"
                next_number += 1
            used_ids.add(slide_id)
            preserved = matched if matched is not None and str(matched["slide_id"]) == slide_id else {}
            slide = {
                "slide_id": slide_id,
                "ordinal": ordinal,
                "section_id": str(section["section_id"]),
                "narrative_section_ref": str(section["section_id"]),
                "slide_type": candidate_stub["slide_type"],
                "headline": candidate_stub["headline"],
                "takeaway": _text(raw.get("takeaway"), limit=500),
                "purpose": candidate_stub["purpose"],
                "audience_question": _text(
                    raw.get("audience_question")
                    or (section.get("key_questions") or [section["purpose"]])[0],
                    limit=400,
                ),
                "content_scope": list(
                    dict.fromkeys(
                        item
                        for item in (
                            _text(raw.get("purpose"), limit=400),
                            *(
                                _text(usable[evidence_id].get("claim"), limit=400)
                                for evidence_id in evidence_ids
                            ),
                        )
                        if item
                    )
                ),
                "evidence_ids": evidence_ids,
                "evidence_requirement": requirement,
                "evidence_qualification": qualification,
                "transition_from": None,
                "transition_to": None,
                "status": (
                    "frozen" if preserved.get("status") == "frozen" else "approved"
                ),
                "derived_from_slide_ids": list(
                    preserved.get("derived_from_slide_ids", [])
                ),
                "operation_id": preserved.get("operation_id"),
                "locked_fields": list(preserved.get("locked_fields", [])),
                "estimated_minutes": per_slide_minutes,
                "revision_note": _text(preserved.get("revision_note"), limit=500),
                "notes": list(preserved.get("notes", [])),
            }
            if any(
                not slide[field]
                for field in ("headline", "takeaway", "purpose", "audience_question")
            ):
                raise OutlinePlanningError(
                    f"Proposed slide {ordinal} lacks required planning content"
                )
            slides.append(slide)

        if slides[0]["slide_type"] != "cover":
            raise OutlinePlanningError("First proposed slide must be a cover")
        if slides[-1]["slide_type"] not in {"action", "summary"}:
            raise OutlinePlanningError("Last proposed slide must be action or summary")
        if frozen:
            proposed_by_ordinal = {int(item["ordinal"]): item for item in slides}
            for old in frozen:
                current = proposed_by_ordinal.get(int(old["ordinal"]))
                if current is None or _signature(current) != _signature(old):
                    raise OutlinePlanningError(
                        f"Regeneration would modify frozen slide {old['slide_id']}"
                    )

        for index, slide in enumerate(slides):
            if index == 0:
                slide["transition_from"] = None
            else:
                slide["transition_from"] = (
                    f"从“{slides[index - 1]['headline']}”进入当前问题。"
                )
            if index == len(slides) - 1:
                slide["transition_to"] = None
            else:
                slide["transition_to"] = (
                    f"继续回答“{slides[index + 1]['audience_question']}”。"
                )

        unmatched_existing = [
            copy.deepcopy(item)
            for item in existing_slides
            if str(item.get("slide_id")) not in used_ids
        ]
        for item in unmatched_existing:
            if item.get("status") == "frozen" or "all" in item.get("locked_fields", []):
                raise OutlinePlanningError(
                    f"Regeneration would remove frozen slide {item.get('slide_id')}"
                )
            item["status"] = "excluded"
            note = "Superseded by Production Outline regeneration."
            item["revision_note"] = note
            notes = list(item.get("notes", []))
            if note not in notes:
                notes.append(note)
            item["notes"] = notes
        all_slides = [*slides, *unmatched_existing]

        lineage_inputs = {
            "evidence_ledger": graph["evidence_ledger"],
            "narrative_blueprint": graph["narrative_blueprint"],
            "project_brief": graph["project_brief"],
        }
        lineage = build_planning_lineage(
            lineage_inputs,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            proposal=copy.deepcopy(proposal_content),
            policy={"service": "outline", "limits": asdict(limits)},
            generated_at=_generated_at(lineage_inputs),
            warnings=warnings,
            assumptions=assumptions,
        )
        lineage = reuse_semantically_current_lineage(
            lineage,
            existing.get("planning_lineage") if existing else None,
            lineage_inputs,
            required_inputs=(
                "evidence_ledger",
                "narrative_blueprint",
                "project_brief",
            ),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": brief["project_id"],
            "deck_id": f"DECK-{brief['project_id']}",
            "status": "approved",
            "target_page_count": len(slides),
            "slides": all_slides,
            "appendix_policy": _text(
                proposal_content.get("appendix_policy")
                or "Only create an appendix when the Brief or evidence density requires it.",
                limit=600,
            ),
            "operations_applied": list(existing.get("operations_applied", [])) if existing else [],
            "planning_lineage": lineage,
        }

    def generate(
        self,
        *,
        limits: PlanningLimits | None = None,
        force: bool = False,
        created_by: str = "outline-planning-service",
    ) -> OutlinePlanningResult:
        """Generate or idempotently reuse a current Production Deck Outline."""

        admitted_limits = limits or PlanningLimits()
        validate_planning_limits(admitted_limits)
        g3 = evaluate_gate(self.workspace, "G3")
        if not g3.passed:
            raise OutlinePlanningError(
                "G3 must pass before Outline generation: " + "; ".join(g3.reasons)
            )
        graph = self.runtime.read_artifact_graph_snapshot(
            (
                "project_brief",
                "evidence_ledger",
                "narrative_blueprint",
                "deck_outline",
            ),
            optional_artifact_types=("deck_outline",),
        )
        existing = graph.get("deck_outline")
        current_policy = {"service": "outline", "limits": asdict(admitted_limits)}
        if (
            not force
            and existing is not None
            and planning_artifact_reusable(
                existing["data"],
                graph,
                artifact_status=str(existing["status"]),
                gate_current=accepted_gate_current(
                    self.runtime.show_artifact("project_state"), "G4"
                ),
                required_inputs=(
                    "evidence_ledger",
                    "narrative_blueprint",
                    "project_brief",
                ),
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                policy=current_policy,
                accepted_provider_names=("deterministic-outline-change-service",),
            )
        ):
            reasons = outline_gate_reasons(
                brief=graph["project_brief"]["data"],
                evidence=graph["evidence_ledger"]["data"],
                narrative=graph["narrative_blueprint"]["data"],
                outline=existing["data"],
                graph=graph,
            )
            if not reasons:
                return OutlinePlanningResult(
                    outline=copy.deepcopy(existing["data"]),
                    changed=False,
                    version=int(existing["version"]),
                    gate_reasons=(),
                )
        context = {
            "project_brief": copy.deepcopy(graph["project_brief"]["data"]),
            "evidence_ledger": copy.deepcopy(graph["evidence_ledger"]["data"]),
            "narrative_blueprint": copy.deepcopy(
                graph["narrative_blueprint"]["data"]
            ),
        }
        proposal = self._proposal(context, admitted_limits)
        candidate = self._admit(
            proposal.content,
            graph=graph,
            warnings=proposal.warnings,
            assumptions=proposal.assumptions,
            limits=admitted_limits,
        )
        reasons = outline_gate_reasons(
            brief=graph["project_brief"]["data"],
            evidence=graph["evidence_ledger"]["data"],
            narrative=graph["narrative_blueprint"]["data"],
            outline=candidate,
            graph=graph,
        )
        if reasons:
            raise OutlinePlanningError(
                "Outline proposal does not meet Production gate: " + "; ".join(reasons)
            )
        existing = graph.get("deck_outline")
        if existing is not None and existing["data"] == candidate:
            return OutlinePlanningResult(
                outline=copy.deepcopy(candidate),
                changed=False,
                version=int(existing["version"]),
                gate_reasons=(),
            )
        expected_version = int(existing["version"]) if existing is not None else 0
        entry = self.runtime.write_artifact(
            "deck_outline",
            candidate,
            expected_version=expected_version,
            status="approved",
            created_by=created_by,
        )
        return OutlinePlanningResult(
            outline=self.runtime.show_artifact("deck_outline"),
            changed=True,
            version=int(entry["version"]),
            gate_reasons=(),
        )

    def audit(self) -> tuple[str, ...]:
        """Audit the current Production Outline against current upstream facts."""

        graph = self.runtime.read_artifact_graph_snapshot(
            (
                "project_brief",
                "evidence_ledger",
                "narrative_blueprint",
                "deck_outline",
            )
        )
        return outline_gate_reasons(
            brief=graph["project_brief"]["data"],
            evidence=graph["evidence_ledger"]["data"],
            narrative=graph["narrative_blueprint"]["data"],
            outline=graph["deck_outline"]["data"],
            graph=graph,
        )
