from __future__ import annotations

import base64
import html
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from slidethus.errors import RenderBackendError
from slidethus.io_utils import atomic_create_bytes, ensure_within, sha256_bytes
from slidethus.protocols import RenderRequest, RenderResult
from slidethus.services.render_assets import RenderAssetService, ResolvedRenderAsset
from slidethus.services.render_compile import RenderCompileResult, RenderCompileService

_TEXT_TYPES = {"text", "list", "metric", "quote", "spacer"}
_PALETTE = ("#154C5A", "#D76745", "#667085", "#84A98C", "#E9C46A", "#7C3AED")


def _text_lines(content: Any, content_type: str) -> list[str]:
    if isinstance(content, list):
        values = [str(item) for item in content]
        if content_type == "list":
            return [f"• {item}" for item in values]
        return values
    if isinstance(content, dict):
        return [f"{key}: {value}" for key, value in content.items()]
    return [str(content)]


def _glyph_units(text: str) -> float:
    return sum(0.56 if ord(char) < 128 else 1.0 for char in text)


def _wrap_line(text: str, max_units: float) -> list[str]:
    if not text:
        return [""]
    output: list[str] = []
    current = ""
    units = 0.0
    for char in text:
        weight = 0.56 if ord(char) < 128 else 1.0
        if current and units + weight > max_units:
            output.append(current.rstrip())
            current = ""
            units = 0.0
        current += char
        units += weight
    if current or not output:
        output.append(current.rstrip())
    return output


def _wrap_content(region: dict[str, Any]) -> tuple[list[str], float, float]:
    style = region["style"]
    font_size = float(style["font_size"])
    line_height = font_size * float(style["line_height"])
    max_units = max(1.0, (float(region["w"]) - 32.0) / max(1.0, font_size))
    lines: list[str] = []
    for raw in _text_lines(region.get("content"), str(region.get("content_type"))):
        lines.extend(_wrap_line(raw, max_units))
    qualification = region.get("evidence_qualification")
    qualification_height = 14.0 * 1.25 + 8.0 if qualification else 0.0
    required_height = len(lines) * line_height + qualification_height + 24.0
    if required_height > float(region["h"]):
        raise RenderBackendError(
            f"Final SVG overflow in {region['region_id']}: "
            f"required={required_height:.1f}, available={region['h']}"
        )
    return lines, line_height, qualification_height


def _decoration_svg(item: dict[str, Any]) -> str:
    fill = "none" if item.get("fill") is None else html.escape(str(item["fill"]), quote=True)
    stroke = "none" if item.get("stroke") is None else html.escape(str(item["stroke"]), quote=True)
    common = (
        f'id="{html.escape(str(item["decoration_id"]), quote=True)}" '
        f'fill="{fill}" stroke="{stroke}"'
    )
    kind = item["kind"]
    x, y, w, h = item["x"], item["y"], item["w"], item["h"]
    if kind == "ellipse":
        return (
            f'<ellipse {common} cx="{x + w / 2}" cy="{y + h / 2}" '
            f'rx="{w / 2}" ry="{h / 2}"/>'
        )
    if kind == "line":
        return (
            f'<line {common} x1="{x}" y1="{y}" x2="{x + w}" y2="{y + h}" '
            'stroke-width="2"/>'
        )
    radius = 12 if kind == "round_rect" else 0
    return (
        f'<rect {common} x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}"/>'
    )


def _group_start(region: dict[str, Any], *, asset_id: str | None = None) -> str:
    attribute = f' data-asset-id="{html.escape(asset_id, quote=True)}"' if asset_id else ""
    return (
        f'<g id="{html.escape(str(region["region_id"]), quote=True)}" '
        f'data-block-id="{html.escape(str(region["block_id"]), quote=True)}"{attribute}>'
    )


def _surface_svg(region: dict[str, Any]) -> str | None:
    style = region["style"]
    if not style.get("fill"):
        return None
    return (
        f'<rect x="{float(region["x"])}" y="{float(region["y"])}" '
        f'width="{float(region["w"])}" height="{float(region["h"])}" rx="10" '
        f'fill="{html.escape(str(style["fill"]), quote=True)}" '
        f'stroke="{html.escape(str(style.get("border_color") or "none"), quote=True)}" '
        f'stroke-width="{float(style.get("border_width", 0))}"/>'
    )


