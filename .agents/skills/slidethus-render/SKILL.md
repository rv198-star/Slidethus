---
name: slidethus-render
description: Produce a PPTX or other presentation candidate from admitted slide specifications, layout, visual system and assets; inspect export/font/media integrity. Use for Slidethus P7, sample/full production or export failure investigation. Does not invent missing design or certify visual release approval.
---

# Slidethus Render — P7

Read the [shared contract](../slidethus/references/shared-contract.md), [host-create](../slidethus/references/host-create.md) and [capability matrix](../slidethus/references/capability-matrix.md).

## Input and scope

Admitted current Specs/Layout/ArtDirection/Visual System/Asset Manifest, complete Renderer IR, VisualAdmissionPolicy, requested backend/formats and target editability. No final production from raw prose or missing design. Reviewed/critical sample IDs are workflow-derived, not caller-selected. A render-only request authorizes production/checks, not visual redesign or release approval.

## Work

1. Verify input lineage, evidence qualification, geometry, fonts/glyphs and manifested asset availability. Missing/failing prerequisites return to their owner; do not fill with a default theme or silently drop unsupported objects.
2. For designed Create, obtain host runtime paths through the dependency loader and use the existing Artifact Tool adapter. Do not install or redistribute that runtime. Compile and freeze one complete full-deck IR before sample, then use the same IR/producer for sample and full:

   ```bash
   slidethus create <workspace> --render
   ```

   The workflow selects actual admitted representative IDs and preserves deck order. Manual `--slide-id` is rejected for reviewed/critical calibration. A separate hand-built sample is not a production test. Existing deterministic M4 routes are explicit controlled baselines only and share full-render admission when a quality policy is active.
3. Respect the adapter's supported primitives and editability limits documented in host-create. Native charts need supported numeric data, not coerced strings. A diagram is either normalized editable nodes/edges or one explicitly admitted raster asset; it is not implicitly a bitmap. Unsupported SVG/rich text/options fail explicitly; request an authorized representation change rather than silently rasterizing or dropping content.
4. After sample attempt, register exact selected pages exported by Microsoft PowerPoint with build/profile/export parameters. Artifact Tool PNG/layout previews are diagnostics only. Immutable review findings and a workflow-derived decision authorize only the exact complete IR/producer/dependency tuple.
5. Invoke the shared RenderAdmissionPolicy before every reviewed/critical full attempt. After full render, export and register every page through PowerPoint for whole-deck review; sample approval never substitutes for adjacent-page cadence or full-sequence inspection.
6. Preserve unique candidate directories, input snapshots, receipt/manifest and originals. Every started attempt has a schema-valid terminal receipt; Office evidence produces a new content-addressed receipt and never overwrites it. If PowerPoint reports repair/deletion, fix the producing source/admitted artifact, regenerate and reopen. Do not deliver repaired-with-deletions output or stack post-export OOXML patches.
7. A `/tmp` permission problem, missing host app, unsupported asset or render error is a specific capability/integrity issue. Diagnose from evidence; do not switch engines or introduce LibreOffice compatibility work merely to avoid PowerPoint validation unless that target is in scope.

## Exit

Deliver candidate and immutable receipt paths, exact dependency/producer/IR identity, selected IDs, Office evidence status, actual checks and editability limits to Review. Sample stays non-G7; full remains `release_approved: false` until formal integration. A render-only request stops with this truthful handoff. Never call a successful file write final acceptance.
