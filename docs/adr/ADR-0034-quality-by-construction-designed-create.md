# ADR-0034 | Quality-by-construction Designed Create

- Status: Accepted for implementation after three independent audits; production proof pending
- Date: 2026-09-04
- Scope: Designed Host Create visual planning, calibration, full render and Office review

## Context

ADR-0031 introduced pre-layout `ArtDirectionSeed` and strict `taste-generated` prototype provenance. Issue #3 proved the direction can propagate through formal Specs, Layout, Visual System, a complete admitted IR and one Artifact Tool producer. YU7 also proved an auto formal path with early assets and continuous design reasoning can yield a user-accepted PowerPoint result.

A later cold-start employment showcase had five chart Blocks, three images, four tables and three diagrams, yet remained visually ordinary. Raw carrier count was not the root problem. The weak points were carrier fitness, visual hierarchy, semantic geometry, palette/typography maturity, executable grammar and whole-deck composition. Provenance, structural planning and deterministic no-finding results did not prove those qualities.

Three independent audits of the first ADR candidate all found the same Critical contradiction: current contracts compile one complete full-deck IR before any sample can be selected, while the candidate proposed P6/P7 expansion after calibration. That would either self-invalidate the calibration or recreate a custom/partial IR bypass.

## Decision

### 1. One complete IR precedes calibration

No new Project State phase is introduced. Reviewed/critical Designed Create follows:

```text
direction evidence + frozen Seed
  → complete full-deck representation Specs
  → complete full-deck Layout and semantic previews
  → complete executable Visual System and page designs
  → one frozen complete admitted IR
  → scope=sample render from that exact IR
  → Office review evidence and derived calibration decision
  → scope=full render from the identical IR/producer identity
  → whole-deck Office review
```

Calibration saves full rendering and whole-deck rework cost; it does not precede or replace full-deck P5/P6 design. Any post-calibration design, asset, compiler or producer change invalidates the authorization and requires a new calibration. Partial/custom IR is not introduced.

### 2. Risk requires evidence; approval mode controls human pauses

Project Brief remains authoritative for `approval_mode` and `quality_profile`. Workflow derives an immutable `VisualAdmissionPolicy` from the exact Brief hash and versioned deterministic policy. It records risk, reason codes, required evidence, approval authority and reviewer independence/capabilities. Providers cannot author the risk result.

`auto` never means “skip review.” Reviewed/critical auto is valid only with a Session-fixed, qualified, independent, Office-image-capable VisualReviewProvider. The provider publishes immutable evidence; workflow derives the decision. If the provider is missing or conflicts with the author identity, the operation stops for human input. Checkpoint/strict uses schema-backed human request/response. The workflow never silently changes risk or approval mode.

### 3. The ordinary pre-P5 step is Design Direction Prototype

After complete Outline and before P5, a native `Design Direction Prototype` covers the high-risk role/representation problems present in the deck, records bounded reference adoption/rejection and produces immutable direction evidence before freezing the Seed. `taste-generated` remains provenance, not approval. A cover-only prototype cannot authorize unexercised body roles.

`Art-direction Lab` retains its repository meaning: an isolated recovery experiment after a formally complete deck still misses the aesthetic bar. It does not become a normal alternate production path.

### 4. Artifact ownership is singular

- Outline owns narrative page role.
- ArtDirectionSeed owns pre-layout visual direction/carrier intent.
- Slide Specs own one discriminated representation and its semantic chart/table/diagram/image facts.
- Layout Plans reference those IDs and own only placement/view geometry, reading/focal order, ports, routing and label anchors.
- ArtDirectionPacket/Visual System own page-family, component and style grammar IDs.
- Renderer IR materializes and traces those decisions.
- VisualReferenceSet is approval evidence only; it owns no style, geometry or allowed renderer behavior.

This supersedes any interpretation that lets a family label, ReferenceSet or renderer invent semantic ownership.

### 5. Semantic planning evidence precedes G5B approval

Structural wireframes remain capacity/geometry diagnostics. Reviewed/critical work also requires a content-addressed semantic planning preview generated from frozen Seed/Specs/Layout and target capabilities. It shows chart orientation, table hierarchy, diagram topology, image crop/focal placeholders and visual weight.

Deterministic and qualitative planning conclusions are independently verifiable. Qualitative evidence binds the exact preview hash and reviewer identity. A deterministic no-finding result, raw JSON or equal placeholder boxes cannot satisfy qualitative planning admission.

This is an in-process planning admission mechanism, not ADR-0026 retrospective Stage AI Review. Implementation must update the workflow and quality documents to make that scope explicit.

### 6. P6 ends at a closed mechanical boundary

The Visual System contains only versioned grammar variants supported by the admitted producer and capability contract. Reviewed/critical compilation rejects unknown, unsupported or unconsumed decisions and disables generic semantic/style/diagram fallback. IR records decision-to-variant-to-slot/asset-to-element consumption.

Mutation-sensitive tests must prove that changing a material executable decision changes IR/output or produces an explicit unsupported failure. Metadata presence alone cannot satisfy G6.

### 7. Calibration reuses Host Candidate Receipt

Host Candidate Receipt remains the sole render-attempt authority. `scope=sample` is extended with the complete calibration dependency key, producer identity and Office refs. There is no second `VisualCalibrationRun` receipt.

The Session owns one pending calibration lifecycle:

