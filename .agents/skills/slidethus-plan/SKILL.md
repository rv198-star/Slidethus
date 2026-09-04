---
name: slidethus-plan
description: Plan slide content blocks, evidence/data/media needs, density, geometry and wireframes before visual styling. Use for PPT page planning or layout planning and Slidethus P5A/P5B. Not a final visual design or renderer; use using-slidethus for a whole deck.
---

# Slidethus Plan — P5A/P5B

Read the [shared contract](../slidethus/references/shared-contract.md), [phase contracts](../slidethus/references/phase-contracts.md), [layout system](../slidethus/references/layout-system.md) and [artifact map](../slidethus/references/artifact-map.md). For host Create read [host-create](../slidethus/references/host-create.md).

## Input and scope

Current Brief, stable Outline and usable Evidence after the targeted pass; known asset/renderer constraints. Missing evidence routes back to Research, not to invented data or last-minute decorative imagery. Direct invocation ends at page plans/wireframes.

## Work

1. P5A: assign each slide its audience question, core message, content blocks, priority, evidence requirement/qualification, speaker notes, density budget, visual intent and editability target. All required slide Evidence must reach a block.
2. Decide one discriminated representation before styling. Compare text, typographic, image, chart, table, diagram and bounded mixed forms by the relationship they explain. Specs own carrier reason/weight/density and kind-specific semantics; a chart needs actual series/categories/data definitions and usable Evidence, a diagram needs explicit nodes/edges, and an image needs a narrative role plus asset strategy. Do not force media into every page or omit it just because text is easier.
3. Plan needed image/diagram regions before asset production: purpose (evidence, explanation or atmosphere), subject, crop/aspect ratio, reading relationship and rights needs. Use existing block content/notes/asset refs and layout rationale; do not create a parallel prose truth store or invented schema fields. Any unresolved asset is an explicit prerequisite, not an invisible final placeholder.
4. P5B: map every Block to an explicit Region with geometry and reading order. Reference the Specs representation ID; record focal order, negative space and a kind-matched view for chart labels/orientation, table hierarchy, diagram routing/anchors or image crop/focal geometry. Semantics stay in Specs; view geometry in Layout; styles are later P6 decisions.
5. Generate content-addressed semantic previews in addition to neutral wireframes. The preview must visibly express actual carrier topology and visual weight, not raw JSON or equal placeholder boxes. Bind a qualitative planning review to the exact preview hashes; deterministic capacity success is not a substitute.
6. Check content capacity, readable hierarchy, safe areas and cross-page pacing. Fix excessive content or wrong grouping upstream before shrinking text. A full-deck sequence needs inspection even when representative samples will later be calibrated.
7. Do not hand-select calibration samples in P5. After full P5/P6 and complete IR, the workflow derives representative IDs from stable roles/representation risks. Do not impose a fixed image/chart quota or optimize coverage by renaming roles.
8. In host Create, submit `slide_specs` then `layout_plans` against current requests; verify runtime-assigned Block/Representation/Region IDs and admitted bindings. Use `slidethus render-wireframe <workspace>` when available. Wireframes prove structural intent; semantic previews plus qualitative decision are required for reviewed/critical G5B.

## Exit

One current Spec and Layout Plan per target slide, all blocks mapped, factual burdens satisfied, representation/view ownership closed, geometry readable and required media/data needs explicit. Reviewed/critical exit also needs current semantic preview receipts and zero open qualitative Critical/Major. A geometry change discovered in Design returns here through admitted revision, not a downstream coordinate patch.
