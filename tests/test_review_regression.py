from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from slidethus.gates import evaluate_gate
from slidethus.protocols import BriefCompletionHints
from slidethus.semantic_reviews import SEMANTIC_DIMENSIONS
from slidethus.services.deterministic_review import DeterministicReviewService
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.quality_review import ProductionQualityReviewService
from slidethus.services.review_regression import ReviewRegressionService
from slidethus.services.semantic_review import SemanticReviewService
from slidethus.services.visual_review import VisualReviewService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace
from tests.fontconfig_fakes import write_fontconfig_tools


class SemanticFixtureProvider:
    name = "semantic-regression-fixture"
    version = "1.0.0"

    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": self.issues}
        issue_ids = [str(item["issue_id"]) for item in context.get("issues", [])]
        return {
            "dimensions": [
                {
                    "dimension": name,
                    "score": 5,
                    "rationale": "Fixture score after explicit Round A issue mining.",
                    "issue_ids": issue_ids if name == "slide_clarity" else [],
                }
                for name in SEMANTIC_DIMENSIONS
            ]
        }


class VisualFixtureProvider:
    name = "visual-regression-fixture"
    version = "1.0.0"

    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []

    def review(self, image_paths: tuple[Path, ...], context: dict[str, Any]) -> dict[str, Any]:
        assert image_paths
        return {"issues": self.issues}


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def _font_match(tmp_path: Path) -> Path:
    return write_fontconfig_tools(tmp_path)


def _build_workspace(tmp_path: Path) -> Path:
    root = _renderer_root()
    if root is None:
        pytest.skip("real M4 sidecar is required for M5 regression integration")
    workspace = init_workspace(tmp_path / "workspace", title="M5 Regression")
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
    return _build_workspace(tmp_path_factory.mktemp("m5-regression-baseline"))


def _copy_workspace(baseline: Path, tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    shutil.copytree(baseline, target)
    return target


def _first_slide(workspace: Path) -> str:
    outline = json.loads((workspace / "outline/deck_outline.json").read_text(encoding="utf-8"))
    return str(next(item["slide_id"] for item in outline["slides"] if item.get("status") != "excluded"))


def _semantic_issue(workspace: Path) -> dict[str, Any]:
    slide_id = _first_slide(workspace)
    return {
        "code": "decision_request_is_implicit",
        "severity": "major",
        "artifact_type": "deck_outline",
        "slide_id": slide_id,
        "block_id": None,
        "region_id": None,
        "earliest_phase": "P4",
        "finding": "The decision request remains implicit.",
        "impact": "The audience may not understand the requested approval.",
        "evidence_ids": [],
        "recommended_fix": "Make the requested decision explicit in the outline.",
        "verification": "Re-review the outline responsibility after repair.",
        "repairability": "manual",
    }


def _review_chain(
    workspace: Path,
    *,
    semantic_issues: list[dict[str, Any]] | None = None,
):
    deterministic = DeterministicReviewService(workspace).analyze()
    semantic_service = SemanticReviewService(
        workspace,
        provider=SemanticFixtureProvider(semantic_issues),
    )
    semantic = semantic_service.open_issues()
    scorecard = semantic_service.scorecard(semantic)
    visual = VisualReviewService(
        workspace,
        provider=VisualFixtureProvider(),
    ).analyze(semantic, scorecard)
    regression = ReviewRegressionService(workspace).run(
        deterministic,
        semantic,
        scorecard,
        visual,
    )
    return deterministic, semantic, scorecard, visual, regression


def test_clean_regression_and_quality_report_reach_g8(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    deterministic, semantic, scorecard, visual, regression = _review_chain(workspace)

    quality = ProductionQualityReviewService(workspace).publish(
        deterministic,
        semantic,
        scorecard,
        visual,
        regression,
    )

    assert regression.report["status"] == "pass"
    assert all(item["status"] == "pass" for item in regression.report["slide_results"])
    assert quality.report["status"] == "pass"
    assert quality.report["production_review"]["issue_sources"] == []
    assert evaluate_gate(workspace, "G8").status == "pass"
    assert json.loads((workspace / "project_state.json").read_text(encoding="utf-8"))["current_phase"] == "REVIEWED"
    assert validate_workspace(workspace, check_hashes=True).ok


def test_major_semantic_issue_blocks_g8_despite_perfect_scores(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    deterministic, semantic, scorecard, visual, regression = _review_chain(
        workspace,
        semantic_issues=[_semantic_issue(workspace)],
    )

    quality = ProductionQualityReviewService(workspace).publish(
        deterministic,
        semantic,
        scorecard,
        visual,
        regression,
    )

    assert scorecard.report["summary"]["overall_score"] == 5.0
    assert quality.report["status"] == "fail"
    assert quality.report["issues"][0]["severity"] == "major"
    assert evaluate_gate(workspace, "G8").status == "fail"


def test_quality_lineage_detects_semantic_report_tampering(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    deterministic, semantic, scorecard, visual, regression = _review_chain(workspace)
    quality = ProductionQualityReviewService(workspace).publish(
        deterministic,
        semantic,
        scorecard,
        visual,
        regression,
    )
    assert quality.report["status"] == "pass"

    payload = json.loads(semantic.path.read_text(encoding="utf-8"))
    payload["capability"]["detail"] = "tampered"
    semantic.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validation = validate_workspace(workspace, check_hashes=True)
    assert not validation.ok
    assert any(item.code in {"invalid_semantic_review_report", "invalid_quality_review_report"} for item in validation.issues)
    assert evaluate_gate(workspace, "G8").status == "fail"
