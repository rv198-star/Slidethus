from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from typing import Any

_POINT_TO_LOGICAL = 4.0 / 3.0
DEFAULT_HORIZONTAL_PADDING = 32.0
DEFAULT_VERTICAL_PADDING = 24.0
_QUALIFICATION_RESERVE = 32.0


@dataclass(frozen=True)
class TextFitResult:
    """One canonical, inspectable text-fit decision shared across stages."""

    fits: bool
    preferred_font_pt: float
    floor_font_pt: float
    fitted_font_pt: float | None
    width: float
    available_height: float
    required_height: float
    line_height: float
    line_count: int
    qualification_reserve: float
    horizontal_padding: float
    vertical_padding: float
    failure_reason: str | None

    @property
    def required_height_increase(self) -> float:
        """Return the minimum additional logical height at the admitted floor."""

        return max(0.0, self.required_height - self.available_height)

    def as_preflight_details(self) -> dict[str, float | int | str | None]:
        """Return stable numeric diagnostics admitted by Render Preflight."""

        return {
            "required_height": round(self.required_height, 3),
            "available_height": round(self.available_height, 3),
            "required_height_increase": round(self.required_height_increase, 3),
            "width": round(self.width, 3),
            "preferred_font_pt": round(self.preferred_font_pt, 3),
            "floor_font_pt": round(self.floor_font_pt, 3),
            "fitted_font_pt": (
                round(self.fitted_font_pt, 3)
                if self.fitted_font_pt is not None
                else None
            ),
            "line_height": round(self.line_height, 3),
            "line_count": self.line_count,
            "qualification_reserve": round(self.qualification_reserve, 3),
            "horizontal_padding": round(self.horizontal_padding, 3),
            "vertical_padding": round(self.vertical_padding, 3),
            "failure_reason": self.failure_reason,
        }


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


def canonical_line_height(semantic_role: str) -> float:
    """Return the planning line-height contract used before visual styling exists."""

    if semantic_role == "headline":
        return 1.18
    if semantic_role in {"caption", "footer", "label"}:
        return 1.2
    return 1.28


def font_floor_for_role(semantic_role: str, min_body_pt: float) -> float:
    """Return the single role-aware readability floor used by layout and review."""

    admitted_body = float(min_body_pt)
    if semantic_role == "headline":
        return max(28.0, admitted_body)
    if semantic_role in {"metric", "quote"}:
        return max(24.0, admitted_body)
    if semantic_role in {"caption", "footer", "label"}:
        return max(12.0, min(16.0, admitted_body))
    return admitted_body


def _text_measurement(
    content: Any,
    content_type: str,
    *,
    width: float,
    font_size: float,
    line_height: float,
    qualification: str | None,
    horizontal_padding: float,
    vertical_padding: float,
) -> tuple[float, int, float]:
    admitted_size = max(1.0, float(font_size))
    logical_size = admitted_size * _POINT_TO_LOGICAL
    admitted_horizontal_padding = max(0.0, float(horizontal_padding))
    admitted_vertical_padding = max(0.0, float(vertical_padding))
    max_units = max(
        1.0,
        (float(width) - admitted_horizontal_padding) / logical_size,
    )
    lines = sum(
        max(1, math.ceil(glyph_units(value) / max_units))
        for value in visible_text_values(content, content_type)
    )
    qualification_height = _QUALIFICATION_RESERVE if qualification else 0.0
    required_height = (
        lines * logical_size * float(line_height)
        + qualification_height
        + admitted_vertical_padding
    )
    return required_height, lines, qualification_height


def estimated_text_height(
    content: Any,
    content_type: str,
    *,
    width: float,
    font_size: float,
    line_height: float,
    qualification: str | None = None,
    horizontal_padding: float = DEFAULT_HORIZONTAL_PADDING,
    vertical_padding: float = DEFAULT_VERTICAL_PADDING,
) -> float:
    """Return the deterministic height estimate shared by P5B and P7."""

    required_height, _lines, _qualification_height = _text_measurement(
        content,
        content_type,
        width=width,
        font_size=font_size,
        line_height=line_height,
        qualification=qualification,
        horizontal_padding=horizontal_padding,
        vertical_padding=vertical_padding,
    )
    return required_height


def fit_text(
    content: Any,
    content_type: str,
    *,
    width: float,
    height: float,
    preferred: float,
    floor: float,
    line_height: float,
    qualification: str | None = None,
    horizontal_padding: float = DEFAULT_HORIZONTAL_PADDING,
    vertical_padding: float = DEFAULT_VERTICAL_PADDING,
) -> TextFitResult:
    """Return the canonical fit result, including failure metrics at the floor."""

    admitted_floor = max(1.0, float(floor))
    current = max(admitted_floor, float(preferred))
    while True:
        required, lines, qualification_height = _text_measurement(
            content,
            content_type,
            width=width,
            font_size=current,
            line_height=line_height,
            qualification=qualification,
            horizontal_padding=horizontal_padding,
            vertical_padding=vertical_padding,
        )
        if required <= float(height):
            return TextFitResult(
                fits=True,
                preferred_font_pt=float(preferred),
                floor_font_pt=admitted_floor,
                fitted_font_pt=current,
                width=float(width),
                available_height=float(height),
                required_height=required,
                line_height=float(line_height),
                line_count=lines,
                qualification_reserve=qualification_height,
                horizontal_padding=max(0.0, float(horizontal_padding)),
                vertical_padding=max(0.0, float(vertical_padding)),
                failure_reason=None,
            )
        if current <= admitted_floor:
            return TextFitResult(
                fits=False,
                preferred_font_pt=float(preferred),
                floor_font_pt=admitted_floor,
                fitted_font_pt=None,
                width=float(width),
                available_height=float(height),
                required_height=required,
                line_height=float(line_height),
                line_count=lines,
                qualification_reserve=qualification_height,
                horizontal_padding=max(0.0, float(horizontal_padding)),
                vertical_padding=max(0.0, float(vertical_padding)),
                failure_reason="required_height_exceeds_available_at_floor",
            )
        current = max(admitted_floor, current - 1.0)


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
    horizontal_padding: float = DEFAULT_HORIZONTAL_PADDING,
    vertical_padding: float = DEFAULT_VERTICAL_PADDING,
) -> float | None:
    """Return the largest whole-point size that fits, bounded by floor."""

    return fit_text(
        content,
        content_type,
        width=width,
        height=height,
        preferred=preferred,
        floor=floor,
        line_height=line_height,
        qualification=qualification,
        horizontal_padding=horizontal_padding,
        vertical_padding=vertical_padding,
    ).fitted_font_pt
