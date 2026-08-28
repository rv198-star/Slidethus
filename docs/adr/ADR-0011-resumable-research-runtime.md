# ADR-0011｜Resumable Research Runtime Separate from Evidence Truth

- Status: Accepted
- Date: 2026-08-27

## Context

ADR-0005 defines two research passes in one Evidence domain: orientation research before narrative work and targeted research after an outline exists. The existing contract records only semantic `research_cycles`; it does not provide a real execution model for queries, provider identity, result lineage, cache reuse, interruption recovery or explicit invalidation.

Treating raw search results as Evidence would collapse two distinct responsibilities. A provider can return stale, duplicated, conflicting, weak or incomplete material. Search completion therefore cannot mean that a claim is verified or that G2/G5A has passed.

The runtime also needs to survive provider failures and process interruption without rerunning completed queries or silently reusing results produced under a different provider, freshness requirement, source-tier preference or cache policy.

## Decision

M2.3 introduces a provider-neutral Research Runtime below the semantic Evidence layer.

### 1. Research Result is not Evidence

A `ResearchResult` is an auditable candidate returned by a `ResearchProvider`. M2.3 does not automatically create Source Ledger records or Evidence claims from it.

M2.4 owns materialization and adjudication:

```text
Research Result
  → source materialization / retrieval boundary
  → source identity + locator
  → Evidence normalization
  → support / conflict / freshness / authority decision
  → Evidence Ledger
```

A completed Research Run therefore proves execution completeness only. It does not by itself complete a semantic `research_cycle`, G2 or G5A.

### 2. Deterministic two-pass planning

`ResearchPlan` is built deterministically from current semantic artifacts:

- orientation: Project Brief title, purpose, desired outcome, audience needs, freshness and admitted external source tiers;
- targeted: the current registered Outline version plus active factual slide headline/takeaway and optional slide selection.

Placeholder context is not converted into search queries. Targeted plans bind the exact current `outline_version`.

Plan IDs, query IDs and task IDs are stable. Research cycle IDs cannot be rebound to another cycle kind or another outline version.

### 3. Provider identity is part of lineage

Every production `ResearchProvider` declares `name` and `version`.

A Run ID binds:

- plan identity;
- provider name;
- provider version.

A query cache input key additionally binds the normalized query contract and result-affecting limits, including cache TTL. Provider or policy drift cannot silently reuse incompatible cache entries.

### 4. Runtime facts are separate from catalog artifacts

Research execution state is stored under:

```text
.slidethus/research/runs/RRN-*.json
```

using `research_run.schema.json`.

Query results are immutable content-addressed snapshots under:

```text
.slidethus/cache/research/<input-key>/<content-hash>.json
```

using `research_cache_snapshot.schema.json`.

These are runtime facts, not semantic catalog artifacts. They are packaged schemas and are included in workspace/package validation, but they are intentionally not registered as normal Artifact Runtime phase artifacts.

### 5. Cache is immutable and generation-invalidated

A successful query snapshot is create-if-absent and never overwritten. Its identity validates:

- project;
- provider identity;
- full query contract;
- result-affecting limits;
- cache TTL/expiry;
- result identities;
- content-addressed filename.

Explicit invalidation increments a generation marker. Historical snapshots remain on disk for audit; later execution can only reuse a snapshot from the current generation.

### 6. Execution checkpoints each task

The orchestrator executes query tasks sequentially. Before and after provider work it atomically checkpoints the Research Run.

- completed tasks are reused on resume;
- provider failure records `failed`/`partial` and can be retried;
- cache/result validation failures also checkpoint failure instead of leaving a false `running` state;
- an interruption after cache publication but before run update can reuse the immutable orphan cache;
- an interruption after invalidation marker publication is reconciled by explicit run loading/recovery.

Workspace validation remains read-only. It verifies Research Runtime state but does not perform recovery writes.

### 7. Offline is an explicit capability state

`OfflineResearchProvider` returns no fabricated result. It blocks the current research task, allowing the higher-level capability policy to choose D3 or D5 honestly.

No M2.3 adapter performs web fetching, script execution or Evidence adjudication.

### 8. Bounded results

Research limits bound:

- query count and query length;
- results per query and total results;
- title and summary size;
- metadata bytes;
- cache TTL.

Provider iterables are consumed only up to the admitted per-query boundary plus one overflow sentinel. Non-JSON metadata, unsafe URLs, malformed timestamps and corrupt cache lineage fail closed.

## Consequences

- Slidethus now has a real resumable research execution layer without coupling the domain model to a search vendor.
- Raw search completion cannot be mistaken for verified Evidence.
- The project carries additional runtime manifests and immutable cache files that need eventual garbage collection based on historical references.
- M2.4 must explicitly define result-to-source/evidence materialization and must not bypass this boundary.
- A future production search adapter can replace the test/offline providers without changing Research Plan, Run or Evidence contracts.
