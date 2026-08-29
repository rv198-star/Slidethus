# ADR-0022｜Workflow Operational Controls

- Status: Accepted
- Date: 2026-08-29

## Context

M6.1 established one Product Workflow boundary for Create、Rebuild、Improve、Audit、Revise and Extract Style. Those workflows can now reuse the frozen M2–M5 Production boundaries, but a product entry point also needs operational facts that survive retries, enforce resource limits, prevent concurrent mutation and explain cache reuse.

The operational layer must not become another semantic state machine. It may control whether and how a workflow attempt executes, but it cannot redefine Source/Evidence/Planning/Render/Review truth.

## Decision

### 1. One exclusive workspace lease per mutating workflow attempt

Every workflow run acquires one non-blocking workspace-level file lease before cache admission, recovery or workflow mutation. A second workflow cannot mutate the same workspace concurrently.

The lease is process-scoped and operational; it is not persisted into Project State as semantic truth.

### 2. Each execution attempt has immutable structured events

Each admitted attempt receives one `WAT-*` identity and publishes immutable `WEV-*` events under `.slidethus/workflows/events/`.

Normal lifecycle:

```text
started → completed | blocked | failed | cache_hit
```

If the previous process terminated after publishing `started` but before a terminal event, the next process may recover it only after acquiring the exclusive lease. It publishes one `recovered` terminal event before starting a new attempt.

### 3. Recovery does not weaken Create/Rebuild admission

Ordinary Create/Rebuild still require a new or stage-0 workspace. A non-stage-0 resume is admitted only when the current lease holder has just recovered an orphan attempt with the same workflow, request hash and execution signature.

This distinguishes process recovery from an unrelated request to overwrite or reuse an existing project.

### 4. Workflow Operation Reports are immutable operational facts

Each terminal attempt publishes a content-addressed `WOP-*` report under `.slidethus/workflows/operations/` containing:

- request/execution identity;
- attempt identity;
- cache miss/hit;
- wall time;
- input and slide-update metrics;
- provider-cost measurement state;
- admitted operational limits;
- lease state;
- linked Workflow Application Report;
- explicit blockers.

WOP validation recomputes its identity and cross-checks workflow/request/status and action/output/change counts against the bound WFR. It also verifies the corresponding started and terminal events.

### 5. Cache reuse is policy-bound, validated and current

A Workflow Application Report may be reused only when:

- its WOP and WEV lineage is valid;
- request hash and execution signature match;
- the operation age is within `max_cache_age_seconds`;
- `artifacts_after` still matches the current workspace graph;
- WFR outputs still exist and match their hashes.

`max_cache_age_seconds = 0` disables cache reuse.

Invalid operational history fails closed instead of influencing cache admission.

### 6. Budgets apply before user-visible work where possible

Operational limits include:

- total input bytes = source-file bytes + canonical structured request payload bytes;
- maximum target slide updates;
- maximum wall time;
- optional maximum external-provider cost;
- maximum cache age.

Static input/slide/cost-meter admission runs before workflow mutation. Wall-time and measured provider-cost budgets are checked at stage boundaries. Budget exhaustion produces a structured blocked WFR/WOP rather than a bare exception.

Provider cost remains host supplied through `WorkflowCostMeter`; Slidethus does not infer vendor billing from token guesses.

### 7. Historical operational facts are tamper-evident

Workflow reports, operations and events are workspace-validated runtime facts. Content drift, invalid refs or event/operation disagreement invalidates the workspace operational history and blocks subsequent workflow execution until reconciled.

## Consequences

- M6 workflows have a recoverable, inspectable operational control plane without creating a second semantic truth source.
- Cache reuse is explainable and cannot be driven by unvalidated mutable metadata.
- Concurrency and resource-policy failures become explicit product outcomes.
- A process interruption can be distinguished from a new user request and safely resumed where the frozen downstream services are idempotent/recoverable.
- Hosts that need real cost enforcement must supply a trustworthy cumulative `WorkflowCostMeter`.
