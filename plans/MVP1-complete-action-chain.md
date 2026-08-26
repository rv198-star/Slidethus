# MVP1 — Complete Action and Output Chain

## Objective

Upgrade the planning proof into a basic MVP whose claimed actions and outputs are complete and independently inspectable.

## Acceptance chain

| Stage | Action | Output | Acceptance |
|---|---|---|---|
| Planning | Compile Slide Specs into geometric plans | `planning-wireframes/*.svg` | one wireframe per active slide |
| Diagnostics | Measure layout constraints | `layout-diagnostics.json` | no bounds, safe-area, collision, capacity, or font-floor failure |
| Debug render | Compile mappings into PowerPoint | `*-debug.pptx` | page count matches; every Region/Block ID mapping is present |
| Debug preview | Independent Office render | `debug-office-previews/*.png` | one non-empty PNG per debug slide |
| Design compile | Apply visual tokens and layout grammar | `design-previews/*.svg` | one designed proof per slide; distinct from planning wireframes |
| Final render | Produce editable output | `*-final.pptx` | reopen succeeds; page count and native text coverage match |
| Final review | Independent Office render and QA | `final-office-previews/*.png`, Quality/Delivery manifests | Critical=0, Major=0, G8/G9 pass |

## Constraints

- D3: user Markdown/TXT only; no external research.
- E3: native editable text and simple shapes.
- Minimal DesignImpl may use panels, markers, typography, and geometric forms; it does not claim images, charts, Hybrid rendering, or production-grade art direction.
- Missing either independent preview path prevents G8/G9.

## Result

- Implemented on 2026-08-26.
- Six-slide acceptance produced 6 planning SVGs, 1 diagnostics report, 1 debug PPTX, 6 debug PNGs, 6 design SVGs, 1 final PPTX, and 6 final PNGs.
- Artifact validation and G7/G8/G9 passed.
