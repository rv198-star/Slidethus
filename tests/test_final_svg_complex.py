from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from slidethus.render_backends.final_svg import _render_slide, _validate_svg
from slidethus.services.render_assets import ResolvedRenderAsset


def _style() -> dict:
    return {
        "font_family": "Arial",
        "font_size": 18,
        "font_weight": 400,
        "line_height": 1.2,
        "color": "#17233C",
        "fill": "#FFFFFF",
        "border_color": "#D8D2C6",
        "border_width": 1,
    }


def _region(
    index: int,
    content_type: str,
    content,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    asset_refs: list[str] | None = None,
) -> dict:
    return {
        "region_id": f"REG-S001-{index:02d}",
        "block_id": f"BLK-S001-{index:02d}",
        "semantic_role": content_type,
        "content_type": content_type,
        "priority": "primary" if index == 1 else "secondary",
        "content": content,
        "claim_mode": "fact" if content_type in {"table", "chart"} else "asset",
        "evidence_qualification": "示例数据，仅用于结构验证" if content_type == "chart" else None,
        "evidence_ids": [],
        "asset_refs": asset_refs or [],
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "z": 1,
        "align": "left",
        "valign": "top",
        "overflow_strategy": "fail",
        "style": _style(),
    }


def test_final_svg_materializes_table_chart_diagram_and_manifested_image(tmp_path: Path) -> None:
    image_path = tmp_path / "asset.png"
    Image.new("RGB", (100, 60), (240, 240, 240)).save(image_path)
    asset = ResolvedRenderAsset(
        asset_id="AST-001",
        kind="image",
        path=image_path,
        media_type="image/png",
        content_hash="a" * 64,
        width=100,
        height=60,
        fit="contain",
        editable_as="raster",
        attribution=None,
    )
    slide = {
        "slide_id": "S-001",
        "ordinal": 1,
        "layout_family": "architecture",
        "decorations": [],
        "regions": [
            _region(
                1,
                "table",
                {"headers": ["Area", "Owner"], "rows": [["Data", "Business"], ["Tools", "Platform"]]},
                x=56,
                y=48,
                w=520,
                h=260,
            ),
            _region(
                2,
                "chart",
                {
                    "type": "bar",
                    "categories": ["Current", "Target"],
                    "series": [{"name": "Coverage", "values": [42, 86]}],
                },
                x=620,
                y=48,
                w=604,
                h=300,
            ),
            _region(
                3,
                "diagram",
                ["Data", "Rules", "Tools"],
                x=56,
                y=390,
                w=730,
                h=250,
            ),
            _region(
                4,
                "image",
                "",
                x=840,
                y=390,
                w=384,
                h=250,
                asset_refs=["AST-001"],
            ),
        ],
    }
    ir = {
        "ir_id": "RIR-0000000000000000",
        "canvas": {"width": 1280, "height": 720, "background": "#F7F4ED"},
    }

    payload = _render_slide(ir, slide, {"AST-001": asset})
    output = tmp_path / "page.svg"
    output.write_bytes(payload)
    _validate_svg(output, slide)
    root = ET.fromstring(payload)
    text = "".join(root.itertext())

    assert "Area" in text and "Business" in text
    assert "Current" in text and "Coverage" in text
    assert "Data" in text and "Rules" in text and "Tools" in text
    image = next(element for element in root.iter() if element.tag.endswith("image"))
    assert image.attrib["href"].startswith("data:image/png;base64,")
    asset_group = next(
        element for element in root.iter() if element.attrib.get("data-asset-id") == "AST-001"
    )
    assert asset_group.attrib["data-block-id"] == "BLK-S001-04"
