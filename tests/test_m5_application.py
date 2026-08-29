from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from slidethus.protocols import BriefCompletionHints
from slidethus.semantic_reviews import SEMANTIC_DIMENSIONS
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.m5_application import M5ApplicationService, evaluate_m5_workspace_gate
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


class CleanSemanticProvider:
    name = "m5-clean-semantic"
    version = "1.0.0"

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": []}
        return {
            "dimensions": [
                {
                    "dimension": dimension,
                    "score": 5,
                    "rationale": "Fixture quality baseline.",
                    "issue_ids": [],
                }
                for dimension in SEMANTIC_DIMENSIONS
            ]
        }


class CleanVisualProvider:
    name = "m5-clean-visual"
    version = "1.0.0"

    def review(self, image_paths: tuple[Path, ...], context: dict[str, Any]) -> dict[str, Any]:
        assert image_paths
        return {"issues": []}


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def _font_match(tmp_path: Path) -> Path:
    path = tmp_path / "fc-match"
    path.write_text("#!/bin/sh\nprintf '%s\\n/fonts/test.ttf\\n' \"$3\"\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _build_workspace(tmp_path: Path) -> Path:
    renderer = _renderer_root()
    if renderer is None:
        pytest.skip("real M4 sidecar is required for M5 application integration")
    workspace = init_workspace(tmp_path / "workspace", title="M5 Application")
    source = tmp_path / "source.md"
    source.write_text(
        "# Enterprise operating model\n\n"
        "Enterprises build data, knowledge, process, rules, tools, permissions and evaluation standards.\n\n"
        "# Risk\n\nAdding more agents does not automatically improve task quality.\n",
        encoding="utf-8",
    )
    m3 = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="Create an 8-page management decision deck about an enterprise agent operating model",
            purpose="Present the enterprise agent operating model",
            desired_outcome="Approve implementation",
            call_to_action="Approve project initiation",
            delivery_context="Management decision meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert m3.report["status"] == "ready"
    m4 = M4ApplicationService(
        workspace,
        renderer_root=renderer,
        font_match=str(_font_match(tmp_path)),
    ).run()
    assert m4.report["status"] == "ready"
    return workspace


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build_workspace(tmp_path_factory.mktemp("m5-app-baseline"))


def _copy_workspace(baseline: Path, tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    shutil.copytree(baseline, target)
    return target


def _service(workspace: Path, tmp_path: Path) -> M5ApplicationService:
    return M5ApplicationService(
        workspace,
        semantic_provider=CleanSemanticProvider(),
        visual_provider=CleanVisualProvider(),
        renderer_root=_renderer_root(),
        font_match=str(_font_match(tmp_path)),
    )


def test_m5_application_reaches_reviewed_and_is_idempotent(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    service = _service(workspace, tmp_path)

    first = service.run()
    second = service.run()

    assert first.report["status"] == "ready"
    assert first.report["final_phase"] == "REVIEWED"
    assert first.report["g8"]["status"] == "pass"
    assert evaluate_m5_workspace_gate(workspace)["status"] == "pass"
    assert second.report == first.report
    assert second.path == first.path
    assert second.changed is False
    assert validate_workspace(workspace, check_hashes=True).ok


def test_m5_application_without_review_providers_blocks_truthfully(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)

    result = M5ApplicationService(workspace).run()

    assert result.report["status"] == "blocked"
    assert result.report["reviews"]["deterministic"] is not None
    assert result.report["reviews"]["semantic"] is not None
    assert result.report["reviews"]["semantic"]["status"] == "blocked"
    assert result.report["g8"]["status"] == "not_run"
    assert any(item["code"] == "semantic_provider_missing" for item in result.report["blockers"])
    assert validate_workspace(workspace, check_hashes=True).ok


def test_m5_application_repairs_missing_generated_output_before_review(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    manifest = json.loads((workspace / "renders/render_manifest.json").read_text(encoding="utf-8"))
    png = next(item for item in manifest["outputs"] if item["role"] == "export_png")
    missing = workspace / png["path"]
    missing.unlink()

    result = _service(workspace, tmp_path).run()

    assert result.report["status"] == "ready"
    assert result.report["reviews"]["repair_report"] is not None
    assert result.report["reviews"]["repair_report"]["status"] == "applied"
    assert missing.is_file()
    assert evaluate_m5_workspace_gate(workspace)["status"] == "pass"
