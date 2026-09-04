# Artifact Map

| Artifact | Default path | Purpose |
|---|---|---|
| Project State | `project_state.json` | phase, gates, versions, blockers |
| Project Brief | `brief/project_brief.json` | objective, audience, constraints |
| Source Ledger | `sources/source_ledger.json` | source inventory and rights |
| Evidence Ledger | `evidence/evidence_ledger.json` | claim-to-source traceability |
| Narrative Blueprint | `narrative/narrative_blueprint.json` | thesis and story arc |
| Deck Outline | `outline/deck_outline.json` | stable slide objects |
| Slide Specs | `slides/slide_specs.json` | per-slide semantic plan |
| Layout Plans | `layout/layout_plans.json` | planning-draft geometry |
| Visual System | `design/visual_system.json` | deck-wide style tokens |
| Asset Manifest | `assets/asset_manifest.json` | asset provenance and rights |
| Render Manifest | `renders/render_manifest.json` | backend inputs and outputs |
| Quality Report | `review/quality_report.json` | issues, scores, gate result |
| Delivery Manifest | `delivery/delivery_manifest.json` | final files and limitations |
| Gate Results | `gates/gate_results.json` | immutable Gate evaluations and waivers |
| Decision Log | `decisions/decision_log.json` | versioned project decisions |
| Assumption Log | `decisions/assumption_log.json` | versioned assumptions and resolution status |

Runtime history and recovery journals live under `.slidethus/`; they are not active artifacts. Use stable IDs and never make prose chat the only copy of an approved artifact.

Designed Create also uses immutable supporting facts under `.slidethus/`: VisualAdmissionPolicy, ArtDirectionSeed/Packet, SemanticPreviewReceipt, VisualQualityReview/Decision, ReviewAdjudication, VisualReferenceSet, Host Create Session/Operations and Host Candidate Receipts. They do not create a second Project State or replace catalog artifacts. Candidate receipts are the sole render-attempt authority; Office evidence is appended as a new content-addressed receipt, never written into chat or over an existing attempt record.
