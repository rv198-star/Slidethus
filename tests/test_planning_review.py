from __future__ import annotations

import json
from pathlib import Path

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.planning_reviews import planning_review_reference_errors
from slidethus.protocols import BriefCompletionHints
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.m2_application import M2ApplicationService
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.planning_review import PlanningReviewService
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.state_machine import Phase
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _layout_ready_workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="Agent Operating Model")
    BriefCompletionService(workspace).complete(
        BriefCompletionHints(
            request_text="给管理层做一份 10 页企业 Agent 方案汇报，推动立项决策"
        )
    )
    source = tmp_path / "source.md"
    source.write_text(
        "# 企业建设重点\n\n企业应建设数据、知识、流程、规则、工具、权限和评价标准。\n\n"
        "# 交付原则\n\nAgent 的通用能力由平台持续推进，企业聚焦业务环境。\n\n"
        "# 风险\n\n多 Agent 数量增加并不自动提高任务质量。\n",
        encoding="utf-8",
    )
    assert M2ApplicationService(workspace).run((source,)).report["status"] == "ready"
    NarrativePlanningService(workspace).generate()
    OutlinePlanningService(workspace).generate()
    SlideSpecPlanningService(workspace).generate()
    EvidenceBindingService(workspace).complete_user_material_targeted_cycle()
    runtime = ArtifactRuntime(workspace)
    runtime.record_gate("G2", target_phase=Phase.EVIDENCE_READY)
    runtime.record_gate("G3", target_phase=Phase.NARRATIVE_READY)
    runtime.record_gate("G4", target_phase=Phase.OUTLINE_READY)
    runtime.record_gate("G5A", target_phase=Phase.SLIDE_SPECS_READY)
    LayoutPlanningService(workspace).generate()
    runtime.record_gate("G5B", target_phase=Phase.LAYOUT_READY)
    return workspace


def test_planning_review_has_no_blocking_issue_on_current_production_chain(
    tmp_path: Path,
) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    service = PlanningReviewService(workspace)

    first = service.analyze()
    second = service.analyze()

    assert first.report["summary"]["critical_count"] == 0
    assert first.report["summary"]["major_count"] == 0
    assert not first.report["requires_rework"]
    assert first.report["target_phase"] is None
    assert first.changed
    assert not second.changed
    assert second.path == first.path
    assert {
        item["artifact_type"] for item in first.report["inputs"]
    } == {
        "project_brief",
        "evidence_ledger",
        "narrative_blueprint",
        "deck_outline",
        "slide_specs",
        "layout_plans",
    }
    assert planning_review_reference_errors(
        workspace,
        first.path,
        SchemaRegistry().schema_dir,
    ) == ()
    assert validate_workspace(workspace, check_hashes=True).ok


def test_outline_review_rejects_truncated_fragment_headline() -> None:
    issues = PlanningReviewService._outline_issues(
        None,
        {
            "slides": [
                {
                    "slide_id": "S-001",
                    "slide_type": "evidence",
                    "headline": "Shift from intake fragments…to accountable resolution…",
                    "takeaway": "Accountable resolution requires a complete operating path.",
                    "evidence_ids": [],
                    "status": "approved",
                }
            ]
        },
        {},
        {"claims": []},
        {"sections": []},
    )

    assert "headline_contains_truncation_marker" in {item["code"] for item in issues}


def _rhythm_fixture(*, same_geometry: bool) -> tuple[dict, dict]:
    plans = []
    specs = []
    relationships = ["sequence", "comparison", "hierarchy", "evidence", "decision"]
    for index, relationship in enumerate(relationships, start=1):
        slide_id = f"S-{index:03d}"
        body_y = 230 if same_geometry else 180 + index * 72
        body_x = 120 if same_geometry else 40 + index * 120
        body_w = 1040 if same_geometry else 1200 - index * 120
        plans.append(
            {
                "slide_id": slide_id,
                "layout_family": (
                    f"semantic-{index}" if same_geometry else "editorial-ledger"
                ),
                "regions": [
                    {
                        "region_id": f"REG-S{index:03d}-01",
                        "role": "headline",
                        "x": 80,
                        "y": 60,
                        "w": 1120,
                        "h": 120,
                    },
                    {
                        "region_id": f"REG-S{index:03d}-02",
                        "role": "body",
                        "x": body_x,
                        "y": body_y,
                        "w": body_w,
                        "h": 300,
                    },
                ],
                "diagnostics": {"content_units": 10, "capacity_units": 100},
            }
        )
        specs.append(
            {
                "slide_id": slide_id,
                "slide_type": "evidence",
                "visual_intent": {"relationship": relationship},
            }
        )
    return {"plans": plans}, {"slides": specs}


def test_layout_rhythm_uses_geometry_not_shared_semantic_family() -> None:
    layout, specs = _rhythm_fixture(same_geometry=False)

    issues = PlanningReviewService._layout_issues(
        object.__new__(PlanningReviewService),
        layout,
        specs,
    )

    codes = {item["code"] for item in issues}
    assert "repetitive_layout_rhythm" not in codes
    assert "layout_relationship_topology_collapse" not in codes


def test_layout_rhythm_cannot_be_gamed_by_renaming_identical_geometry() -> None:
    layout, specs = _rhythm_fixture(same_geometry=True)

    issues = PlanningReviewService._layout_issues(
        object.__new__(PlanningReviewService),
        layout,
        specs,
    )

    by_code = {item["code"]: item for item in issues}
    assert by_code["repetitive_layout_rhythm"]["severity"] == "major"
    assert by_code["layout_relationship_topology_collapse"]["severity"] == "major"


def test_review_routes_outline_contract_break_to_p4(tmp_path: Path) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    outline, version = runtime.read_artifact_snapshot("deck_outline")
    active = [item for item in outline["slides"] if item["status"] != "excluded"]
    active[2]["takeaway"] = active[1]["takeaway"]
    runtime.write_artifact(
        "deck_outline",
        outline,
        expected_version=version,
        status="approved",
        created_by="review-test",
    )

    report = PlanningReviewService(workspace).analyze().report

    assert report["requires_rework"]
    assert report["target_phase"] == "OUTLINE_READY"
    assert report["summary"]["major_count"] >= 1
    assert any(
        item["code"] in {"g4_contract_failure", "near_duplicate_takeaway"}
        for item in report["issues"]
    )


def test_historical_review_remains_valid_after_planning_advances(tmp_path: Path) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    first = PlanningReviewService(workspace).analyze()
    runtime = ArtifactRuntime(workspace)
    layout, version = runtime.read_artifact_snapshot("layout_plans")
    layout["plans"][0]["revision_note"] = "Later review note"
    runtime.write_artifact(
        "layout_plans",
        layout,
        expected_version=version,
        status="approved",
        created_by="review-test",
    )

    assert planning_review_reference_errors(
        workspace,
        first.path,
        SchemaRegistry().schema_dir,
    ) == ()


def test_review_report_tamper_is_detected_by_workspace_validation(tmp_path: Path) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    result = PlanningReviewService(workspace).analyze()
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["summary"]["overall_score"] = 5
    result.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(item.code == "invalid_planning_review_report" for item in validation.issues)
