"""Deterministic admission checks mirrored by the Artifact Tool sidecar."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from slidethus.services.render_assets import ResolvedRenderAsset
from slidethus.text_capacity import fit_text

_TEXT_TYPES = {"text", "list", "metric", "quote"}
_IMAGE_TYPES = {"image", "icon"}
_CHART_TYPES = {"bar", "line", "pie", "doughnut", "area"}
ARTIFACT_TOOL_TEXT_HORIZONTAL_PADDING = 0.0
ARTIFACT_TOOL_TEXT_VERTICAL_PADDING = 0.0
ARTIFACT_TOOL_TABLE_CELL_HORIZONTAL_PADDING = 16.0
ARTIFACT_TOOL_TABLE_CELL_VERTICAL_PADDING = 8.0


def artifact_tool_host_contract() -> dict[str, Any]:
    """Describe the target-specific choices that Host Seed/Specs must honor."""

    return {
        "backend": "artifact-tool",
        "overflow_strategies": ["fail", "wrap", "shrink_with_floor"],
        "qualified_non_text_requires_visible_caption": True,
        "text_insets": {
            "horizontal": ARTIFACT_TOOL_TEXT_HORIZONTAL_PADDING,
            "vertical": ARTIFACT_TOOL_TEXT_VERTICAL_PADDING,
        },
        "table_layout": {
            "column_sizing": "content_weighted",
            "row_sizing": "wrapped_line_demand",
            "cell_margins": {
                "horizontal": ARTIFACT_TOOL_TABLE_CELL_HORIZONTAL_PADDING,
                "vertical": ARTIFACT_TOOL_TABLE_CELL_VERTICAL_PADDING,
            },
            "overflow": "block_before_render",
        },
        "raster": {
            "content_types": ["image", "icon", "diagram"],
            "asset_count": 1,
            "media_types": ["image/png", "image/jpeg"],
            "image_fit_required": True,
            "editable_as": ["raster", "not_editable"],
        },
        "editable_diagram": {
            "asset_count": 0,
            "content": {
                "nodes": "[{id,label,x,y,w,h}] with normalized 0..1 geometry",
                "edges": "[{from,to,label?}] referencing distinct node IDs",
            },
        },
        "migration_options": [
            "use normalized editable diagram nodes/edges",
            "bind one admitted PNG/JPEG asset",
            "revise the Seed carrier to textual/typographic/table/chart",
        ],
    }


@dataclass(frozen=True)
class ArtifactToolAdmissionIssue:
    """One target-specific condition that can be checked before Node starts."""

    code: str
    message: str
    slide_id: str
    block_id: str
    region_id: str


@dataclass(frozen=True)
class ArtifactToolTableLayout:
    """Deterministic table geometry mirrored by the Artifact Tool sidecar."""

    fits: bool
    column_widths: tuple[float, ...]
    row_heights: tuple[float, ...]
    required_height: float
    available_height: float


def _primitive_text(content: Any) -> str | None:
    if isinstance(content, (str, int, float)) and not isinstance(content, bool):
        return str(content)
    if isinstance(content, list) and all(
        isinstance(item, (str, int, float)) and not isinstance(item, bool)
        for item in content
    ):
        return "\n".join(str(item) for item in content)
    return None


def _valid_chart(content: Any) -> bool:
    if not isinstance(content, dict) or set(content) - {"type", "categories", "series"}:
        return False
    categories = content.get("categories")
    series = content.get("series")
    if (
        content.get("type") not in _CHART_TYPES
        or not isinstance(categories, list)
        or not categories
        or any(not isinstance(item, str) for item in categories)
        or not isinstance(series, list)
        or not series
    ):
        return False
    for item in series:
        if (
            not isinstance(item, dict)
            or set(item) - {"name", "values"}
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("values"), list)
            or len(item["values"]) != len(categories)
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in item["values"]
            )
        ):
            return False
    return True


def _table_rows(content: Any) -> list[list[str]] | None:
    if isinstance(content, list):
        rows = content
    elif isinstance(content, dict) and not set(content) - {"headers", "rows"}:
        headers = content.get("headers") or []
        body = content.get("rows") or []
        if not isinstance(headers, list) or not isinstance(body, list):
            return False
        rows = [headers, *body] if headers else body
    else:
        return None
    if not rows or not isinstance(rows[0], list) or not rows[0]:
        return None
    width = len(rows[0])
    if not all(
        isinstance(row, list)
        and len(row) == width
        and all(
            isinstance(value, (str, int, float)) and not isinstance(value, bool)
            for value in row
        )
        for row in rows
    ):
        return None
    return [[str(value) for value in row] for row in rows]


def _valid_table(content: Any) -> bool:
    return _table_rows(content) is not None


def _artifact_tool_glyph_units(value: str) -> float:
    """Mirror the sidecar's bounded ASCII/non-ASCII table width estimator."""

    return sum(0.56 if ord(char) <= 0x7F else 1.0 for char in value)


