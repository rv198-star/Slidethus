# ADR-0017｜Stable Digital Sticky Notes, Planning Review, and Local Repair

- Status: Accepted
- Date: 2026-08-27

## Context

A Deck Outline is the page-level decision layer between Narrative and page design. Treating it as a replaceable numbered list makes every reorder renumber slides, loses review history and forces unrelated pages to regenerate. M3 also needs a quality loop before final visual design: duplicate pages, weak transitions, density, layout monotony and local defects should be found and routed to the earliest responsible stage.

## Decision

### 1. Stable digital sticky notes

Every Outline slide is a persistent `S-*` object. Ordinal is presentation order, not identity. Explicit operations are implemented by `OutlineChangeService`:

- insert;
- exclude;
- reorder;
- split;
- merge;
- freeze/unfreeze;
- update.

Deleted/replaced pages remain as `status=excluded` history. Split/merge mappings record source and destination slide IDs. Frozen fields protect approved responsibilities from incidental regeneration.

### 2. Change Report and atomic publication

Every operation publishes a content-addressed `Planning Change Report` (`PCH-*`) in the same Artifact Runtime transaction as the new Outline version. The report persists:

- operation payload and reason;
- idempotency key;
- PlanningLimits;
- input/output Outline refs;
- created/excluded/preserved IDs and mappings;
- changed fields and downstream invalidation.

The request hash is independently recomputable. Reusing one idempotency key with a different payload or policy is an explicit conflict, not a second operation. The output Outline must carry local-operation provider lineage and every `operations_applied` ID must have a valid Change Report.

### 3. Dependency propagation

Artifact Runtime invalidates only downstream stages:

```text
Outline change
  → Slide Specs draft/stale
  → Layout/Visual/Render/Review/Delivery draft
```

Narrative and Evidence remain unchanged unless the operation explicitly reveals an earlier-stage problem. Stable Slide IDs allow unchanged page responsibilities and Block IDs to be reused.

### 4. Planning Review

`PlanningReviewService` recomputes current planning quality and publishes immutable `PRV-*` reports binding Brief, Evidence, Narrative, Outline, Specs and Layout versions/hashes.

Deterministic checks cover:

- G0/G3/G4/G5A/G5B readiness;
- Narrative objections, call to action and section budgets;
- duplicate/near-duplicate takeaways;
- headline length, page timing and slide-type rhythm;
- content density and competing primary blocks;
- Layout capacity, family repetition and Bento overuse;
- current Evidence/lineage/geometry contracts.

Each issue records severity, stable identity, earliest responsible phase, location, suggested action and repairability. Open Critical/Major issues determine the formal rework target. Open-issue mining is performed before scorecard interpretation.

### 5. Local Repair

`PlanningRepairService` automatically applies only explicitly admitted deterministic repairs. The initial automatic operation is headline shortening; assisted/manual issues are reported without semantic mutation.

A repair:

1. binds a current Planning Review and selected issue IDs;
2. records PlanningLimits and frozen provider identity;
3. performs explicit Outline changes;
4. regenerates only dependent Specs and Layout;
5. rebinds the current user-material targeted cycle;
6. re-records G2/G3/G4/G5A/G5B as required;
7. reruns the complete Planning Review;
8. publishes a content-addressed `PRP-*` report.

Repair identity includes review, issue set, reason, limits and provider. Regenerated artifacts must carry the same provider lineage. Failure after a valid partial transaction leaves the workspace at the earliest safe phase; `M3ApplicationService` publishes a failed Application Report rather than hiding the checkpoint.

### 6. No speculative automatic rewriting

Near-duplicate pages, competing primary messages, Narrative objections and semantic restructuring require assisted/manual judgment unless a future ADR admits a deterministic repair. The system routes them to the earliest phase instead of performing plausible but unreviewed rewriting.

## Consequences

- Page review comments survive reorder and local changes.
- Explicit operations are recoverable and independently auditable.
- Local repairs minimize affected stages while still running cross-deck regression.
- Automatic repair remains bounded and honest about semantic limits.
- M4 can consume approved Layout Plans without inheriting unresolved structural defects.
