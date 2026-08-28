# ADR-0019｜Production Rendering Boundary

- Status: Accepted
- Date: 2026-08-28

## Context

M3 Exit freezes the presentation-planning boundary at current Project Brief, Evidence, Deck Outline, Slide Specs, Layout Plans and immutable planning wireframes. M4 must turn that frozen graph into real deliverables without letting a renderer reinterpret business facts, page responsibilities or layout ownership.

The previous MVP used `python-pptx` debug/minimal renderers as a vertical proof. Those files are useful compatibility fixtures but do not satisfy the Production requirements for Final SVG, PptxGenJS Native, Hybrid, asset/font policy, measured editability or a multi-backend Render Manifest.

## Decision

### 1. One backend-neutral Renderer IR

`RenderCompileService` compiles the current approved M3 graph plus Production Visual System and Asset Manifest into one immutable, content-addressed Renderer IR under:

```text
.slidethus/render/ir/<content-hash>.json
```

The IR preserves stable `S-*`, `BLK-*` and `REG-*` identities, geometry, semantic/content roles, Evidence IDs and qualifications, visual tokens, asset references, resolved font information and complete input artifact lineage.

Final SVG, Native PPTX and Hybrid PPTX consume the same IR. They do not read or mutate Narrative, Outline, Slide Specs or Layout Plans directly.

### 2. Production Visual System is a versioned artifact

`VisualSystemService` compiles style tokens only after current G5B. Its `render_lineage` binds Project Brief, Deck Outline, Slide Specs, Layout Plans and Asset Manifest versions/content hashes. G6 validates this current lineage instead of only checking file existence.

Explicit legacy MVP themes remain accepted only for the frozen MinimalImpl regression path. M4 Exit requires Production lineage.

### 3. Three truthful Production backends

- `final-svg` produces one immutable SVG page per slide and measures output editability as E1.
- `pptxgenjs-native` uses PptxGenJS 4.0.1 through a Node sidecar. Text, shapes, tables, charts and admitted native diagrams remain editable. The generated PPTX is reopened and structurally measured; actual editability is E3 only when the real output contains no non-native picture dependency, otherwise E2.
- `pptxgenjs-hybrid` retains native text/basic objects while embedding complex SVG/image objects and is conservatively measured as E2.

`python-pptx` debug/minimal backends keep their existing compatibility role and are not renamed as Production implementations.

### 4. Renderer preflight precedes output generation

`RenderPreflightService` compiles the IR once, resolves fonts and assets, and checks backend capability, safe-area geometry, same-z collisions, bounded text capacity and backend content-type support.

Major/Critical preflight failures block rendering. M4 does not globally shrink typography to hide P5A/P5B defects.

### 5. Assets remain local and rights-aware

Production renderers resolve only Asset Manifest entries admitted for use. Local files are content-hash checked. Raster dimensions are verified; SVG active content/external references are rejected. Chart/table data is loaded as bounded JSON/CSV/TSV without formula execution. Renderers perform no network acquisition.

### 6. Font resolution is explicit

Visual System font families are resolved through Fontconfig and admitted fallbacks. The resolved family is compiled into the shared IR. Substitutions are recorded in preflight and the Render Manifest. Font files are not copied into user deliverables by this boundary.

### 7. Independent export and preview capability is separate from PPTX generation

Final SVG is independently rasterized to PNG through `resvg` and compiled to PDF through `pdf-lib`. These outputs are reopened/validated.

Office-compatible PPTX preview is an optional host capability using the existing independent document renderer. Its absence is recorded as a capability limitation; a caller may explicitly require it and block the M4 run.

### 8. Render Manifest is the semantic render result

A successful Production Render Manifest uses `pipeline_mode=production_multi_backend` and binds:

- Renderer IR and preflight report;
- current semantic input artifacts;
- all backend runs and backend versions;
- Final SVG, Native/Hybrid PPTX, PNG/PDF exports and measurement reports;
- resolved fonts/assets and capability state;
- target versus independently measured actual editability.

G7 recomputes Production Manifest references and requires successful Final SVG, Native and Hybrid runs plus independent SVG PNG/PDF export.

### 9. M4 Application is orchestration, not a second render truth

`M4ApplicationService` sequences Visual System → G6 → preflight/shared IR → Production backends → export/optional Office preview → Render Manifest → G7. Its immutable Application Report records actions, failures and final state, while the Render Manifest remains the canonical render-output contract.

## Consequences

- Backend switching does not modify M2/M3 semantic schemas or planning artifacts.
- Evidence qualification cannot disappear at the renderer boundary.
- Native/Hybrid editability claims come from reopened files rather than requested targets.
- Missing Node, assets, fonts or required preview capability fails/degrades explicitly.
- Node/PptxGenJS becomes an admitted M4 toolchain dependency; `package-lock.json` pins the sidecar dependencies.
- Distribution/bootstrap of the Node sidecar is an M6 productization concern; M4 proves the repository Production rendering boundary.
- M5 remains responsible for independent visual-quality review and repair; M4 render success is not equivalent to visual approval.
