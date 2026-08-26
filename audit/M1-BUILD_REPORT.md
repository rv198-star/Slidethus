# Slidethus v0.2.0 — M1 Build Report

## Outcome

M1 Artifact Runtime is complete and ready for public repository release. The package remains honest about its scope: M2 ingestion/research and M4 final rendering are not implemented.

## Delivered

- unified registry metadata with stable artifact IDs and schema/artifact version separation;
- optimistic locking, immutable artifact/project-state history and downstream Gate invalidation;
- journaled multi-file commits, fsynced atomic replace, cross-platform workspace locks and deterministic recovery;
- explicit `project_state 0.1.0 → 0.2.0` migration with retained pre-migration state;
- schema-backed Gate history, decision log and assumption log;
- persisted failed/blocked/pass/waived Gate outcomes and Critical/Major waiver enforcement;
- `artifact list/show/validate/migrate/recover` CLI;
- 52 tests including failure injection and M0 regression coverage;
- updated README, workflow contracts, compatibility guide, ADR and Skill references.

## Key decisions

- `.slidethus/` contains runtime history, pending journals and locks; active artifact paths remain stable.
- `project_state` uses `revision` and is not self-registered, avoiding an impossible self-hash.
- An upstream artifact write atomically rolls the project to the producing Gate's predecessor phase and invalidates downstream summaries.
- Archived transaction records are redacted summaries; recoverable pending journals retain payloads only until confirmation or rollback.

## Verification

All commands required by `AGENTS.md` pass. Detailed open-issue fixes and the final scorecard are in `M1-round-1-open-issues.md` and `M1-round-2-scorecard.md`.

## Remaining boundaries

- no production file-ingestion or research providers;
- no final SVG/PPTX renderer or Office round-trip validation;
- no visual-model review loop;
- no GUI, cloud service or multi-tenant runtime.

These are roadmap work, not hidden M1 defects.
