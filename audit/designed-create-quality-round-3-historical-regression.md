# Designed Create Quality Audit — Round 3: Historical and Regression

Date: 2026-09-04
Mode: independent, read-only
Verdict on audit candidate: **REWORK**

## Audited inputs

- Plan SHA-256: `3bfc6e8f7c2afe2ab9c20f9fe5e390484a7ab03ceeb7c23b42dcd6e53ed6c89e`
- ADR SHA-256: `8d5996bea31ad2ba2b4de04edf73e3f87b8604aeacea2c5a212ffd6c9cb35714`
- Baseline: `8ad3e49c8b3a6929d3d871da025282b7db2e2653`

This audit did not read or reuse the other two audit conclusions.

## Critical finding

### R3-C1 — Current contracts make “same complete IR” incompatible with post-sample design expansion

Historical and implementation evidence agree:

- page designs cover every Slide Spec;
- Specs/Layout cover the complete Outline;
- IR compilation requires the complete active slide set;
- sample selection occurs after the complete IR exists;
- tests lock sample/full to the same IR and byte-identical selected PNGs.

The candidate's post-sample P6/P7 expansion would either self-invalidate or recreate the custom/partial path that hotel and earlier M6 work showed to be unsafe. Required disposition: freeze the full design and complete IR before calibration; after approval run only the full render.

## Major findings

### R3-M1 — A blanket ban on reviewed/critical auto would remove a proven positive path

The YU7 case used auto, early real assets, complete whole-deck visual planning and formal Host Create, and produced a user-accepted PowerPoint result. The key control is not a mandatory human Gate; it is complete design reasoning plus independent, inspectable review evidence.

Required disposition: separate risk-required evidence from human approval mode. Auto remains possible when a fixed, qualified, independent VisualReviewProvider supplies the required evidence; otherwise pause for human review.

### R3-M2 — Regression corpus omitted the most informative historical controls

The implementation corpus must lock:

1. YU7 accepted auto/asset-rich formal-path positive;
2. hotel initial custom-render bypass negative;
3. hotel accepted low-luxury whole-deck propagation positive;
4. FDE formal-sample positive and remaining-page drift negative;
5. employment cold-start negative;
6. one post-freeze holdout not used to write the rules.

If holdout failure changes the implementation, that case becomes training evidence and a new holdout is required.

### R3-M3 — The direct Issue #3 Seed replay regression was missing

Issue #3 confirmed that repeated Seed preparation and stale response replay could overwrite the revised Taste Seed across process resume. The new transaction must extend the existing test through:

```text
Seed revision → Specs → Layout → P6 → calibration stop/resume → full render
```

Every step preserves the same Seed content hash. Old response injection and duplicate prepare cannot overwrite it. A real Seed change invalidates calibration/reference facts.

## Minor findings

### R3-N1 — Employment failure was described as a carrier-count shortage

The deck actually had five chart Blocks, three images, four tables and three diagrams. The problem was carrier fitness, visual weight, semantic geometry and cross-page composition, not raw counts. The architecture must avoid media quotas.

### R3-N2 — v0.8 success causality was overstated

The repository proves that v0.8.0 art direction came after P5 and that its release added no new cross-case Office proof. It does not prove that “smaller path and tuned cases” caused its perceived quality. Treat case/author/asset conditions as hypotheses. The auditable positive baseline is v0.8.1 YU7.

### R3-N3 — “Design Direction Lab” conflicts with the repository's lab meaning

The ordinary pre-P5 step should be named `Design Direction Prototype`. `Art-direction Lab` remains the isolated recovery experiment used after a formally complete deck still misses the aesthetic bar.

## Historical attribution conclusion

- No evidence establishes a universal visual regression from every v0.8 deck; there is one strong v0.8.1 YU7 positive.
- The v0.9.0 reference library was primarily distribution/provenance work and was not visually proven; its size is not a causal regression.
- v0.9.1 renderer/recovery changes preserved 11 of 12 YU7 pages byte-for-byte and improved the table; they are not the main cause.
- The direct regression at the Issue #3 checkpoint was stale Seed replay.
- The current broader quality causes are weak design reasoning, underspecified P5 representation/geometry, non-transactional sample approval, self-review and generic diagram fallback.

## Independent conclusion

The candidate addressed the correct broad causes and rejected fixed templates/quotas, but its central sequencing could recreate the exact custom-sample bypass it intended to eliminate. Verdict: **REWORK**.

## Closure verification

The reviewer independently verified the revised substantive design at:

- Plan SHA-256: `b0503db1f8345bb14ec4e4a95839ec839f3cfd7a0498b7a834a42cfeab13804b`
- ADR SHA-256: `376e9cda4d78c64c045f4398d9425b2bbe7e7f05cb1625e8a95ff32400835833`

R3-C1, R3-M1 through R3-M3 and R3-N1 through R3-N3 were closed. The final design preserves reviewed/critical auto with independent evidence, locks the YU7/hotel/FDE/employment/holdout matrix, extends the exact Seed replay regression through calibration/full render, separates Prototype from Lab and uses one complete IR for sample/full. The final dependency-key and Receipt-version delta introduced no regression.

Final verdict: **ACCEPT FOR IMPLEMENTATION**. This does not certify implementation or production output quality.
