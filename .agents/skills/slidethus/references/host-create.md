# Host-led Create entry

## Ownership and scope

The host performs research/reasoning/design. Slidethus owns IDs, admission, evidence rules, persistence, compilation and checks. Taste remains a pinned, replaceable design resource. A deterministic resource-to-token adapter is not a native Taste design run.

This entry produces inspectable candidates, not automatic release approval. Full archive/replay packaging and user-led new-case visual acceptance remain subsequent work. Never modify an accepted reference PPTX to test the entry.

## Invocation

```bash
slidethus create <workspace> --source <source.txt> --title "<title>" --request "<purpose, audience, outcome, length>"
```

Re-run the same command after answering a pending request. A missing Brief answer uses the existing `slidethus m3 answer` command. A missing research capability or evidence gap is not resolved by inventing host prose; use the source/evidence workflow.

The result gives `pending.stage`, `request_path`, `request_hash` and `response_path`. Read the complete request. Write only the response at that path:

```json
{
  "schema_version": "0.1.0",
  "request_hash": "sha256:<exact request hash>",
  "stage": "<exact stage>",
  "proposal": {"content": {}, "warnings": [], "assumptions": []}
}
```

Requests bind context and limits. Old responses do not apply to changed context. Received response snapshots are records of submission, not proof of admission. The resulting formal artifact and its gate are authoritative. Do not copy default proposals from `DeterministicPlanningProvider` to satisfy a host request.

### Stage proposal shapes

| Stage | `proposal` body |
|---|---|
| narrative_blueprint | `content`: central_thesis, story_arc, sections; each section has title, purpose, key_questions, evidence_ids, transition, thesis, audience_shift, slide_budget. Use existing Evidence, not new claims. |
| deck_outline | `content.slides`: section_index (zero-based), slide_type, headline, takeaway, purpose, audience_question, evidence_ids, evidence_requirement. Code assigns stable slide IDs. |
| slide_specs | `content.slides`: current slide_id, content_blocks, visual_intent (relationship, suggested_layout_families, avoid), density_budget, speaker_notes, editability_target. Blocks contain semantic_role, content_type, priority, content, claim_mode, evidence_ids, evidence_requirement, asset_refs, notes. Code assigns stable Block IDs. |
| layout_plans | `content.plans`: current slide_id, layout_family, rationale, regions. Each region has exactly block_id, x, y, w, h, z, align, valign, overflow_strategy. Array order is reading order. Optional `content.safe_area` has top/right/bottom/left. Canvas remains 1280×720. Code derives Region IDs, bindings and diagnostics. |
| art_direction | No `content` wrapper: design_read, dials, direction, warnings, assumptions. `direction` follows `art_direction_packet.schema.json` and must include `page_designs`. |

For the first three stages consult the matching artifact schema for field enums/required semantic fields. Version/lineage/approval/generated IDs are assigned by admission, not submitted by the host. A rejected proposal should be corrected, not bypassed by writing final artifacts by hand.

`direction.page_designs` is ordered like Slide Specs. Each page has slide_id, background, regions, decorations. Each appearance region has block_id and a complete style: font_family, font_size (points), font_weight, line_height, color, fill, border_color, border_width. Optional italic/corner_radius; image/icon requires image_fit (`cover`/`contain`), chart requires chart_colors. Geometry/content are not repeated here. Decorations are non-semantic rect/round_rect/ellipse/line entries with slide-scoped DEC IDs and explicit geometry/colors/z; they cannot carry claims or replace content blocks. No decorations means none are generated.

After approval, explicitly revise existing planning with `--revise-stage narrative_blueprint|deck_outline|slide_specs|layout_plans`. Editing a previously submitted response alone does not silently rewrite an approved stage. Changed upstream artifacts require new downstream proposals. Art direction is re-admitted from its current request on each run.

## Native design and assets

Read `providers/art-direction/taste/SKILL.md` completely before using it. Use static presentation-relevant principles, not automatic web UI constraints. Native prototypes remain isolated and never satisfy gates. Translate actual approved composition back into formal plans; if geometry changes, revise Layout before submitting the new P6 response. Record the prototype/approval reference in proposal assumptions without claiming it is machine-verified Office evidence.

Source/generate assets only after planning their role and crop. Add local files to Asset Manifest with truthful source/license/status. Missing, forbidden, remote or unsupported assets fail; no invisible placeholder substitution. Numerical charts need factual Evidence or clearly labeled synthetic/assumption data. Consider whether a chart clarifies comparison/trend rather than requiring one on every slide.

## One sample/full producer

Use the host dependency loader to obtain `RUNTIME_NODE`, `RUNTIME_NODE_MODULES`, and the runtime binaries. Do not install or redistribute Artifact Tool. Explicit `--node` / `--node-modules` arguments override those environment paths.

```bash
slidethus create <workspace> --render --slide-id S-001 --slide-id S-003
slidethus create <workspace> --render
```

Both commands consume the same current full-deck IR and `scripts/render_artifact.mjs`. Selection preserves deck order and IDs; unknown/duplicate IDs fail. Fontconfig checks the requested font families and glyphs (`--font-match` may select the host binary). A declared fallback/substitution is recorded, not silently represented as the original font.

Current adapter: native primitive text/list, table, bar/line/pie/doughnut/area charts, embedded PNG/JPEG images, and non-semantic shape decoration. Chart content is `{type, categories: string[], series: [{name, values: number[]}]}`; no type inference, numeric coercion or unsupported option dropping. Table content is a rectangular primitive matrix or `{headers, rows}`. Diagram/icon currently requires one manifested PNG/JPEG asset; editable diagram topology, SVG/vector assets, complex charts and rich text are not claimed. Unsupported content/clip/paginate paths fail explicitly. Non-text qualified evidence needs its own planned visible caption.

Outputs live in a unique `outputs/host-candidates/candidate-*` directory: PPTX, per-page Artifact Tool previews/layouts, input snapshot and receipt. The receipt binds exact IR, adapter version/hash, actual file hashes and selected IDs. It always says `candidate_office_review_pending`, `release_approved: false`. PNGs are **not** PowerPoint renders. No existing accepted output is overwritten. Check opening, fonts, embedded pictures, charts and every real PowerPoint page before delivery/release.
