from __future__ import annotations

from enum import StrEnum

from slidethus.errors import StateTransitionError


class Phase(StrEnum):
    CREATED = "CREATED"
    BRIEF_READY = "BRIEF_READY"
    SOURCES_READY = "SOURCES_READY"
    EVIDENCE_READY = "EVIDENCE_READY"
    NARRATIVE_READY = "NARRATIVE_READY"
    OUTLINE_READY = "OUTLINE_READY"
    SLIDE_SPECS_READY = "SLIDE_SPECS_READY"
    LAYOUT_READY = "LAYOUT_READY"
    VISUAL_SYSTEM_READY = "VISUAL_SYSTEM_READY"
    DRAFT_RENDERED = "DRAFT_RENDERED"
    REVIEWED = "REVIEWED"
    DELIVERY_READY = "DELIVERY_READY"
    COMPLETED = "COMPLETED"


FORWARD_SEQUENCE = list(Phase)

ALLOWED_TRANSITIONS: dict[Phase, set[Phase]] = {
    phase: ({FORWARD_SEQUENCE[index + 1]} if index + 1 < len(FORWARD_SEQUENCE) else set())
    for index, phase in enumerate(FORWARD_SEQUENCE)
}

# Explicit rework routes. A runtime should invalidate dependent downstream artifacts.
ALLOWED_TRANSITIONS.update(
    {
        Phase.SOURCES_READY: {Phase.EVIDENCE_READY, Phase.BRIEF_READY},
        Phase.EVIDENCE_READY: {Phase.NARRATIVE_READY, Phase.SOURCES_READY, Phase.BRIEF_READY},
        Phase.NARRATIVE_READY: {Phase.OUTLINE_READY, Phase.EVIDENCE_READY, Phase.BRIEF_READY},
        Phase.OUTLINE_READY: {Phase.SLIDE_SPECS_READY, Phase.NARRATIVE_READY, Phase.EVIDENCE_READY},
        Phase.SLIDE_SPECS_READY: {Phase.LAYOUT_READY, Phase.OUTLINE_READY, Phase.EVIDENCE_READY},
        Phase.LAYOUT_READY: {Phase.VISUAL_SYSTEM_READY, Phase.SLIDE_SPECS_READY, Phase.OUTLINE_READY},
        Phase.VISUAL_SYSTEM_READY: {Phase.DRAFT_RENDERED, Phase.LAYOUT_READY, Phase.BRIEF_READY},
        Phase.DRAFT_RENDERED: {Phase.REVIEWED, Phase.VISUAL_SYSTEM_READY, Phase.LAYOUT_READY},
        Phase.REVIEWED: {Phase.DELIVERY_READY, Phase.DRAFT_RENDERED, Phase.LAYOUT_READY},
        Phase.DELIVERY_READY: {Phase.COMPLETED, Phase.REVIEWED},
    }
)


def can_transition(current: Phase, target: Phase) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def require_transition(current: Phase, target: Phase) -> None:
    if not can_transition(current, target):
        raise StateTransitionError(f"Invalid phase transition: {current} -> {target}")
