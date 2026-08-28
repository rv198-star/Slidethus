# 13｜Codex Compatibility

## 1. Discovery

Codex discovers the repository Skill at `.agents/skills/slidethus/SKILL.md`. The root `AGENTS.md` supplies persistent engineering rules; the Skill supplies presentation workflow behavior. `tests/test_skill_layout.py` and `scripts/audit_package.py` verify the discovery layout and frontmatter.

## 2. Local execution

- Python: 3.11 or newer.
- Development install: `python -m pip install -e '.[dev]'`.
- Runtime multi-format install: `python -m pip install -e '.[ingestion]'`.
- Repository tests use the `src` layout through `pyproject.toml`.
- Repository scripts bootstrap the local `src/` path, so the documented bare validation commands work before installation.
- Installed wheels use the packaged Schema mirror in `src/slidethus/_schemas/` and do not require a repository checkout.

## 3. Artifact Runtime behavior

Codex should use `slidethus artifact list/show/validate/migrate/recover` for runtime inspection. Registered artifact writes require an expected version; out-of-band edits produce an explicit conflict. POSIX `flock` and Windows `msvcrt.locking` serialize workspace writes. Transaction payloads exist only while recovery is possible; archived journal summaries contain paths and status, not artifact bodies.

## 4. Capability truthfulness

M2.1–M2.2 provide Production ingestion through `slidethus source ingest/show`: deterministic detection, Parser Registry selection, bounded resources, format-native Chunk/locator/hash, immutable snapshots, source-risk records, `parsed/partial` and Source Ledger lineage. Admitted formats are Markdown/TXT、HTML、PDF、DOCX、PPTX、CSV/TSV、XLSX and common raster-image metadata. Optional dependency absence is a capability failure; macro-enabled OOXML、encrypted PDF、legacy OLE、SVG and unknown families remain unsupported. Codex must never widen capability by routing them through the text parser.

M2.3 adds provider-neutral Research Planning/Runtime without bundling a production Web-search vendor: deterministic orientation/targeted plans, provider identity, resumable query tasks, immutable result cache, TTL/generation invalidation, offline blocking and `slidethus research plan/list/show/invalidate`.

M2.4 adds deterministic Production Evidence through `slidethus evidence source/research/show/reconcile`. Research Results first become materializer-owned `partial` Web Sources; raw summaries remain provisional and pass through Source-risk scanning. Claims use conservative exact identity, stable `EVD-*`, persisted Candidate bindings, Source/locator/Chunk/hash lineage, explicit conflict groups, authority/freshness decisions and fail-closed use policy. High-risk Source promotion requires an explicit override and remains qualified. Source updates may commit but invalidate G2 until re-adjudication. Codex must not bypass these contracts with raw search summaries or fuzzy claim merging.

M2.5 adds `slidethus evidence gaps/complete-targeted/target-plan/rework`. Gap Reports bind current artifact versions/hashes and check explicit/conservative slide/block requirements, qualification and current targeted-cycle lineage. A query suggestion is only a Research Plan input. Formal rework records a Decision and routes to `EVIDENCE_READY`; it does not edit page content.

M2.6 adds `slidethus m2 run/list/show/gate`. The CLI intentionally has no online provider. Python callers may inject `ResearchProvider`, but actual execution also requires external-disclosure approval. Provider identity is frozen for each Research Runtime; mutation blocks application acceptance. Missing research defaults to D5; explicit D3 is admitted only without freshness requirements. High-risk Sources are inventoried but excluded from automatic Evidence by default. Content-addressed M2 Reports bind full config/security facts, Project State/artifact history, immutable Research Run snapshots/cache lineage and admitted runtime paths. They are operational facts, not Delivery Manifests or proof that M3–M5 are complete.

**M2 Exit Gate: PASS（2026-08-27）.** The M2 boundary is frozen and reused by M3.

M3 adds `slidethus m3 run/answer/list/show/gate`. Brief completion records bounded questions/assumptions and resumes from answers. `PlanningProvider` remains protocol-driven; deterministic services admit the complete proposal, own stable `SEC-*`/`S-*`/`BLK-*`/`REG-*`, bind current Evidence and publish through Artifact Runtime. Sticky-note operations produce verified `PCH-*`; Planning Review/Repair produce `PRV-*`/`PRP-*`; M3 Application Reports bind M2 reports, final planning artifacts, wireframes, Review/Repair and Project State. The CLI ships a deterministic offline planning baseline and no model/search SDK.

**M3 Exit Gate: PASS（2026-08-27）. M4 Exit Gate: PASS（2026-08-28）.** Codex should begin M5 from the frozen M2/M3/M4 boundaries and must not recreate them with ad-hoc prose, page-local facts, renderer-owned planning state or review-owned rendering truth.

v0.4 adds a D3/E3 complete-action MVP: admitted user-source Chunks → evidence → planning artifacts/wireframes → layout diagnostics → debug PPTX/Office previews → design previews → final PPTX/Office previews → QA/delivery. Its Rendering path remains MinimalImpl and does not provide Production Final SVG, PptxGenJS/Hybrid rendering or M5 independent visual repair. A `partial` source exposes only its recorded text/metadata; a planning wireframe is not final visual design. Codex must not treat a planning artifact serialized as PPTX as a completed Production render stage.

The Python package owns PPTX generation through `python-pptx`. LibreOffice, Poppler and `fc-match` are optional host tools: when unavailable, the CLI preserves the output but G8/G9 do not pass. Temporary preview fonts come from the host and are never included in the deck or delivery.

## 5. Required verification

```bash
python -m pytest
python scripts/validate_all.py
python scripts/validate_m2_exit.py
python scripts/validate_m3_exit.py
python scripts/audit_package.py
python -m compileall -q src tests scripts
ruff check src tests scripts
```

The first three commands must also succeed from a clean checkout after development dependencies are installed.
