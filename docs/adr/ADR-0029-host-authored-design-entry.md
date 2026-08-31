# ADR-0029 | Host-authored Create entry

- Status: Accepted for implementation; visual acceptance pending
- Date: 2026-08-31

## Decision

The host Agent owns reasoning and art direction. Deterministic services admit proposals and execute approved artifacts; they do not impersonate reasoning. The bundled Taste resource remains unchanged. A host may use it for a native visual prototype, but merely reading it or translating fixed tokens is not “Taste-generated”.

Use a file-backed bridge over the existing PlanningProvider and ArtDirectionProvider protocols. Each request includes complete bounded stage context and a content hash. Responses bind that hash. No model SDK, role chain, new policy DSL, or industry-specific branch is introduced.

Keep authority singular: Slide Specs own content/evidence/media choice, Layout Plans own block geometry, Visual System owns explicit page appearance. The IR compiles these without applying baseline family decorations to authored pages. Unknown or incomplete authored geometry/appearance fails rather than falling back.

The host Create entry uses one Artifact Tool IR adapter for both selected-page samples and full candidates. Artifact Tool is optional host capability, not a core/redistributed dependency. Absence is reported; never silently switch producer. Legacy deterministic/multi-backend execution remains an explicitly selected engineering baseline, not the default designed Create path.

An exported candidate is not a release. Its receipt records actual output hashes, source IR and selected slide IDs, with Office review pending. It does not satisfy the existing multi-backend G7 contract or fabricate M5/Delivery state. Office acceptance and release integration remain explicit subsequent work; old review evidence cannot approve a changed file.

## Scope and consequences

This narrows ADR-0016’s “production-capable baseline” claim: that baseline is deterministic engineering coverage, not general visual reasoning. It supplements ADR-0019 with an explicit candidate-rendering entry, without spoofing its three required backend runs. It preserves ADR-0027’s real Office release boundary and ADR-0028’s provider-neutral packet and pinned Taste provenance.

No hotel/fashion/technology palette or fixed sample count defines success. Automated tests cover propagation and failure behavior. User-led new-case acceptance and complete replay-package archival are deferred, not silently counted as done.
