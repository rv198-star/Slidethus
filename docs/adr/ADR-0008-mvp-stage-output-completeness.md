# ADR-0008｜MVP Stages Require Distinct Outputs

- Status: Accepted
- Date: 2026-08-26

## Context

MVP0 generated valid planning artifacts and serialized their content into a PPTX. That proved file generation, but it did not prove distinct planning, layout-debugging, design-compilation, final-rendering, and review actions. A file-extension change was incorrectly counted as a completed downstream stage.

## Decision

A Slidethus MVP is complete only when every claimed workflow action produces a distinct, inspectable output with an explicit acceptance check.

The minimum presentation path is:

1. Planning wireframes from Slide Specs and Layout Plans.
2. Layout diagnostics covering bounds, safe area, collision, text capacity, and font floor.
3. Debug PPTX showing grid, safe area, Region IDs, Block IDs, and their mappings.
4. Independent Office previews of the debug PPTX.
5. Design previews that consume Layout Plans and Visual System tokens.
6. Final editable PPTX, structurally reopened and checked.
7. Independent Office previews, Quality Report, and Delivery Manifest for the final PPTX.

`Render Manifest.pipeline_stages` records actions; `Render Manifest.outputs[].role` records their outputs. G7 requires all non-review stages and output roles. G8 additionally requires independent previews for both debug and final PPTX files.

The debug PPTX and final PPTX must be different files with different purposes. The debug file is not a deliverable design, and a planning wireframe exported to PPTX does not satisfy the final-render stage.

## Consequences

- Missing stages can no longer be hidden behind a successful `.pptx` write.
- The MVP produces more files and runs the independent renderer twice.
- Render Manifest remains the schema-backed source of truth for the multi-output pipeline.
- Production implementations can replace individual stages without changing their observable contracts.
