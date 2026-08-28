from __future__ import annotations

import os
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import RenderCapabilityError
from slidethus.protocols import BriefCompletionHints, RenderRequest
from slidethus.render_backends.final_svg import FinalSvgRenderBackend
from slidethus.render_backends.svg_export import SvgPreviewExportService
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.visual_system import VisualSystemService
from slidethus.state_machine import Phase
from slidethus.workspace import init_workspace


def _workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="SVG Export")
    source = tmp_path / "source.md"
    source.write_text(
        "# Responsibility\n\nEnterprises should build data, knowledge, tools and evaluation standards.\n\n"
        "# Risk\n\nMore agents do not automatically improve quality.\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="Create an 8-page management decision deck about an agent operating model",
            purpose="Present an agent operating model",
            desired_outcome="Approve the implementation project",
            call_to_action="Approve project initiation",
            delivery_context="Management meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert result.report["status"] == "ready"
    VisualSystemService(workspace).compile()
    ArtifactRuntime(workspace).record_gate(
        "G6",
        approved_by="svg-export-test",
        target_phase=Phase.VISUAL_SYSTEM_READY,
    )
    return workspace


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def test_svg_export_reports_missing_node_dependencies(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    svg = FinalSvgRenderBackend().render(
        RenderRequest(
            workspace=workspace,
            target_format="svg",
            target_editability_level="E1",
            output_dir=workspace / "outputs/m4",
        )
    )
    empty = tmp_path / "empty-renderer"
    empty.mkdir()
    (empty / "preview.mjs").write_text("", encoding="utf-8")
    fake_node = tmp_path / "node"
    fake_node.write_text("#!/bin/sh\necho v22.0.0\n", encoding="utf-8")
    fake_node.chmod(0o755)

    with pytest.raises(RenderCapabilityError, match="npm ci"):
        SvgPreviewExportService(
            workspace,
            renderer_root=empty,
            node=str(fake_node),
        ).export(
            svg.output_paths,
            generated_at="2026-08-28T00:00:00Z",
            output_dir=workspace / "outputs/m4/export",
        )


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real resvg/pdf-lib integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_svg_export_produces_idempotent_png_and_pdf_outputs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    svg = FinalSvgRenderBackend().render(
        RenderRequest(
            workspace=workspace,
            target_format="svg",
            target_editability_level="E1",
            output_dir=workspace / "outputs/m4",
        )
    )
    root = _renderer_root()
    assert root is not None
    service = SvgPreviewExportService(workspace, renderer_root=root)

    first = service.export(
        svg.output_paths,
        generated_at="2026-08-28T00:00:00Z",
        output_dir=workspace / "outputs/m4/export",
    )
    second = service.export(
        svg.output_paths,
        generated_at="2026-08-28T00:00:00Z",
        output_dir=workspace / "outputs/m4/export",
    )

    assert len(first.png_paths) == len(svg.output_paths)
    assert all(path.read_bytes().startswith(b"\x89PNG") for path in first.png_paths)
    assert first.pdf_path.read_bytes().startswith(b"%PDF")
    assert first.png_paths == second.png_paths
    assert first.pdf_path == second.pdf_path
    assert first.report_path == second.report_path
    assert first.changed
    assert not second.changed
