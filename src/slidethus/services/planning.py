from __future__ import annotations

from typing import Any


def missing_slide_coverage(outline: dict[str, Any], slide_specs: dict[str, Any], layout_plans: dict[str, Any]) -> dict[str, list[str]]:
    """Return missing/extra slide IDs across planning artifacts."""

    outline_ids = {item["slide_id"] for item in outline.get("slides", []) if item.get("status") != "excluded"}
    spec_ids = {item["slide_id"] for item in slide_specs.get("slides", [])}
    layout_ids = {item["slide_id"] for item in layout_plans.get("plans", [])}
    return {
        "spec_missing": sorted(outline_ids - spec_ids),
        "spec_extra": sorted(spec_ids - outline_ids),
        "layout_missing": sorted(outline_ids - layout_ids),
        "layout_extra": sorted(layout_ids - outline_ids),
    }
