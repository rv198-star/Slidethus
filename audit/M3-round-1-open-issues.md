# M3 Review Round A — Open Issue Mining

## Review rule

This review was performed without scores. It inspected the M3 diff as a repository-wide Production planning boundary rather than accepting passing happy-path tests as completion. Findings were assigned to the earliest responsible layer and fixed directly; no waiver was used.

## Initial result

```text
Critical: 0
Major:   14
Minor:    5
```

## Major findings and root fixes

### M3-A-MAJ-001 — M3 Application Report package mirror was absent

- Risk: installed-wheel validation could not load the runtime Report Schema even though repository execution worked.
- Root fix: added byte-identical `src/slidethus/_schemas/m3_application_report.schema.json` and mirror checks.

### M3-A-MAJ-002 — Planning limits were fragmented and incompletely preflighted

- Risk: Narrative, Outline, Specs, Layout and Brief accepted different limit ranges; Outline had no complete validation. Invalid nested limits could be discovered only after earlier semantic writes.
- Root fix: introduced `planning_limits.validate_planning_limits`, applied it to every M3 service and preflighted Planning/M2 limits in `M3ApplicationService` before mutation.

### M3-A-MAJ-003 — Invalid/oversized Brief hints could mutate Source inventory first

- Risk: M3 pre-inspected Sources before discovering invalid request text, audience arrays, duration or enum values.
- Root fix: exposed complete `validate_brief_completion_hints`, aligned Report Schema bounds and invoked it before Source preinspection.

### M3-A-MAJ-004 — Provider payload budget covered content only

- Risk: warnings/assumptions could bypass `max_provider_payload_bytes` or contain unbounded/non-string values.
- Root fix: `admit_planning_proposal` validates and normalizes the complete proposal, message counts/lengths and serialized bytes for every planning artifact.

### M3-A-MAJ-005 — Planning Change Report could not independently recompute its request

- Risk: the report persisted only an opaque request hash; operation payload, idempotency key and limits were absent.
- Root fix: Change Reports now persist and validate raw operation payload, reason, idempotency key and complete PlanningLimits; request hash and `PCH-*` are recomputed.

### M3-A-MAJ-006 — Sticky-note operation policy was absent from identity

- Risk: an operation admitted under one limit policy could be silently reused under another. Reusing the same idempotency key with changed policy could create ambiguous history.
- Root fix: PlanningLimits enter the Change request hash. A key already bound to a different payload/policy is an explicit conflict.

### M3-A-MAJ-007 — Explicit Change requests could bypass resource budgets

- Risk: large insert/update payloads or idempotency keys could enter the Report path independently of provider limits.
- Root fix: the complete operation request is JSON-validated and bounded before Outline mutation; keys are limited to 1–512 characters.

### M3-A-MAJ-008 — Change output lineage was trusted indirectly

- Risk: a forged Report and arbitrary Outline version could satisfy basic references without proving that the controlled sticky-note service produced it.
- Root fix: validation recomputes the internal operation provider, policy/limits, proposal hash, timestamp and `operations_applied`/Change Report relation.

### M3-A-MAJ-009 — Planning Repair identity omitted limits and provider

- Risk: a repair could reuse results generated under a different budget/provider and could not prove which provider rebuilt Specs/Layout.
- Root fix: `PRP-*` identity and Report now bind PlanningLimits and frozen provider identity; regenerated artifact lineage must match both. M3 Report validation cross-checks them against application config.

### M3-A-MAJ-010 — Repair did not inherit M3 Application limits

- Risk: initial planning could use strict limits while automatic regeneration silently reverted to defaults.
- Root fix: Repair accepts/validates limits, passes them into Outline changes, Specs and Layout, and records them in the Report.

### M3-A-MAJ-011 — Rehashed M3 Reports could forge provider, Sources or planning level

- Risk: self-consistent hash/filename changes could alter provider identity, requested Source facts or lower the claimed planning level.
- Root fix: M3 validation independently checks provider lineage, Source Ledger and referenced M2 reports, exact artifact set, Project State phase, Gate set and planning level.

### M3-A-MAJ-012 — Final Planning Review was not required to bind final artifacts

- Risk: a passing older Review could be combined with newer Outline/Specs/Layout in a ready Application Report.
- Root fix: ready Reports require a passing Review whose six semantic input refs exactly match the final bound planning artifacts.

### M3-A-MAJ-013 — Repair and Artifact Runtime failures could escape without an Application fact

- Risk: a valid partial transaction followed by a regeneration conflict/provider failure raised directly, leaving no integrated result.
- Root fix: M3 converts admitted M2/Planning/Artifact Runtime domain failures into failed reports at the current safe phase. Automatic repair failure is checkpointed as `planning_repair_failed`; unexpected programming errors still propagate.

### M3-A-MAJ-014 — M3 Report did not recompute repair policy/count/action relations

- Risk: repair outputs could be attached when `auto_repair=false`, exceed `max_repair_passes`, use blocked repairs in a ready report or disagree with action/M2 references.
- Root fix: Report validation now cross-checks config, action stages, M2 IDs, repair count/status/limits/provider, Review and wireframe coverage.

## Minor findings and fixes

### M3-A-MIN-001 — Local-operation Outline lineage was initially treated as provider drift

The first provider-hardening pass incorrectly rejected legitimate Outline versions produced by `OutlineChangeService`. Validation now permits the internal provider only when every `operations_applied` entry has a verified Change Report.

### M3-A-MIN-002 — Blocked Source-budget reports were initially rejected by the validator

A blocked report must be able to record the over-budget request. Budget conformance is enforced for ready/rework-capable states; blocked/failed reports retain the factual violation.

### M3-A-MIN-003 — M3 execution-plan statuses lagged implementation

The plan still showed M3.1 in progress after M3.1–M3.6 and the Application/Repair implementation existed. Final status is synchronized only after the Exit Gate.

### M3-A-MIN-004 — Architecture/compatibility documents lacked the Production M3 boundary

ADRs 0015–0018 and architecture, artifact, quality, capability, roadmap and host compatibility documentation were added/updated.

### M3-A-MIN-005 — M3 verification was not persistent

A repository-level validator, negative-control tests, Makefile target and package-audit invocation were added so future changes cannot preserve only documentation claims.

## Verification added during root fixes

The new or strengthened tests cover:

- invalid Planning/M2 limits and Brief hints before mutation;
- complete provider proposal budget;
- Change request budget and idempotency-policy conflict;
- Repair limit/provider identity and idempotent reuse;
- rehashed provider/Source/level report forgery;
- M2 and Artifact Runtime failure checkpointing;
- automatic repair failure after a valid partial transaction;
- final Review and wireframe/current-state binding;
- CLI run/answer/list/show/gate behavior.

## Round A disposition

- Open Critical: 0.
- Open Major: 0.
- Open Minor blocking M3 Exit: 0.
- Waivers: none.

Round B is permitted only after full Python 3.11/3.12, workspace, M2 regression, M3 Exit, Package Audit and diff checks pass.
