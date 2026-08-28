from __future__ import annotations

import math
from typing import Any

from slidethus.errors import LayoutPlanningError
from slidethus.planning_rules import planning_content_units

_LAYOUT_FAMILIES = {
    "hero",
    "split",
    "process",
    "timeline",
    "matrix",
    "architecture",
    "chart-story",
    "case",
    "full-bleed",
    "bento",
    "custom",
}


def region_capacity_units(width: float, height: float, font_pt: float) -> int:
    """Estimate readable text units for one logical region."""

    if width <= 0 or height <= 0 or font_pt <= 0:
        return 0
    characters_per_line = max(1, math.floor((width - 28) / (font_pt * 0.72)))
    line_count = max(1, math.floor((height - 42) / (font_pt * 1.45)))
    return max(1, characters_per_line * line_count)


def _grid_boxes(
    count: int,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    columns: int,
    gap: float,
) -> list[tuple[float, float, float, float]]:
    if count < 1:
        return []
    columns = max(1, min(columns, count))
    rows = math.ceil(count / columns)
    cell_width = (width - gap * (columns - 1)) / columns
    cell_height = (height - gap * (rows - 1)) / rows
    if cell_width <= 0 or cell_height <= 0:
        raise LayoutPlanningError("Layout grid has no positive cell area")
    boxes = []
    for index in range(count):
        row, column = divmod(index, columns)
        boxes.append(
            (
                x + column * (cell_width + gap),
                y + row * (cell_height + gap),
                cell_width,
                cell_height,
            )
        )
    return boxes


def _stack_boxes(
    count: int,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    gap: float,
) -> list[tuple[float, float, float, float]]:
    return _grid_boxes(
        count,
        x=x,
        y=y,
        width=width,
        height=height,
        columns=1,
        gap=gap,
    )


def _body_boxes(
    family: str,
    count: int,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    gap: float,
) -> list[tuple[float, float, float, float]]:
    if count < 1:
        return []
    if family in {"process", "timeline"} and count <= 5:
        return _grid_boxes(
            count,
            x=x,
            y=y,
            width=width,
            height=height,
            columns=count,
            gap=gap,
        )
    if family == "chart-story" and count >= 2:
        left_width = width * 0.64
        right_width = width - left_width - gap
        boxes = [(x, y, left_width, height)]
        boxes.extend(
            _stack_boxes(
                count - 1,
                x=x + left_width + gap,
                y=y,
                width=right_width,
                height=height,
                gap=gap,
            )
        )
        return boxes
    if family == "hero":
        return _stack_boxes(
            count,
            x=x,
            y=y,
            width=width,
            height=height,
            gap=gap,
        )
    if family == "split":
        return _grid_boxes(
            count,
            x=x,
            y=y,
            width=width,
            height=height,
            columns=2,
            gap=gap,
        )
    if family in {"matrix", "architecture", "case", "bento", "custom", "full-bleed"}:
        columns = min(3, max(2, math.ceil(math.sqrt(count)))) if count > 1 else 1
        return _grid_boxes(
            count,
            x=x,
            y=y,
            width=width,
            height=height,
            columns=columns,
            gap=gap,
        )
    return _grid_boxes(
        count,
        x=x,
        y=y,
        width=width,
        height=height,
        columns=2 if count > 1 else 1,
        gap=gap,
    )


def _font_floor(block: dict[str, Any], slide: dict[str, Any]) -> float:
    role = str(block.get("semantic_role", "body"))
    if role == "headline":
        return max(28.0, float(slide["density_budget"]["min_body_pt"]))
    if role in {"metric", "quote"}:
        return max(24.0, float(slide["density_budget"]["min_body_pt"]))
    if role in {"caption", "footer", "label"}:
        return max(12.0, min(16.0, float(slide["density_budget"]["min_body_pt"])))
    return float(slide["density_budget"]["min_body_pt"])


