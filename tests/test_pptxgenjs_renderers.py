from __future__ import annotations

import os
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import RenderCapabilityError
from slidethus.protocols import BriefCompletionHints, RenderRequest
from slidethus.render_backends.pptxgenjs import (
    PptxGenJSHybridRenderBackend,
    PptxGenJSNativeRenderBackend,
    measure_pptx_structure,
)
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.visual_system import VisualSystemService
from slidethus.state_machine import Phase
from slidethus.workspace import init_workspace


def _m4_workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="PptxGenJS Production")
    source = tmp_path / "source.md"
    source.write_text(
        "# Enterprise operating model\n\n"
        "Enterprises should build data, knowledge, process, rules, tools, permissions and evaluation standards.\n\n"
        "# Delivery risk\n\nAdding more agents does not automatically improve task quality.\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text=(
                "Create an 8-page management decision deck about an enterprise agent operating "
                "model and request project approval"
            ),
            purpose="Present an enterprise agent operating model for management decision",
            desired_outcome="Approve the operating-model implementation project",
            call_to_action="Approve project initiation and assign executive ownership",
            delivery_context="Management decision meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert result.report["status"] == "ready"
    VisualSystemService(workspace).compile()
    ArtifactRuntime(workspace).record_gate(
        "G6",
        approved_by="pptxgenjs-test",
        target_phase=Phase.VISUAL_SYSTEM_READY,
    )
    return workspace


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def test_pptxgenjs_backend_reports_missing_node_dependencies(tmp_path: Path) -> None:
    workspace = _m4_workspace(tmp_path)
    empty = tmp_path / "empty-renderer"
    empty.mkdir()
    (empty / "render.mjs").write_text("", encoding="utf-8")
    fake_node = tmp_path / "node"
    fake_node.write_text("#!/bin/sh\necho v22.0.0\n", encoding="utf-8")
    fake_node.chmod(0o755)

    with pytest.raises(RenderCapabilityError, match="npm ci"):
        PptxGenJSNativeRenderBackend(renderer_root=empty, node=str(fake_node)).render(
            RenderRequest(
                workspace=workspace,
                target_format="pptx",
                target_editability_level="E3",
                output_dir=workspace / "outputs/m4",
            )
        )


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real PptxGenJS integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_native_and_hybrid_render_same_ir_without_semantic_mutation(tmp_path: Path) -> None:
    workspace = _m4_workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    before = {
        str(item["artifact_type"]): (int(item["version"]), str(item["content_hash"]))
        for item in runtime.list_artifacts()
        if item["artifact_type"]
        in {
            "project_brief",
            "source_ledger",
            "evidence_ledger",
            "narrative_blueprint",
            "deck_outline",
            "slide_specs",
            "layout_plans",
            "visual_system",
            "asset_manifest",
        }
    }
    root = _renderer_root()
    assert root is not None
    request = RenderRequest(
        workspace=workspace,
        target_format="pptx",
        target_editability_level="E3",
        output_dir=workspace / "outputs/m4",
    )
    native = PptxGenJSNativeRenderBackend(renderer_root=root).render(request)
    native_again = PptxGenJSNativeRenderBackend(renderer_root=root).render(request)
    hybrid = PptxGenJSHybridRenderBackend(renderer_root=root).render(
        RenderRequest(
            workspace=workspace,
            target_format="pptx",
            target_editability_level="E2",
            output_dir=workspace / "outputs/m4",
        )
    )

    assert native.status == "success"
    assert native.actual_editability_level == "E3"
    assert native.output_paths[0] == native_again.output_paths[0]
    assert native.output_paths[0].read_bytes() == native_again.output_paths[0].read_bytes()
    assert hybrid.status == "success"
    assert hybrid.actual_editability_level == "E2"
    assert native.output_paths[0] != hybrid.output_paths[0]
    native_measurement = measure_pptx_structure(native.output_paths[0], mode="native")
    hybrid_measurement = measure_pptx_structure(hybrid.output_paths[0], mode="hybrid")
    assert native_measurement.slide_count == hybrid_measurement.slide_count
    assert native_measurement.text_shapes > 0
    assert hybrid_measurement.text_shapes > 0

    after = {
        str(item["artifact_type"]): (int(item["version"]), str(item["content_hash"]))
        for item in runtime.list_artifacts()
        if item["artifact_type"] in before
    }
    assert after == before
