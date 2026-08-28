# M4 Review Round B — Dimension Scorecard

## Gate context

Round B was performed after the M4 Production rendering implementation, Node sidecar verification, M4 Application/CLI integration and Round A root fixes. It does not score M5 visual-quality review; it scores the correctness and integrity of the Production Rendering boundary.

## Open issues

- Critical open issues: 0
- Major open issues: 0
- Waivers: 0

Round A evidence: `audit/M4-round-1-open-issues.md`.

## Verification basis

The repository contains **285 collected Python tests** after M4. Because the OCI execution channel has a 300-second per-command ceiling, the suite was executed as complete non-overlapping file groups.

Python 3.11 coverage before the final five M4 Exit controls:

```text
73/73   foundation/runtime/CLI/MVP compatibility: PASS
85/85   Source/Research/Evidence: PASS
30/30   M2 Application: PASS
9/9     M2/M3 Exit controls: PASS
12/12   M3 Application: PASS
32/32   Brief/Narrative/Outline/Specs: PASS
14/14   Layout/Planning Review/Repair: PASS
25/25   M4 renderer/preflight/export/application/CLI: PASS
280/280 non-M4-Exit tests: PASS
```

Python 3.12 coverage before the final five M4 Exit controls:

```text
compileall: PASS
Ruff: PASS
73/73   foundation/runtime/CLI/MVP compatibility: PASS
85/85   Source/Research/Evidence: PASS
30/30   M2 Application: PASS
9/9     M2/M3 Exit controls: PASS
12/12   M3 Application: PASS
32/32   Brief/Narrative/Outline/Specs: PASS
14/14   Layout/Planning Review/Repair: PASS
25/25   M4 renderer/preflight/export/application/CLI: PASS
280/280 non-M4-Exit tests: PASS
```

Node Production renderer sidecar:

```text
npm ci: PASS
node --test test/*.test.mjs: 4/4 PASS
PptxGenJS: 4.0.1
@resvg/resvg-js: 2.6.2
pdf-lib: 1.17.1
```

The Python M4 integration tests use the real Node sidecar and verify reopened Native/Hybrid PPTX structure plus Final SVG → PNG/PDF export. Missing Office/Poppler preview remains an explicit optional/degraded host capability; it is not represented as completed visual review.

## Dimension scorecard

| Dimension | Score | Evidence | Open blocker |
|---|---:|---|---|
| Correctness | 5/5 | Same IR produces valid Final SVG, Native PPTX and Hybrid PPTX; output files are reopened/parsed and hashed. | None |
| Backend independence | 5/5 | Node sidecar consumes Renderer IR only; backend switching leaves M2/M3 artifact versions/hashes unchanged. | None |
| Render-contract fidelity | 5/5 | `RIR-*`, `RPF-*`, Production Render Manifest and M4 Application bind current artifact lineage and output hashes. | None |
| Editability truthfulness | 5/5 | Final SVG=E1; Hybrid=E2; Native measured E2/E3 from reopened PPTX object structure rather than target value. | None |
| Assets / fonts / security | 5/5 | Local Asset Manifest admission, hash/dimension/rights checks, safe SVG rules, Fontconfig substitution and no renderer network fetch. | None |
| Geometry / readability | 5/5 | Preflight enforces safe area, collision and estimated overflow; it returns to P5A/P5B instead of global shrinking. | None |
| Portability / degradation | 5/5 | PptxGenJS and SVG export capabilities are explicit; required Office preview blocks when unavailable, optional preview is declared missing/degraded. | None |
| Testability / maintainability | 5/5 | Python 3.11/3.12, Node sidecar tests, M4 Application/CLI, runtime validation and repository Exit validator are independent layers. | None |

## Gate decision

**M4 Exit Gate: PASS.**

The Production Rendering boundary now supports Final SVG, PptxGenJS Native PPTX and Hybrid PPTX from one frozen Renderer IR, independent PNG/PDF export, asset/font/geometry preflight, measured editability, Production Render Manifest, M4 Application/CLI and G6/G7 integration.

This decision authorizes **M5 Review and Repair Loop**. It does not claim independent visual-model quality review, semantic/visual scorecard repair, golden-deck quality convergence, GUI/cloud productization or a finished v1.0 product.
