# ADR-0030｜Modular Skill Suite, Single Orchestrator

- Status: Accepted
- Date: 2026-08-31

## Context

The user needs one entry that can finish a presentation request, plus reusable phase skills for bounded work. A monolithic instruction file conflates routing, specialist responsibilities and runtime details. Splitting by industry or visual style would encode local preferences and duplicate the pipeline.

## Decision

1. `using-slidethus` is the primary routing and end-to-end orchestration skill. It executes the requested workflow, not merely recommends another skill. Existing user checkpoints, permissions and capability boundaries remain authoritative.
2. Seven phase skills own existing boundaries: brief (P0), research (P1/P2), story (P3/P4), plan (P5A/P5B), design (P6), render (P7), review (P8/P9). Direct invocation stops at its requested output. Missing prerequisites do not authorize an unrequested full deck.
3. One host Agent reads the necessary phase skills in sequence. These are instruction modules, not separate agents, CLI executors, truth stores or state machines. Six existing workflows and existing schema-backed artifacts remain canonical.
4. `slidethus` remains a compatibility entry and owns the existing shared references/workflows/Taste resource/render script. Cross-skill references are relative and require installation of the complete suite. Third-party provider files remain unchanged.
5. Distribution uses an explicit skill allowlist, never arbitrary sibling-directory discovery. Repo, Plugin and new Wheel layouts preserve sibling skill directories. `skill_source_root()` and `materialize_skill()` retain their legacy return value; the installed-share resolver can still locate the old single-skill location. An incomplete suite cannot be installed or bundled as a complete one.
6. Installation preflights all existing skill targets before copying missing directories. Matching installs are idempotent; modified or symlinked destinations are refused rather than overwritten. Automatic upgrade/merge of user skills is not introduced.
7. No new semantic schema, production dependency, render backend, theme, fixed media quota or release claim is introduced. Full-deck visual rhythm and representative sampling are phase judgment responsibilities, not industry presets or new scoring gates.

This refines ADR-0023's single-tree packaging into a complete suite. It does not supersede ADR-0021 workflow ownership, ADR-0026 retrospective review, ADR-0027 Office release evidence, or ADR-0029 host-authored Create.

## Consequences and limits

- One-shot mode proceeds through all available required phases, including targeted research rework. It pauses only at requested approvals, scope-changing decisions or genuine blockers; it never fabricates missing capabilities.
- Host candidate receipts still do not satisfy legacy G7/M5 or release integration. New skill names do not turn missing provider capabilities into completed functionality.
- Installed-skill upgrades remain explicit: preserve existing customizations or use a clean destination.
- Packaging tests can verify discoverability, link closure, hashes and mutation safety. Agent interpretation and full PPT aesthetics still require execution/acceptance evidence, not string-matching tests.