def artifact_tool_table_layout(
    content: Any,
    *,
    width: float,
    height: float,
    font_size: float,
    line_height: float,
) -> ArtifactToolTableLayout | None:
    """Plan content-weighted columns and demand-weighted rows for one table.

    The adapter receives no semantic column-width or row-height artifact, so it
    must derive both deterministically. Equal tracks are unsafe for asymmetric
    content and previously allowed Office-visible cell overflow.
    """

    rows = _table_rows(content)
    if rows is None:
        return None
    column_count = len(rows[0])
    admitted_width = float(width)
    admitted_height = float(height)
    font_px = max(1.0, float(font_size) * 4.0 / 3.0)
    horizontal_padding = ARTIFACT_TOOL_TABLE_CELL_HORIZONTAL_PADDING
    vertical_padding = ARTIFACT_TOOL_TABLE_CELL_VERTICAL_PADDING
    available_text_width = admitted_width - horizontal_padding * column_count
    demands = [
        max(1.0, max(_artifact_tool_glyph_units(row[column]) for row in rows))
        for column in range(column_count)
    ]
    if available_text_width <= 0:
        column_widths = tuple(admitted_width / column_count for _ in demands)
    else:
        total_demand = sum(demands)
        column_widths = tuple(
            horizontal_padding + available_text_width * demand / total_demand
            for demand in demands
        )
    required_rows: list[float] = []
    for row in rows:
        row_lines = max(
            max(
                1,
                math.ceil(
                    _artifact_tool_glyph_units(value)
                    / max(
                        1.0,
                        (column_widths[column] - horizontal_padding) / font_px,
                    )
                ),
            )
            for column, value in enumerate(row)
        )
        required_rows.append(
            row_lines * font_px * float(line_height) + vertical_padding
        )
    required_height = sum(required_rows)
    if required_height <= admitted_height:
        extra_per_row = (admitted_height - required_height) / len(required_rows)
        row_heights = tuple(value + extra_per_row for value in required_rows)
    else:
        row_heights = tuple(required_rows)
    return ArtifactToolTableLayout(
        fits=required_height <= admitted_height,
        column_widths=column_widths,
        row_heights=row_heights,
        required_height=required_height,
        available_height=admitted_height,
    )


def _valid_editable_diagram(content: Any) -> bool:
    """Validate backend-neutral editable nodes/edges with normalized geometry."""

    if not isinstance(content, dict) or set(content) - {"nodes", "edges"}:
        return False
    nodes = content.get("nodes")
    edges = content.get("edges", [])
    if not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
        return False
    node_ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or set(node) - {"id", "label", "x", "y", "w", "h"}:
            return False
        node_id = node.get("id")
        label = node.get("label")
        values = [node.get(key) for key in ("x", "y", "w", "h")]
        if (
            not isinstance(node_id, str)
            or not node_id.strip()
            or not isinstance(label, str)
            or not label.strip()
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in values
            )
        ):
            return False
        x, y, width, height = (float(value) for value in values)
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > 1
            or y + height > 1
        ):
            return False
        node_ids.append(node_id)
    if len(node_ids) != len(set(node_ids)):
        return False
    admitted_ids = set(node_ids)
    for edge in edges:
        if (
            not isinstance(edge, dict)
            or set(edge) - {"from", "to", "label"}
            or not isinstance(edge.get("from"), str)
            or not isinstance(edge.get("to"), str)
            or edge.get("from") not in admitted_ids
            or edge.get("to") not in admitted_ids
            or edge.get("from") == edge.get("to")
            or (
                "label" in edge
                and not isinstance(edge.get("label"), str)
            )
        ):
            return False
    return True


