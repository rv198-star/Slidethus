# ADR-0006｜Journaled Artifact Runtime

- Status: Accepted
- Date: 2026-08-26

## Context

M1 requires artifact and project-state updates to behave as one recoverable operation. A single atomic rename protects one file, but it cannot make an artifact file, its registry entry, Gate history, and phase state change atomically together. Silent overwrite would also destroy manual edits or another process's update.

## Decision

Use one `ArtifactRuntime` as the only supported writer for registered artifacts.

- Every write requires an expected artifact version and verifies the registered content hash.
- Every published version has stable registry metadata and an immutable prior-version snapshot.
- Multi-file changes first persist a journal under `.slidethus/transactions/`, then atomically replace individual files.
- A completed journal is archived; an interrupted journal is deterministically rolled back before further writes.
- A workspace lock serializes registry and Gate state writes.
- Schema migrations are explicit registered functions. They never change the meaning of an old artifact silently and retain the pre-migration version.
- Gate history is a schema-backed artifact; `project_state.completed_gates` is only the latest phase-control summary.

## Consequences

- Crashes between artifact and state writes are recoverable.
- Manual edits and concurrent writers fail with an explicit optimistic-lock conflict.
- Workspace-local history costs additional disk space but remains inspectable and provider-neutral.
- Render, research, model, and image adapters remain outside the runtime.
- All future application services must use the runtime instead of writing registered JSON files directly.
