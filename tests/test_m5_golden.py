from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from slidethus.protocols import BriefCompletionHints
from slidethus.semantic_reviews import SEMANTIC_DIMENSIONS
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.m5_application import M5ApplicationService
from slidethus.workspace import init_workspace


class GoldenSemanticProvider:
    name = "golden-semantic-fixture"
    version = "1.0.0"

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": []}
        return {
            "dimensions": [
                {
                    "dimension": dimension,
                    "score": 5,
                    "rationale": "Golden case expected clean semantic baseline.",
                    "issue_ids": [],
                }
                for dimension in SEMANTIC_DIMENSIONS
            ]
        }


class GoldenVisualProvider:
    name = "golden-visual-fixture"
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


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M4 sidecar is required for M5 golden integration",
)
def test_m5_golden_management_decision_case(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    manifest = json.loads((repository / "golden/m5/manifest.json").read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    expected = case["expected"]
    source = repository / case["source"]
    renderer = _renderer_root()
    assert renderer is not None

    workspace = init_workspace(tmp_path / "workspace", title="M5 Golden")
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
    m5 = M5ApplicationService(
        workspace,
        semantic_provider=GoldenSemanticProvider(),
        visual_provider=GoldenVisualProvider(),
        renderer_root=renderer,
        font_match=str(_font_match(tmp_path)),
    ).run()

    quality = json.loads((workspace / "review/quality_report.json").read_text(encoding="utf-8"))
    rendered_pages = [
        item
        for item in json.loads((workspace / "renders/render_manifest.json").read_text(encoding="utf-8"))["outputs"]
        if item["role"] == "export_png"
    ]
    assert m5.report["status"] == expected["m5_status"]
    assert m5.report["g8"]["status"] == expected["g8_status"]
    assert sum(item["severity"] == "critical" for item in quality["issues"]) == expected["critical_count"]
    assert sum(item["severity"] == "major" for item in quality["issues"]) == expected["major_count"]
    assert min(int(item["score"]) for item in quality["scores"]) >= expected["minimum_semantic_score"]
    assert len(rendered_pages) >= expected["minimum_rendered_pages"]
