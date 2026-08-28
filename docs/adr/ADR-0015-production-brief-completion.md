# ADR-0015｜Production Project Brief Completion and Minimum-question Intake

- Status: Accepted
- Date: 2026-08-27

## Context

M2 requires a resolved Project Brief before research and Evidence work, but the bootstrap Brief intentionally contains placeholders and one broad blocking question. A production presentation workflow cannot ask the user to complete a long questionnaire when the request and supplied materials already reveal purpose, audience, context, page count or desired action. It also cannot silently infer materially different intent or mutate Sources before discovering that the request itself is outside admitted bounds.

M3 therefore needs an intake boundary that is deterministic, idempotent, auditable and compatible with future reasoning providers without making user conversation history the only source of truth.

## Decision

### 1. Brief completion is a versioned semantic service

`BriefCompletionService` reads the current Project Brief and current Source inventory, admits explicit `BriefCompletionHints`, computes conservative request inferences and publishes a new Brief version through Artifact Runtime. It never edits the file directly.

The service records a `completion` fact containing:

- status: `resolved` or `needs_input`;
- input/context/result hashes;
- resolved and inferred field paths;
- generated question and assumption IDs;
- completion engine/version and timestamp.

Generated IDs use reserved high ranges (`Q-9xx`, `ASM-9xx`) so reruns replace their own facts without colliding with user-authored items.

### 2. Ask only material questions

The deterministic core asks only for missing fields that materially change the deck:

- purpose;
- desired outcome/action;
- primary audience;
- delivery context when it cannot be safely inferred.

The number of generated blocking questions is bounded by `PlanningLimits.max_blocking_questions`. Existing answered questions and explicit hints are never asked again. Safe defaults are recorded as assumptions instead of hidden behavior.

### 3. Conservative inference

Request parsing recognizes only explicit presentation signals such as audience phrases, decision/training context, requested page count and duration. It does not perform open-ended domain reasoning or invent business facts. Supplied Source content contributes only bounded structural context at this phase; factual use remains governed by M2 Evidence.

### 4. Complete input preflight before mutation

`validate_brief_completion_hints` validates all hints before Source or Brief mutation:

- request/scalar lengths;
- tuple type, item count, uniqueness and item lengths;
- admitted enums;
- finite duration and page-count bounds;
- complete `PlanningLimits`.

`M3ApplicationService` invokes this validation before Source preinspection. Invalid intake cannot leave a partially modified workspace.

### 5. G0 uses semantic completion, not placeholder absence alone

G0 requires:

- no open blocking questions;
- resolved purpose, outcome, audience and delivery context;
- a valid current completion fact when Production Brief completion has been used;
- consistent input/context/result hashes.

Legacy resolved Briefs remain valid for backward compatibility, but they do not count as Production M3 evidence in the repository Exit Gate.

## Consequences

- A concise user request can reach a reviewable Brief without a mandatory questionnaire.
- Known information is not repeatedly requested.
- Assumptions and unresolved decisions remain visible.
- Invalid or oversized hints fail before workspace mutation.
- Future model-assisted intake can propose hints, but the same deterministic admission and Brief Schema remain authoritative.
- M3 can stop honestly at `needs_input/P0` and resume after `m3 answer` without discarding Source inventory.
