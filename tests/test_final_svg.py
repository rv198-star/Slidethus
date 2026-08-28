from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.protocols import BriefCompletionHints, RenderRequest
from slidethus.render_backends.final_svg import FinalSvgRenderBackend
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.visual_system import VisualSystemService
from slidethus.workspace import init_workspace


def _workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="Final SVG")
    source = tmp_path / "source.md"
    source.write_text(
        "# Principle\n\n企业应建设数据、知识、流程、规则、工具、权限和评价标准。\n\n"
        "# Risk\n\n多 Agent 数量增加并不自动提高任务质量。\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="给管理层做一份 8 页企业 Agent 方案汇报，推动立项决策"
        ),
    )
    assert result.report["status"] == "ready"
    VisualSystemService(workspace).compile()
    return workspace


def _m3_refs(runtime: ArtifactRuntime) -> dict[str, tuple[int, str]]:
    return {
        str(item["artifact_type"]): (int(item["version"]), str(item["content_hash"]))
        for item in runtime.list_artifacts()
        if item.get("artifact_type") in {"deck_outline", "slide_specs", "layout_plans"}
    }


def test_final_svg_renders_same_m3_graph_without_semantic_mutation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    before = _m3_refs(runtime)
    backend = FinalSvgRenderBackend()
    request = RenderRequest(
        workspace=workspace,
        target_format="svg",
        target_editability_level="E1",
        output_dir=workspace / "outputs/m4",
    )

    first = backend.render(request)
    second = backend.render(request)

    assert first.status == "success"
    assert first.actual_editability_level == "E1"
    assert first.output_paths == second.output_paths
    assert len(first.output_paths) == len(runtime.show_artifact("layout_plans")["plans"])
    assert _m3_refs(runtime) == before
    for path in first.output_paths:
        root = ET.parse(path).getroot()
        assert root.tag.endswith("svg")
        assert path.name.startswith("S-")
        assert path.stat().st_size > 200


def test_final_svg_reports_editability_below_native_pptx_request(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    result = FinalSvgRenderBackend().render(
        RenderRequest(
            workspace=workspace,
            target_format="svg",
            target_editability_level="E3",
            output_dir=workspace / "outputs/m4",
        )
    )

    assert result.status == "success"
    assert result.actual_editability_level == "E1"
    assert any("below requested E3" in warning for warning in result.warnings)
