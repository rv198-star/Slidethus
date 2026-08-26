# Repair Planner Contract

## Purpose

Turn review findings into the smallest root-cause repair plan while preserving stable IDs where possible.

## Procedure

1. Triage each issue to the earliest responsible phase.
2. Identify downstream artifacts that depend on the changed item.
3. Repair upstream truth before downstream rendering.
4. Invalidate and regenerate only affected artifacts/slides.
5. Run local verification, then cross-deck regression.
6. Record the decision, changed hashes and remaining waivers.

## Anti-patterns

- shrinking all text to hide overflow;
- adding explanatory notes to compensate for a broken slide;
- duplicating claims instead of fixing narrative structure;
- stacking exception rules over an incorrect schema or state transition;
- regenerating the entire deck when one stable dependency chain is sufficient.
