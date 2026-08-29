from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from slidethus.errors import SemanticReviewError
from slidethus.protocols import BriefCompletionHints
from slidethus.semantic_reviews import SEMANTIC_DIMENSIONS
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.semantic_review import SemanticReviewService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


class FakeSemanticProvider:
    name = "fake-semantic"
    version = "1.0.0"

    def __init__(self, issues: list[dict[str, Any]] | None = None, *, low_score: bool = False) -> None:
        self.issues = issues or []
        self.low_score = low_score

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": self.issues}
        issue_ids = [str(item["issue_id"]) for item in context.get("issues", [])]
        return {
            "dimensions": [
                {
                    "dimension": name,
                    "score": 2 if self.low_score and name == "slide_clarity" else 5,
                    "rationale": "Fixture score grounded in the admitted Round A issue set.",
                    "issue_ids": issue_ids if name == "slide_clarity" and issue_ids else [],
                }
                for name in SEMANTIC_DIMENSIONS
            ]
        }


class InvalidScoreInRoundAProvider(FakeSemanticProvider):
    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": [], "scores": [{"dimension": "slide_clarity", "score": 5}]}
        return super().review(context)


class LowScoreWithoutIssueProvider(FakeSemanticProvider):
    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": []}
        return {
            "dimensions": [
                {
                    "dimension": name,
                    "score": 2 if name == "slide_clarity" else 5,
                    "rationale": "Fixture deliberately violates the Round A binding rule.",
                    "issue_ids": [],
                }
                for name in SEMANTIC_DIMENSIONS
            ]
        }


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def _font_match(tmp_path: Path) -> Path:
    path = tmp_path / "fc-match"
    path.write_text("#!/bin/sh\nprintf '%s\\n/fonts/test.ttf\\n' \"$3\"\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _build_workspace(tmp_path: Path) -> Path:
    root = _renderer_root()
    if root is None:
        pytest.skip("real M4 sidecar is required for M5 semantic review integration")
    workspace = init_workspace(tmp_path / "workspace", title="M5 Semantic Review")
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
    return _build_workspace(tmp_path_factory.mktemp("m5-semantic-baseline"))


def _copy_workspace(baseline: Path, tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    shutil.copytree(baseline, target)
    return target


def _issue(workspace: Path, *, severity: str = "major", slide_id: str | None = None) -> dict[str, Any]:
    outline = __import__("json").loads((workspace / "outline/deck_outline.json").read_text(encoding="utf-8"))
    target = slide_id or str(next(item["slide_id"] for item in outline["slides"] if item.get("status") != "excluded"))
    return {
        "code": "decision_request_is_implicit",
        "severity": severity,
        "artifact_type": "deck_outline",
        "slide_id": target,
        "block_id": None,
        "region_id": None,
        "earliest_phase": "P4",
        "finding": "The decision request is not explicit enough on the selected slide.",
        "impact": "Executives may not know which approval is requested.",
        "evidence_ids": [],
        "recommended_fix": "Make the decision request explicit in the outline responsibility.",
        "verification": "Re-review the current outline and confirm the approval request is explicit.",
        "repairability": "manual",
    }


def test_semantic_open_issue_and_scorecard_pass_on_clean_proposal(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    service = SemanticReviewService(workspace, provider=FakeSemanticProvider())

    round_a = service.open_issues()
    scorecard = service.scorecard(round_a)

    assert round_a.report["status"] == "pass"
    assert round_a.report["issues"] == []
    assert scorecard.report["status"] == "pass"
    assert scorecard.report["summary"]["overall_score"] == 5.0
    assert validate_workspace(workspace, check_hashes=True).ok


def test_semantic_round_a_rejects_scores(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    with pytest.raises(SemanticReviewError, match="cannot contain scores"):
        SemanticReviewService(workspace, provider=InvalidScoreInRoundAProvider()).open_issues()


def test_semantic_admission_rejects_unknown_slide(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    bad = _issue(workspace, slide_id="S-999")
    with pytest.raises(SemanticReviewError, match="unknown slide"):
        SemanticReviewService(workspace, provider=FakeSemanticProvider([bad])).open_issues()


def test_semantic_blocker_cannot_be_masked_by_high_score(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    provider = FakeSemanticProvider([_issue(workspace, severity="major")])
    service = SemanticReviewService(workspace, provider=provider)

    round_a = service.open_issues()
    scorecard = service.scorecard(round_a)

    assert round_a.report["status"] == "issues"
    assert round_a.report["target_phase"] == "NARRATIVE_READY"
    assert scorecard.report["summary"]["overall_score"] == 5.0
    assert scorecard.report["summary"]["blocking_count"] == 1
    assert scorecard.report["status"] == "issues"


def test_semantic_low_score_requires_round_a_issue(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    service = SemanticReviewService(workspace, provider=LowScoreWithoutIssueProvider())
    round_a = service.open_issues()
    with pytest.raises(SemanticReviewError, match="low score lacks"):
        service.scorecard(round_a)


def test_semantic_provider_absence_is_explicitly_blocked(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    service = SemanticReviewService(workspace)

    round_a = service.open_issues()
    scorecard = service.scorecard(round_a)

    assert round_a.report["status"] == "blocked"
    assert round_a.report["capability"]["status"] == "missing"
    assert scorecard.report["status"] == "blocked"
    assert scorecard.report["capability"]["status"] == "missing"
    assert validate_workspace(workspace, check_hashes=True).ok
