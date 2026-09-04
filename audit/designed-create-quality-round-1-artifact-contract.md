# Designed Create Quality Audit — Round 1: Artifact and Contract

Date: 2026-09-04
Mode: independent, read-only
Verdict on audit candidate: **REWORK**

## Audited inputs

- Plan SHA-256: `3bfc6e8f7c2afe2ab9c20f9fe5e390484a7ab03ceeb7c23b42dcd6e53ed6c89e`
- ADR SHA-256: `8d5996bea31ad2ba2b4de04edf73e3f87b8604aeacea2c5a212ffd6c9cb35714`
- Baseline: `8ad3e49c8b3a6929d3d871da025282b7db2e2653`

This audit did not read or reuse the other two audit conclusions.

## Critical finding

### R1-C1 — Calibration approval self-invalidates under the proposed P6/P7 expansion

The candidate calibrated a P6 grammar and then proposed P6/P7 full-deck expansion. Current contracts require complete Outline/Specs/Layout/page designs and one complete IR before a sample can be rendered. Any later P6 or page-design change changes the lineage that the calibration approved.

Evidence:

- `src/slidethus/services/render_compile.py` requires the complete active slide set;
- `src/slidethus/page_design.py` requires page designs to cover Slide Specs;
- current Host Create samples select pages from one complete full-deck IR;
- the candidate's own invalidation rule made later P6 changes stale.

Required disposition: complete and freeze full-deck P5/P6/page designs and one admitted IR before calibration; render the sample as a projection of that exact IR; after approval perform only the full render. Any design change invalidates calibration.

## Major findings

### R1-M1 — A new `VisualCalibrationRun` would duplicate Host Candidate Receipt authority

`host_candidate_receipt` already owns sample/full scope, slide IDs, renderer, IR, preflight and outputs. Extend it; do not create a second render receipt.

### R1-M2 — Calibration substate, resume and full-render admission were not closed

Session and operation schemas do not yet model calibration. A HostCreate-only check would also allow another formal render entry to bypass it. The implementation needs one pending calibration substate and one shared `RenderAdmissionPolicy` at every full-render entry.

### R1-M3 — `visual_risk_class` could become a drifting second policy fact

Project Brief already owns `approval_mode` and `quality_profile`. Risk must be a deterministic admission fact derived from the exact Brief hash plus a versioned policy, with reason codes; it must not be provider-authored editable metadata.

### R1-M4 — Review evidence and approval authority were conflated

A VisualReviewProvider may publish findings but must not directly write approval. Workflow derives the decision from immutable evidence, coverage, policy and open severity. Reviewer identity, capability and author/reviewer independence must be explicit.

### R1-M5 — Page roles and visual lineage had multiple owners

The candidate spread role identity across Outline, Specs, Layout and ReferenceSet. Required ownership:

- Outline owns narrative page role;
- Specs owns representation kind and semantic content;
- Layout owns placement/view geometry;
- Visual System owns page family/component variants;
- ReferenceSet is approval evidence only, never a second design system.

### R1-M6 — P5A/P5B duplicated chart/table/diagram semantics

Specs must own chart question/data, diagram nodes/edges/roles/direction and table schema/hierarchy. Layout only owns orientation, ports, routing/label anchors and placement that reference those semantic IDs. Use a discriminated `representation.kind` union.

### R1-M7 — Executable Visual Grammar was still an open vocabulary

The candidate named grammar concepts but did not close them against Artifact Tool capabilities. Reviewed/critical compilation must reject unknown or unconsumed decisions, disable generic fallbacks and emit a decision-to-IR consumption trace. Mutation-sensitive tests must prove a material input decision changes IR/output.

### R1-M8 — Calibration identity omitted material dependencies

The dependency key must bind complete design artifact hashes, selection policy/version, compiler, IR schema, backend/adapter, capability contract, assets, fonts, Office build and export settings. Initial implementation should conservatively invalidate all calibration on any design dependency change.

### R1-M9 — Semantic planning preview and qualitative planning review lacked evidence facts

The preview needs a content-addressed receipt bound to Seed/Specs/Layout/capabilities, and the qualitative report must bind that exact preview hash and reviewer identity. The architecture must distinguish this admission review from ADR-0026 retrospective Stage AI Review and update `docs/03`/`docs/05` during implementation.

### R1-M10 — Migration was underspecified

Specs, Layout, Visual System, Session, Operation, Receipt, Review and IR are strict schemas. The plan needs a version/migration matrix. Non-derivable representation and slot facts cannot be backfilled with defaults; reviewed/critical legacy workspaces must explicitly replan.

## Minor findings

- Approved sample pages may not be silently rewritten, but P8 may still find a whole-deck-context defect and revoke the calibration decision.
- A controlled lightweight path is not automatically `degraded`; degradation applies only when a promised capability/deliverable is missing.

## Independent conclusion

The candidate correctly moved quality judgment before full rendering and preserved Office-first evidence, but its central transaction and ownership model were not yet implementable without ambiguity. Verdict: **REWORK**.

## Closure verification

The reviewer independently verified the revised substantive design at:

- Plan SHA-256: `b0503db1f8345bb14ec4e4a95839ec839f3cfd7a0498b7a834a42cfeab13804b`
- ADR SHA-256: `376e9cda4d78c64c045f4398d9425b2bbe7e7f05cb1625e8a95ff32400835833`

R1-C1 and R1-M1 through R1-M10 were closed. A first closure pass identified two remaining Major details: direction review/decision/adjudication hashes were absent from the dependency key, and Host Candidate Receipt incorrectly reused the existing 0.2.0 version. The final revision added those refs to the key and required full admission to resolve them; it also defined the additive `0.2.0 → 0.3.0` receipt migration and the condition requiring a breaking generation.

Final verdict: **ACCEPT FOR IMPLEMENTATION**. This does not certify implementation or production output quality.
