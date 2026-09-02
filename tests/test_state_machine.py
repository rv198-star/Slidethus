from __future__ import annotations

import pytest

from slidethus.errors import StateTransitionError
from slidethus.state_machine import (
    PLANNING_REWORK_TARGETS,
    Phase,
    can_transition,
    require_transition,
)


def test_forward_and_rework_transitions() -> None:
    assert can_transition(Phase.CREATED, Phase.BRIEF_READY)
    assert can_transition(Phase.LAYOUT_READY, Phase.VISUAL_SYSTEM_READY)
    assert can_transition(Phase.LAYOUT_READY, Phase.SLIDE_SPECS_READY)
    assert can_transition(Phase.REVIEWED, Phase.DRAFT_RENDERED)


def test_invalid_transition_is_rejected() -> None:
    assert not can_transition(Phase.CREATED, Phase.DRAFT_RENDERED)
    with pytest.raises(StateTransitionError):
        require_transition(Phase.CREATED, Phase.DRAFT_RENDERED)


def test_every_planning_review_owner_is_reachable_from_layout() -> None:
    for target in PLANNING_REWORK_TARGETS.values():
        if target is Phase.LAYOUT_READY:
            continue
        assert can_transition(Phase.LAYOUT_READY, target)
