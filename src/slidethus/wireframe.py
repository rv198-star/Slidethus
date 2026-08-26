from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from slidethus.io_utils import read_json


def _block_text(block: dict[str, Any]) -> str:
    content = block.get("content", "")
    if isinstance(content, list):
        return "\n".join(f"• {item}" for item in content)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _font_size(block: dict[str, Any], region: dict[str, Any]) -> int:
    role = block.get("semantic_role")
    base = {"headline": 38, "subhead": 26, "metric": 34, "caption": 15, "footer": 13}.get(role, 20)
    if region.get("h", 0) < 90:
        base = min(base, 18)
    return base


def _wrap(text: str, max_chars: int) -> list[str]:
    if max_chars <= 1:
        return [text]
    lines: list[str] = []
    for explicit in text.splitlines() or [""]:
        current = ""
        for char in explicit:
            current += char
            if len(current) >= max_chars:
                lines.append(current)
                current = ""
        if current or not explicit:
            lines.append(current)
    return lines


def render_wireframes(workspace: Path, output_dir: Path | None = None) -> list[Path]:
    """Render deterministic gray planning drafts from slide specs and layout plans."""

    workspace = workspace.resolve()
    specs_data = read_json(workspace / "slides/slide_specs.json")
    layout_data = read_json(workspace / "layout/layout_plans.json")
    specs = {slide["slide_id"]: slide for slide in specs_data["slides"]}
    width = layout_data["canvas"]["width"]
    height = layout_data["canvas"]["height"]
    output_dir = (output_dir or workspace / "outputs/wireframes").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    for plan in layout_data["plans"]:
        slide_id = plan["slide_id"]
        slide = specs[slide_id]
        blocks = {block["block_id"]: block for block in slide["content_blocks"]}
        svg: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
            '<rect width="100%" height="100%" fill="#f4f5f7"/>',
            '<style>text{font-family:Arial,"Noto Sans CJK SC",sans-serif;fill:#20242a}.meta{font-size:12px;fill:#727983}.label{font-size:12px;font-weight:700;fill:#5a616b}</style>',
            f'<text x="24" y="24" class="meta">{html.escape(slide_id)} · {html.escape(plan["layout_family"])} · planning wireframe</text>',
        ]
        for index, region in enumerate(sorted(plan["regions"], key=lambda item: item.get("z", 0))):
            block = blocks[region["block_id"]]
            fill = "#ffffff" if index % 2 == 0 else "#eceff2"
            x, y, w, h = region["x"], region["y"], region["w"], region["h"]
            svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="#b9c0c8" stroke-width="2"/>')
            svg.append(f'<text x="{x + 12}" y="{y + 20}" class="label">{html.escape(region["region_id"])} → {html.escape(region["block_id"])}</text>')
            font_size = _font_size(block, region)
            max_chars = max(4, math.floor((w - 28) / (font_size * 0.62)))
            lines = _wrap(_block_text(block), max_chars)
            line_height = font_size * 1.25
            max_lines = max(1, math.floor((h - 48) / line_height))
            visible = lines[:max_lines]
            if len(lines) > max_lines and visible:
                visible[-1] = visible[-1][:-1] + "…" if visible[-1] else "…"
            start_y = y + 48
            for line_index, line in enumerate(visible):
                text_x = x + 16
                anchor = "start"
                if region.get("align") == "center":
                    text_x = x + w / 2
                    anchor = "middle"
                elif region.get("align") == "right":
                    text_x = x + w - 16
                    anchor = "end"
                text_y = start_y + line_index * line_height
                svg.append(f'<text x="{text_x}" y="{text_y}" font-size="{font_size}" text-anchor="{anchor}">{html.escape(line)}</text>')
        svg.append('</svg>')
        output = output_dir / f"{slide_id}.svg"
        output.write_text("\n".join(svg) + "\n", encoding="utf-8")
        outputs.append(output)
    return outputs
