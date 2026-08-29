from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from slidethus.errors import ReviewSynthesisError, StageReviewError
from slidethus.io_utils import atomic_create_json, read_json
from slidethus.services.review_synthesis import ReviewSynthesisService
from slidethus.services.stage_ai_review import StageAIReviewService
from slidethus.stage_ai_reviews import STAGES, stage_is_applicable
from slidethus.validation import validate_workspace
from slidethus.workflow_application_reports import workflow_report_file_key, workflow_report_id

_TRACKED = (
    "asset_manifest",
    "deck_outline",
    "evidence_ledger",
    "layout_plans",
    "narrative_blueprint",
    "project_brief",
    "render_manifest",
    "slide_specs",
    "source_ledger",
    "visual_system",
)


class ReviewProvider:
    name = "retrospective-stage-review-fixture"
    version = "1.0.0"

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        stage = context["stage"]
        if stage == "P4":
            return {
                "issues": [
                    {
                        "code": "headline_responsibility_failure",
                        "severity": "major",
                        "earliest_phase": "P4",
                        "artifact_type": "deck_outline",
                        "slide_id": "S-001",
                        "block_id": None,
                        "region_id": None,
                        "scope": "multi_slide",
                        "finding": "The outline headline is carrying body-level information instead of a single proposition.",
                        "impact": "Downstream layout and render must absorb content that should have been synthesized earlier.",
                        "generalized_pattern_hint": "Outline generation can confuse evidence/body prose with headline responsibility.",
                        "verification": "Run unrelated long-form inputs and verify headlines remain concise synthesized propositions.",
                    }
                ]
            }
        if stage == "P5B":
            return {
                "issues": [
                    {
                        "code": "layout_relation_weakness",
                        "severity": "minor",
                        "earliest_phase": "P5B",
                        "artifact_type": "layout_plans",
                        "slide_id": "S-002",
                        "block_id": None,
                        "region_id": "REG-S002-01",
                        "scope": "local",
                        "finding": "One layout region does not strongly express its semantic relationship.",
                        "impact": "The page is usable but could communicate hierarchy more efficiently.",
                        "generalized_pattern_hint": "Layout selection can under-model semantic relationships in isolated pages.",
                        "verification": "Check whether the same weakness recurs across independent pages or cases.",
                    }
                ]
            }
        return {"issues": []}


class RepairingReviewProvider(ReviewProvider):
    name = "invalid-repairing-stage-review-fixture"

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["stage"] != "P4":
            return {"issues": []}
        issue = ReviewProvider().review(context)["issues"][0]
        issue["recommended_fix"] = "Rewrite this exact headline."
        return {"issues": [issue]}


class SynthesisProvider:
    name = "whole-attempt-synthesis-fixture"
    version = "1.0.0"

    def synthesize(self, context: dict[str, Any]) -> dict[str, Any]:
        by_code = {str(item["code"]): str(item["issue_id"]) for item in context["issues"]}
        return {
            "clusters": [
                {
                    "pattern_code": "headline_semantic_responsibility",
                    "title": "Headline responsibility is not enforced",
                    "scenario_independent_statement": (
                        "A slide headline must express a synthesized page proposition rather than act as a container for body or evidence prose."
                    ),
                    "issue_ids": [by_code["headline_responsibility_failure"]],
                    "root_phase": "P4",
                    "attribution": (
                        "The downstream density symptom originates in outline semantics because the page proposition was never compressed before layout."
                    ),
                    "classification": "systemic_candidate",
                },
                {
                    "pattern_code": "isolated_layout_relation_weakness",
                    "title": "One page has a weak spatial relationship",
                    "scenario_independent_statement": (
                        "Layout regions should encode the semantic relationship between content blocks when that relationship is known."
                    ),
                    "issue_ids": [by_code["layout_relation_weakness"]],
                    "root_phase": "P5B",
                    "attribution": "The weakness is local to spatial planning and has not yet demonstrated recurrence.",
                    "classification": "systemic_candidate",
                },
            ],
            "unclustered_issue_ids": [],
        }


def _workspace(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1] / "examples" / "minimal_project"
    workspace = tmp_path / "workspace"
    shutil.copytree(source, workspace)
    return workspace


