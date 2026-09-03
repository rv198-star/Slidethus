# Host-led Create entry

## Ownership and scope

The host performs research/reasoning/design. Slidethus owns IDs, admission, evidence rules, persistence, compilation and checks. Taste remains a pinned, replaceable design resource. A deterministic resource-to-token adapter is not a native Taste design run.

This entry produces inspectable candidates, not automatic release approval. Full archive/replay packaging and user-led new-case visual acceptance remain subsequent work. Never modify an accepted reference PPTX to test the entry.

## Invocation

```bash
slidethus create <workspace> --source <source.txt> --title "<title>" --request "<purpose, audience, outcome, length>"
```

The first invocation freezes a schema-backed Host Create Session in a new workspace. A populated legacy workspace without this Session is not silently adopted; use a new workspace until an explicit migration route exists. After answering any pending Host request, resume with only:

```bash
slidethus create <workspace>
```

Omitted title/request/Sources/limits reuse the persisted intent. Do not repeat the long command. Supplying a different value during ordinary resume fails before Project State, Brief, Source, Evidence or planning mutation; it is never interpreted as an informal revision.

Use explicit intent transactions when the user changes scope:

```bash
slidethus create <workspace> --revise-brief --request "<new purpose/audience/outcome>"
slidethus create <workspace> --revise-sources --source <new-or-updated-source>
slidethus create <workspace> --revise-stage slide_specs
```

Brief revision overlays only explicitly supplied Brief fields. Source revision adds or updates local Sources and re-fingerprints the complete retained set; omission never deletes a Source. A revision invocation cannot also render. A missing Brief answer may still use `slidethus m3 answer`; a missing research capability or evidence gap is not resolved by inventing host prose.

The result gives `pending.stage`, `request_path`, `request_hash` and `response_path`. Read the complete request. Write only the response at that path:

```json
{
  "schema_version": "0.1.0",
  "request_hash": "sha256:<exact request hash>",
  "stage": "<exact stage>",
  "proposal": {"content": {}, "warnings": [], "assumptions": []}
}
```

Requests bind context and limits. Old responses do not apply to changed context. A corrected proposal for an unchanged request must atomically replace the response file; Slidethus records separate response/proposal hashes under `received/`, so “same request, different response” remains visible. Envelope and stage pre-admission report all currently determinable findings in stable order; correct the complete set against the same pending request. Received response snapshots are records of submission, not proof of admission. The resulting formal artifact and its current Gate are authoritative. Do not copy default proposals from `DeterministicPlanningProvider` to satisfy a host request.

Every invocation returns `session_path`, `attempt_id` and `operation_path`. The operation closes as `host_input_required`, `rework_required`, `blocked`, `failed`, `design_ready`, render terminal or `candidate_office_review_pending`. Planning rework also returns `rework.target_phase`, the exact Planning Review path, open `PRI-*` issue IDs and allowed next actions. These operational facts do not satisfy deck Gates.

### Stage proposal shapes

| Stage | `proposal` body |
|---|---|
| narrative_blueprint | `content`: central_thesis, story_arc, story_rationale, proof_strategy, call_to_action, at least three ordered audience_journey stages, and sections; each section has title, purpose, key_questions, evidence_ids, transition, thesis, audience_shift, proof_strategy and slide_budget. Use existing Evidence, not new claims. |
| deck_outline | `content.slides`: section_index (zero-based), slide_type, headline, takeaway, purpose, audience_question, evidence_ids, evidence_requirement. Code assigns stable slide IDs. |
| art_direction_seed | No `content` wrapper: design_read, dials, foundation, direction, warnings, assumptions. Designed Create requires `foundation.kind: taste-generated` plus a workspace-local, hash-bound `prototype` (`html-css`, `svg` or image). `direction` supplies one ordered carrier for every active slide (`kind`, `required`/`optional`/`none`, `surface_treatment`, rationale), image treatment, deck rhythm, maximum consecutive `plain` surfaces and forbidden patterns. The request includes `target_backend_contract`; choose only a realizable required carrier or one of its explicit migration options. This is requested after Outline and before Slide Specs. |
| slide_specs | `content.slides`: current slide_id, content_blocks, visual_intent (relationship, non-empty bounded semantic `suggested_layout_families`, avoid), density_budget, speaker_notes, editability_intent. Blocks contain semantic_role, content_type, priority, content, claim_mode, evidence_ids, evidence_requirement, asset_refs, notes. Density must cover the submitted Blocks/content without exceeding request limits. The request repeats the target backend contract. An editable `diagram` uses `{nodes:[{id,label,x,y,w,h}], edges:[{from,to,label?}]}` with normalized 0..1 node geometry and no asset; a raster diagram uses one admitted PNG/JPEG. Code assigns stable Block IDs. |
| layout_plans | `content.plans`: current slide_id, semantic layout_family declared by the matching Slide Spec, rationale, regions. Each region has exactly block_id, x, y, w, h, z, align, valign, overflow_strategy. Array order is reading order. Optional `content.safe_area` has top/right/bottom/left. Canvas remains 1280×720. Code derives Region IDs, bindings and diagnostics. `custom` is not an escape hatch; repetition review uses observable geometry rather than family text. |
| art_direction | No `content` wrapper: design_read, dials, direction, warnings, assumptions. `direction` follows `art_direction_packet.schema.json` and must include `page_designs`. Each page must carry the same `surface_treatment` frozen in the Seed; an `image-led` surface needs an image Block and a `field` surface needs a visible field via a Block fill/border or decoration. |

