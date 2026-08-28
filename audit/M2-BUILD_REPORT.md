# M2 Build Report — Ingestion, Research, Evidence Production Boundary

## Milestone

**M2 — Ingestion, Research, Evidence**

- Date: 2026-08-27
- Result: PASS
- Critical open issues: 0
- Major open issues: 0
- Waivers: 0
- Next milestone: M3 Narrative and Planning ProductionImpl

## What M2 completed

### M2.1 — Ingestion Core

- deterministic format detection and Parser Registry;
- stable Source/Chunk/locator/content-hash identity;
- immutable create-if-absent Source Snapshots;
- Source Ledger parser/format/limit/risk lineage;
- interruption recovery and idempotent ingestion;
- Markdown/TXT Production adapter.

### M2.2 — Multi-format Source Adapters

- HTML, PDF, DOCX, PPTX, CSV/TSV, XLSX and common raster-image metadata;
- native page/paragraph/table/slide/shape/sheet/cell locators;
- OOXML ZIP preflight, decompression limits, duplicate/path/symlink/macro/external-relation handling;
- formula/active-content/embedded-object isolation;
- truthful `parsed/partial/unsupported/capability failure` behavior.

### M2.3 — Research Planning and Runtime

- deterministic orientation and current-outline targeted Research Plans;
- provider-neutral `ResearchProvider` contract;
- stable Plan/Run/Query/Task/Result identity;
- frozen provider identity per Runtime;
- resumable checkpointed Runs;
- immutable query cache, TTL, generation invalidation and offline blocking;
- bounded query/result/title/summary/metadata resources;
- Result remains separate from Source and Evidence.

### M2.4 — Evidence Engine

- conservative `EvidenceCandidate` contract and exact claim identity;
- Research Result → materializer-owned partial Web Source;
- stable `EVD-*`, exact dedupe and persisted Candidate bindings;
- Source/locator/Chunk/hash plus Research Run/Result lineage;
- conflict, authority, freshness and use-policy adjudication;
- high-risk Source/Research summary enforcement at the Engine boundary;
- explicit high-risk override remains provisional/qualified;
- stale/legacy Evidence reconciliation and semantic Research-cycle completion.

### M2.5 — Block Evidence Binding, Gap and Rework

- explicit/conservative `evidence_requirement` and qualification contracts;
- current Outline/Slide Spec block-level Evidence validation;
- unknown/unusable/unqualified and slide-to-block coverage checks;
- immutable content-addressed Evidence Gap Reports;
- deterministic targeted-query handoff to M2.3;
- gap-free user-material targeted completion;
- optimistic `OUTLINE_READY/SLIDE_SPECS_READY → EVIDENCE_READY` rework with Decision Log lineage;
- current G5A recomputation.

### M2.6 — Application, Capability and Security Boundary

- one `M2ApplicationService` over the completed domain services;
- local D3, approved provider D0, formal rework D4 and blocked D5;
- provider capability separated from external-disclosure approval;
- default high-risk Source exclusion, including old Evidence and provider summaries;
- requested/current/final Source and Research budgets;
- Brief/provider drift detection and current G1/G2/G3/G4/G5A revalidation;
- no Narrative/Outline/Slide Spec generation or silent editing;
- content-addressed M2 Application Reports with full config/security facts;
- bound Project State/artifact history, immutable Research Run snapshots/cache lineage and admitted runtime paths;
- `m2 run/list/show/gate` CLI.

### M2.7 — Repository-wide Exit Gate

- deterministic `scripts/validate_m2_exit.py`;
- positive and negative validator controls;
- Package Audit and `make verify` persistence;
- cross-module direct-service, high-risk, concurrency, history, path and budget audit;
- synchronized TASKS, roadmap, README, Skill, Codex handoff and master plan;
- final two-round M2-wide review.

## Key cross-module root fixes

M2.7 found and fixed issues that individual submodule reviews could not prove alone:

1. high-risk Source protection moved from only the application layer into Evidence Engine direct Source/Research paths;
2. Research summaries now create Source-risk records;
3. old high-risk Evidence no longer grants permanent default application permission;
4. workspace validation enforces high-risk qualification, while `reconcile_current_evidence` supplies a repair path;
5. Research Runtime freezes provider identity so Run/cache lineage cannot split;
6. Application Reports archive immutable Research Run facts and validate cache lineage;
7. report config/security/budget/Source/Evidence facts are recomputable;
8. Gap/Run/Cache paths are constrained to workspace roots;
9. failed Research integration still reports every Run/Source side effect;
10. Brief/provider concurrency and post-Research final budgets fail closed;
11. repository-level status, package evidence and verification are persistently aligned.

Detailed findings: `audit/M2.7-round-1-open-issues.md`.

## Public operational surfaces

```bash
slidethus source ingest <workspace> <file>
slidethus source show <workspace> SRC-001

slidethus research plan <workspace> orientation|targeted
slidethus research list <workspace>
slidethus research show <workspace> RRN-XXXXXXXXXXXXXXXX
slidethus research invalidate <workspace> RRN-XXXXXXXXXXXXXXXX --reason "..."

slidethus evidence source <workspace> SRC-001
slidethus evidence research <workspace> RRN-XXXXXXXXXXXXXXXX
slidethus evidence reconcile <workspace>
slidethus evidence gaps <workspace>
slidethus evidence targeted-plan <workspace>
slidethus evidence complete-user-targeted <workspace>
slidethus evidence rework <workspace> --reason "..."

slidethus m2 run <workspace> [--source <file> ...]
slidethus m2 list <workspace>
slidethus m2 show <workspace> M2R-XXXXXXXXXXXXXXXX
slidethus m2 gate <workspace>
```

The CLI intentionally contains no online ResearchProvider or credential path.

## Verification

The final repository state is validated under both Python 3.11 and Python 3.12:

```text
compileall: PASS
Ruff: PASS
pytest: 190 passed
validate_all.py: PASS
validate_m2_exit.py: PASS
```

Package/repository:

```text
audit_package.py: PASS — 20/20 checks; 286 files hashed
git diff --check: PASS
```

The generated evidence is recorded in `audit/automated-audit.json`, `audit/automated-audit.md` and `audit/manifest.sha256`.

## Capability boundary retained

M2 does **not** provide:

- a bundled production Web-search vendor;
- unrestricted external disclosure;
- general LLM claim extraction, semantic equivalence or truth verification;
- OCR/image semantic understanding/audio-video interpretation/formula calculation for unsupported coverage;
- Production Narrative/Outline/Slide Spec/Layout generation;
- final SVG/PptxGenJS/Hybrid rendering;
- visual-model review and repair;
- a production-ready end-to-end PPT product.

MVP Narrative/Planning/Rendering implementations remain MinimalImpl and are not relabeled by this milestone.

## Final decision

**M2 Exit Gate: PASS.**

The Source → Research → Evidence → Block Binding → Application boundary is now a versioned, traceable, recoverable, provider-neutral and fail-closed ProductionImpl. M3 may build Narrative and Planning ProductionImpl on this frozen boundary; it must not recreate M2 with raw prose, ad-hoc search state or direct unadjudicated page claims.
