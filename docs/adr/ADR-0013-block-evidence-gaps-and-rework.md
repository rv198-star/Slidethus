# ADR-0013｜Block-level Evidence Gaps and Explicit P2 Rework

- Status: Accepted
- Date: 2026-08-27

## Context

M2.4 produces stable, current, policy-bearing Evidence. That does not prove a proposed page uses Evidence correctly. The existing G5A checked that Slide Specs existed and that a targeted cycle matched the Outline version, but it did not prove that required factual blocks were bound, usable or qualified.

A deterministic core also cannot infer whether every arbitrary sentence is factual. It needs explicit schema intent plus a small set of unambiguous slide/block types. Gaps must be inspectable and able to route back to P2 without inventing a new workflow Phase.

## Decision

### Evidence requirement contract

Deck Outline slides and Slide Spec blocks may declare:

- `evidence_requirement=required`;
- `evidence_requirement=optional`;
- `evidence_requirement=none`.

Blocks may also declare `evidence_qualification` for provisional, inferred, assumed, stale or otherwise qualified support.

When explicit fields are absent, the deterministic core uses only conservative type defaults:

- cover/agenda/section → none;
- evidence/comparison/timeline/matrix/chart/case/quote slides → required;
- metric/evidence/quote/chart/table blocks → required;
- other content → optional.

No general natural-language factuality classifier is claimed.

### Current-version gap analysis

The Evidence Binding Service reads Project Brief, Source Ledger, Evidence Ledger, Deck Outline and optional Slide Specs in one locked graph snapshot. It checks:

- current G2-compatible Evidence lineage;
- current-outline targeted cycle;
- required slide/block binding;
- unknown or policy-blocked Evidence;
- required slide-to-block coverage;
- block-to-Outline declaration consistency;
- explicit qualification for qualified Evidence.

G5A recomputes the blocking subset from current artifacts. A historical report never substitutes for current Gate evaluation.

### Evidence Gap Report

Each analysis may publish an immutable, content-addressed runtime report under:

```text
.slidethus/evidence/gaps/<sha256>.json
```

The report binds artifact versions/content hashes for Brief, Source, Evidence, Outline and Specs. It contains stable issue IDs, query suggestion IDs, per-slide status, severity, earliest responsible phase and rework target. It is a non-catalog runtime fact and cannot itself advance a phase.

Historical reports validate against current or Artifact Runtime history versions.

### Research handoff

Blocking gaps may produce deterministic query suggestions only when Brief policy admits external research and external source tiers. Suggestions are converted through `plan_explicit_targeted_research`, which validates current active slide IDs and uses the same M2.3 cycle/outline/provider-neutral contracts.

A suggestion or Plan is not executed research and is not Evidence.

### Offline/user-material targeted completion

When no blocking binding gaps remain, G2 passes, Slide Specs exist and all bound Sources are non-Web, the service may complete a targeted cycle with:

- basis `user_materials` or `none_required`;
- query_count 0;
- no Research Run IDs.

Web-backed or existing Run lineage must complete through the M2.4 Evidence Engine. Completion is idempotent.

### Rework route

A blocking report may route:

```text
OUTLINE_READY or SLIDE_SPECS_READY
  → EVIDENCE_READY
```

Artifact Runtime performs one transaction that:

- verifies expected input artifact versions;
- records the rationale in Decision Log and Project State summary;
- retains only G0–G2;
- marks Narrative, Outline, Slide Specs and later staged artifacts draft;
- histories the prior Project State.

`blocked` remains a status, not a Phase.

## Consequences

- G5A now proves page-level Evidence readiness rather than only cycle existence.
- Explicit requirements make model/agent intent inspectable while preserving legacy compatibility.
- Gap reports can drive targeted research and audit without becoming semantic truth.
- Offline projects can complete targeted review from user materials without fake search.
- Source/Evidence/Outline/Spec changes invalidate stale reports through version/hash lineage.
- M2.6 can build an application-level orchestration path from the established Source → Research → Evidence → Gap contracts.
