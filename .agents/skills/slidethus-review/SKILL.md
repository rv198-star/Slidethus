---
name: slidethus-review
description: Audit presentation facts, narrative, layout, visual rhythm and real target-rendered pages, synthesize root-phase findings, verify authorized repairs and prepare an honest delivery handoff (P8/P9). Use for PPT critique/review/acceptance; audit alone never authorizes editing. Not a deck creation or style-generation skill.
---

# Slidethus Review — P8/P9

Read the [shared contract](../slidethus/references/shared-contract.md), [quality gates](../slidethus/references/quality-gates.md), [failure recovery](../slidethus/references/failure-recovery.md), [artifact map](../slidethus/references/artifact-map.md) and the applicable [Audit](../slidethus/workflows/audit-deck.md), [Improve](../slidethus/workflows/improve-deck.md) or [Revise](../slidethus/workflows/revise-slide.md) workflow.

## Input and scope

Actual deck/preview files, current artifacts when available, intended change set, user-approved references and acceptance criteria. For a deck without its workspace, inspect available evidence and declare provenance/lineage limitations; do not require rebuilding it merely to critique it.

An audit may produce findings but must not mutate content, styling, source/evidence or rendered truth. “What went wrong?” and “is this good enough?” are not repair authorization. In full Create or an explicit fix request, repair is bounded by the agreed outcome.

## Review after the production attempt

1. Run deterministic checks on artifacts/files that actually exist. If the attempt reached a hard blocker, record absent downstream output; do not invent a completed review or repair mid-attempt just to make the trial pass.
2. Inspect actual target-rendered pages. For reviewed/critical PowerPoint, sample calibration reviews the workflow-selected real PowerPoint pages and P8 reviews every full-candidate page, not only the title, a contact sheet or library PNGs. Bind application build/profile/export parameters and page hashes. Lack of Office access is pending capability, not visual PASS.
3. Mine open issues without scores. Read phase-owned facts through P0–P7 lenses: audience/context, sources/evidence, argument, sequence, page message/density, composition, style, export. Attach severity and exact file/page/S/BLK/REG location where known, impact and earliest responsible phase.
4. Review full-deck rhythm separately from page correctness. Verify sample role/representation coverage, then inspect the full sequence for plan/grammar fulfillment, sample-language propagation, adjacent transitions and narrative rhythm. P8 may revoke calibration based on full-deck context even when sample bytes did not change.
5. Check chart integrity (data source/units/bases/labels/scale), visual asset rights, media embedding and measured editability. Data charts are a considered communication option, not a required decoration.
6. Synthesize the complete issue set before considering changes. Separate local choice/preferences from general contract failures. Do not turn a single deck preference into project-code or skill-rule changes without a separate authorized optimization task.

## Authorized repair and stopping

Route accepted repairs to the owning skill: Brief for wrong audience; Research for sources/claims; Story for argument/repetition; Plan for content/grouping/geometry; Design for appearance/full-deck treatment; Render for export/font/embedding; Review for missed regression. Use existing change/rework services and invalidate only dependencies.

Then rerender, retest locally, compare intended versus actual changes across the deck, and only afterward score and decide the Gate. Review evidence is immutable: an admitted Critical/Major stays open on the same page hash despite omission, downgrade or reviewer switch. Repair changes the page; a factual false positive needs an authorized immutable adjudication. Do not lower the bar or use a waiver to manufacture reviewed/critical approval.

## Delivery or bounded result

- Audit-only: report observed evidence, findings and proposed root-phase actions; no hidden changes.
- Failed/limited attempt: identify exact missing capability/check, preserved candidate paths and the next action. Never call an unreviewed or repaired-with-deletions PPTX final.
- Final accepted output: provide requested files plus minimum useful provenance, review/Delivery Manifest where supported, exact hashes, target versus actual editability, delivery level and limitations/waivers.
- Host Create candidate receipts do not by themselves satisfy legacy G7/M5/release integration. Office observations are separate immutable receipt/review/decision facts; do not flip attempt flags or fabricate a Quality/Delivery Manifest Gate. Hand off as a reviewed candidate if integration remains pending.

Skill tests, package tests and accepted case aesthetics are different evidence. Do not announce a project release because this review or one new deck passed.
