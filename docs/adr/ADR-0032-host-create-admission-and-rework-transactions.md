# ADR-0032 | Host Create admission and rework transactions

- Status: Accepted; real Office release acceptance pending
- Date: 2026-09-02

## Context

Three independent v0.9.0 Host Create runs reached valid intermediate artifacts but produced no deliverable candidate. The failures were not one bad font size. Planning, visual compilation and the Artifact Tool adapter used overlapping but different capacity and capability rules; Planning Review could name rework targets that the state machine could not reach; an upstream revision was validated against already-invalidated downstream bodies; and a started renderer process could terminate without a durable terminal fact.

Those mismatches leaked internal Region dimensions, font floors and adapter assumptions into the user workflow. Adding more exact layout instructions to the Skill would preserve the ownership error instead of fixing it.

## Decision

### 1. One deterministic text-fit contract

`text_capacity.py` owns font-floor-aware fitting, Office point-to-logical scaling, explicit renderer insets, line wrapping, line-height and qualification reserve. It returns a structured result containing the preferred and floor sizes, fitted size, line count, required/available height, applied padding, minimum height increase and a stable failure reason. Generic Office planning keeps conservative insets; the Artifact Tool profile uses zero insets because the admitted adapter explicitly emits zero text insets. A profile may not reserve padding that its renderer does not create.

Generated Layout uses the same contract and may make one bounded whitespace reallocation across a compatible stacked text layout. It never crosses approved font floors. G5B consumes the Region's admitted floor. Render compilation evaluates every text Region, and preflight publishes all failures before a backend starts. Backends consume the admitted size with auto-fit disabled; they do not invent a second fit policy.

### 2. Planning Review owns the rework-target vocabulary

The P0/P2/P3/P4/P5A/P5B target map is declared once in `state_machine.py`. Planning Review derives its targets from that map, and every later workflow phase can return to an earlier declared planning owner. Returning to the current owner is an idempotent no-op; forward movement still requires the normal Gate.

### 3. Upstream revision and downstream invalidation are one graph transaction

Artifact Runtime writes the new upstream version, rolls back the phase/Gates and marks dependent catalog artifacts `draft` in the same journaled transaction. A draft downstream artifact still has to pass its own Schema, hash and registry checks, but stale cross-artifact references are warnings until that artifact is rebuilt and approved. Approved/current artifacts retain error-level cross-reference enforcement. This permits stable-ID and page-signature changes to commit without exposing a temporary mixed graph as current.

`ArtDirectionSeed` also has a direct Host Create revision route. The request binds the superseded Seed reference and does not require a synthetic Outline change.

### 4. Target capability is admitted before Node

Host Seed and Slide Specs requests include the selected Artifact Tool contract: supported overflow strategies, qualification-caption requirement, raster asset cardinality/media types, editable diagram shape and explicit migration options. Preflight mirrors every deterministic adapter condition and aggregates it across the full deck.

`diagram` no longer means “bitmap”. It may be either one admitted PNG/JPEG asset or a backend-neutral editable node/edge object with normalized geometry. The adapter emits editable shapes, text and lines for the latter. Image and icon remain one-asset raster primitives on this adapter.

Artifact Tool tables do not use equal tracks blindly. The target contract derives content-weighted column widths, explicit cell margins and wrapped-line-demand row heights inside the admitted Region. Python preflight and the JavaScript adapter mirror the calculation; a table that cannot fit is a P5A/P5B blocker rather than an Office-visible overflow.

### 5. Every started render attempt closes with a receipt

Artifact Tool writes a schema-valid `render_started` receipt before creating its input or invoking Node. It atomically replaces that fact with `render_failed`, `render_timed_out` or `candidate_office_review_pending`. The receipt binds current semantic artifact references, Renderer IR, preflight, input/output hashes, adapter identity, stage, duration, exit/timeout state and bounded path-sanitized diagnostics. CLI blocked results point to the receipt.

Host request identity remains the hash of stage context and limits. Each valid response and proposal receives its own hash and immutable `received` snapshot, so a corrected response to the same request is distinguishable from a replay even when the final admitted artifact is unchanged.

### 6. One Artifact Tool runtime resolver

Doctor, preflight and rendering use the same resolver and validation. Resolution is per field in this order: explicit CLI/API argument, `RUNTIME_NODE` / `RUNTIME_NODE_MODULES`, then the admitted Codex bundled runtime location. Doctor reports the exact paths that rendering will use. No dependency is installed and no renderer fallback is selected implicitly.

## Consequences

- A readable font floor remains a hard contract; success is not manufactured by global shrinking.
- Preflight reports may contain multiple failures for one page because they expose independent repair obligations.
- Old draft bodies can remain inspectable while the current workflow graph is repaired, but they cannot satisfy a Gate or render lineage.
- Editable diagram geometry becomes part of semantic block content and remains backend-neutral normalized data; page placement remains owned by Layout Plans.
- A candidate receipt is operational evidence only. It does not satisfy G7, M5, Delivery or real Office visual acceptance.
- The optional Artifact Tool package remains host-owned and is neither installed nor redistributed by Slidethus.

## Rejected alternatives

- Lower every font floor or enable renderer auto-fit: hides planning overload and makes Office output nondeterministic.
- Add exact font sizes and pixel repairs to the Skill: moves deterministic geometry into prompt prose and recreates the mismatch.
- Let the adapter rasterize every diagram silently: violates the requested editability and changes design intent.
- Validate a new upstream artifact against stale downstream bodies as if they were current: makes legitimate graph repair impossible.
- Treat process exit text as sufficient diagnostics: leaves no durable, hash-bound recovery fact.

## Acceptance boundary

Automated acceptance covers contract equivalence, multi-finding preflight, all planning rework targets, upstream commit/rollback, Seed revision, response identity, target admission, runtime parity and started/failed/timed-out/success receipts. A copied real failure case now produces PPTX/PDF, opens without a repair dialog and has been inspected across all eight PowerPoint-rendered pages without geometry overflow. Its visual direction was rejected, so that artifact remains technical failure-reproduction evidence rather than a product aesthetic baseline. A separately isolated replay of the previously user-accepted YU7 Host Create case opened without repair and passed all twelve real PowerPoint pages without Critical/Major visual regression: eleven program-rendered pages were byte-identical and the only changed page improved table allocation. Issue #2 can therefore close on its stability scope; package publication remains a separate release transaction.
