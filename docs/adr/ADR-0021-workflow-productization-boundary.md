# ADR-0021｜Workflow Productization Boundary

- Status: Accepted
- Date: 2026-08-29

## Context

M2–M5 freeze the Source/Evidence、Planning、Rendering and Review/Repair Production boundaries. The Skill already documents six user-facing workflows—Create、Rebuild、Improve、Audit、Revise Slide and Extract Style—but those workflow names are not yet backed by one Production runtime/report layer. Productization must add stable entry points without creating six competing state machines or moving workflow-specific state into frozen artifacts.

## Decision

### 1. One Workflow Application boundary

M6 introduces one workflow application layer above M2–M5:

```text
Workflow Request
  → deterministic admission
  → one Workflow Application Service
  → existing M2–M5 services/artifacts
  → immutable Workflow Application Report
```

Workflow type changes orchestration policy, not artifact truth ownership.

### 2. Workflow runtime is operational truth only

Workflow reports live under `.slidethus/workflows/runs/`. They record request identity、capabilities、mutation policy、actions、artifact/output refs and final status.

They do not replace Project Brief、Source/Evidence、Narrative/Outline/Specs/Layout、Visual System、Render Manifest or Quality Report.

### 3. Create and Rebuild establish workspaces; Rebuild never overwrites the original

Create starts from a new or admitted empty workspace and user sources/brief hints.

Rebuild accepts an existing PPTX/PDF/image as read-only source material and creates a separate workspace/output graph. The source file hash must remain unchanged. Rebuild may reuse content extracted through M2, but unsupported visual semantics are declared rather than inferred as fact.

### 4. Audit is non-mutating with respect to semantic/render truth

Audit may create immutable review facts and Quality/Gate facts. It runs review with automatic repair disabled. It must prove that Source/Evidence/Planning/Visual System/Render Manifest versions and hashes are unchanged across the audit.

### 5. Improve uses admitted Repair/Change paths only

Improve first audits. It may apply only repairs already admitted by M5 or structured changes admitted by existing M3 Change services. If a finding requires semantic judgment that no provider or automatic contract owns, Improve returns an assisted/manual route instead of patching output bytes.

### 6. Revise Slide is target-scoped and lineage-preserving

Revise accepts explicit stable slide IDs and structured changes. It uses existing Outline Change/Planning regeneration/Rendering/Review services, preserves history and stable IDs where allowed, and reports every changed and propagated slide/artifact.

It cannot silently broaden the target set.

### 7. Extract Style produces a candidate, not unverified brand truth

Extract Style may inspect supported reference decks and current Visual System artifacts. It produces a Visual System candidate plus provenance/capability/rights notes. Font files, brand assets and copyrighted media are not copied merely because they exist in the reference.

The candidate must satisfy the existing Visual System schema before publication.

### 8. Capability boundaries remain explicit

Natural-language Improve/Revise/Style extraction may require injected providers. Provider absence is a first-class blocked/degraded result. M6 does not bundle a fake universal model implementation to make workflow demos appear complete.

### 9. Workflow reports are immutable and idempotent

A normalized request plus bound input state determines workflow request identity. Re-running an unchanged completed/blocked request returns the same report rather than appending duplicate operational history.

### 10. Productization cannot reverse frozen Gates

M6 workflow validation respects the monotonic responsibility-scoped Gate behavior established in M5. Product entry points cannot reinterpret a downstream distribution error as an upstream Evidence/Planning/Rendering failure.

## Consequences

- Six workflows share one runtime/report/CLI architecture.
- Existing M2–M5 services remain reusable and independently testable.
- Audit and assisted workflows can be useful without pretending unavailable model capabilities exist.
- Workflow-level observability、budgets、concurrency and packaging can be added in M6.2–M6.3 without changing semantic artifacts.
- Distribution work can package Skill/workflow/schema/sidecar resources around the same runtime contract.