For the first three stages consult the matching artifact schema for field enums/required semantic fields. Version/lineage/approval/generated IDs are assigned by admission, not submitted by the host. A rejected proposal should be corrected, not bypassed by writing final artifacts by hand.

`direction.page_designs` is ordered like Slide Specs. Each page has slide_id, background, regions, decorations. Each appearance region has block_id and a complete style: font_family, font_size (points), font_weight, line_height, color, fill, border_color, border_width. Optional italic/corner_radius; image/icon requires image_fit (`cover`/`contain`), chart requires chart_colors. Geometry/content are not repeated here. Decorations are non-semantic rect/round_rect/ellipse/line entries with slide-scoped DEC IDs and explicit geometry/colors/z; they cannot carry claims or replace content blocks. No decorations means none are generated.

After approval, explicitly revise existing planning with `--revise-stage narrative_blueprint|deck_outline|art_direction_seed|slide_specs|layout_plans`. The revision is persisted before the provider request, so a later plain resume continues the same transaction. Do not start a stage revision while another Host request is unanswered, and do not render while a stage revision is pending. Once the owning artifact commits, the Session checkpoints completion before downstream rebuilding, so a later failure does not repeat the same revision. Narrative/Outline/Specs/Layout revision requests bind the superseded artifact version and content hash; a Seed revision binds the superseded immutable Seed and does not perturb Outline. Editing a previously submitted response alone does not silently rewrite an approved stage. Changed upstream artifacts atomically invalidate downstream catalog artifacts, which must receive new proposals before they are current again. Art direction is re-admitted from its current request on each run.

## Native design and assets

At `art_direction_seed`, read the design skill and its [bounded reference selection policy](design-reference-selection.md) before proposing a new direction. Reuse/none are valid; optional search reads the index, then normally 1–3 adapted cards and only necessary preview images. Record actual reference use and trade-offs in existing `design_read`/`assumptions`, and preserve them in the final Packet. This adds no response fields, provider requirement or fallback route.

Read `providers/art-direction/taste/SKILL.md` completely before using it. Use static presentation-relevant principles, not automatic web UI constraints. Native prototypes remain isolated and never satisfy PPTX/release gates, but their file path and SHA-256 are machine-verified as the designed Create Seed's provenance. A fixed token proposal or a post-hoc PPTX is not a native prototype. Translate actual approved composition back into formal plans; if geometry changes, revise Layout before submitting the new P6 response.

Source/generate assets only after planning their role and crop. Add local files to Asset Manifest with truthful source/license/status. Missing, forbidden, remote or unsupported assets fail; no invisible placeholder substitution. Numerical charts need factual Evidence or clearly labeled synthetic/assumption data. Consider whether a chart clarifies comparison/trend rather than requiring one on every slide.

## One sample/full producer

Use the host dependency loader when available. Do not install or redistribute Artifact Tool. Doctor, preflight and render share one resolver: explicit `--node` / `--node-modules`, then `RUNTIME_NODE` / `RUNTIME_NODE_MODULES`, then an admitted Codex bundled runtime. Run `slidethus doctor` to see the exact paths that render will use.

```bash
slidethus create <workspace> --render --slide-id S-001 --slide-id S-003
slidethus create <workspace> --render
```

Both commands consume the same current full-deck IR and `scripts/render_artifact.mjs`. Selection preserves deck order and IDs; unknown/duplicate IDs fail. Fontconfig checks the requested font families and glyphs (`--font-match` may select the host binary). A declared fallback/substitution is recorded, not silently represented as the original font.

Current adapter: native primitive text/list, table, bar/line/pie/doughnut/area charts, editable node/edge diagrams, embedded PNG/JPEG images, and non-semantic shape decoration. Chart content is `{type, categories: string[], series: [{name, values: number[]}]}`; no type inference, numeric coercion or unsupported option dropping. Table content is a rectangular primitive matrix or `{headers, rows}`. The adapter derives content-weighted column widths and wrapped-line-demand row heights inside the admitted table Region; preflight blocks the same calculation when the table cannot fit. Editable diagram topology is emitted as native shapes/text/lines; raster image/icon/diagram needs one manifested PNG/JPEG and explicit fit. SVG/vector assets, complex charts and rich text are not claimed. Unsupported content/clip/paginate paths fail explicitly. Non-text qualified evidence needs its own planned visible caption.

Outputs live in a unique `outputs/host-candidates/candidate-*` directory: PPTX, per-page Artifact Tool previews/layouts, input snapshot and receipt. A started attempt is immediately recorded and must close as failed, timed out or `candidate_office_review_pending`; blocked CLI output points to the terminal receipt. The receipt binds current artifacts, exact IR/preflight/input, adapter version/hash, actual output hashes, selected IDs and bounded sanitized diagnostics. A successful candidate still says `release_approved: false`. PNGs are **not** PowerPoint renders. No existing accepted output is overwritten. Check opening, fonts, embedded pictures, charts and every real PowerPoint page before delivery/release.
