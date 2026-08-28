# M4 Build Report — Production Rendering Backends

## Scope

M4 freezes the Production Rendering boundary on top of the completed M2/M3 semantic and planning contracts. It does not move planning truth into a renderer and it does not claim M5 independent visual review/repair.

## Completed capabilities

### Production Visual System and Renderer IR

- `VisualSystemService` compiles a current, lineage-bound Production Visual System from Brief/Outline/Specs/Layout/Asset Manifest.
- `Renderer IR` is a content-addressed non-catalog runtime fact under `.slidethus/render/ir/`.
- Renderer IR preserves stable slide/block/region identities, content, Evidence qualifications, geometry, style tokens, font substitutions and asset refs.
- Final SVG, PptxGenJS Native and Hybrid consume the same Renderer IR; renderers do not read or mutate Narrative/Outline/Specs/Layout as private planning state.

### Final SVG

- Produces one immutable SVG per slide.
- Supports text/list/metric/quote, tables, bar/line/pie/doughnut charts, manifested image/SVG assets, icons and diagrams.
- Re-parses generated SVG and verifies content, IDs, asset lineage and Evidence qualifications.
- Actual editability is measured/declared as E1.

### PptxGenJS Native

- Node sidecar is pinned by `package-lock.json` and requires Node >=20 plus PptxGenJS 4.0.1.
- Native text, shapes, tables and charts are generated as PPTX objects.
- Diagrams can be generated as editable native shapes when representable.
- Python reopens the real PPTX and measures object structure; Native is E3 only when no non-native pictures lower the result, otherwise it is E2.

### Hybrid PPTX

- Keeps ordinary text/shapes/tables/charts native.
- Embeds complex SVG/image objects where native representation is not appropriate.
- Reopens the output and conservatively measures E2 editability.

### Assets, fonts, geometry and export

- Asset Manifest now records media/dimensions/fit/editability/data contracts needed by renderers.
- RenderAssetService admits local workspace assets, validates status/use/hash/dimensions and rejects renderer network/data-URI acquisition.
- SVG assets reject scripts, event handlers, DTD/entity declarations and unadmitted external refs.
- CSV/TSV/JSON data assets are bounded and formulas remain inert strings.
- FontResolutionService resolves requested/fallback families through Fontconfig without bundling font files.
- Render Preflight checks host capabilities, font substitutions, assets, backend content support, safe area, collision and estimated overflow.
- `@resvg/resvg-js` exports Final SVG pages to real PNG; `pdf-lib` builds a real multipage PDF; Python independently validates PNG/PDF structures.
- Office/Poppler preview remains a separate optional host capability. Required preview blocks when unavailable; optional preview is declared unavailable/degraded rather than fabricated.

### Render Manifest, M4 Application and CLI

- Production Render Manifest records Renderer IR, Preflight, current artifact inputs, three backend runs, output hashes/roles, font substitutions, assets, capabilities, previews and measured editability.
- G6 validates current Production Visual System lineage.
- G7 validates the Production multi-backend Manifest and required output coverage.
- `M4ApplicationService` orchestrates Visual System → G6 → Preflight → Final SVG → Native → Hybrid → PNG/PDF → optional Office preview → Manifest → G7.
- M4 Application Reports are content-addressed and historical/current-state references are validated.
- CLI exposes `m4 run/list/show/gate`.

## Architecture decision

ADR: `docs/adr/ADR-0019-production-rendering-boundary.md`.

The key invariant is:

```text
M2/M3 semantic & planning graph
        ↓
Production Visual System
        ↓
one immutable Renderer IR
        ↓
Final SVG / PptxGenJS Native / Hybrid
        ↓
Render Manifest + G7
```

Changing the render backend does not require changing the M2/M3 domain Schemas.

## Round A

`audit/M4-round-1-open-issues.md` records:

```text
Critical: 0
Major:    9
Minor:    4
Waivers:  0
```

All Major findings were fixed at their earliest responsible contract layer. No new feature surface was added after Round A; subsequent work was verification and repository-level completion evidence.

## Round B

`audit/M4-round-2-scorecard.md` records zero open Critical/Major and **M4 Exit Gate: PASS**.

## Verification

The repository contains **285 Python tests** after M4. The OCI execution channel has a 300-second single-command ceiling, so the suite is executed as non-overlapping file groups.

Python 3.11:

```text
280/280 non-M4-Exit tests: PASS
real Node-sidecar integration: PASS
```

Python 3.12:

```text
compileall: PASS
Ruff: PASS
280/280 non-M4-Exit tests: PASS
real Node-sidecar integration: PASS
```

Node sidecar:

```text
npm ci: PASS
4/4 tests: PASS
```

Final repository verification completed in a Python 3.11 + Node 22 environment after the report and Round B evidence existed. The final pass also exposed two release-boundary defects and fixed them at the owning contract: the PptxGenJS lockfile was regenerated from the pinned `package.json` after `npm ci` detected invalid integrity metadata, and Package Audit now excludes local `node_modules` installation trees from delivery-content scans.

```text
test_m4_exit.py: 5/5 PASS
validate_all.py: PASS
M2 Exit: 12/12 PASS
M3 Exit: 13/13 PASS
M4 Exit: 15/15 PASS
Node tests: 4/4 PASS
Package Audit: 22/22 PASS
git diff --check: PASS
```

## Final Gate record

- Open Critical: 0.
- Open Major: 0.
- Waivers: 0.
- **M4 Exit Gate: PASS.**
- Next milestone: **M5 Review and Repair Loop**.

## Capability boundary

M4 completion means Slidethus has a Production rendering boundary with multiple real backends and truthful output/editability/preview lineage. It does not claim:

- independent visual-model review or automatic visual repair;
- a golden-deck quality convergence system;
- bundled online search/LLM/image-generation providers;
- guaranteed Office rendering equivalence on a host where Office/LibreOffice preview capability is unavailable;
- GUI/cloud/multi-tenant productization;
- v1.0 release readiness.
