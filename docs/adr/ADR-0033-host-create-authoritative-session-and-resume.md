# ADR-0033 | Host Create authoritative session, resume and revision

- Status: Accepted; cold-start candidate and real Office acceptance pending
- Date: 2026-09-03

## Context

Issue #3 showed that a valid response-driven Create could repeatedly lose progress even when every individual artifact and provider response was well formed. The CLI rebuilt `BriefCompletionHints` from each invocation, while `HostCreateService` re-entered the complete M3 intake whenever the whole planning stack was not already finished. A changed, omitted or repurposed `--request` therefore changed the Brief context hash, invalidated downstream planning, and made a response written for the previous request obsolete before it could be consumed.

The same failure appeared in revision and reuse paths:

- `--revise-stage` generated one phase and then re-ran P0/P1/P2 as if the revision were a new Create;
- structurally valid planning files could be reused after Project State had rolled back or their registry entry was draft;
- a targeted M2 report could remain historically valid while still being stale for the current Slide Specs;
- semantic layout-family names were forced through a fixed Layout enum and collapsed to `custom`, while Review treated repeated `custom` labels as repeated geometry;
- failures before the renderer had no durable create-level terminal fact;
- malformed Host responses exposed deterministic defects one at a time.

The previous two uncommitted repair attempts changed too many owners at once and accumulated follow-on conditions. This decision starts again from `origin/main@b1af33c` and uses the existing Artifact Runtime, Gate and provider boundaries rather than adopting either half implementation.

## Decision

### 1. One canonical Host Create session owns initial intent

A designed Create workspace may have one schema-backed mutable runtime fact at:

```text
.slidethus/host-create/session.json
```

The session records the initial title, complete Source fingerprints, Brief hints, Planning/M2 limits, capability-policy flags and provider identities. Its `config_hash` is the canonical identity of the user intent. It also records pending Host request, pending stage revision, reusable M2 report references, the latest M3 report and the latest terminal Create operation.

The session is an operational fact, not a catalog artifact. It does not satisfy a Gate, advance Project State or replace Project Brief, Source Ledger, Evidence Ledger or any planning artifact. An already-populated workspace without this Session is not silently adopted with defaults; designed Create must use a new workspace until an explicit migration contract exists.

### 2. Omission means resume; an explicit difference means revision or conflict

After a session exists, omitted CLI/API values reuse the persisted config. A normal invocation that explicitly supplies a different title, request/Brief hint, Source fingerprint, limit, policy flag or provider identity is rejected before any Project State, Brief, Source, Evidence or planning artifact mutation.

The rejected invocation may still write its own started and terminal operation facts. Those facts are audit evidence, not production-artifact mutation.

`--request` is no longer overloaded as a revision instruction. Intent changes use an explicit operation:

- `--revise-brief --request ...` overlays only explicitly supplied Brief fields, increments `intent_revision`, clears stale pending/planning caches and resumes from the formal Brief path;
- `--revise-sources --source ...` explicitly adds or updates canonical local Sources and re-fingerprints the complete retained set. Omission never silently removes a Source;
- `--revise-stage <stage>` is a planning-phase revision and cannot also revise intent or render.

### 3. Phase revision has a durable owner and a distinct request identity

A stage revision is persisted in the session before the owning service runs. If the invocation stops for a Host response, a later plain `slidethus create <workspace>` resumes the same revision. A pending stage revision must finish before rendering and cannot replace an unanswered request from another stage.

As soon as the owning artifact commits, the Session checkpoints that completion and clears the pending revision/request before downstream regeneration begins. A later downstream failure therefore resumes dependency rebuilding instead of submitting the same revision a second time.

Narrative, Outline, Slide Specs and Layout revision requests bind the superseded artifact type, version and content hash. Art Direction Seed continues to bind its immutable Seed reference. This makes a revision request distinct from the original proposal request and prevents an old response from being silently replayed as a new revision.

After the owning artifact is admitted, only its real dependents are invalidated. P0/P1/P2 and unaffected upstream planning are not reinterpreted merely because a downstream phase is being revised.

### 4. Current Gate authority, not file existence, controls reuse

A planning artifact is reusable only when all applicable facts agree:

- Project State has reached the owning phase;
- the artifact body has approved semantics and its planning lineage binds current upstream inputs;
- the expected provider and policy match;
- the artifact registry is approved/frozen, or its accepted current Gate still binds the current registry versions and hashes;
- every Gate needed for the resume point is accepted and current.

