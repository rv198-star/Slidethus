# M3 Build Report — Narrative and Planning Production Boundary

## Objective

Replace the MVP planning layer with a provider-neutral, schema-backed Production planning system that can turn a resolved Brief and current M2 Evidence into an auditable Narrative, stable Deck Outline, Slide Specs, Layout Plans and planning wireframes without entering final visual rendering.

## Implemented production chain

```text
Project Brief completion
  → current M2 Source / Evidence boundary
  → Narrative Blueprint
  → Deck Outline / digital sticky notes
  → Slide Specs
  → current targeted Evidence completion
  → Layout Plans / wireframes
  → Planning Review
  → bounded local Repair / formal rework
  → M3 Application Report / workspace Gate
```

## Main capabilities

### Brief completion

- Minimum-question deterministic completion from explicit request/hints and existing workspace facts.
- Stable questions/assumptions and bounded materiality policy.
- Input/result hashes, idempotency, optimistic version checks and stricter G0 readiness.

### Narrative

- Central thesis, story arc/rationale, audience journey, proof strategy, objections, sections/transitions and call to action.
- Production planning lineage binds Brief/Evidence identity and provider/engine identity.
- G3 validates current Production lineage instead of artifact existence only.

### Deck Outline / digital sticky notes

- Stable `S-*` page identity and explicit active/excluded/frozen lifecycle.
- Insert, exclude, reorder, split, merge, freeze/unfreeze and update operations.
- Immutable `PCH-*` Planning Change Reports bind request payload, policy, limits, idempotency key and resulting Outline lineage.
- Changed semantics receive new IDs while retired page objects remain explainable history.

### Slide Specs

- Active Outline slides map one-to-one to specs and stable `BLK-*` content blocks.
- Factual blocks remain subsets of Outline Evidence and must carry M2 Evidence qualification when support is provisional/inference/assumption/stale/unknown/internal-only.
- Density/editability and current Outline/Evidence lineage are explicit.

### Layout Plans and planning wireframes

- Stable `REG-*` Region identity, one Block per Region, complete reading order, safe-area containment and collision/capacity checks.
- Layout family derives from semantic relationships; Bento is one option, not a default.
- Content-addressed deterministic SVG wireframes are planning outputs, not final visual design.
- G5B checks current Specs/Layout lineage and geometry rather than file existence only.

### Planning Review and Repair

- Content-addressed `PRV-*` Planning Review Reports cover Gate readiness, Narrative quality, duplicate/rhythm/timing, Slide density, Layout capacity/diversity and recovery/lineage dimensions.
- Every issue identifies earliest responsible phase and repairability.
- `PRP-*` Repair Reports bind source Review, limits/provider, operations, downstream invalidation and result Review.
- Automatic repair is bounded; assisted/manual issues route to the earliest admitted rework phase rather than being cosmetically patched downstream.

### Integrated M3 Application boundary

- `M3ApplicationService` is the single orchestrator for Brief → M2 → Planning → Review/Repair.
- CLI provides `m3 run/answer/list/show/gate`.
- Application Reports bind complete config/limits/provider identity, requested Sources, semantic artifact versions/hashes, M2 reports, Planning Review/Repair facts, final Project State/Gates and wireframes.
- needs-input, blocked, failed, ready and rework-required states remain explicit and independently verifiable.
- M3 generates or updates only planning artifacts. Visual System and render outputs remain M4+.

## Main files

- `src/slidethus/brief_completion.py`
- `src/slidethus/planning_limits.py`
- `src/slidethus/planning_lineage.py`
- `src/slidethus/planning_provider.py`
- `src/slidethus/planning_rules.py`
- `src/slidethus/planning_changes.py`
- `src/slidethus/planning_reviews.py`
- `src/slidethus/planning_repairs.py`
- `src/slidethus/layout_geometry.py`
- `src/slidethus/m3_application_reports.py`
- `src/slidethus/services/brief_completion.py`
- `src/slidethus/services/narrative.py`
- `src/slidethus/services/outline.py`
- `src/slidethus/services/outline_changes.py`
- `src/slidethus/services/slide_specs.py`
- `src/slidethus/services/layout.py`
- `src/slidethus/services/planning_review.py`
- `src/slidethus/services/planning_repair.py`
- `src/slidethus/services/m3_application.py`
- `scripts/validate_m3_exit.py`

Runtime Schemas:

- `schemas/m3_application_report.schema.json`
- `schemas/planning_change_report.schema.json`
- `schemas/planning_review_report.schema.json`
- `schemas/planning_repair_report.schema.json`

Architecture decisions:

- `docs/adr/ADR-0015-production-brief-completion.md`
- `docs/adr/ADR-0016-provider-neutral-production-planning-lineage.md`
- `docs/adr/ADR-0017-stable-sticky-notes-review-and-local-repair.md`
- `docs/adr/ADR-0018-m3-application-and-exit-boundary.md`

## Review outcome

Round A:

```text
Critical: 0
Major:   14
Minor:    5
```

All Critical/Major findings were root-fixed, all blocking Minors were cleared, and no waiver was used. Details: `audit/M3-round-1-open-issues.md`.

Round B records zero open Critical/Major and M3 Exit PASS. Details: `audit/M3-round-2-scorecard.md`.

## Verification

The final repository contains 255 collected tests. OCI imposes a 300-second per-command ceiling, so the dual-version suite was executed as complete non-overlapping file groups instead of one monolithic pytest invocation. All 255 tests passed under both Python 3.11 and Python 3.12.

Python 3.11:

```text
compileall: PASS
Ruff: PASS
250/250 non-M3-Exit tests: PASS
M3 Exit tests: 5/5 PASS
255/255 total tests: PASS
validate_all.py: PASS
M2 Exit: 12/12 PASS
```

Python 3.12:

```text
compileall: PASS
Ruff: PASS
250/250 non-M3-Exit tests: PASS
M3 Exit tests: 5/5 PASS
255/255 total tests: PASS
validate_all.py: PASS
M2 Exit: 12/12 PASS
```

Final repository checks:

```text
validate_m3_exit.py: 13/13 PASS
audit_package.py: 21/21 PASS; 332 files hashed
git diff --check: PASS
```

## Final Gate record

- Open Critical: 0.
- Open Major: 0.
- Waivers: 0.
- M2 Exit regression: PASS.
- **M3 Exit Gate: PASS.**
- Next milestone: **M4 Rendering Backends**.

## Capability boundary

M3 completion means Slidethus can finish and audit presentation structure, evidence binding and page planning without final visual design. It does not claim:

- a bundled LLM or online search provider;
- model-level factual truth verification;
- Production final SVG rendering;
- PptxGenJS Native or Hybrid rendering;
- final visual assets or visual-system quality;
- visual-model review and M5 repair;
- a production-ready end-to-end PPT product.