def _qualification_svg(region: dict[str, Any]) -> str | None:
    qualification = region.get("evidence_qualification")
    if not qualification:
        return None
    style = region["style"]
    return (
        f'<text x="{float(region["x"]) + 16.0}" '
        f'y="{float(region["y"]) + float(region["h"]) - 12.0}" '
        f'font-family="{html.escape(str(style["font_family"]), quote=True)}" '
        'font-size="12" fill="#667085">'
        f'{html.escape("限定：" + str(qualification))}</text>'
    )


def _text_region_svg(region: dict[str, Any]) -> list[str]:
    lines, line_height, qualification_height = _wrap_content(region)
    style = region["style"]
    x, y, w, h = map(float, (region["x"], region["y"], region["w"], region["h"]))
    output: list[str] = [_group_start(region)]
    surface = _surface_svg(region)
    if surface:
        output.append(surface)
    font_size = float(style["font_size"])
    text_height = len(lines) * line_height
    available_text_height = h - qualification_height - 24.0
    if region["valign"] == "middle":
        start_y = y + 12.0 + max(0.0, (available_text_height - text_height) / 2.0) + font_size
    elif region["valign"] == "bottom":
        start_y = y + h - qualification_height - 12.0 - text_height + font_size
    else:
        start_y = y + 12.0 + font_size
    if region["align"] == "center":
        text_x, anchor = x + w / 2.0, "middle"
    elif region["align"] == "right":
        text_x, anchor = x + w - 16.0, "end"
    else:
        text_x, anchor = x + 16.0, "start"
    family = html.escape(str(style["font_family"]), quote=True)
    color = html.escape(str(style["color"]), quote=True)
    weight = int(style["font_weight"])
    output.append(
        f'<text x="{text_x}" y="{start_y}" text-anchor="{anchor}" '
        f'font-family="{family}" font-size="{font_size}" font-weight="{weight}" '
        f'fill="{color}">'
    )
    for index, line in enumerate(lines):
        dy = 0 if index == 0 else line_height
        output.append(f'<tspan x="{text_x}" dy="{dy}">{html.escape(line)}</tspan>')
    output.append("</text>")
    qualification = _qualification_svg(region)
    if qualification:
        output.append(qualification)
    output.append("</g>")
    return output


def _normalize_table(content: Any) -> list[list[str]]:
    if isinstance(content, list) and all(isinstance(row, list) for row in content):
        rows = [[str(cell) for cell in row] for row in content]
    elif isinstance(content, dict):
        headers = [str(item) for item in content.get("headers", [])]
        raw_rows = content.get("rows", [])
        if not isinstance(raw_rows, list) or not all(isinstance(row, list) for row in raw_rows):
            raise RenderBackendError("Table rows must be arrays")
        rows = ([headers] if headers else []) + [[str(cell) for cell in row] for row in raw_rows]
    else:
        raise RenderBackendError("Table content must be rows or {headers, rows}")
    if not rows or not rows[0]:
        raise RenderBackendError("Table has no cells")
    columns = len(rows[0])
    if any(len(row) != columns for row in rows):
        raise RenderBackendError("Table rows have inconsistent column counts")
    return rows


