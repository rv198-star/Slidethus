---
name: slidethus-render
description: Produce a PPTX or other presentation candidate from admitted slide specifications, layout, visual system and assets; inspect export/font/media integrity. Use for Slidethus P7, sample/full production or export failure investigation. Does not invent missing design or certify visual release approval.
---

# Slidethus Render — P7

Read the [shared contract](../slidethus/references/shared-contract.md), [host-create](../slidethus/references/host-create.md) and [capability matrix](../slidethus/references/capability-matrix.md).

## Input and scope

Admitted current Specs/Layout/ArtDirection/Visual System/Asset Manifest, requested backend/formats, target editability and sample IDs if any. No final production from raw prose or missing design. A render-only request authorizes production/checks, not a visual redesign or release decision.

## Work

1. Verify input lineage, evidence qualification, geometry, fonts/glyphs and manifested asset availability. Missing/failing prerequisites return to their owner; do not fill with a default theme or silently drop unsupported objects.
2. For designed Create, obtain host runtime paths through the dependency loader and use the existing Artifact Tool adapter. Do not install or redistribute that runtime. Use the same full-deck IR and producer for both sample and full candidates:

   ```bash
   slidethus create <workspace> --render --slide-id S-001 --slide-id S-003
   slidethus create <workspace> --render
   ```

   Select actual admitted IDs; preserve deck order. A separate hand-built sample is not a production test. Existing deterministic M4 render routes are only for explicitly selected baseline/backend tasks, never an automatic substitution.
3. Respect the adapter's supported primitives and editability limits documented in host-create. Native charts need supported numeric data, not coerced strings. A diagram is either normalized editable nodes/edges or one explicitly admitted raster asset; it is not implicitly a bitmap. Unsupported SVG/rich text/options fail explicitly; request an authorized representation change rather than silently rasterizing or dropping content.
4. Inspect every exported page and package integrity for fonts, missing pictures, clipped text and chart completeness. PNG/layout previews are useful diagnostics, not Office renders. Record which checks actually ran and the exact artifact hashes.
5. Preserve unique candidate directories, input snapshots, receipt/manifest and originals. Every started Artifact Tool attempt must have a schema-valid terminal receipt; when failed, return its path and use the recorded stage/exit/timeout/sanitized diagnostics. If PowerPoint reports repair/deletion, the file has failed integrity; inspect and fix the producing source/admitted artifact, regenerate and reopen. Do not deliver PowerPoint's deleted-content repair as a success or stack post-export OOXML patches.
6. A `/tmp` permission problem, missing host app, unsupported asset or render error is a specific capability/integrity issue. Diagnose from evidence; do not switch engines or introduce LibreOffice compatibility work merely to avoid PowerPoint validation unless that target is in scope.

## Exit

Deliver candidate paths, producer/input identity, selected page IDs, actual check results and editability measurement/limits to Review. The host receipt stays `candidate_office_review_pending` and `release_approved: false`; it is not the legacy multi-backend Render Manifest, G7 or M5 approval. A render-only request stops with this truthful candidate handoff. Never call a successful file write final acceptance.
