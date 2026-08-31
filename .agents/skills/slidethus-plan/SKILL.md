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
2. Decide representation before styling. Compare text, table, numerical chart, photograph, illustration and diagram by the relationship they explain. A chart needs actual series/categories/data definitions and usable Evidence. Do not force media into every page or omit it just because text is easier.
3. Plan needed image/diagram regions before asset production: purpose (evidence, explanation or atmosphere), subject, crop/aspect ratio, reading relationship and rights needs. Use existing block content/notes/asset refs and layout rationale; do not create a parallel prose truth store or invented schema fields. Any unresolved asset is an explicit prerequisite, not an invisible final placeholder.
4. P5B: map every Block to an explicit Region with geometry and reading order. Choose layout from information relationships, not a global card template. Semantics stay in Specs; coordinates in Layout Plans; styles are later P6 decisions.
5. Check content capacity, readable hierarchy, safe areas and cross-page pacing. Fix excessive content or wrong grouping upstream before shrinking text. A full-deck sequence needs inspection even if four attractive samples were approved.
6. Select any requested calibration samples from the current full-deck plan: include important content roles and high-risk dense/chart/media pages, not just covers. Record coverage and what is still untested in existing plan/review notes. Do not impose a fixed number or ratio of image pages.
7. In host Create, submit `slide_specs` then `layout_plans` against current requests; verify runtime-assigned Block/Region IDs and admitted bindings. Use `slidethus render-wireframe <workspace>` when available. Wireframes prove layout intent, not final visual quality.

## Exit

One current Spec and Layout Plan per target slide, all blocks mapped, factual burdens satisfied, geometry readable and required media/data needs explicit. Layout Gate must pass before production Design. A geometry change discovered in Design returns here through admitted revision, not a downstream coordinate patch. Hand off the planned visual roles, sample coverage and asset requirements as artifact references.
