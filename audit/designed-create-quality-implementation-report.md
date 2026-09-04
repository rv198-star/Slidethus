# Designed Create Quality-by-Construction — Implementation Report

Date: 2026-09-04
Branch: `codex/issue3-visual-repair-trial`
Design baseline: `8ad3e49c8b3a6929d3d871da025282b7db2e2653` (`v0.9.2-rc.1`)
Design authority: `plans/designed-create-quality-by-construction.md`
Architecture decision: `docs/adr/ADR-0034-quality-by-construction-designed-create.md`
Release decision: **DO NOT RELEASE — Batch 4 real-PowerPoint proof is still open**

## 1. Outcome

The three-round accepted design has been implemented as one fail-closed Designed Create mainline. It does not add a second design system, sample renderer, custom partial IR or reviewer-owned approval path.

The implemented control sequence is:

```text
Brief-bound VisualAdmissionPolicy
  → Taste-generated native direction prototype and independent direction evidence
  → full-deck discriminated Representation Specs
  → geometry-only Layout plus semantic previews and qualitative planning evidence
  → closed capability-bound Visual Grammar and full admitted IR
  → representative sample from that exact IR
  → Microsoft PowerPoint pages and immutable calibration evidence
  → workflow-derived authorization
  → identical-IR/producer full render
  → whole-deck Microsoft PowerPoint review
```

## 2. Implemented ownership and controls

| Boundary | Implemented control |
|---|---|
| risk vs pause mode | deterministic `VisualAdmissionPolicy`; auto reviewed/critical still requires a fixed qualified independent reviewer |
| direction quality | Taste provenance remains separate from direction approval; prototype coverage must include relevant roles/carriers |
| P5A semantics | Slide Specs 0.2 owns discriminated representations and carrier rationale |
| P5B geometry | Layout Plans 0.2 owns placement/view grammar and binds content-addressed semantic previews |
| P6 execution | Packet/Visual System/Renderer IR 0.2 use a closed producer vocabulary and explicit decision-consumption trace |
| renderer boundary | reviewed/critical generic semantic/style fallback is rejected; Artifact Tool consumes explicit chart/table/diagram decisions |
| attempt authority | Host Candidate Receipt 0.3 is the single sample/full attempt receipt and records dependency, producer and Office facts |
| sample/full identity | representative pages are selected from one complete frozen IR; full render requires the same IR, producer and dependency key |
| review history | findings and adjudications are immutable; workflow derives decisions; same-page Critical/Major cannot disappear by omission, downgrade or reviewer switch |
| resume safety | Host Create Session 0.2 persists the exact prepared Seed and calibration lifecycle; an admitted Seed is not reconstructed from an older Host response |
| render admission | Host Create and direct formal M4 rendering call the shared `RenderAdmissionPolicy` |
| release evidence | whole-deck Microsoft PowerPoint evidence is separately required and can revoke sample authorization |

## 3. Regression evidence

New or extended automated controls cover:

- legacy planning and direct M4 bypass rejection on reviewed/critical work;
- immutable same-page Major findings across omission, downgrade and reviewer change;
- append-only Microsoft PowerPoint evidence and rejection of Artifact Tool preview reuse;
- explicit Host Create Session 0.1 migration failure;
- material representation/view mutations changing compiled output;
- Seed revision pause/resume using the frozen Session Seed even when the historical Host Seed response is no longer usable;
- complete reviewed Host Create progression through direction, planning, sample Office evidence, identical full rendering and whole-deck approval.

The repository-wide checks listed by `AGENTS.md` are the acceptance authority for this implementation candidate. Their final command results are recorded in the handoff response and package manifest rather than treated as PowerPoint visual evidence.

## 4. Deliberately unclaimed

This report does not claim that visual quality is already proven in production. The following Batch 4 evidence remains required:

1. the locked YU7, hotel, FDE and employment historical matrix;
2. one genuine post-freeze holdout that was not used to tune the implementation;
3. real Microsoft PowerPoint-rendered sample and whole-deck reviews for all positive cases;
4. zero current open Critical/Major findings before an RC/stable decision;
5. first-pass acceptance, revision-cost and earliest-owner measurements.

Until those facts exist, successful unit tests, schema validation, Artifact Tool export and synthetic Office fixtures are engineering evidence only. They do not satisfy the visual release Gate.
