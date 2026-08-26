# 13｜Codex Compatibility

## 1. Discovery

Codex discovers the repository Skill at `.agents/skills/slidethus/SKILL.md`. The root `AGENTS.md` supplies persistent engineering rules; the Skill supplies presentation workflow behavior. `tests/test_skill_layout.py` and `scripts/audit_package.py` verify the discovery layout and frontmatter.

## 2. Local execution

- Python: 3.11 or newer.
- Development install: `python -m pip install -e '.[dev]'`.
- Repository tests use the `src` layout through `pyproject.toml`.
- Repository scripts bootstrap the local `src/` path, so the documented bare validation commands work before installation.
- Installed wheels use the packaged Schema mirror in `src/slidethus/_schemas/` and do not require a repository checkout.

## 3. Artifact Runtime behavior

Codex should use `slidethus artifact list/show/validate/migrate/recover` for runtime inspection. Registered artifact writes require an expected version; out-of-band edits produce an explicit conflict. POSIX `flock` and Windows `msvcrt.locking` serialize workspace writes. Transaction payloads exist only while recovery is possible; archived journal summaries contain paths and status, not artifact bodies.

## 4. Capability truthfulness

v0.4 adds a D3/E3 complete-action MVP: Markdown/TXT → evidence → planning artifacts/wireframes → layout diagnostics → debug PPTX/Office previews → design previews → final PPTX/Office previews → QA/delivery. It remains a MinimalImpl and does not provide production research/model/image adapters, PptxGenJS/Hybrid rendering or automatic repair. Codex must not treat a planning artifact serialized as PPTX as a completed debug, design, or final-render stage.

The Python package owns PPTX generation through `python-pptx`. LibreOffice, Poppler and `fc-match` are optional host tools: when unavailable, the CLI preserves the output but G8/G9 do not pass. Temporary preview fonts come from the host and are never included in the deck or delivery.

## 5. Required verification

```bash
python -m pytest
python scripts/validate_all.py
python scripts/audit_package.py
python -m compileall -q src tests scripts
ruff check src tests scripts
```

The first three commands must also succeed from a clean checkout after development dependencies are installed.