def _table_region_svg(region: dict[str, Any]) -> list[str]:
    rows = _normalize_table(region.get("content"))
    x, y, w, h = map(float, (region["x"], region["y"], region["w"], region["h"]))
    qualification_height = 30.0 if region.get("evidence_qualification") else 0.0
    table_height = h - qualification_height
    cell_w = w / len(rows[0])
    cell_h = table_height / len(rows)
    if cell_w < 40 or cell_h < 24:
        raise RenderBackendError(
            f"Final SVG table cells are too small in {region['region_id']}; return to P5A/P5B"
        )
    style = region["style"]
    font_size = min(float(style["font_size"]), max(10.0, cell_h * 0.32))
    output = [_group_start(region)]
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            cell_x = x + column_index * cell_w
            cell_y = y + row_index * cell_h
            fill = "#F2F4F7" if row_index == 0 else str(style.get("fill") or "#FFFFFF")
            output.append(
                f'<rect x="{cell_x}" y="{cell_y}" width="{cell_w}" height="{cell_h}" '
                f'fill="{html.escape(fill, quote=True)}" stroke="#D0D5DD"/>'
            )
            value_text = str(value)
            max_units = max(1.0, (cell_w - 16.0) / font_size)
            wrapped = _wrap_line(value_text, max_units)
            if len(wrapped) * font_size * 1.2 > cell_h - 8:
                raise RenderBackendError(
                    f"Final SVG table cell overflows in {region['region_id']}"
                )
            start_y = cell_y + font_size + 6
            output.append(
                f'<text x="{cell_x + 8}" y="{start_y}" '
                f'font-family="{html.escape(str(style["font_family"]), quote=True)}" '
                f'font-size="{font_size}" fill="{html.escape(str(style["color"]), quote=True)}" '
                f'font-weight="{700 if row_index == 0 else int(style["font_weight"])}">'
            )
            for index, line in enumerate(wrapped):
                output.append(
                    f'<tspan x="{cell_x + 8}" dy="{0 if index == 0 else font_size * 1.2}">'
                    f'{html.escape(line)}</tspan>'
                )
            output.append("</text>")
    qualification = _qualification_svg(region)
    if qualification:
        output.append(qualification)
    output.append("</g>")
    return output


def _normalize_chart(content: Any) -> tuple[str, list[str], list[dict[str, Any]]]:
    if not isinstance(content, dict):
        raise RenderBackendError("Chart content must be an object")
    chart_type = str(content.get("type") or "bar")
    categories = [str(item) for item in content.get("categories", [])]
    raw_series = content.get("series", [])
    if not categories or not isinstance(raw_series, list) or not raw_series:
        raise RenderBackendError("Chart requires categories and series")
    series: list[dict[str, Any]] = []
    for index, item in enumerate(raw_series):
        if not isinstance(item, dict):
            raise RenderBackendError("Chart series must be objects")
        values = [float(value) for value in item.get("values", [])]
        if len(values) != len(categories) or any(not math.isfinite(value) for value in values):
            raise RenderBackendError("Chart values must be finite and match categories")
        series.append({"name": str(item.get("name") or f"Series {index + 1}"), "values": values})
    return chart_type, categories, series


def _pie_path(cx: float, cy: float, radius: float, start: float, end: float) -> str:
    start_x = cx + radius * math.cos(start)
    start_y = cy + radius * math.sin(start)
    end_x = cx + radius * math.cos(end)
    end_y = cy + radius * math.sin(end)
    large = 1 if end - start > math.pi else 0
    return (
        f"M {cx} {cy} L {start_x} {start_y} A {radius} {radius} 0 {large} 1 "
        f"{end_x} {end_y} Z"
    )


