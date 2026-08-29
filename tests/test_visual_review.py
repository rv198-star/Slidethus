from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from slidethus.errors import VisualReviewError
from slidethus.protocols import BriefCompletionHints
from slidethus.semantic_reviews import SEMANTIC_DIMENSIONS
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.semantic_review import SemanticReviewService
from slidethus.services.visual_review import VisualReviewService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace
from tests.fontconfig_fakes import write_fontconfig_tools


class CleanSemanticProvider:
    name = "clean-semantic"
    version = "1.0.0"

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": []}
        return {
            "dimensions": [
                {
                    "dimension": name,
                    "score": 5,
                    "rationale": "Fixture semantic baseline passes.",
                    "issue_ids": [],
                }
                for name in SEMANTIC_DIMENSIONS
            ]
        }


class FakeVisualProvider:
    name = "fake-visual"
    version = "1.0.0"

    def __init__(self, issues: list[dict[str, Any]] | None = None, *, add_scores: bool = False) -> None:
        self.issues = issues or []
        self.add_scores = add_scores

    def review(self, image_paths: tuple[Path, ...], context: dict[str, Any]) -> dict[str, Any]:
        assert len(image_paths) == len(context["pages"])
        result: dict[str, Any] = {"issues": self.issues}
        if self.add_scores:
            result["scores"] = [{"dimension": "composition", "score": 5}]
        return result


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def _font_match(tmp_path: Path) -> Path:
    return write_fontconfig_tools(tmp_path)


def _build_workspace(tmp_path: Path) -> Path:
    root = _renderer_root()
    if root is None:
        pytest.skip("real M4 sidecar is required for M5 visual review integration")
    workspace = init_workspace(tmp_path / "workspace", title="M5 Visual Review")
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
        renderer_root=root,
        font_match=str(_font_match(tmp_path)),
    ).run()
    assert m4.report["status"] == "ready"
    return workspace


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build_workspace(tmp_path_factory.mktemp("m5-visual-baseline"))


def _copy_workspace(baseline: Path, tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    shutil.copytree(baseline, target)
    return target


def _semantic_inputs(workspace: Path):
    semantic_service = SemanticReviewService(workspace, provider=CleanSemanticProvider())
    semantic = semantic_service.open_issues()
    scorecard = semantic_service.scorecard(semantic)
    return semantic, scorecard


def _first_slide(workspace: Path) -> str:
    import json

    outline = json.loads((workspace / "outline/deck_outline.json").read_text(encoding="utf-8"))
    return str(next(item["slide_id"] for item in outline["slides"] if item.get("status") != "excluded"))


def _visual_issue(workspace: Path, *, slide_id: str | None = None) -> dict[str, Any]:
    target = slide_id or _first_slide(workspace)
    return {
        "code": "weak_visual_hierarchy",
        "severity": "major",
        "slide_id": target,
        "related_slide_ids": [target],
        "region_id": None,
        "earliest_phase": "P6",
        "finding": "The page hierarchy does not sufficiently emphasize the decision point.",
        "impact": "The audience may miss the page's primary message.",
        "recommended_fix": "Strengthen the visual-system hierarchy for the primary message.",
        "verification": "Re-render and review the page at full-page scale.",
        "repairability": "automatic",
    }


def test_visual_review_passes_on_clean_real_png_set(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    semantic, scorecard = _semantic_inputs(workspace)

    result = VisualReviewService(workspace, provider=FakeVisualProvider()).analyze(semantic, scorecard)

    assert result.report["status"] == "pass"
    assert result.report["summary"]["page_count"] >= 3
    assert result.report["summary"]["office_page_count"] == 0
    assert {item["kind"] for item in result.report["image_set"]} == {"final_svg_png"}
    assert validate_workspace(workspace, check_hashes=True).ok


def test_visual_review_provider_absence_is_explicitly_blocked(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    semantic, scorecard = _semantic_inputs(workspace)

    result = VisualReviewService(workspace).analyze(semantic, scorecard)

    assert result.report["status"] == "blocked"
    assert result.report["capability"]["status"] == "missing"
    assert result.report["summary"]["page_count"] >= 3


def test_visual_review_rejects_unknown_slide(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    semantic, scorecard = _semantic_inputs(workspace)
    bad = _visual_issue(workspace, slide_id="S-999")

    with pytest.raises(VisualReviewError, match="unknown slides"):
        VisualReviewService(workspace, provider=FakeVisualProvider([bad])).analyze(semantic, scorecard)


def test_visual_round_a_rejects_scores(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    semantic, scorecard = _semantic_inputs(workspace)

    with pytest.raises(VisualReviewError, match="cannot contain scores"):
        VisualReviewService(workspace, provider=FakeVisualProvider(add_scores=True)).analyze(semantic, scorecard)


def test_visual_issue_routes_to_earliest_phase_and_downgrades_auto(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    semantic, scorecard = _semantic_inputs(workspace)

    result = VisualReviewService(
        workspace,
        provider=FakeVisualProvider([_visual_issue(workspace)]),
    ).analyze(semantic, scorecard)

    assert result.report["status"] == "issues"
    assert result.report["target_phase"] == "LAYOUT_READY"
    assert result.report["issues"][0]["repairability"] == "assisted"


def test_visual_report_detects_later_page_tampering(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    semantic, scorecard = _semantic_inputs(workspace)
    result = VisualReviewService(workspace, provider=FakeVisualProvider()).analyze(semantic, scorecard)
    page = workspace / result.report["image_set"][0]["path"]
    page.write_bytes(page.read_bytes() + b"tamper")

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(item.code == "invalid_visual_review_report" for item in validation.issues)
