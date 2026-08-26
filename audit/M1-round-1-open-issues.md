# M1 Review Round A — Open Issue Mining

## Scope

Review the Artifact Runtime without scores and look only for concrete correctness, recovery, state, Gate, security, and regression defects. Evidence came from source inspection, failure injection, Schema validation, CLI execution, and the full M0 regression suite.

## Findings

### Major — archived journal redaction happened before the move

- Location: `src/slidethus/artifact_runtime.py`, journal archive path.
- Problem: the pending journal was replaced with a redacted summary before moving it to the archive. If the move failed, the only pending recovery file no longer contained before/after payloads.
- Root fix: move the full journal out of the pending directory first, then redact the archived copy.
- Verification: partial-write, fully-written-valid, and fully-written-invalid crash tests all recover deterministically.

### Major — upstream writes had no supported dependency invalidation route

- Location: artifact publish transaction and project state.
- Problem: changing Evidence after G2 would make Gate inputs stale while leaving the project at a later phase. Full validation correctly rejected the state, but the runtime offered no root-phase rollback path.
- Root fix: each domain artifact now maps to its producing Gate and predecessor phase. A write atomically removes that Gate and all downstream summaries, rolls the phase back when required, and marks downstream registry entries draft.
- Verification: changing Evidence in the M1 example rolls `VISUAL_SYSTEM_READY` back to `SOURCES_READY`, preserves only G0/G1 summaries, retains Gate history, and leaves the workspace valid.

### Major — unrelated Major issues could authorize a deterministic integrity waiver

- Location: Gate waiver policy.
- Problem: a caller could cite an open Major Quality issue while the actual Gate failure was a missing/invalid artifact or incomplete render.
- Root fix: deterministic validation, missing-input, incomplete-render, and equivalent integrity failures are classified Critical and cannot be waived. Only explicit open Major issue refs with an approver and reason use the waiver path; any open Critical issue blocks every waiver.
- Verification: Critical waiver rejection and explicit Major G8 waiver are covered by tests.

### Major — failed Gate evaluations could not always be persisted

- Location: `record_gate` transaction.
- Problem: replacing a previously passing phase Gate with a failing summary could make the current phase invalid, causing the transaction validator to roll back the failure record itself.
- Root fix: a failed/blocked Gate record is persisted while project state rolls back to that Gate's predecessor phase and removes later Gate summaries.
- Verification: the example persists a failing G7 record without advancing or leaving an invalid workspace.

### Minor — read operations released the workspace lock before reading

- Location: artifact list/show/validate.
- Problem: recovery ran under the lock, but the subsequent read did not. A writer could begin a transaction in the gap.
- Root fix: recovery and the complete read/validation now share one workspace lock.
- Verification: all API/CLI and concurrency-sensitive optimistic-lock tests pass.

## Regression checks

- No source-preserved material changed.
- No provider SDK or renderer dependency entered the domain/runtime layer.
- Schema mirror remains byte-identical.
- Existing G0–G6 behavior and G7 negative control remain intact.

## Result

All identified Critical/Major issues are fixed. Round B may proceed after the complete verification suite passes again.
