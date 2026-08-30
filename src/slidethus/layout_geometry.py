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

_POINT_TO_LOGICAL = 4.0 / 3.0


def region_capacity_units(width: float, height: float, font_pt: float) -> int:
    """Estimate readable text units for one logical region."""

    if width <= 0 or height <= 0 or font_pt <= 0:
        return 0
    logical_font = font_pt * _POINT_TO_LOGICAL
    characters_per_line = max(1, math.floor((width - 32) / logical_font))
    line_count = max(1, math.floor((height - 48) / (logical_font * 1.35)))
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


def _ordered_body_boxes(
    family: str,
    blocks: list[dict[str, Any]],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    gap: float,
) -> list[tuple[float, float, float, float]]:
    if not blocks:
        return []
    lead_positions = [
        index for index, block in enumerate(blocks)
        if block.get("semantic_role") == "subhead"
    ]
    if family == "process" and len(blocks) == 2 and len(lead_positions) == 1:
        lead_position = lead_positions[0]
        step_position = 1 - lead_position
        lead_width = width * 0.44
        boxes = {
            lead_position: (x, y, lead_width, height),
            step_position: (
                x + lead_width + gap,
                y,
                width - lead_width - gap,
                height,
            ),
        }
        return [boxes[index] for index in range(len(blocks))]
    if family == "timeline" and not lead_positions and len(blocks) > 1:
        cell_width = (width - gap * (len(blocks) - 1)) / len(blocks)
        card_height = height * 0.72
        return [
            (
                x + index * (cell_width + gap),
                y if index % 2 == 0 else y + height - card_height,
                cell_width,
                card_height,
            )
            for index in range(len(blocks))
        ]
    boxes: dict[int, tuple[float, float, float, float]] = {}
    step_positions = [index for index in range(len(blocks)) if index not in lead_positions]
    step_y = y
    step_height = height
    if lead_positions:
        lead_height = min(height * 0.45, max(140.0, min(170.0, height * 0.36)))
        lead_boxes = _stack_boxes(
            len(lead_positions),
            x=x,
            y=y,
            width=width,
            height=lead_height,
            gap=gap,
        )
        for index, box in zip(lead_positions, lead_boxes, strict=True):
            boxes[index] = box
        step_y = y + lead_height + (gap if step_positions else 0.0)
        step_height = height - lead_height - (gap if step_positions else 0.0)
    if step_positions:
        count = len(step_positions)
        columns = count if count <= 5 else min(4, math.ceil(count / 2))
        step_boxes = _grid_boxes(
            count,
            x=x,
            y=step_y,
            width=width,
            height=step_height,
            columns=columns,
            gap=gap,
        )
        for index, box in zip(step_positions, step_boxes, strict=True):
            boxes[index] = box
    return [boxes[index] for index in range(len(blocks))]


def _matrix_body_boxes(
    blocks: list[dict[str, Any]],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    gap: float,
) -> list[tuple[float, float, float, float]]:
    """Give one high-cardinality classification list a full-width evidence band."""

    list_positions = [
        index
        for index, block in enumerate(blocks)
        if block.get("content_type") == "list"
        and isinstance(block.get("content"), list)
        and len(block["content"]) >= 3
    ]
    if len(list_positions) != 1 or len(blocks) < 2:
        columns = min(3, max(2, math.ceil(math.sqrt(len(blocks)))))
        return _grid_boxes(
            len(blocks),
            x=x,
            y=y,
            width=width,
            height=height,
            columns=columns,
            gap=gap,
        )
    list_position = list_positions[0]
    other_positions = [index for index in range(len(blocks)) if index != list_position]
    other_width = width * 0.46
    list_x = x + other_width + gap
    list_width = width - other_width - gap
    if len(other_positions) == 3:
        half_width = (other_width - gap) / 2
        half_height = (height - gap) / 2
        upper_boxes = [
            (x, y, half_width, half_height),
            (x + half_width + gap, y, half_width, half_height),
            (x, y + half_height + gap, other_width, half_height),
        ]
    else:
        upper_boxes = _grid_boxes(
            len(other_positions),
            x=x,
            y=y,
            width=other_width,
            height=height,
            columns=2 if len(other_positions) >= 3 else 1,
            gap=gap,
        )
    boxes: dict[int, tuple[float, float, float, float]] = {
        list_position: (list_x, y, list_width, height)
    }
    for index, box in zip(other_positions, upper_boxes, strict=True):
        boxes[index] = box
    return [boxes[index] for index in range(len(blocks))]


def _body_boxes(
    family: str,
    count: int,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    gap: float,
    blocks: list[dict[str, Any]] | None = None,
) -> list[tuple[float, float, float, float]]:
    if count < 1:
        return []
    if family in {"process", "timeline"}:
        if blocks is None or len(blocks) != count:
            raise LayoutPlanningError(
                f"{family} layout requires block semantics for ordered topology"
            )
        return _ordered_body_boxes(
            family,
            blocks,
            x=x,
            y=y,
            width=width,
            height=height,
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
    if family == "matrix":
        if blocks is None or len(blocks) != count:
            raise LayoutPlanningError("matrix layout requires block semantics")
        return _matrix_body_boxes(
            blocks,
            x=x,
            y=y,
            width=width,
            height=height,
            gap=gap,
        )
    if family == "case" and count >= 2:
        lead_width = width * 0.58
        return [
            (x, y, lead_width, height),
            *_stack_boxes(
                count - 1,
                x=x + lead_width + gap,
                y=y,
                width=width - lead_width - gap,
                height=height,
                gap=gap,
            ),
        ]
    if family in {"architecture", "bento", "custom", "full-bleed"}:
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
        headline_units = planning_content_units(blocks[headline_index].get("content"))
        header_height = min(
            content_height
            * (0.30 if family == "hero" or headline_units > 42 else 0.20),
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
        blocks=[blocks[index] for index in body_indices],
    )
    for index, box in zip(body_indices, body_boxes, strict=True):
        boxes_by_index[index] = box

    regions: list[dict[str, Any]] = []
    spotlight_index = (
        body_indices[0]
        if body_indices and family in {"case", "process"}
        else None
    )
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
                "valign": "middle" if family == "hero" or index == spotlight_index else "top",
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