def build_layout_plan(
    slide: dict[str, Any],
    *,
    family: str,
    canvas: dict[str, int],
    safe_area: dict[str, float],
) -> dict[str, Any]:
    """Build one deterministic collision-free region plan for all content blocks."""

    if family not in _LAYOUT_FAMILIES:
        raise LayoutPlanningError(f"Unsupported layout family: {family}")
    blocks = list(slide.get("content_blocks", []))
    if not blocks:
        raise LayoutPlanningError(f"Slide {slide.get('slide_id')} has no content blocks")
    width = float(canvas["width"])
    height = float(canvas["height"])
    left = float(safe_area["left"])
    right = float(safe_area["right"])
    top = float(safe_area["top"])
    bottom = float(safe_area["bottom"])
    content_width = width - left - right
    content_height = height - top - bottom
    if content_width <= 0 or content_height <= 0:
        raise LayoutPlanningError("Safe area leaves no usable canvas")
    gap = 24.0
    headline_index = next(
        (
            index
            for index, block in enumerate(blocks)
            if block.get("semantic_role") == "headline"
        ),
        None,
    )
    boxes_by_index: dict[int, tuple[float, float, float, float]] = {}
    body_indices = list(range(len(blocks)))
    if headline_index is not None:
        header_height = min(
            content_height * (0.30 if family == "hero" else 0.20),
            170.0,
        )
        boxes_by_index[headline_index] = (
            left,
            top,
            content_width,
            header_height,
        )
        body_indices.remove(headline_index)
        body_y = top + header_height + (gap if body_indices else 0)
        body_height = content_height - header_height - (gap if body_indices else 0)
    else:
        body_y = top
        body_height = content_height
    body_boxes = _body_boxes(
        family,
        len(body_indices),
        x=left,
        y=body_y,
        width=content_width,
        height=body_height,
        gap=gap,
    )
    for index, box in zip(body_indices, body_boxes, strict=True):
        boxes_by_index[index] = box

    regions: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        x, y, region_width, region_height = boxes_by_index[index]
        block_id = str(block["block_id"])
        suffix = block_id.rsplit("-", 1)[-1]
        slide_token = str(slide["slide_id"]).replace("-", "")
        font_floor = _font_floor(block, slide)
        capacity = region_capacity_units(region_width, region_height, font_floor)
        content_units = planning_content_units(block.get("content"))
        if content_units > capacity:
            raise LayoutPlanningError(
                f"Block {block_id} requires {content_units} units but region capacity is {capacity}"
            )
        content_type = str(block.get("content_type", "text"))
        regions.append(
            {
                "region_id": f"REG-{slide_token}-{suffix}",
                "block_id": block_id,
                "x": round(x, 3),
                "y": round(y, 3),
                "w": round(region_width, 3),
                "h": round(region_height, 3),
                "z": index,
                "align": (
                    "center"
                    if block.get("semantic_role") in {"headline", "metric", "quote"}
                    and family == "hero"
                    else "left"
                ),
                "valign": "middle" if family == "hero" else "top",
                "overflow_strategy": (
                    "fail"
                    if content_type in {"image", "chart", "table", "diagram"}
                    else "shrink_with_floor"
                ),
                "role": str(block.get("semantic_role", "body")),
                "min_font_pt": font_floor,
                "content_capacity_units": capacity,
                "source_block_hash": str(block["content_hash"]),
            }
        )
    content_units = sum(planning_content_units(item.get("content")) for item in blocks)
    capacity_units = sum(int(item["content_capacity_units"]) for item in regions)
    return {
        "slide_id": slide["slide_id"],
        "layout_family": family,
        "reading_order": [item["region_id"] for item in regions],
        "regions": regions,
        "rationale": (
            f"Use {family} to express the declared relationship "
            f"“{slide['visual_intent']['relationship']}” while mapping every Block once."
        ),
        "grid_notes": [
            "All regions are inside the 1280×720 safe area.",
            "Region identity follows stable Block identity.",
            "Bento is used only when selected by content relationship and block density.",
        ],
        "diagnostics": {
            "block_count": len(blocks),
            "region_count": len(regions),
            "content_units": content_units,
            "capacity_units": capacity_units,
            "warnings": [],
        },
    }
