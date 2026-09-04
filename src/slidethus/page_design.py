"""Cross-artifact checks for explicit appearance, without aesthetic scoring."""

from __future__ import annotations

from typing import Any

from slidethus.errors import ArtifactError
from slidethus.io_utils import sha256_json


def validate_page_designs(
    pages: list[dict[str, Any]], specs: dict[str, Any], layouts: dict[str, Any]
) -> None:
    """Require complete, exact block coverage and respect approved typography floors."""

    if [p["slide_id"] for p in pages] != [s["slide_id"] for s in specs["slides"]]:
        raise ArtifactError("Page designs must cover every Slide Spec once, in order")
    plans = {p["slide_id"]: p for p in layouts["plans"]}
    strict = str(specs.get("schema_version", "")).startswith("0.2.")
    style_hashes: dict[str, str] = {}
    for page, spec in zip(pages, specs["slides"], strict=True):
        if strict and not page.get("page_family_id"):
            raise ArtifactError("Closed page grammar requires page_family_id")
        if strict and not page.get("component_variant_id"):
            raise ArtifactError("Closed page grammar requires component_variant_id")
        block_ids = [b["block_id"] for b in spec["content_blocks"]]
        rows = page["regions"]
        if len(rows) != len(block_ids) or {r["block_id"] for r in rows} != set(block_ids):
            raise ArtifactError("Page appearance must style every Block exactly once")
        floors = {r["block_id"]: r["min_font_pt"] for r in plans[page["slide_id"]]["regions"]}
        for row in rows:
            if strict and not row.get("style_id"):
                raise ArtifactError(f"Closed page grammar requires style_id: {row['block_id']}")
            if strict:
                style_id = str(row["style_id"])
                style_hash = sha256_json(row["style"])
                prior = style_hashes.setdefault(style_id, style_hash)
                if prior != style_hash:
                    raise ArtifactError(
                        f"Style ID maps to different concrete styles: {style_id}"
                    )
            if row["style"]["font_size"] < floors[row["block_id"]]:
                raise ArtifactError(f"Authored style violates approved font floor: {row['block_id']}")
        ids = [d["decoration_id"] for d in page["decorations"]]
        prefix = "DEC-" + page["slide_id"].replace("-", "") + "-"
        if len(ids) != len(set(ids)) or any(not value.startswith(prefix) for value in ids):
            raise ArtifactError("Page decoration IDs must be unique and slide-scoped")
        styles = {r["block_id"]: r["style"] for r in rows}
        for block in spec["content_blocks"]:
            style = styles[block["block_id"]]
            if block["content_type"] in {"image", "icon"} and "image_fit" not in style:
                raise ArtifactError("Image appearance requires an explicit image_fit")
            if block["content_type"] == "chart" and "chart_colors" not in style:
                raise ArtifactError("Chart appearance requires explicit series colors")


def authored_styles(visual: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Look up existing visual authority by globally stable Block IDs."""

    return {
        row["block_id"]: row["style"]
        for page in visual.get("page_designs", [])
        for row in page["regions"]
    }
