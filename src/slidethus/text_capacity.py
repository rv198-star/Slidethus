from __future__ import annotations

import math
import unicodedata
from typing import Any


def visible_text_values(content: Any, content_type: str) -> list[str]:
    """Return independently wrapped text runs visible in one region."""

    if isinstance(content, list):
        prefix = "• " if content_type == "list" else ""
        return [prefix + str(item) for item in content]
    if isinstance(content, dict):
        return [f"{key}: {value}" for key, value in content.items()]
    return [str(content or "")]


def glyph_units(value: str) -> float:
    """Estimate horizontal demand without coupling planning to one script."""

    units = 0.0
    for char in value:
        if char == "\t":
            units += 4.0
        elif unicodedata.east_asian_width(char) in {"W", "F"}:
            units += 1.0
        else:
            units += 0.56
    return units


def estimated_text_height(
    content: Any,
    content_type: str,
    *,
    width: float,
    font_size: float,
    line_height: float,
    qualification: str | None = None,
) -> float:
    """Return the deterministic height estimate shared by P5B and P7."""

    admitted_size = max(1.0, float(font_size))
    max_units = max(1.0, (float(width) - 32.0) / admitted_size)
    lines = sum(
        max(1, math.ceil(glyph_units(value) / max_units))
        for value in visible_text_values(content, content_type)
    )
    qualification_height = 24.0 if qualification else 0.0
    return lines * admitted_size * float(line_height) + qualification_height + 24.0


def fitting_font_size(
    content: Any,
    content_type: str,
    *,
    width: float,
    height: float,
    preferred: float,
    floor: float,
    line_height: float,
    qualification: str | None = None,
) -> float | None:
    """Return the largest whole-point size that fits, bounded by floor."""

    current = max(float(floor), float(preferred))
    admitted_floor = float(floor)
    while current >= admitted_floor:
        required = estimated_text_height(
            content,
            content_type,
            width=width,
            font_size=current,
            line_height=line_height,
            qualification=qualification,
        )
        if required <= float(height):
            return current
        current -= 1.0
    return None