A draft body may therefore be reused only when the current accepted Gate proves it was deliberately revalidated after an operational upstream update. A merely present or schema-valid file cannot advance the workflow.

M2 report reuse is stricter. The report path, hash, Schema, config, provider, requested Sources, required phase, accepted Gate and relevant artifact refs must all match. Targeted M2 additionally binds the current Outline and Slide Specs. Evidence Ledger version drift is tolerated only when its claims semantic projection is unchanged and the required Gate remains current.

### 5. Every Create invocation has a closed operational record

Each invocation writes:

```text
.slidethus/host-create/operations/HCO-*/started.json
.slidethus/host-create/operations/HCO-*/terminal.json
```

The terminal status is one of `host_input_required`, `rework_required`, `blocked`, `failed`, `design_ready`, `candidate_office_review_pending`, `render_failed` or `render_timed_out`. It binds the session/config identity, invocation hash, state before/after, duration, pending request, exact result references and permitted next actions.

A later invocation holding the workspace lease closes an orphaned start as failed before continuing. Artifact Tool receipts remain the authority for an actually started renderer attempt; a Host Create operation may reference that receipt but does not replace it.

For Planning Review rework, the terminal result includes the earliest target phase, exact open Critical/Major `PRI-*` IDs, Review path and allowed recovery actions. A generic “issues remain” message is insufficient.

### 6. Semantic layout family and observable geometry are separate facts

Slide Specs and Layout Plans use the same bounded provider-neutral semantic-family syntax. A Host-authored layout with explicit Regions may preserve a semantic family such as `editorial-ledger`; deterministic auto-layout continues to support only its canonical implementation families.

The selected Layout family must be declared by the matching Slide Spec. `custom` is not an admission escape hatch.

Planning Review detects repetition and relationship collapse from an observable, coarse geometry fingerprint of Regions. Reusing one semantic name with genuinely different geometry is not automatically a defect; renaming identical geometry does not create visual rhythm.

### 7. Host proposal admission reports all deterministic findings visible at that boundary

The response envelope aggregates all JSON Schema and request-binding findings in stable order. Narrative, Outline, Slide Specs and Layout pre-admission then aggregate required fields, enums, page/Block coverage, evidence requirement, semantic family, density and basic geometry findings before returning control to the Host.

A rejected response remains bound to the same pending request and may be atomically replaced. Received snapshots prove submission only; the admitted artifact and Gate remain authoritative.

### 8. Structural recovery and visual release remain independent conclusions

Session stability, phase recovery, Artifact Tool generation and Office visual quality are separate acceptance layers. A generated PPTX, library PNG or valid operation receipt does not approve hierarchy, rhythm, composition or release. M6 remains reopened and v1.0 remains `DO NOT RELEASE` until the required fresh-case and real PowerPoint acceptance is complete.

## Consequences

- A plain resume command is sufficient after the initial invocation; long user intent is no longer copied through every Host turn.
- Explicit input drift fails early and predictably instead of causing downstream request-hash churn.
- Runtime facts increase, but they stay outside the semantic artifact graph and are validated as supporting records.
- M3 can skip expensive orientation/targeted work only with exact evidence, not optimistic heuristics.
- Host proposal errors become longer but require fewer round trips.
- Add/update Source revision is supported; silent Source removal is intentionally not inferred from omission.
- Layout taxonomy can evolve without turning semantic names into renderer-specific enums.

## Rejected alternatives

- Continue patching either uncommitted repair branch: both mixed ownership boundaries and had already produced follow-on state defects.
- Require the Agent to retype the original command exactly: conversational repetition is not a durable task identity.
- Treat an empty argument as omission: empty, default and unspecified must remain distinguishable.
- Reuse planning because JSON files exist and validate: this recreates phase rollback and stale Gate defects.
- Reuse any historically valid M2 report: historical auditability is not current approval.
- Convert every unknown family to `custom`: this erases semantics and makes Review depend on a label artifact.
- Close only renderer attempts: most Issue #3 failures occur before P7.

## Acceptance boundary

Automated acceptance covers session/config hashing, plain resume, zero production-artifact mutation on conflict, explicit Brief/Source revision, persistent phase-local revision, phase/Gate/provider currentness, stale M2 rejection, multi-finding proposal admission, semantic family/topology review and started/terminal Create operations.

At least one fresh cold-start workspace must still pass a controlled revision and produce candidate outputs before the implementation checkpoint closes. Real Microsoft PowerPoint whole-deck review remains mandatory for visual release and cannot be performed by this ADR.
