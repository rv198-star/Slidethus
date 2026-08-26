# Layout Planner Contract

## Purpose

Convert Slide Specs into a planning draft that answers where each semantic block belongs, without applying final visual styling.

## Inputs

- `slide_specs`;
- target canvas and safe area;
- readability and editability constraints;
- optional reference style boundaries.

## Procedure

1. Choose a layout family from information relationships, not from habit.
2. Map every content block to exactly one primary region unless a documented repeated element is required.
3. Assign stable region IDs, coordinates, reading order, alignment and overflow strategy.
4. Keep every region inside the canvas and safe area unless full-bleed is intentional.
5. Preserve hierarchy through area, position and reading order.
6. Enforce layout diversity across the deck; Bento is only one family.
7. Prefer a deterministic gray wireframe before final visual design.
8. Route semantic overload back to Slide Specs instead of shrinking everything.

## Exit conditions

- complete block coverage;
- valid reading order;
- no known collision or canvas escape;
- page hierarchy can be understood without color or decoration.
