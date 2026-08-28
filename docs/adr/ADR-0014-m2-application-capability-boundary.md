# ADR-0014｜M2 Application Orchestration and Explicit Capability Boundaries

- Status: Accepted
- Date: 2026-08-27

## Context

M2.1–M2.5 established independent Production services for Source ingestion, multi-format parsing, Research planning/runtime, Evidence adjudication, block-level binding, gap analysis and formal rework. Running those services manually remained possible, but there was no single application boundary responsible for:

- applying one resource budget across existing and newly requested Sources;
- choosing full, user-material or explicitly degraded research behavior;
- preventing accidental external disclosure;
- isolating high-risk Source content from automatic Evidence promotion;
- re-recording G1 after Research materializes new Web Sources;
- revalidating existing planning artifacts without pretending M2 can generate M3 outputs;
- publishing one inspectable operational result.

A convenience script that silently skipped missing capabilities would make the individual contracts less trustworthy. A vendor-specific orchestrator would also violate provider neutrality.

## Decision

### 1. One application orchestrator

`M2ApplicationService` is the only integrated M2 application entry. It calls the completed services in order:

```text
resolved Brief
  → bounded Source ingestion
  → safe Source-backed Evidence
  → orientation Research/user-material completion
  → G1/G2
  → optional existing Narrative/Outline revalidation
  → targeted Research/user-material completion
  → block Evidence Gap analysis
  → G5A or formal EVIDENCE_READY rework
```

It never writes Source or Evidence facts directly. Artifact Runtime remains the only semantic artifact writer through the relevant services.

### 2. Provider-neutral CLI and injected online providers

The repository CLI exposes local/offline M2 orchestration. It does not ship a search vendor adapter.

An online `ResearchProvider` may be injected through the Python application API. Provider execution requires a separate `approve_external_disclosure=True` decision. Provider availability alone does not authorize transmitting Brief or Outline query text. Research Runtime captures provider name/version once at construction and uses that immutable identity for Run, cache and result lineage; the application additionally blocks if the provider object mutates its advertised identity during execution.

### 3. Explicit degradation

Research policy is resolved as follows:

- external research disabled: user-material mode, M2-level D3;
- provider present and disclosure approved: full M2 research mode, M2-level D0;
- external research required but provider/disclosure missing: D5 blocked by default;
- explicit degradation, with no freshness requirement: orientation may be waived and the run continues as D3;
- freshness-constrained external research cannot be waived by the deterministic CLI.

These levels describe the M2 application boundary, not final deck rendering or Delivery Manifest readiness.

### 4. High-risk Source isolation

All requested Sources are safely ingested and inventoried. A Source with high-severity risk findings is excluded from automatic Evidence promotion unless the caller explicitly enables the override. The same default applies to already-persisted high-risk Evidence and provider summaries, so an old override does not become a permanent application permission. Source text remains untrusted data regardless of override, and the Evidence Engine independently enforces qualification.

### 5. Application-level budgets

The application enforces:

- unique requested Source count;
- current workspace Source count;
- requested and current Source byte totals;
- per-Source parser limits;
- Research query/result/cache limits.

Budgets are checked before adapters/providers where possible and rechecked against the resulting Source Ledger and archived Research Runs after materialization. File growth, Web Source insertion and pre-existing inventory cannot bypass the final count/byte/query/result constraints.

### 6. No M3 generation

M2 may revalidate existing Narrative, Outline and Slide Specs against current Evidence. It may not create or edit them. New targeted Evidence that is not yet bound produces a Gap Report and formal P2 rework rather than silent page mutation.

### 7. Content-addressed Application Report

Every application run publishes a non-catalog runtime report under:

```text
.slidethus/m2/runs/<content-hash>.json
```

The report records:

- Project Brief and final artifact versions/hashes;
- a bound Project State revision;
- requested Source fingerprints and the complete application config/limits hash;
- provider/capability decisions;
- actions, blockers and warnings;
- disclosure and high-risk handling;
- Source/Evidence/Research/Gap outputs;
- current Gate evaluations and final phase.

Each referenced Research Run is copied once into an immutable content-addressed snapshot under `.slidethus/m2/research-runs/`; its cache references remain bound by immutable cache hashes. Report validation recomputes Source/Evidence/security/budget facts, constrains runtime paths to admitted workspace roots and supports historical Artifact Runtime versions. Reports are immutable and idempotent for an unchanged final state. They are operational facts, not a Delivery Manifest.

### 8. Workspace M2 Gate

`evaluate_m2_workspace_gate` checks current workspace validity plus G1/G2 and, when both Outline and Slide Specs exist, G5A. It does not replace the repository-wide M2.7 audit and release Gate.

## Consequences

- Users gain one honest application path without losing individual service inspectability.
- No vendor SDK or network behavior enters the deterministic core.
- External research cannot occur through accidental provider injection alone.
- High-risk Source instructions do not silently become Evidence.
- Research materialization correctly revalidates G1 before G2.
- Existing mature workspaces can be revalidated without unnecessary phase rollback when semantic cycle facts are already equivalent.
- Runtime reports add files and validation cost, but make degradation and failure decisions recoverable and reviewable.
- Future vendor adapters require separate ADR/security review and continue to implement `ResearchProvider`.
