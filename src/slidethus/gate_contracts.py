from __future__ import annotations

GATE_REQUIRED_PATHS: dict[str, tuple[str, ...]] = {
    "G0": ("brief/project_brief.json",),
    "G1": ("brief/project_brief.json", "sources/source_ledger.json"),
    "G2": ("brief/project_brief.json", "sources/source_ledger.json", "evidence/evidence_ledger.json"),
    "G3": ("brief/project_brief.json", "sources/source_ledger.json", "evidence/evidence_ledger.json", "narrative/narrative_blueprint.json"),
    "G4": ("narrative/narrative_blueprint.json", "outline/deck_outline.json"),
    "G5A": ("outline/deck_outline.json", "slides/slide_specs.json"),
    "G5B": ("slides/slide_specs.json", "layout/layout_plans.json"),
    "G6": ("layout/layout_plans.json", "design/visual_system.json"),
    "G7": ("design/visual_system.json", "renders/render_manifest.json"),
    "G8": ("renders/render_manifest.json", "review/quality_report.json"),
    "G9": ("renders/render_manifest.json", "review/quality_report.json", "delivery/delivery_manifest.json"),
}
