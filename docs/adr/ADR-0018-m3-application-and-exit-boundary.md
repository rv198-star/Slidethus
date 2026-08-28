# ADR-0018｜M3 Application Orchestration and Repository Exit Boundary

- Status: Accepted
- Date: 2026-08-27

## Context

M3 subservices can be invoked independently, but users need one application path that completes intake, uses the frozen M2 boundary, produces current planning artifacts, runs targeted Evidence review, generates wireframes, audits quality and applies bounded repair. Without one orchestrator, callers can skip G2/G5A, treat provider output as an artifact, or claim planning readiness from stale JSON files.

M3 also needs a repository-level completion Gate distinct from deck Gates G0–G9. The repository Gate must prove the Production planning boundary without claiming M4 rendering or M5 visual repair.

## Decision

### 1. Single M3 application orchestrator

`M3ApplicationService` owns the integrated sequence:

```text
Brief hints + Sources
  → Brief completion / G0
  → M2 orientation / G2
  → Narrative / G3
  → Outline / G4
  → Slide Specs
  → M2 targeted Evidence / G5A
  → Layout + immutable wireframes / G5B
  → Planning Review
  → bounded automatic Repair + regression
  → immutable M3 Application Report
```

Subservices remain independently testable. They do not form a role-play multi-agent chain and cannot independently declare the application complete.

### 2. Honest stopping levels

Every run records the furthest valid planning level:

- P0: Brief/intake;
- P2: Evidence-ready;
- P3: Narrative-ready;
- P4: Outline-ready;
- P5A: Slide Specs-ready;
- P5B: Layout/wireframe-ready.

Status is `ready`, `needs_input`, `rework_required`, `blocked` or `failed`. The final level is derived from the bound Project State, not selected by the caller. Failures and rework reports bind exactly the artifacts and Gates valid at that phase.

### 3. M2 remains authoritative

The application invokes `M2ApplicationService` twice when required:

- orientation before Narrative;
- targeted Evidence integration after Specs.

M3 stores verified M2 Report references. Requested Sources and ResearchProvider identity must agree across M2 and M3 reports. M3 never copies raw Research Results into planning facts.

### 4. Content-addressed M3 Application Report

Each run publishes `.slidethus/m3/runs/<content-hash>.json` containing:

- full Brief hints and all planning/M2 limits;
- frozen planning/research provider identities;
- requested Source fingerprints;
- capability decisions;
- canonical action chain;
- blockers/warnings;
- exact final artifact refs;
- M2 Report, Planning Review and Repair refs;
- immutable wireframe refs;
- final Project State phase and Gate evaluations.

Validation independently recomputes configuration hash, limits, Source/M2/provider consistency, artifact set for the planning level, planning lineage, Review finality, Repair policy, wireframe coverage and Gate/Project State agreement. A rehashed forged report remains invalid.

### 5. Recovery behavior

Domain errors from M2, Planning services, Artifact Runtime and Repair are converted into explicit Application reports when a safe Project State exists. Valid partial transactions are retained. The application does not erase history or roll forward around a failed Gate.

Invalid hints and nested limits are validated before any Source or Brief mutation. Unexpected programming/runtime errors still propagate rather than being mislabeled as an admitted domain failure.

### 6. CLI boundary

The deterministic CLI exposes:

```text
slidethus m3 run
slidethus m3 answer
slidethus m3 list
slidethus m3 show
slidethus m3 gate
```

It ships the deterministic PlanningProvider and no online ResearchProvider. External research remains subject to M2 protocol injection and disclosure approval through the Python API.

### 7. Repository M3 Exit Gate

`validate_m3_exit.py` is a repository-level validator, not a new deck Gate. It checks:

- required code, schemas/mirrors, tests, ADRs and audit evidence;
- completion markers and capability truthfulness;
- provider neutrality and no bundled network/model client;
- current M2 Exit regression;
- a temporary end-to-end Production M3 run and workspace Gate;
- zero open Critical/Major in Round B;
- persistent Makefile/package-audit wiring.

M3 Exit PASS authorizes M4 Rendering Backends only.

## Consequences

- Hosts gain one resumable, inspectable planning workflow.
- Partial/failed runs cannot masquerade as P5B readiness.
- Reports survive later artifact versions through Artifact Runtime history.
- M2 contracts remain frozen and reused rather than duplicated.
- M3 completion means structure, evidence, page semantics, geometry and wireframes are reviewable without final visual design.
- It does not provide final SVG/PptxGenJS/Hybrid rendering, asset generation, independent visual inspection or automatic visual repair.