def _workflow_report(workspace: Path) -> dict[str, Any]:
    state = read_json(workspace / "project_state.json")
    entries = {str(item["artifact_type"]): item for item in state["artifacts"]}
    after = [
        {
            "artifact_type": artifact_type,
            "version": int(entries[artifact_type]["version"]),
            "content_hash": str(entries[artifact_type]["content_hash"]),
        }
        for artifact_type in _TRACKED
    ]
    after.sort(key=lambda item: item["artifact_type"])
    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "project_id": str(state["project_id"]),
        "report_id": "",
        "workflow": "create",
        "request_hash": "sha256:" + "1" * 64,
        "mutation_policy": "create_workspace",
        "status": "blocked",
        "capabilities": [],
        "actions": [
            {
                "action_id": "WFA-001",
                "stage": "review",
                "status": "blocked",
                "detail": "The production attempt terminated at an existing review capability boundary.",
                "refs": [],
            }
        ],
        "artifacts_before": [],
        "artifacts_after": after,
        "changed_artifacts": sorted(item["artifact_type"] for item in after),
        "outputs": [],
        "final_phase": str(state["current_phase"]),
        "gate_result": {"gate_id": "G8", "status": "blocked", "reasons": ["review capability unavailable"]},
        "blockers": [
            {
                "code": "semantic_provider_missing",
                "message": "The production attempt stopped at its existing review capability boundary.",
            }
        ],
    }
    report["report_id"] = workflow_report_id(report)
    root = workspace / ".slidethus" / "workflows" / "runs"
    path = root / f"{workflow_report_file_key(report)}.json"
    assert atomic_create_json(path, report)
    return report


def test_retrospective_stage_reviews_and_synthesis_are_immutable_workspace_facts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workflow = _workflow_report(workspace)
    service = StageAIReviewService(
        workspace,
        str(workflow["report_id"]),
        provider=ReviewProvider(),
    )

    reviews = service.review_all()

    assert tuple(result.report["stage"] for result in reviews) == STAGES
    assert [result.report["status"] for result in reviews].count("issues") == 2
    assert all("recommended_fix" not in issue for result in reviews for issue in result.report["issues"])
    synthesis = ReviewSynthesisService(
        workspace,
        str(workflow["report_id"]),
        provider=SynthesisProvider(),
    ).synthesize(reviews)
    clusters = {item["pattern_code"]: item for item in synthesis.report["clusters"]}

    assert synthesis.report["status"] == "issues"
    assert clusters["headline_semantic_responsibility"]["promotion_eligible"] is True
    assert clusters["headline_semantic_responsibility"]["root_phase"] == "P4"
    assert clusters["isolated_layout_relation_weakness"]["promotion_eligible"] is False
    assert validate_workspace(workspace, check_hashes=True).ok


def test_stage_applicability_requires_real_p6_p7_outputs() -> None:
    report = {
        "artifacts_after": [
            {"artifact_type": "asset_manifest"},
            {"artifact_type": "layout_plans"},
        ],
        "outputs": [],
    }

    assert stage_is_applicable("P5B", report)
    assert not stage_is_applicable("P6", report)
    assert not stage_is_applicable("P7", report)


def test_stage_review_rejects_any_pre_synthesis_repair_field(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workflow = _workflow_report(workspace)
    service = StageAIReviewService(
        workspace,
        str(workflow["report_id"]),
        provider=RepairingReviewProvider(),
    )

    with pytest.raises(StageReviewError, match="repair/mutation fields"):
        service.review("P4")


def test_synthesis_requires_complete_stage_lens_set(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workflow = _workflow_report(workspace)
    reviews = StageAIReviewService(
        workspace,
        str(workflow["report_id"]),
        provider=ReviewProvider(),
    ).review_all()

    with pytest.raises(ReviewSynthesisError, match="Missing stage lenses"):
        ReviewSynthesisService(
            workspace,
            str(workflow["report_id"]),
            provider=SynthesisProvider(),
        ).synthesize(reviews[:-1])


def test_stage_review_tampering_is_detected_by_workspace_validation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workflow = _workflow_report(workspace)
    result = StageAIReviewService(
        workspace,
        str(workflow["report_id"]),
        provider=ReviewProvider(),
    ).review("P4")
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["issues"][0]["finding"] = "tampered"
    result.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(item.code == "invalid_stage_ai_review_report" for item in validation.issues)
