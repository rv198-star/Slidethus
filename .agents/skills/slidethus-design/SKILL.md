---
name: slidethus-design
description: Establish or propagate a presentation art direction, native visual prototype, imagery and whole-deck styling from approved page plans, or extract style from references. Use for Slidethus P6 and PPT aesthetic direction/consistency work; not for standalone frontend delivery or direct PPTX rendering.
---

# Slidethus Design — P6

Read the [shared contract](../slidethus/references/shared-contract.md), [artifact map](../slidethus/references/artifact-map.md) and [host-create](../slidethus/references/host-create.md). For style extraction also read the [Extract Style workflow](../slidethus/workflows/extract-style.md).

## Input and scope

Brief, current Outline/Specs/Layout Plans, brand/style references, Asset Manifest and available design capabilities. A reference-only style extraction may start without target page plans, but produces a candidate, not an admitted target-deck direction. An isolated prototype never satisfies production Gates or edits accepted outputs.

## Work

1. Identify the communication purpose and expression demanded by the material. Distinguish tone, visual intensity and information density; “showcase” does not prescribe a technology style, and “elegant” does not require every page to be pale and empty.
   Before establishing a new direction, use [bounded reference selection](../slidethus/references/design-reference-selection.md). Reuse a suitable approved direction or choose no library reference; otherwise read the compact index and only promising adapted cards/images. The host decides, not a user theme picker. Do not preload the library or treat source-theme imperatives as production rules.
2. The default provider resource is [bundled Taste](../slidethus/providers/art-direction/taste/SKILL.md). Read it completely before applying it. Preserve the resource verbatim and translate only static presentation-relevant principles; do not import DOM/navigation/CTA/scroll behavior. A host may substitute another ArtDirectionProvider under the same contract.
3. For a new designed Create direction, let Taste drive an isolated native prototype (e.g. HTML/CSS plus real assets), inspect it, and freeze an `ArtDirectionSeed` before Slide Specs. The Seed must state every page's intended visual carrier and surface treatment, plus the permitted run of plain pages. In auto mode make and record the host's direction decision; when user approval is required, pause there. A user-requested four-page test stops at that test, not a full deck. Mere palette selection or direct PPT authoring is Taste-informed, not Taste-generated. `Taste-generated` establishes this provenance only: it does not itself show that color relationships, composition or the final deck are aesthetically sound.
4. Translate the accepted visual grammar into formal artifacts: palette, type hierarchy, spacing, imagery/crops, shape/chart/icon treatment, compositions, contrast by page role and non-flat surface rhythm. A required Seed carrier must become a matching semantic Block and Region; optional carriers must remain explicit choices, never decorative quotas. Revise Specs/Layout through their owning phase if content or geometry changes; do not hide geometry inside style prose.
5. Source/generate assets only for planned roles and crops. Inspect actual assets and record file/rights/provenance/status in Asset Manifest. Do not substitute missing pictures with empty frames or label generated illustrations as factual photos. Prefer native numeric charts to chart screenshots when supported and required editable.
6. Apply the direction across the complete Outline with explicit `page_designs`, not only to cover/sample pages. Review the whole sequence for repeated composition, focal hierarchy, useful contrast, data-page integration and breathing room. Independently judge whether the palette stays coherent and whether layout makes the information relationship legible; a non-flat surface rhythm alone is not an aesthetic pass. Consistency is shared grammar, not identical backgrounds; variation must serve content, not a fixed image/dark-page quota.
7. Compare approved samples to the full sequence. If samples disproportionately show the strongest visuals, extend the design treatment to the actual remaining roles and inspect them; do not treat sample approval as whole-deck approval.
8. Submit one immutable context-bound ArtDirectionPacket through existing admission and publish the Visual System only when G6 permits. Packet inputs bind Brief/Outline/Specs/Layout/Assets, provider identity and the same pre-layout Seed. Record native prototype provenance without claiming it is Office evidence.

## Exit

Current admitted direction and Visual System cover all planned pages; required assets exist with truthful rights; no unreviewed silent style fallback. Direct design-only work stops with the prototype/candidate or admitted design artifacts appropriate to scope. Rendering remains a separate phase and actual Office review remains required for final PPTX acceptance.
