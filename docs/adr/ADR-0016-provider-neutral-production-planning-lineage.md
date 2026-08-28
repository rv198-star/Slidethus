# ADR-0016｜Provider-neutral Production Planning and Current-artifact Lineage

- Status: Accepted
- Date: 2026-08-27

## Context

MVP1 proved that rule-based Narrative, Outline, Slide Specs and Layout artifacts can drive a complete action chain. Those MinimalImpl outputs are intentionally narrow and do not establish a production planning boundary. M3 needs replaceable reasoning while preserving deterministic identity, Evidence policy, current-version validation and recovery.

Passing unstructured prose from one model call to the next would make it impossible to prove which Brief/Evidence/Outline version produced a page, detect stale planning after upstream changes, or safely reuse unchanged work.

## Decision

### 1. One PlanningProvider protocol

Production planning uses the provider-neutral `PlanningProvider.propose` contract for:

- `narrative_blueprint`;
- `deck_outline`;
- `slide_specs`;
- `layout_preferences`.

The repository ships `DeterministicPlanningProvider` as a production-capable deterministic baseline, not a claim of general LLM reasoning. Model adapters may replace it without writing semantic artifacts directly.

### 2. Providers propose; deterministic services admit

A provider returns `PlanningProposal`. The responsible service:

1. freezes provider name/version;
2. validates the complete proposal, including content, warnings and assumptions, against `PlanningLimits`;
3. reconstructs stable IDs and cross-references;
4. applies Evidence and density policy;
5. validates the candidate artifact and Gate reasons;
6. publishes through Artifact Runtime with optimistic locking.

Providers cannot choose artifact versions, Gate status, lineage IDs, stable slide/block/region IDs or output paths.

### 3. Complete proposal budget

`admit_planning_proposal` validates:

- exact artifact type;
- JSON-serializable object content;
- bounded warning/assumption count and text length;
- total serialized proposal bytes;
- the complete PlanningLimits contract.

Warnings and assumptions cannot bypass the content payload budget.

### 4. Planning Lineage

Each Production Narrative, Outline, Slide Specs and Layout Plans artifact carries `planning_lineage`:

- stable `PLN-*` identity;
- planning engine/version;
- provider name/version;
- generated timestamp;
- proposal hash;
- policy payload/hash;
- sorted input artifact refs with version/content hash;
- bounded warnings and assumptions.

Evidence Ledger refs additionally carry a semantic hash of the claims projection. Operational research-cycle metadata may advance without forcing Narrative regeneration when policy-bearing claims are unchanged; changes to claims still invalidate planning.

### 5. Stage-specific lineage

- Narrative binds current Brief and Evidence.
- Outline binds current Brief, Evidence and Narrative.
- Slide Specs bind current Brief, Evidence and Outline.
- Layout Plans bind current Brief, Outline and Slide Specs.

G3/G4/G5A/G5B recompute these relationships against current Artifact Runtime state. A file that merely validates against JSON Schema cannot pass as current Production planning.

### 6. Stable identities and conservative factuality

- Sections use stable `SEC-*`.
- Slides use stable `S-*` and preserve excluded historical objects.
- Blocks use stable `BLK-*` based on slide and semantic block responsibility.
- Regions use stable `REG-*` based on mapped blocks.

Factual slide/block content remains a subset of policy-usable M2 Evidence. Qualified Evidence carries visible qualification. Provider prose cannot become a new factual source.

### 7. Legacy compatibility

Legacy MinimalImpl artifacts remain schema-valid and renderable for MVP regression. Production M3 Gate and repository Exit validation require current Production planning lineage; legacy compatibility never upgrades MinimalImpl capability claims.

## Consequences

- Planning providers are replaceable without changing domain schemas or Artifact Runtime.
- Upstream changes deterministically invalidate the correct stages.
- Semantically unchanged Evidence can avoid unnecessary full-deck regeneration.
- Provider identity drift and oversized output fail before publication.
- Every page plan can be traced to the exact Brief/Evidence/Outline facts that produced it.
- The deterministic baseline provides a real offline D3 planning path while clearly limiting semantic sophistication.