def _chart_region_svg(region: dict[str, Any]) -> list[str]:
    chart_type, categories, series = _normalize_chart(region.get("content"))
    x, y, w, h = map(float, (region["x"], region["y"], region["w"], region["h"]))
    qualification_height = 30.0 if region.get("evidence_qualification") else 0.0
    chart_h = h - qualification_height
    output = [_group_start(region)]
    surface = _surface_svg(region)
    if surface:
        output.append(surface)
    if chart_type in {"pie", "doughnut"}:
        values = series[0]["values"]
        total = sum(max(0.0, value) for value in values)
        if total <= 0:
            raise RenderBackendError("Pie/doughnut chart requires a positive total")
        radius = min(w, chart_h) * 0.32
        cx, cy = x + w * 0.42, y + chart_h / 2
        angle = -math.pi / 2
        for index, value in enumerate(values):
            next_angle = angle + (max(0.0, value) / total) * math.tau
            output.append(
                f'<path d="{_pie_path(cx, cy, radius, angle, next_angle)}" '
                f'fill="{_PALETTE[index % len(_PALETTE)]}"/>'
            )
            angle = next_angle
        if chart_type == "doughnut":
            output.append(
                f'<circle cx="{cx}" cy="{cy}" r="{radius * 0.52}" fill="#FFFFFF"/>'
            )
        legend_x = x + w * 0.75
        for index, category in enumerate(categories):
            legend_y = y + 30 + index * 24
            output.append(
                f'<rect x="{legend_x}" y="{legend_y - 11}" width="12" height="12" '
                f'fill="{_PALETTE[index % len(_PALETTE)]}"/>'
                f'<text x="{legend_x + 18}" y="{legend_y}" font-size="12" '
                f'fill="#17233C">{html.escape(category)}</text>'
            )
    else:
        plot_x, plot_y = x + 54, y + 20
        plot_w, plot_h = w - 74, chart_h - 64
        values = [value for item in series for value in item["values"]]
        minimum = min(0.0, min(values))
        maximum = max(0.0, max(values))
        span = maximum - minimum or 1.0
        output.append(
            f'<line x1="{plot_x}" y1="{plot_y + plot_h}" x2="{plot_x + plot_w}" '
            f'y2="{plot_y + plot_h}" stroke="#98A2B3"/>'
        )
        output.append(
            f'<line x1="{plot_x}" y1="{plot_y}" x2="{plot_x}" '
            f'y2="{plot_y + plot_h}" stroke="#98A2B3"/>'
        )
        group_w = plot_w / len(categories)
        if chart_type == "line":
            for series_index, item in enumerate(series):
                points: list[str] = []
                for index, value in enumerate(item["values"]):
                    px = plot_x + group_w * (index + 0.5)
                    py = plot_y + plot_h - ((value - minimum) / span) * plot_h
                    points.append(f"{px},{py}")
                    output.append(
                        f'<circle cx="{px}" cy="{py}" r="4" '
                        f'fill="{_PALETTE[series_index % len(_PALETTE)]}"/>'
                    )
                output.append(
                    f'<polyline points="{" ".join(points)}" fill="none" '
                    f'stroke="{_PALETTE[series_index % len(_PALETTE)]}" stroke-width="3"/>'
                )
        else:
            bar_w = group_w * 0.72 / len(series)
            zero_y = plot_y + plot_h - ((0.0 - minimum) / span) * plot_h
            for category_index, _category in enumerate(categories):
                for series_index, item in enumerate(series):
                    value = item["values"][category_index]
                    value_y = plot_y + plot_h - ((value - minimum) / span) * plot_h
                    bar_x = plot_x + category_index * group_w + group_w * 0.14 + series_index * bar_w
                    output.append(
                        f'<rect x="{bar_x}" y="{min(value_y, zero_y)}" width="{bar_w * 0.88}" '
                        f'height="{max(1.0, abs(zero_y - value_y))}" '
                        f'fill="{_PALETTE[series_index % len(_PALETTE)]}"/>'
                    )
        for index, category in enumerate(categories):
            label_x = plot_x + group_w * (index + 0.5)
            output.append(
                f'<text x="{label_x}" y="{plot_y + plot_h + 20}" text-anchor="middle" '
                f'font-size="11" fill="#667085">{html.escape(category)}</text>'
            )
        for series_index, item in enumerate(series):
            legend_x = x + 60 + series_index * 150
            output.append(
                f'<rect x="{legend_x}" y="{y + chart_h - 20}" width="12" height="12" '
                f'fill="{_PALETTE[series_index % len(_PALETTE)]}"/>'
                f'<text x="{legend_x + 18}" y="{y + chart_h - 9}" font-size="11" '
                f'fill="#17233C">{html.escape(item["name"])}</text>'
            )
    qualification = _qualification_svg(region)
    if qualification:
        output.append(qualification)
    output.append("</g>")
    return output


def _asset_region_svg(
    region: dict[str, Any],
    assets: dict[str, ResolvedRenderAsset],
) -> list[str]:
    refs = list(region.get("asset_refs", []))
    if len(refs) != 1:
        raise RenderBackendError(
            f"Asset block {region['block_id']} must bind exactly one Asset ID"
        )
    asset = assets.get(str(refs[0]))
    if asset is None:
        raise RenderBackendError(f"Resolved asset is missing: {refs[0]}")
    payload = base64.b64encode(asset.path.read_bytes()).decode("ascii")
    href = f"data:{asset.media_type};base64,{payload}"
    preserve = {
        "contain": "xMidYMid meet",
        "cover": "xMidYMid slice",
        "stretch": "none",
        "none": "xMinYMin meet",
    }.get(asset.fit, "xMidYMid meet")
    output = [_group_start(region, asset_id=asset.asset_id)]
    output.append(
        f'<image x="{float(region["x"])}" y="{float(region["y"])}" '
        f'width="{float(region["w"])}" height="{float(region["h"])}" '
        f'href="{href}" preserveAspectRatio="{preserve}"/>'
    )
    qualification = _qualification_svg(region)
    if qualification:
        output.append(qualification)
    output.append("</g>")
    return output


