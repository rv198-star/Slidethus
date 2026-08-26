# Slidethus Repository Instructions

## Mission

Build Slidethus as a provider-neutral Agentic Skill for evidence-backed presentation engineering. Preserve the staged workflow and structured artifacts before adding visual spectacle.

## Read first

Before changing code or architecture, read in this order:

1. `docs/00-product-charter.md`
2. `docs/01-source-to-design-trace.md`
3. `docs/02-architecture.md`
4. `docs/03-workflow-state-machine.md`
5. `docs/04-artifact-contracts.md`
6. `docs/05-quality-system.md`
7. `TASKS.md`
8. The applicable ADRs under `docs/adr/`

For Skill behavior, also read `.agents/skills/slidethus/SKILL.md` and only the referenced workflow/reference files needed for the current task.

## Non-negotiable architecture rules

- Keep one primary orchestrator. Do not create role-play multi-agent chains by default.
- Use subagents only for bounded, independent, read-heavy work such as exploration, test analysis, or separate audits. Use one writer for overlapping code.
- Keep semantic artifacts independent from render backends.
- Never pass long unstructured prose between phases when a schema-backed artifact exists.
- Do not skip the page-planning layer between content and final design.
- Treat Bento Grid as one layout family, not a universal default.
- Keep model, search, image, chart, and render providers replaceable behind protocols.
- Never invent citations, evidence, source locations, or completed capabilities.
- Use root-cause fixes. Replace incorrect logic directly; do not accumulate compensating patches or double-negative rules.
- Architecture changes require an ADR update or a new ADR.

## Engineering rules

- Python target: 3.11+.
- Keep the deterministic core dependency-light.
- JSON artifacts must validate against Draft 2020-12 schemas in `schemas/`.
- IDs are stable and explicit: `SRC-*`, `EVD-*`, `SEC-*`, `S-*`, `BLK-*`, `REG-*`, `ISS-*`.
- Public functions need type hints and docstrings when behavior is not obvious.
- No network calls in unit tests.
- Do not add a production dependency without documenting why in the active execution plan.
- Preserve third-party source material verbatim under `source_material/source-preserved/`; place improvements elsewhere.

## Required checks

Run before considering a task complete:

```bash
python -m pytest
python scripts/validate_all.py
python scripts/audit_package.py
```

When Python source changes, also run:

```bash
python -m compileall -q src tests scripts
ruff check src tests scripts
```

## Definition of done

A change is done only when:

- the requested behavior is implemented;
- affected schemas, examples, docs, and tests agree;
- relevant gates have explicit pass/fail behavior;
- failure and degraded paths are covered;
- the diff has been reviewed for factual, architectural, and regression risks;
- no major or critical known issue is hidden behind a score.

## Work discipline

- Start complex work with an execution plan based on `PLANS.md`.
- Make small coherent changes and keep the tree runnable.
- Record decisions, assumptions, and remaining risks.
- Do not mark roadmap tasks complete because only interfaces or placeholders exist.
- Do not call a workflow an MVP unless every claimed action has a distinct, inspectable output and acceptance check. Serializing a planning artifact into another file format is not a new completed stage.
- When the user corrects a recurring project rule, update this file or the closest applicable nested `AGENTS.md`.
