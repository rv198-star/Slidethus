# M4 Review Round A — Open Issue Mining

## Review rule

This round was performed without scores. It reviewed M4 as a repository-wide Production rendering boundary and focused on backend independence, Renderer IR fidelity, asset/font handling, measured editability, Manifest/G7 truthfulness, host degradation and persistent verification. M5 visual-quality judgment is intentionally out of scope.

## Initial result

```text
Critical: 0
Major:   9
Minor:    4
```

No waiver was used.

## Major findings and root fixes

### M4-A-MAJ-001 — G6 only proved that a Visual System file existed

- Risk: a stale or Minimal visual system could be accepted as current Production style state.
- Root fix: Production Visual System gained explicit `render_lineage` over Brief/Outline/Specs/Layout/Asset Manifest; G6 now recomputes current version/content-hash lineage. The frozen MinimalImpl themes remain an explicit compatibility path only.

### M4-A-MAJ-002 — Render backends had no single frozen backend-neutral input

- Risk: Final SVG, Native PPTX and Hybrid could independently reinterpret the domain artifacts and drift from one another.
- Root fix: introduced immutable content-addressed Renderer IR. All Production backends consume the same IR and do not own Narrative/Outline/Specs/Layout truth.

### M4-A-MAJ-003 — Evidence qualification could be lost at the rendering boundary

- Risk: provisional/inference/stale qualifications could disappear even though M3 correctly required them.
- Root fix: `claim_mode`, Evidence IDs and `evidence_qualification` are preserved in Renderer IR and rendered visibly by Final SVG/PptxGenJS paths.

### M4-A-MAJ-004 — Requested font families and actual host fonts could diverge between backends

- Risk: preflight could resolve one font while an individual backend recompiled IR with the requested family again.
- Root fix: font resolution is performed in preflight and the resulting shared compiled IR/assets are injected into all Production backends.

### M4-A-MAJ-005 — Native/Hybrid editability could be inferred from the requested backend rather than the real file

- Risk: a PPTX containing raster/embedded visual objects could be advertised as E3.
- Root fix: generated PPTX is normalized, reopened with `python-pptx`, native object classes are counted and actual editability is derived from the real file. Native is E3 only when the output structure supports it; otherwise E2. Hybrid remains conservatively E2; Final SVG is E1.

### M4-A-MAJ-006 — Complex content had incomplete Production materialization

- Risk: diagrams/icons/tables/charts/assets could be replaced by placeholders or silently rasterized.
- Root fix: Final SVG implements table/chart/diagram/icon/local-asset paths; PptxGenJS Native preserves supported objects as native shapes/tables/charts and renders diagrams as editable geometry; Hybrid embeds complex SVG/images while retaining ordinary objects natively. Unsupported/missing assets fail explicitly.

### M4-A-MAJ-007 — Rendering lacked one shared geometry/asset/font capability Gate

- Risk: backend-specific rendering might proceed despite known safe-area, collision, overflow, missing font or missing asset problems.
- Root fix: `RenderPreflightService` now compiles the shared IR once and runs backend-aware geometry, text-capacity, asset, font and host-capability checks before output generation.

### M4-A-MAJ-008 — Production Render Manifest and G7 were still oriented around the old MVP pipeline

- Risk: multi-backend outputs and actual editability could not be expressed/recomputed as one current render fact.
- Root fix: `production_multi_backend` manifest records the shared IR, preflight, backend runs, Final SVG/Native/Hybrid outputs, PNG/PDF export, measurements, fonts/assets/capabilities and actual editability. G7 recomputes these Production references while keeping `complete_mvp` compatibility.

### M4-A-MAJ-009 — M4 completion was not persistent at repository level

- Risk: passing local tests could be mistaken for a completed milestone without future verification of the Node sidecar, M2/M3 regressions or M4 contracts.
- Root fix: added `validate_m4_exit.py`, negative controls, Makefile `m4-exit`/`renderer-test`, and Package Audit integration. Package Audit now validates the real pinned Production renderer instead of asserting that no renderer package exists.

## Minor findings and fixes

### M4-A-MIN-001 — Final SVG post-render text validation treated normal wrap boundaries as lost content

The validator now verifies actual wrapped segments instead of requiring re-concatenated source text with identical whitespace.

### M4-A-MIN-002 — Node dependency state was not represented as repository hygiene

`package-lock.json` is present and accepted by `npm ci --dry-run`; `node_modules` is ignored and remains a local host installation artifact.

### M4-A-MIN-003 — M4 architecture changes lacked an ADR

ADR-0019 now records the shared IR, Visual System lineage, backend/editability rules, preflight, asset/font policy, Manifest and M4 Application boundary.

### M4-A-MIN-004 — Independent Office preview availability could be confused with basic render success

SVG→PNG/PDF independent export is a required Production G7 path. Office-compatible PPTX preview remains a separately declared host capability and can be explicitly required by a caller; its absence is not hidden.

## Verification added during root fixes

Coverage now includes:

- Production Visual System lineage and G6;
- Renderer IR identity, history and tamper detection;
- Final SVG text/table/chart/diagram/asset rendering;
- real PptxGenJS Native/Hybrid generation and reopened-file editability measurement;
- Node dependency absence and pinned sidecar tests;
- raster/SVG/data asset safety and font fallback;
- preflight geometry/overflow/capability behavior;
- real PNG/PDF export;
- M4 Application blocked/required-preview/success/idempotency/tamper paths;
- M4 CLI run/list/show/gate;
- M4 repository Exit negative controls.

## Round A disposition

- Critical open issues: 0.
- Major open issues: 0.
- Minor blocking M4 Exit: 0.
- Waivers: none.

Round B is permitted only after the final dual-Python regression, Node tests, M2/M3 Exit regressions, M4 Exit, Package Audit and `git diff --check` pass.