def _diagram_region_svg(region: dict[str, Any]) -> list[str]:
    values = _text_lines(region.get("content"), str(region.get("content_type")))
    if not values:
        values = [str(region.get("semantic_role") or "visual")]
    x, y, w, h = map(float, (region["x"], region["y"], region["w"], region["h"]))
    output = [_group_start(region)]
    surface = _surface_svg(region)
    if surface:
        output.append(surface)
    if region["content_type"] == "icon":
        radius = min(w, h) * 0.28
        output.append(
            f'<circle cx="{x + w / 2}" cy="{y + h / 2}" r="{radius}" fill="#154C5A"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + 6}" text-anchor="middle" '
            f'font-size="18" fill="#FFFFFF">{html.escape(values[0][:24])}</text>'
        )
    else:
        gap = w / (len(values) + 1)
        radius = max(18.0, min(gap * 0.3, h * 0.24))
        cy = y + h / 2
        for index, value in enumerate(values):
            cx = x + gap * (index + 1)
            output.append(
                f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="#154C5A"/>'
                f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="12" '
                f'fill="#FFFFFF">{html.escape(value[:18])}</text>'
            )
            if index < len(values) - 1:
                next_cx = x + gap * (index + 2)
                output.append(
                    f'<line x1="{cx + radius}" y1="{cy}" x2="{next_cx - radius}" '
                    f'y2="{cy}" stroke="#D76745" stroke-width="3"/>'
                )
    qualification = _qualification_svg(region)
    if qualification:
        output.append(qualification)
    output.append("</g>")
    return output


def _region_svg(
    region: dict[str, Any],
    assets: dict[str, ResolvedRenderAsset],
) -> list[str]:
    content_type = str(region.get("content_type"))
    if content_type in _TEXT_TYPES:
        return _text_region_svg(region)
    if content_type == "table":
        return _table_region_svg(region)
    if content_type == "chart":
        return _chart_region_svg(region)
    if content_type == "image" or region.get("asset_refs"):
        return _asset_region_svg(region, assets)
    if content_type in {"icon", "diagram"}:
        return _diagram_region_svg(region)
    raise RenderBackendError(
        f"Final SVG does not support content_type={content_type}: {region['block_id']}"
    )


