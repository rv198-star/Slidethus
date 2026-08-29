from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.protocols import BriefCompletionHints
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.render_preflight import RenderPreflightService
from slidethus.services.visual_system import VisualSystemService
from slidethus.state_machine import Phase
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace
from tests.fontconfig_fakes import write_fontconfig_tools


def _workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="Render Preflight")
    source = tmp_path / "source.md"
    source.write_text(
        "# Operating model\n\nEnterprises build data, knowledge, process, tools and evaluation standards.\n\n"
        "# Risk\n\nMore agents do not automatically improve quality.\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="Create an 8-page management decision deck about an agent operating model",
            purpose="Present the agent operating model",
            desired_outcome="Approve implementation",
            call_to_action="Approve the project",
            delivery_context="Management meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert result.report["status"] == "ready"
    VisualSystemService(workspace).compile()
    ArtifactRuntime(workspace).record_gate(
        "G6",
        approved_by="render-preflight-test",
        target_phase=Phase.VISUAL_SYSTEM_READY,
    )
    return workspace


def _font_match(tmp_path: Path) -> Path:
    return write_fontconfig_tools(tmp_path)


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def test_final_svg_preflight_passes_and_is_idempotent(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    service = RenderPreflightService(
        workspace,
        font_match=str(_font_match(tmp_path)),
    )

    first = service.run(("final-svg",), include_exports=False)
    second = service.run(("final-svg",), include_exports=False)

    assert first.report["status"] == "pass"
    assert first.report["summary"]["major_count"] == 0
    assert first.path == second.path
    assert first.changed
    assert not second.changed
    assert validate_workspace(workspace, check_hashes=True).ok


def test_preflight_tampering_is_detected_by_workspace_validation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    result = RenderPreflightService(
        workspace,
        font_match=str(_font_match(tmp_path)),
    ).run(("final-svg",), include_exports=False)
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["status"] = "blocked"
    result.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(
        item.code == "invalid_render_preflight_report"
        for item in validation.issues
    )


def test_preflight_blocks_when_resolved_fonts_miss_visible_deck_glyphs(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    matcher = write_fontconfig_tools(tmp_path, charset="20-7e")

    result = RenderPreflightService(
        workspace,
        font_match=str(matcher),
    ).run(("final-svg",), include_exports=False)

    assert result.report["status"] == "blocked"
    assert any(
        item["code"] == "font_resolution_failed"
        and "required deck glyphs" in item["message"]
        for item in result.report["checks"]
    )


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="PptxGenJS preflight requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_all_production_backends_and_export_capabilities_pass_preflight(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    root = _renderer_root()
    assert root is not None

    result = RenderPreflightService(
        workspace,
        renderer_root=root,
        font_match=str(_font_match(tmp_path)),
    ).run(
        ("final-svg", "pptxgenjs-native", "pptxgenjs-hybrid"),
        include_exports=True,
    )

    assert result.report["status"] == "pass"
    capability = {
        item["capability"]: item["status"]
        for item in result.report["capabilities"]
    }
    assert capability == {
        "fontconfig": "available",
        "pptxgenjs": "available",
        "svg_png_pdf_export": "available",
    }
