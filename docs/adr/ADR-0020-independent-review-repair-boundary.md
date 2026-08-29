# ADR-0020｜Independent Review and Repair Boundary

- Status: Accepted
- Date: 2026-08-28

## Context

M4 freezes the Production Rendering boundary: current M2/M3 semantic/planning facts compile into a Production Visual System and one immutable Renderer IR, then Final SVG、PptxGenJS Native、Hybrid、PNG/PDF and the Production Render Manifest are produced and validated through G7.

That proves render structure, lineage, output integrity and editability claims. It does not prove that the deck is semantically persuasive, visually good, presentation-usable or free from cross-page quality defects. M5 must add independent review and bounded repair without moving quality judgment into the renderer or allowing reviewer prose to become a second source of semantic truth.

## Decision

### 1. Review is downstream and independent of rendering

M5 reviewers consume persisted artifacts and real render outputs. They do not participate in M4 compile/render decisions and do not mutate Renderer IR or Render Manifest during review.

A successful M4 preflight, preview or G7 is review input, not proof of G8 quality.

### 2. Review modes publish immutable runtime facts before Quality Report aggregation

M5 review modes produce content-addressed runtime reports under `.slidethus/review/`.

The catalog `review/quality_report.json` remains the canonical aggregate used by G8. Individual deterministic, semantic, scorecard and visual reviewers do not compete to rewrite that file.

This keeps review evidence inspectable, resumable and independently re-runnable while preserving one final Quality Report truth.

### 3. Deterministic review independently recomputes current facts

M5.1 re-evaluates:

- workspace schema/cross-reference/hash integrity;
- G0–G7 regressions;
- current Production Render Manifest and runtime references;
- required backend/output coverage;
- slide-count consistency across Renderer IR、Final SVG、PNG、Native PPTX and Hybrid PPTX;
- output signatures and editability/capability declarations.

It does not accept `M4 Application status=ready` as sufficient evidence by itself.

### 4. Open issue mining precedes scorecard

M5.2 discovers concrete issues without dimension scores. M5.3 scores only after Round A issues are explicit.

Critical/Major issues block G8 regardless of average score. Scores are explanatory evidence, not a severity override.

### 5. Every issue routes to the earliest responsible phase

Review findings identify the earliest phase that owns the root cause:

```text
P0 purpose/audience
P1 source availability
P2 evidence/factual support
P3 narrative
P4 outline/pacing
P5A slide semantics/content load
P5B layout/composition structure
P6 visual system
P7 rendering/export
P8 review/regression machinery
```

A reviewer may recommend a route; deterministic admission validates that the referenced artifact/slide/block/region exists and that repair is allowed for that phase.

### 6. Repair is planned before mutation

M5.5 creates an immutable Repair Plan that binds selected review issues, current artifact versions/hashes, the earliest responsible phase, expected invalidation scope and verification requirements.

Repair execution uses the existing phase services and Artifact Runtime. It does not patch final output files as a substitute for correcting the responsible artifact.

### 7. Cross-deck regression is mandatory after local repair

M5.6 verifies both the intended changed scope and unaffected deck behavior. A local issue is not considered fixed only because the edited slide looks better; global consistency, evidence lineage, Gate state and render output integrity must remain valid.

### 8. Visual review consumes real page images

M5.4 uses independently rendered page images. Final SVG→PNG is the minimum M4-provided visual evidence. Office-compatible preview, when available, adds cross-render evidence but is not fabricated or required as the sole review source.

Visual reviewer integrations remain provider-neutral and treat slide content as data, not instructions.

### 9. Golden Deck is a quality baseline, not a template lock

M5.7 stores representative cases, expected issue/Gate behavior and tolerances. Golden cases test quality-system behavior across content types and degradation modes; they do not require pixel-copying one reference design.

### 10. G8 remains the deck review Gate; M5 Exit is repository-level

Final M5 aggregation publishes a current Quality Report with `gate_result.gate_id = G8`. G8 passes only when the review evidence is current and no blocking Critical/Major issue remains under the existing waiver policy.

M5 Exit additionally proves the repository has persistent deterministic/semantic/visual review, repair, regression and Golden Deck controls. It does not become a new deck phase.

## Consequences

- M4 remains frozen and reusable; review does not contaminate render truth.
- Review can be repeated or upgraded independently when a better semantic/visual provider becomes available.
- Repair remains phase-correct rather than output-patching.
- G8 gains real Production evidence instead of relying on a manually authored Quality Report.
- Hosts without semantic/visual providers can still run deterministic review and receive an explicit capability boundary rather than a false PASS.