```text
requested → render_started → sample_candidate_ready
  → office_pending → review_pending
  → approved | rework | blocked | failed
```

Sample rendering leaves Project State at `VISUAL_SYSTEM_READY`; it does not satisfy G7. Each transition binds the prior fact; resume continues the first missing step; orphan closure follows ADR-0033. Decision and ReferenceSet commit atomically or ReferenceSet is an idempotent derivation of the approved decision.

Every formal full-render entry uses one shared `RenderAdmissionPolicy`; a HostCreate-only check is insufficient.

### 8. The dependency key is conservative and complete

Initial calibration identity binds complete Brief/policy/Narrative/Outline hashes; direction review evidence, decision and adjudication hashes; Seed/Specs/Layout/preview review/Packet/Visual System/page designs hashes; selection policy and IDs; complete IR/compiler/schema/code hash; backend/adapter/Artifact Tool/capability identity; asset/font receipts; and Office application/build/profile/export settings. Full admission resolves and verifies the current direction refs even when the Seed itself does not reference the direction decision.

Any dependency change invalidates sample receipt, review, decision and ReferenceSet. Per-slide or per-family reuse is out of scope until a later ADR defines a sound dependency projection.

### 9. Review evidence is immutable; workflow derives approval

Reviewers receive real Office-rendered sample pages as their primary image inputs. They submit immutable findings, not an approval status. Finding identity is stable across severity changes and excludes severity itself. Workflow derives a decision only when coverage, reviewer policy/currentness and zero open Critical/Major all hold.

An admitted Critical/Major on the same page hash cannot disappear through omission, re-review, reviewer replacement or severity downgrade. An authorized immutable adjudication may record a factual false positive while preserving the original finding. A user waiver may record acceptance but cannot produce reviewed/critical `quality_approved`.

Earliest rework may be P4, Design Direction Prototype/Seed, P5A, P5B, P6 or P7. Direction acceptance never overrides a failed formal sample; capability conflict stops visibly.

### 10. ReferenceSet authorizes only the identical full render

The workflow derives a content-addressed VisualReferenceSet containing accepted Office page refs, coverage, receipt/decision and dependency hashes. It is evidence, not a design grammar.

After approval, full render must use the identical complete IR and producer identity tuple. New pages, roles, components, assets or any design mutation revoke authorization. Reviewed/critical work has no uncalibrated high-risk-role exception.

Identical sample pages may reuse local page-correctness observations, but the full candidate still requires currentness, adjacency/cadence and whole-deck Office review. P8 may revoke calibration based on full-deck context even when sample bytes did not change.

### 11. Compatibility is explicit

Semantic-breaking Specs, Layout, Visual System, IR, Session/Operation and Review changes use a new contract generation and synchronized packaged schemas. Host Candidate Receipt moves from existing 0.2.0 to additive 0.3.0 for dependency/producer/Office refs; historical 0.2.0 remains readable but cannot authorize this new path. If existing receipt field meanings change or the additions become globally required, implementation must use a breaking generation instead. Facts requiring design judgment are never backfilled with defaults. Mixed-version reviewed/critical work is rejected and must explicitly replan/migrate.

Controlled legacy/lightweight work may retain its declared path and is not automatically called degraded. Degraded status remains reserved for missing promised capability or deliverable.

### 12. The guarantee is fail-closed evidence, not universal beauty

This architecture guarantees that reviewed/critical work cannot be treated as quality-approved without current, same-path, Office-rendered evidence; complete role coverage; immutable review history; zero admitted open Critical/Major; identical sample/full IR/producer identity; and whole-deck Office review.

It cannot guarantee an infallible model/reviewer or universal taste. Missing evidence, assets, reviewer independence, producer capability or Office rendering produces a visible stop—not a false pass.

## Consequences

- Full P5/P6 design cost occurs before sample; savings come from preventing weak full rendering and all-page rework.
- Auto remains viable when independent evidence exists, preserving the proven YU7-style path without allowing self-review.
- Renderer authority shrinks while artifact/review contracts and provenance grow.
- Initial invalidation is deliberately conservative; optimization waits for evidence.
- Planning and calibration may stop more often when capabilities are honest rather than silently degraded.

## Rejected alternatives

- Partial/sample-only IR followed by design expansion: reintroduces the custom-path bypass or requires a separate fragment architecture.
- Mandatory human Gate for every high-risk deck: confuses review evidence with pause mode and discards a proven auto path.
- Reviewer-authored pass/severity overwrite: cannot preserve blocking history.
- Separate VisualCalibrationRun receipt: duplicates Host Candidate Receipt authority.
- Media quotas or industry templates: optimize metadata/counts rather than communicative fitness.
- ReferenceSet as style authority: creates a second Visual System.
- Renderer fallback for missing semantics: violates the mechanical boundary.
- Fixed four-page sample: role coverage, not page count, controls selection.

## Acceptance boundary

Three independent audits of the original candidate returned REWORK. After revision, all three reviewers independently returned `ACCEPT FOR IMPLEMENTATION`; the synthesis records zero open Critical/Major design findings.

Even after architecture acceptance, production capability remains unproven. Implementation acceptance requires exact Seed replay/resume regression, negative bypass controls, same-IR/sample/full identity, immutable review/adjudication behavior, shared render admission, real Office inputs, the locked historical matrix and a post-freeze holdout. Stable release remains blocked until those tests and real PowerPoint reviews pass.