def artifact_tool_admission_issues(
    ir: dict[str, Any],
    assets: dict[str, ResolvedRenderAsset],
) -> tuple[ArtifactToolAdmissionIssue, ...]:
    """Return every sidecar precondition violation in stable deck order."""

    issues: list[ArtifactToolAdmissionIssue] = []
    for page in ir.get("slides", []):
        slide_id = str(page.get("slide_id", ""))
        regions = list(page.get("regions", []))
        visible_page_text = [
            value
            for region in regions
            if str(region.get("content_type")) in {"text", "list", "quote"}
            if (value := _primitive_text(region.get("content"))) is not None
        ]
        for region in regions:
            block_id = str(region.get("block_id", ""))
            region_id = str(region.get("region_id", ""))
            content_type = str(region.get("content_type", ""))

            def add(
                code: str,
                message: str,
                *,
                current_slide_id: str = slide_id,
                current_block_id: str = block_id,
                current_region_id: str = region_id,
            ) -> None:
                issues.append(
                    ArtifactToolAdmissionIssue(
                        code=code,
                        message=message,
                        slide_id=current_slide_id,
                        block_id=current_block_id,
                        region_id=current_region_id,
                    )
                )

            if region.get("overflow_strategy") in {"clip", "paginate"}:
                add(
                    "artifact_tool_overflow_strategy_unsupported",
                    f"Artifact Tool does not support overflow_strategy={region.get('overflow_strategy')}.",
                )
            if content_type == "spacer":
                continue
            if content_type in _TEXT_TYPES:
                if _primitive_text(region.get("content")) is None:
                    add(
                        "artifact_tool_text_content_unsupported",
                        "Artifact Tool text requires a string, number, or primitive list.",
                    )
                continue
            qualification = str(region.get("evidence_qualification") or "").strip()
            if qualification and not any(
                qualification in visible for visible in visible_page_text
            ):
                add(
                    "artifact_tool_qualification_caption_missing",
                    "Qualified non-text evidence requires a planned visible caption containing the qualification.",
                )
            if content_type == "diagram":
                refs = [str(item) for item in region.get("asset_refs", [])]
                if not refs:
                    if not _valid_editable_diagram(region.get("content")):
                        add(
                            "artifact_tool_diagram_contract_invalid",
                            "Artifact Tool diagram requires normalized editable nodes/edges or one admitted PNG/JPEG asset.",
                        )
                    else:
                        failed_nodes = []
                        style = region.get("style", {})
                        for node in region["content"]["nodes"]:
                            node_fit = fit_text(
                                node["label"],
                                "text",
                                width=float(region["w"]) * float(node["w"]),
                                height=float(region["h"]) * float(node["h"]),
                                preferred=float(style["font_size"]),
                                floor=float(style["font_size"]),
                                line_height=float(style["line_height"]),
                                horizontal_padding=ARTIFACT_TOOL_TEXT_HORIZONTAL_PADDING,
                                vertical_padding=ARTIFACT_TOOL_TEXT_VERTICAL_PADDING,
                            )
                            if not node_fit.fits:
                                failed_nodes.append(str(node["id"]))
                        if failed_nodes:
                            add(
                                "artifact_tool_diagram_text_overflow",
                                "Editable diagram node labels do not fit their admitted geometry: "
                                + ", ".join(failed_nodes),
                            )
                    continue
                if len(refs) != 1:
                    add(
                        "artifact_tool_asset_cardinality_invalid",
                        "Raster diagram requires exactly one admitted asset.",
                    )
                    continue
                if _primitive_text(region.get("content")) is None:
                    add(
                        "artifact_tool_image_alt_unsupported",
                        "Raster diagram alt text requires a string, number, or primitive list.",
                    )
                asset = assets.get(refs[0])
                if asset is None:
                    add(
                        "artifact_tool_asset_unresolved",
                        f"Artifact Tool asset is not resolved: {refs[0]}.",
                    )
                elif asset.media_type not in {"image/png", "image/jpeg"}:
                    add(
                        "artifact_tool_asset_media_type_unsupported",
                        f"Artifact Tool requires PNG/JPEG, got {asset.media_type} for {refs[0]}.",
                    )
                if asset is not None and asset.editable_as not in {
                    "raster",
                    "not_editable",
                }:
                    add(
                        "artifact_tool_asset_editability_mismatch",
                        f"Artifact Tool embeds {refs[0]} as raster, but Asset Manifest declares editable_as={asset.editable_as}.",
                    )
                if not region.get("style", {}).get("image_fit"):
                    add(
                        "artifact_tool_image_fit_missing",
                        "Raster diagram requires explicit image_fit.",
                    )
                continue
            if content_type in _IMAGE_TYPES:
                refs = [str(item) for item in region.get("asset_refs", [])]
                if len(refs) != 1:
                    add(
                        "artifact_tool_asset_cardinality_invalid",
                        "Artifact Tool image/icon/diagram requires exactly one admitted asset.",
                    )
                    continue
                if _primitive_text(region.get("content")) is None:
                    add(
                        "artifact_tool_image_alt_unsupported",
                        "Artifact Tool image/icon alt text requires a string, number, or primitive list.",
                    )
                asset = assets.get(refs[0])
                if asset is None:
                    add(
                        "artifact_tool_asset_unresolved",
                        f"Artifact Tool asset is not resolved: {refs[0]}.",
                    )
                elif asset.media_type not in {"image/png", "image/jpeg"}:
                    add(
                        "artifact_tool_asset_media_type_unsupported",
                        f"Artifact Tool requires PNG/JPEG, got {asset.media_type} for {refs[0]}.",
                    )
                if asset is not None and asset.editable_as not in {
                    "raster",
                    "not_editable",
                }:
                    add(
                        "artifact_tool_asset_editability_mismatch",
                        f"Artifact Tool embeds {refs[0]} as raster, but Asset Manifest declares editable_as={asset.editable_as}.",
                    )
                if not region.get("style", {}).get("image_fit"):
                    add(
                        "artifact_tool_image_fit_missing",
                        "Artifact Tool image/icon/diagram requires explicit image_fit.",
                    )
                continue
            if content_type == "chart":
                if not _valid_chart(region.get("content")):
                    add(
                        "artifact_tool_chart_contract_invalid",
                        "Artifact Tool chart requires a supported type and finite numeric series aligned with string categories.",
                    )
                if not region.get("style", {}).get("chart_colors"):
                    add(
                        "artifact_tool_chart_colors_missing",
                        "Artifact Tool chart requires explicit series colors.",
                    )
                continue
            if content_type == "table":
                layout = artifact_tool_table_layout(
                    region.get("content"),
                    width=float(region.get("w", 0)),
                    height=float(region.get("h", 0)),
                    font_size=float(region.get("style", {}).get("font_size", 0)),
                    line_height=float(region.get("style", {}).get("line_height", 1.0)),
                )
                if layout is None:
                    add(
                        "artifact_tool_table_contract_invalid",
                        "Artifact Tool table requires a non-empty rectangular primitive matrix.",
                    )
                elif not layout.fits:
                    add(
                        "artifact_tool_table_text_overflow",
                        f"Artifact Tool table needs {layout.required_height:.1f}px "
                        f"after content-weighted column allocation, but {layout.available_height:.1f}px "
                        "is available; widen or increase the table in P5A/P5B.",
                    )
                continue
            add(
                "backend_content_type_unsupported",
                f"Artifact Tool does not support content_type={content_type}.",
            )
    return tuple(issues)
