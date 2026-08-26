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

v0.2 provides deterministic artifact persistence, validation, Gate history, migration, recovery and planning wireframes. It does not provide production research/model/image adapters or final SVG/PPTX rendering. Codex must select a delivery level from the Skill capability matrix and declare degraded phases instead of claiming missing capabilities.

## 5. Required verification

```bash
python -m pytest
python scripts/validate_all.py
python scripts/audit_package.py
python -m compileall -q src tests scripts
ruff check src tests scripts
```

The first three commands must also succeed from a clean checkout after development dependencies are installed.
