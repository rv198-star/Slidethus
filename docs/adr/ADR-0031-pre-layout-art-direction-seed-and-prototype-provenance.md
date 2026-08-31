# ADR-0031｜Pre-layout Art Direction Seed and Native-prototype Provenance

- Status: Accepted
- Date: 2026-08-31
- Scope: Host-authored Create / P5A–P6 visual-decision propagation

## Context

ADR-0028 made `ArtDirectionPacket` a frozen P6 input fact and bundled Taste as the default resource. The current default adapter is intentionally deterministic, however: it translates a fixed editorial token set and cannot prove that Taste drove a native visual prototype. Because P6 starts after Layout Planning, the final packet cannot cause P5A to select a legitimate image/chart/diagram carrier or cause P5B to reserve its Region.

That produces two distinct but easily conflated states: the package contains Taste, and a final deck happens to use restrained tokens; neither proves that a Taste-based visual direction was created or that it influenced the planned page.

## Decision

1. Introduce a schema-backed, immutable `ArtDirectionSeed` runtime fact before Slide Specs. It is content-addressed under `.slidethus/art-direction/seeds/` and binds the current Project Brief and Deck Outline. It does not add a user-editable state-machine phase.
2. The Seed may express only pre-layout visual decisions: design read/dials, per-slide visual carrier intent, image treatment, deck rhythm and prohibited patterns. It cannot own content, evidence, assets or geometry. Slide Specs remain the sole owner of semantic Blocks and Layout Plans remain the sole owner of Regions.
3. A Seed declares foundation provenance as exactly one of:
   - `resource-only`: a resource is available but no design reasoning is represented;
   - `taste-informed`: a provider translated applicable Taste principles, without a native visual prototype;
   - `taste-generated`: the provider used Taste to drive an inspectable workspace-local native prototype, whose medium, relative path and SHA-256 are frozen.
4. `taste-generated` requires a readable workspace-contained prototype with the declared hash. A resource hash, a written design read, or a CSS/PPTX file produced after the fact is insufficient. This status records the production path only: it does not certify palette coherence, composition quality, layout quality, or approval of the visual result. The prototype remains a design-lab input; it neither satisfies a PPTX release gate nor becomes a factual/evidence source.
5. Host-authored Create requests the Seed before P5A. It sends the frozen Seed to host reasoning for Slide Specs and Layout Plans, preserves its reference in Slide Specs, and requires the final `ArtDirectionPacket` to bind the same reference. A Host path that requests Taste-generated provenance pauses for an explicit response when it is missing or invalid; it never falls back to a deterministic generic direction.
6. A seed carrier marked `required` must be implemented by a semantic Block of the same visual carrier family in that slide's Slide Spec. This is an accountability check, not an image/chart quota. `optional` and `none` remain legitimate decisions; charts still require suitable evidence/data and images still require an admitted asset.
7. The bundled deterministic Taste adapter may emit `taste-informed`, never `taste-generated`. Existing explicit deterministic workflows retain their declared baseline behavior rather than being silently upgraded to Host design.

## Consequences

- Art direction can affect the earliest owning P5 decisions without giving a renderer or provider authority over semantic facts or geometry.
- An actual native visual prototype becomes auditable provenance rather than a screenshot-based side path.
- A final Packet/Visual System is stale when its pre-layout visual reasoning changes, even if its palette is unchanged.
- The design system can support different subjects and delivery contexts through provider proposals, not industry/keyword branches or a universal dark-tech theme.
- Human target-renderer review remains essential. This ADR establishes traceability and propagation, not an automatic beauty score or a proxy for palette and composition judgment.

## Non-goals

- No mandatory four-page sample, image quota, chart count, palette or layout family.
- No model vendor SDK, multi-agent chain, web UI/animation semantics or new rendering backend.
- No claim that an isolated prototype is an approved PowerPoint deliverable.
