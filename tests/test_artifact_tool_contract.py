from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from slidethus.io_utils import atomic_write_json
from slidethus.render_backends.artifact_tool_contract import (
    artifact_tool_admission_issues,
    artifact_tool_table_layout,
)
from slidethus.render_backends.artifact_tool_runtime import (
    resolve_artifact_tool_runtime,
)
from slidethus.services.render_assets import ResolvedRenderAsset


def _region(
    ordinal: int,
    content_type: str,
    content: Any,
    *,
    asset_refs: list[str] | None = None,
    qualification: str | None = None,
    overflow_strategy: str = "fail",
) -> dict[str, Any]:
    return {
        "region_id": f"REG-S001-{ordinal:02d}",
        "block_id": f"BLK-S001-{ordinal:02d}",
        "content_type": content_type,
        "content": content,
        "asset_refs": asset_refs or [],
        "evidence_qualification": qualification,
        "overflow_strategy": overflow_strategy,
        "w": 800,
        "h": 400,
        "style": {
            "font_size": 12,
            "line_height": 1.2,
            "color": "#111111",
            "border_color": "#111111",
            "border_width": 1,
        },
    }


def test_artifact_tool_admission_aggregates_target_specific_failures() -> None:
    regions = [
        _region(1, "text", {"structured": "not flattened"}, overflow_strategy="clip"),
        _region(2, "image", "Missing asset", qualification="internal only"),
        _region(
            3,
            "image",
            {"alt": "not primitive"},
            asset_refs=["AST-001"],
        ),
        _region(4, "icon", "Too many", asset_refs=["AST-001", "AST-002"]),
        _region(5, "chart", {"type": "bar", "categories": [], "series": []}),
        _region(6, "diagram", {"nodes": [], "edges": []}),
    ]
    ir = {"slides": [{"slide_id": "S-001", "regions": regions}]}
    assets = {
        "AST-001": ResolvedRenderAsset(
            asset_id="AST-001",
            kind="image",
            path=Path("asset.svg"),
            media_type="image/svg+xml",
            content_hash="0" * 64,
            width=None,
            height=None,
            fit="contain",
            editable_as="vector",
            attribution=None,
        )
    }

    issues = artifact_tool_admission_issues(ir, assets)
    codes = [item.code for item in issues]

    assert codes == [
        "artifact_tool_overflow_strategy_unsupported",
        "artifact_tool_text_content_unsupported",
        "artifact_tool_qualification_caption_missing",
        "artifact_tool_asset_cardinality_invalid",
        "artifact_tool_image_alt_unsupported",
        "artifact_tool_asset_media_type_unsupported",
        "artifact_tool_asset_editability_mismatch",
        "artifact_tool_image_fit_missing",
        "artifact_tool_asset_cardinality_invalid",
        "artifact_tool_chart_contract_invalid",
        "artifact_tool_chart_colors_missing",
        "artifact_tool_diagram_contract_invalid",
    ]
    assert len({(item.region_id, item.code) for item in issues}) == len(issues)


def test_editable_diagram_is_admitted_without_a_raster_asset() -> None:
    diagram = {
        "nodes": [
            {"id": "start", "label": "Start", "x": 0.0, "y": 0.2, "w": 0.3, "h": 0.3},
            {"id": "end", "label": "End", "x": 0.7, "y": 0.2, "w": 0.3, "h": 0.3},
        ],
        "edges": [{"from": "start", "to": "end", "label": "then"}],
    }
    ir = {
        "slides": [
            {
                "slide_id": "S-001",
                "regions": [_region(1, "diagram", diagram)],
            }
        ]
    }

    assert artifact_tool_admission_issues(ir, {}) == ()


def test_table_layout_weights_tracks_by_content_and_blocks_real_overflow() -> None:
    compact = {
        "headers": ["基准需满足", "不可写成"],
        "rows": [
            ["500台、USD26.90、50%定金", "客户正式订单"],
            ["首单一次性投入不重复承担", "公司净利润"],
            ["包装、交期、现金占用重新测算", "已批准备货"],
        ],
    }
    compact_layout = artifact_tool_table_layout(
        compact,
        width=379.2,
        height=320,
        font_size=18,
        line_height=1.28,
    )
    assert compact_layout is not None
    assert compact_layout.fits
    assert compact_layout.column_widths[0] > compact_layout.column_widths[1]
    assert sum(compact_layout.row_heights) == pytest.approx(320)

    overloaded = {
        "headers": ["阶段", "关键交付物 / 关卡"],
        "rows": [
            ["0-30天：确认", "确认500台意向的时间、颜色、包装与正式文件状态"],
            ["31-60天：重算与锁定", "更新现金暴露、贡献率、价格敏感性；确认排产、文件冻结与安全交期"],
            ["61-90天：闭环验收", "升级说明书、彩盒保护、备件标准与CRM交接字段；管理层复核"],
        ],
    }
    overloaded_region = _region(1, "table", overloaded)
    overloaded_region.update({"w": 357.333, "h": 328.32})
    overloaded_region["style"].update({"font_size": 18, "line_height": 1.28})
    issues = artifact_tool_admission_issues(
        {"slides": [{"slide_id": "S-001", "regions": [overloaded_region]}]},
        {},
    )
    assert [item.code for item in issues] == ["artifact_tool_table_text_overflow"]
    assert "369.9px" in issues[0].message


@pytest.mark.skipif(
    not os.environ.get("RUNTIME_NODE_MODULES"),
    reason="optional host Artifact Tool runtime",
)
def test_real_artifact_adapter_exports_editable_diagram(tmp_path: Path) -> None:
    runtime = resolve_artifact_tool_runtime()
    diagram = {
        "nodes": [
            {"id": "start", "label": "Start", "x": 0.0, "y": 0.2, "w": 0.3, "h": 0.3},
            {"id": "end", "label": "End", "x": 0.7, "y": 0.2, "w": 0.3, "h": 0.3},
        ],
        "edges": [{"from": "start", "to": "end", "label": "then"}],
    }
    region = _region(1, "diagram", diagram)
    region.update(
        {
            "semantic_role": "body",
            "priority": "primary",
            "claim_mode": "label",
            "evidence_ids": [],
            "x": 100,
            "y": 100,
            "z": 1,
            "align": "center",
            "valign": "middle",
        }
    )
    region["style"].update(
        {
            "font_family": "Arial",
            "font_weight": 400,
            "fill": "#FFFFFF",
            "corner_radius": 8,
        }
    )
    payload = tmp_path / "input.json"
    output = tmp_path / "output"
    atomic_write_json(
        payload,
        {
            "ir": {
                "canvas": {"width": 1280, "height": 720},
                "slides": [
                    {
                        "slide_id": "S-001",
                        "background": "#F8FAFC",
                        "decorations": [],
                        "regions": [region],
                    }
                ],
            },
            "assets": {},
            "slide_ids": ["S-001"],
            "notes": {"S-001": "[Sources]"},
        },
    )

    result = subprocess.run(
        [
            runtime.node,
            str(runtime.script),
            str(payload),
            str(output),
            str(runtime.modules),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr
    assert (output / "S-001.png").is_file()
    with ZipFile(output / "candidate.pptx") as archive:
        slide = archive.read("ppt/slides/slide1.xml")
    assert slide.count(b"<p:sp>") >= 4
