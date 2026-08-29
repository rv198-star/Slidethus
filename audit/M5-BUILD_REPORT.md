# M5 Build Report — Review and Repair Loop

## Scope

M5 freezes the Production Review and Repair boundary on top of frozen M2/M3/M4 semantic, planning and rendering truth. It adds independent deterministic/semantic/visual review, bounded repair planning/execution, cross-deck regression, Production Quality/G8, Golden cases and M5 Application/CLI without moving review logic into renderers.

## Completed capabilities

### M5.1 Deterministic Review Core

- Immutable `DVR-*` runtime reports under `.slidethus/review/deterministic/`.
- Independent workspace/hash validation, G0–G7 regression, Production Render Manifest/IR/preflight/output verification, PPTX reopen and editability remeasurement.
- Responsibility-scoped Gate validation keeps frozen upstream Gates monotonic when downstream P7 defects appear.
- Persisted deterministic reports validate expected and observed artifact hashes and fail on tampering.

### M5.2 Open Issue Semantic Review

- Provider-neutral `SemanticReviewProvider` proposal boundary.
- Deterministic admission for artifact/slide/block/region/Evidence references, severity, earliest responsible phase and repairability.
- Stable `SRI-*` issue identity; Round A contains no scores.
- Missing provider is an explicit capability block rather than fabricated semantic judgment.

### M5.3 Dimension Scorecard

- Scorecard runs only after a current Open Issue Review.
- Low scores require explicit Round A issue references when scoring capability exists.
- Critical/Major issue counts remain authoritative regardless of average score.

### M5.4 Full-page Visual Review

- Provider-neutral visual review consumes real Final SVG→PNG page images.
- Office-compatible preview is optional additional evidence rather than a fabricated or mandatory sole source.
- Slide/region references and earliest P5B/P6/P7 routing are deterministically admitted.
- Stable `VRI-*` identities and persisted visual lineage detect tampering.

### M5.5 Repair Plan and Regeneration

- Immutable Repair Plan binds selected issues, current review facts, root phase, invalidation scope and verification requirements before mutation.
- Automatic execution is narrowly admitted. The Production automatic path regenerates missing P7 generated outputs by re-running M4 rather than patching files.
- Existing corrupted outputs are never silently overwritten and route to assisted/manual handling.

### M5.6 Cross-deck Regression and Production Quality/G8

- Regression records changed and unchanged scope plus G0–G7/workspace results.
- Production Quality Report aggregates immutable DVR/SVR/SCR/VVR/optional Repair/Regression facts; it does not discover a new fifth set of review issues.
- Every current semantic/visual source issue maps to one Quality `ISS-*`.
- G8 recomputes Production review lineage, capability state, severity and regression status.
- Runtime review tampering invalidates workspace validation and G8.

### M5.7 Golden Deck, Application, CLI and Exit

- `M5ApplicationService` orchestrates deterministic review → semantic Round A → scorecard → visual review → repair → regression → Production Quality/G8.
- Clean runs reach `REVIEWED`; reruns are idempotent.
- Missing providers block truthfully; recoverable missing P7 outputs are root-repaired before review continues.
- CLI exposes `m5 run/list/show/gate`. CLI does not bundle fake semantic/visual providers.
- `golden/m5/manifest.json` and the management-decision Golden case provide executable expected M5/G8 behavior.
- Repository `validate_m5_exit.py`, negative controls, Makefile and Package Audit persist the M5 Exit boundary.

## Architecture decision

ADR: `docs/adr/ADR-0020-independent-review-repair-boundary.md`.

The frozen boundary is:

```text
Frozen M2/M3 semantic + planning truth
              ↓
Frozen M4 render truth
              ↓
Independent M5 Review facts
DVR → SVR → SCR → VVR
              ↓
Repair Plan / bounded regeneration
              ↓
Cross-deck Regression
              ↓
Production Quality Report + G8
```

## Round A

`audit/M5-round-1-open-issues.md` records:

```text
Critical: 0
Major:    7
Minor:    3
Waivers:  0
```

All Major findings and blocking Minor findings were root-fixed. No waiver was used.

## Round B

`audit/M5-round-2-scorecard.md` records zero open Critical/Major and **M5 Exit Gate: PASS**.

## Verification

Primary final environment: **Python 3.11 + Node 22**. The repository intentionally avoids repeating every M5 submodule across multiple Python minor versions; one supported final environment plus persistent Exit regressions is the M5 freeze policy.

Verified results before final repository invocation:

```text
compileall: PASS
Ruff: PASS
M5.1 deterministic review: 5/5 PASS
M5.2/M5.3 semantic review + scorecard: 6/6 PASS
M5.4 visual review: 6/6 PASS
M5.5 repair: 4/4 PASS
M5.6 regression/quality/G8: 3/3 PASS
M5 Application: 3 critical paths PASS
M5 CLI: 1/1 PASS
M5 Golden: 1/1 PASS
M5 Exit negative controls: 5/5 PASS
M2 Exit: 12/12 PASS
M3 Exit: 13/13 PASS
M4 Exit: 15/15 PASS
Node sidecar: 4/4 PASS
git diff --check: PASS
```

Final repository checks after all status/evidence documents existed:

```text
validate_all.py: PASS
M5 Exit runtime: 16/16 PASS
M5 Exit persistent/static: 16/16 PASS
Package Audit: 21/21 PASS
git diff --check: PASS
```

The final verification baseline is Python 3.11 + Node 22. M5 submodules are not redundantly re-run under multiple Python minor versions; the repository Exit validator owns the runtime M2→M5 regression, while Package Audit checks the persistent/static Exit contract without repeating the expensive smoke chain.

## Final Gate record

- Open Critical: 0.
- Open Major: 0.
- Waivers: 0.
- **M5 Exit Gate: PASS.**
- Next milestone: **M6 Productization and Distribution**.

## Capability boundary

M5 completion means Slidethus has an independent Production review/repair loop with truthful capability boundaries, phase-correct bounded repair and G8 lineage. It does not claim:

- bundled production LLM/visual-review providers;
- automatic repair for arbitrary semantic or aesthetic issues;
- GUI/cloud/multi-tenant productization;
- every Create/Rebuild/Improve/Audit/Revise/Extract Style workflow is fully productized;
- v1.0 release readiness.