def _render_slide(
    ir: dict[str, Any],
    slide: dict[str, Any],
    assets: dict[str, ResolvedRenderAsset],
) -> bytes:
    width = int(ir["canvas"]["width"])
    height = int(ir["canvas"]["height"])
    metadata = json.dumps(
        {
            "ir_id": ir["ir_id"],
            "slide_id": slide["slide_id"],
            "ordinal": slide["ordinal"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f"<metadata>{html.escape(metadata)}</metadata>",
        f'<rect width="{width}" height="{height}" '
        f'fill="{html.escape(str(ir["canvas"]["background"]), quote=True)}"/>',
    ]
    for decoration in sorted(
        slide["decorations"],
        key=lambda item: (int(item["z"]), item["decoration_id"]),
    ):
        output.append(_decoration_svg(decoration))
    for region in sorted(
        slide["regions"],
        key=lambda item: (int(item["z"]), item["region_id"]),
    ):
        output.extend(_region_svg(region, assets))
    output.append("</svg>")
    return ("\n".join(output) + "\n").encode("utf-8")


def _expected_text(region: dict[str, Any]) -> list[str]:
    content_type = str(region.get("content_type"))
    if content_type in _TEXT_TYPES:
        wrapped: list[str] = []
        style = region["style"]
        max_units = max(
            1.0,
            (float(region["w"]) - 32.0) / max(1.0, float(style["font_size"])),
        )
        for value in _text_lines(region.get("content"), content_type):
            wrapped.extend(_wrap_line(value, max_units))
        return wrapped
    if content_type == "table":
        return [cell for row in _normalize_table(region.get("content")) for cell in row]
    if content_type == "chart":
        _chart_type, categories, series = _normalize_chart(region.get("content"))
        return [*categories, *(item["name"] for item in series)]
    if content_type in {"icon", "diagram"} and not region.get("asset_refs"):
        return _text_lines(region.get("content"), content_type)
    return []


def _validate_svg(path: Path, slide: dict[str, Any]) -> None:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise RenderBackendError(f"Final SVG is invalid XML: {path}: {exc}") from exc
    if not root.tag.endswith("svg"):
        raise RenderBackendError(f"Final SVG root element is not svg: {path}")
    elements_by_id = {
        str(element.attrib["id"]): element
        for element in root.iter()
        if "id" in element.attrib
    }
    for region in slide["regions"]:
        group = elements_by_id.get(str(region["region_id"]))
        if group is None:
            raise RenderBackendError(
                f"Final SVG {slide['slide_id']} lost region {region['region_id']}"
            )
        region_text = "".join(value for value in group.itertext() if value)
        for segment in _expected_text(region):
            if segment and segment not in region_text:
                raise RenderBackendError(
                    f"Final SVG {slide['slide_id']} lost content from {region['block_id']}"
                )
        if region.get("asset_refs"):
            expected_asset = str(region["asset_refs"][0])
            if group.attrib.get("data-asset-id") != expected_asset:
                raise RenderBackendError(
                    f"Final SVG {slide['slide_id']} lost asset lineage from {region['block_id']}"
                )
        qualification = region.get("evidence_qualification")
        if qualification and str(qualification) not in region_text:
            raise RenderBackendError(
                f"Final SVG {slide['slide_id']} lost Evidence qualification from {region['block_id']}"
            )


class FinalSvgRenderBackend:
    """Render current Production Renderer IR into deterministic final SVG pages."""

    name = "final-svg"
    version = "1.1.0"

    def __init__(
        self,
        *,
        compiled: RenderCompileResult | None = None,
        assets: dict[str, ResolvedRenderAsset] | None = None,
    ) -> None:
        self.compiled = compiled
        self.assets = assets

    def render(self, request: RenderRequest) -> RenderResult:
        if request.target_format != "svg":
            raise RenderBackendError("FinalSvgRenderBackend only supports target_format=svg")
        workspace = request.workspace.resolve()
        output_root = ensure_within(workspace, request.output_dir.resolve())
        page_dir = output_root / "final-svg"
        page_dir.mkdir(parents=True, exist_ok=True)
        compiled = self.compiled or RenderCompileService(workspace).compile()
        assets = self.assets or RenderAssetService(workspace).resolve(
            tuple(compiled.ir.get("asset_ids", []))
        )
        outputs: list[Path] = []
        for slide in compiled.ir["slides"]:
            payload = _render_slide(compiled.ir, slide, assets)
            digest = sha256_bytes(payload)
            path = page_dir / f"{slide['slide_id']}-{digest[:16]}.svg"
            created = atomic_create_bytes(path, payload)
            if not created and path.read_bytes() != payload:
                raise RenderBackendError(
                    f"Immutable Final SVG path contains different content: {path}"
                )
            _validate_svg(path, slide)
            outputs.append(path)
        if not outputs:
            raise RenderBackendError("Final SVG renderer produced no pages")
        warnings: list[str] = list(compiled.ir.get("warnings", []))
        if request.target_editability_level not in {"E0", "E1"}:
            warnings.append(
                f"Final SVG measured editability is E1, below requested "
                f"{request.target_editability_level}."
            )
        return RenderResult(
            status="success",
            output_paths=tuple(outputs),
            actual_editability_level="E1",
            font_substitutions=tuple(
                (str(item["requested"]), str(item["actual"]))
                for item in compiled.ir.get("font_substitutions", [])
                if item.get("status") == "substituted"
            ),
            warnings=tuple(warnings),
        )
