# ADR-0026｜Stage AI Review and Systemic Repair Promotion

Status: Accepted
Date: 2026-08-29

## Context

The first real v1.0 preview trial exposed two classes of defects that the existing repository Exit checks did not surface:

1. normal business prose was over-classified as high-risk prompt injection and excluded from Evidence;
2. the deterministic planning baseline copied source-length prose into slide headlines and repeatedly selected the same simple two-region composition, which only became visible later as an M4 overflow failure.

The existing quality system has deterministic Planning Review in M3 and semantic/visual review in M5, but AI judgment is concentrated too late and is not explicitly organized by the responsibility of every production phase.

The project also has a strict root-fix discipline: fixes must replace the incorrect general logic, not add scenario-specific patches. A review system that immediately repairs every local observation would create exactly the patch accumulation the project wants to avoid.

## Decision

### 1. Finish one production attempt before any AI review begins

Stage AI Review is retrospective, not interleaved with production execution.

One Production Attempt first runs through the existing production chain until it either:

- completes normally; or
- reaches an existing deterministic hard blocker such as invalid evidence, unsafe input, unreadable geometry, missing required capability, or corrupt output.

AI Review does not create a new mid-pipeline Gate, does not interrupt a still-valid production attempt, and does not mutate any production artifact while the attempt is running.

Only after the attempt has terminated does P8 run independent stage lenses for:

- P0 Intake / Project Brief;
- P1 Source Reconstruction;
- P2 Evidence;
- P3 Narrative;
- P4 Deck Outline;
- P5A Slide Specifications;
- P5B Layout Planning;
- P6 Visual System;
- P7 Render / full-page output.

A stage lens reads the current facts owned by that phase and may reference downstream evidence only to explain impact. It does not become a second truth source for the phase.

Stage AI Review is a review-time meta-layer. It is not inserted as a new mutable state machine between every production stage. If the Production Attempt ended at an existing hard blocker before P7, Review runs over every artifact and failure fact that actually exists and records the missing downstream stages as impact, rather than repairing the blocker on the spot merely to continue the trial.

### 2. Stage reviewers only observe and record; they never alter the just-finished attempt

Each stage review performs Round-A-style open issue mining and records:

- exact artifact / slide / block / region location when available;
- severity;
- observed failure;
- impact;
- earliest responsible phase;
- a generalized failure-pattern hint;
- how a future fix could be verified.

Stage review does not score first, does not silently mutate production artifacts, and does not retroactively change the just-finished attempt.

All AI findings—including Critical findings—are accumulated for synthesis. Safety, validity, evidence and render hard stops remain the responsibility of the existing deterministic production contracts; an AI reviewer itself never stops or resumes production.

### 3. Final Review Synthesis is the first point where change is even considered

The synthesis step runs only after all applicable stage lenses have finished. It consumes the complete review set for that Production Attempt and groups findings by abstract failure pattern.

No framework change, provider-prompt change, rule addition, artifact repair or case-specific workaround is admitted before this synthesis is complete.

It separates:

- local defects that should remain case-local;
- systemic defects that indicate a reusable framework capability gap.

Only systemic defects are eligible for framework-level repair promotion.

### 4. Review-to-Rule Promotion Policy

Framework repair is intentionally conservative.

A finding may be promoted when:

- any Critical issue reveals a general contract/invariant failure;
- any Major issue reveals a general production capability failure;
- a Minor issue recurs across multiple slides, multiple artifacts, or multiple evaluation cases;
- a lower-severity issue clearly demonstrates an architectural contradiction or repeated provider failure mode.

Suggestions are not promoted by default.

A release-hardening round should promote only a small number of high-value systemic fixes. The objective is to protect the quality floor, not encode every reviewer preference.

### 5. Every promoted repair must be abstract and scenario-independent

Before a repair is admitted, it must pass an anti-overfit test:

> If the current topic, wording, slide IDs and business scenario are removed, does the repair still describe a valid general production rule?

If not, the repair remains case-local and must not enter framework logic.

Production rules must not match exact preview-case wording, topic terms, slide IDs, or one-off artifacts.

Tests may use concrete scenarios as regression evidence, but production behavior must be expressed as reusable invariants, provider contracts, quality lenses, or deterministic guards.

### 6. Attribute first, decide whether to change second, then repair at the earliest owning phase

Synthesis first establishes causal attribution across the whole attempt. A visible downstream symptom may therefore remain unfixed until the analysis determines whether its real owner is P1, P3, P4, P5A, P5B, P6 or P7.

Only promoted systemic fixes are applied, in a batch after attribution and synthesis, and routed to the earliest responsible phase.

Examples:

- source-risk false positive → P1 risk-classification semantics;
- copied evidence paragraph used as a headline → P4 headline responsibility / planning-provider contract;
- repeated two-region composition regardless of semantic relationship → P5B layout-family selection responsibility;
- weak visual hierarchy after correct layout semantics → P6;
- clipping/export/font corruption → P7.

After admitted repairs, the existing dependency invalidation/rebuild path regenerates downstream artifacts and the full review stack runs again.

### 7. Quality-floor rules are preferred over exhaustive style rules

The system should enforce a small number of strong invariants, for example:

- one slide has one recognizable core proposition;
- a headline is a synthesized proposition, not a copied evidence paragraph;
- layout family follows information relationship rather than a global default;
- a deck must not mechanically repeat one composition when semantics differ;
- blocking factual claims remain evidence-qualified;
- rendered output must remain readable and complete.

The framework should not attempt to enumerate all acceptable headline styles, all valid layouts, or all aesthetic preferences.

## Consequences

- M2–M4 production artifacts remain the only phase truth; stage reviews are immutable P8 review facts.
- M5/P8 becomes responsible for multi-lens stage review, synthesis, promotion and final regression rather than only end-state semantic/visual inspection.
- The first real preview case becomes regression evidence, not a template for production rules.
- v1.0 release is blocked until the Stage AI Review / synthesis mechanism is implemented and the preview case is rerun without scenario-specific production exceptions.

## Non-goals

- No per-stage autonomous repair loop.
- No requirement to eliminate every Minor/Suggestion.
- No large rule catalog that attempts to encode taste.
- No topic-specific prompt or exact-string production workaround.
