from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.protocols import BriefCompletionHints
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import (
    M4ApplicationService,
    evaluate_m4_workspace_gate,
)
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="M4 Production")
    source = tmp_path / "source.md"
    source.write_text(
        "# Enterprise operating model\n\n"
        "Enterprises build data, knowledge, process, rules, tools, permissions and evaluation standards.\n\n"
        "# Risk\n\nAdding more agents does not automatically improve task quality.\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="Create an 8-page management decision deck about an agent operating model",
            purpose="Present the enterprise agent operating model",
            desired_outcome="Approve the implementation project",
            call_to_action="Approve project initiation and assign executive ownership",
            delivery_context="Management decision meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert result.report["status"] == "ready"
    return workspace


def _font_match(tmp_path: Path) -> Path:
    path = tmp_path / "fc-match"
    path.write_text(
        "#!/bin/sh\nprintf '%s\\n/fonts/test.ttf\\n' \"$3\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def test_m4_blocks_when_node_renderer_dependencies_are_missing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    empty = tmp_path / "empty-renderer"
    empty.mkdir()
    (empty / "render.mjs").write_text("", encoding="utf-8")
    (empty / "preview.mjs").write_text("", encoding="utf-8")
    fake_node = tmp_path / "node"
    fake_node.write_text("#!/bin/sh\necho v22.0.0\n", encoding="utf-8")
    fake_node.chmod(0o755)

    result = M4ApplicationService(
        workspace,
        renderer_root=empty,
        node=str(fake_node),
        font_match=str(_font_match(tmp_path)),
    ).run()

    assert result.report["status"] == "blocked"
    assert result.report["preflight"]["status"] == "blocked"
    assert result.report["render_manifest"] is None
    assert any(
        item["code"] == "pptxgenjs_capability_missing"
        for item in result.report["blockers"]
    )
    assert ArtifactRuntime(workspace).show_artifact("project_state")["current_phase"] == "VISUAL_SYSTEM_READY"


def test_m4_required_office_preview_blocks_before_rendering(tmp_path: Path) -> None:
    root = _renderer_root()
    if root is None:
        pytest.skip("real sidecar is required for the Office preview policy test")
    workspace = _workspace(tmp_path)

    result = M4ApplicationService(
        workspace,
        renderer_root=root,
        font_match=str(_font_match(tmp_path)),
    ).run(require_office_preview=True)

    assert result.report["status"] == "blocked"
    assert result.report["render_manifest"] is None
    assert any(
        item["code"] == "office_preview_required"
        for item in result.report["blockers"]
    )


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M4 integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_m4_application_reaches_g7_and_is_idempotent(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    root = _renderer_root()
    assert root is not None
    service = M4ApplicationService(
        workspace,
        renderer_root=root,
        font_match=str(_font_match(tmp_path)),
    )

    first = service.run()
    second = service.run()
    third = service.run()

    assert first.report["status"] == "ready"
    assert first.report["final_phase"] == "DRAFT_RENDERED"
    assert first.report["g7"]["status"] == "pass"
    assert first.report["render_manifest"] is not None
    roles = {item["role"] for item in first.report["outputs"]}
    assert {
        "final_svg",
        "native_pptx",
        "hybrid_pptx",
        "export_png",
        "export_pdf",
        "backend_measurement",
    }.issubset(roles)
    manifest = ArtifactRuntime(workspace).show_artifact("render_manifest")
    assert manifest["pipeline_mode"] == "production_multi_backend"
    assert {item["backend"] for item in manifest["backend_runs"]} == {
        "final-svg",
        "pptxgenjs-native",
        "pptxgenjs-hybrid",
    }
    assert {item["editability_level"] for item in manifest["backend_runs"]} == {
        "E1",
        "E2",
        "E3",
    }
    assert second.report == first.report
    assert second.path == first.path
    assert not second.changed
    assert third.report == first.report
    assert not third.changed
    assert evaluate_m4_workspace_gate(workspace)["status"] == "pass"
    assert validate_workspace(workspace, check_hashes=True).ok


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M4 integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_m4_report_tampering_is_detected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    root = _renderer_root()
    assert root is not None
    result = M4ApplicationService(
        workspace,
        renderer_root=root,
        font_match=str(_font_match(tmp_path)),
    ).run()
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["final_phase"] = "COMPLETED"
    result.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(item.code == "invalid_m4_application_report" for item in validation.issues)
