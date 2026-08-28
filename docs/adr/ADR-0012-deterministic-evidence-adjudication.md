# ADR-0012｜Deterministic Evidence Materialization and Adjudication

- Status: Accepted
- Date: 2026-08-27

## Context

M2.1–M2.2 created stable, locatable Source Snapshots. M2.3 created bounded Research Plans, Runs and immutable query-result cache facts while deliberately keeping Research Results separate from Evidence. The next boundary must decide what can enter the Evidence Ledger without turning parser text or search summaries into automatically verified facts.

A deterministic core cannot honestly perform general semantic claim extraction, paraphrase clustering or factual truth verification. It can, however, preserve explicit candidate facts, exact normalized identity, Source lineage, authority/freshness decisions, declared conflicts and fail-closed use policy.

## Decision

### Candidate boundary

The Evidence Engine accepts structured `EvidenceCandidate` values. A conservative Production path creates one candidate per persisted Source Chunk. Future reasoning/model adapters may propose candidates, but they must use the same contract and may not write the Evidence Ledger directly.

Candidate identity binds:

- normalized claim key;
- Source ID and locator;
- support type and origin kind;
- Source Chunk ID;
- Research Run/Result IDs;
- explicit conflict key and stance.

Production claims persist `candidate_bindings`, not only opaque IDs. Bindings include current Chunk content hash and sufficient Research/conflict/freshness lineage to be independently recomputed.

### Claim identity and deduplication

`claim_key` uses conservative Unicode normalization. Presentation punctuation and spacing normalize, but units, percentages, ratios, decimal marks, unary signs and numeric ranges remain meaningful. Only exact normalized matches merge automatically. Semantic-near duplicates stay separate until an explicit reasoning decision exists.

Existing claim keys retain their `EVD-*`. New keys receive the next ID; sorting or inserting claims never renumbers history.

### Research materialization

A Research Result is materialized before adjudication as a `kind=web`, `parse_status=partial` Source and immutable Source Snapshot. It contains only provider-returned title, summary, URL and bounded metadata. It records `remote_body_fetched=false` and cannot be described as fetched page text.

Canonical HTTP(S) URL is the Web Source identity. Materializer-owned Sources merge distinct `RSLT-*` records across Runs while a refreshed identical result replaces only itself. A Web Source owned by another ingestion/fetch path is never overwritten.

Research-summary candidates use indirect support and can be at most provisional without independently fetched direct source content. Provider-returned title/summary text passes through the same deterministic Source-risk scan as local material, so prompt-injection or active-content wording is persisted as risk rather than silently promoted.

### Adjudication

The deterministic decision order is fail closed:

1. opposing current stances in an explicit conflict group → `disputed`;
2. explicit source-less inference/assumption stays qualified;
3. no current Source support → `unsupported`;
4. direct, fully parsed, non-Web Source support may be `verified`;
5. partial/indirect support is `provisional`.

Authority is derived from Source Ledger tiers and recorded with reason codes. Freshness is evaluated only against parseable dates/cutoffs; unknown values require qualification. Source allowed-use and confidentiality constrain use policy. `unsupported`, `disputed`, metadata-only and do-not-use Sources are never usable facts.

High-severity Source risks are enforced at the Evidence Engine boundary, not only by one application caller. Direct Source and Research materialization paths require an explicit `allow_high_risk_source_evidence` override before adjudication. An override never executes Source instructions and never converts the claim into unqualified verified support: the Engine records `high_risk_source_requires_qualification` and keeps the claim provisional or stricter. Workspace validation independently enforces this policy.

### Invalidation and repair

Production Source refs bind Source ID, locator, Chunk ID and content hash. A Source update may commit, but downstream Evidence becomes draft and G2 fails until reconciliation. The Engine filters only invalid candidate bindings, re-adjudicates surviving support and preserves historical `EVD-*` by downgrading unsupported claims rather than reusing IDs. `reconcile_current_evidence` exposes the repair operation independently of adding new candidates, allowing application startup to repair stale or legacy Production claims before Gate evaluation.

Artifact body and expected version are read under one Runtime lock. Concurrent writes fail with `ArtifactConflictError`.

### Research-cycle completion

A semantic research cycle becomes complete only when:

- every referenced Research Run is complete;
- every expected result is materialized into current partial Web Source lineage;
- each result has a current adjudicated claim whose use policy is not `do_not_use`.

Completion unions Run/Source IDs, aggregates query count and is idempotent. A completed Research Run alone cannot pass G2 or G5A.

## Consequences

- Evidence can be traced to current Source bytes/Chunks and Research lineage.
- Search summaries remain visibly provisional.
- Exact dedupe is explainable and avoids unsafe fuzzy merging.
- Source updates create an explicit rework path instead of making the workspace unrepairable.
- The Evidence Ledger schema gains optional Production fields while legacy examples remain compatible through conditional cross-artifact validation.
- The deterministic Engine remains intentionally conservative; semantic extraction, claim equivalence and external factual verification remain adapter/reasoning responsibilities.
- M2.5 may rely on stable, policy-bearing Evidence IDs for block-level binding and targeted gap analysis.
