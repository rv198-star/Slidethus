from __future__ import annotations

import json
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import PlanningReviewError
from slidethus.gates import evaluate_gate
from slidethus.planning_rules import planning_content_units
from slidethus.protocols import BriefCompletionHints, PlanningLimits
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.m2_application import M2ApplicationService
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.planning_repair import PlanningRepairService
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
    assert evaluate_gate(workspace, "G5B").passed
    return workspace


def _introduce_long_headline(workspace: Path) -> tuple[str, int]:
    runtime = ArtifactRuntime(workspace)
    outline, version = runtime.read_artifact_snapshot("deck_outline")
    slide = next(
        item
        for item in outline["slides"]
        if item["status"] != "excluded" and item["slide_type"] not in {"cover", "section", "action"}
    )
    slide["headline"] = "超长标题用于验证稳定页面身份与局部自动修复" * 12
    runtime.write_artifact(
        "deck_outline",
        outline,
        expected_version=version,
        status="approved",
        created_by="planning-repair-test",
    )
    return str(slide["slide_id"]), version + 1


def test_automatic_headline_repair_rebuilds_only_dependent_planning_stages(
    tmp_path: Path,
) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    slide_id, changed_outline_version = _introduce_long_headline(workspace)
    runtime = ArtifactRuntime(workspace)
    narrative_before = runtime.list_artifacts()
    narrative_entry_before = next(
        item for item in narrative_before if item["artifact_type"] == "narrative_blueprint"
    )
    review = PlanningReviewService(workspace).analyze()
    issue = next(
        item
        for item in review.report["issues"]
        if item["code"] == "headline_too_long" and item["slide_id"] == slide_id
    )

    first = PlanningRepairService(workspace).apply(
        review.report["report_id"],
        issue_ids=(issue["issue_id"],),
        reason="缩短过长标题并重建受影响策划层",
    )
    second = PlanningRepairService(workspace).apply(
        review.report["report_id"],
        issue_ids=(issue["issue_id"],),
        reason="缩短过长标题并重建受影响策划层",
    )

    assert first.report["status"] == "applied"
    assert first.changed
    assert second.report == first.report
    assert second.path == first.path
    assert not second.changed
    outline = runtime.show_artifact("deck_outline")
    repaired = next(item for item in outline["slides"] if item["slide_id"] == slide_id)
    assert planning_content_units(repaired["headline"]) <= 42
    assert "…" not in repaired["headline"]
    assert next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "deck_outline"
    )["version"] > changed_outline_version
    narrative_entry_after = next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "narrative_blueprint"
    )
    assert narrative_entry_after["version"] == narrative_entry_before["version"]
    assert issue["issue_id"] not in first.report["remaining_issue_ids"]
    assert evaluate_gate(workspace, "G5B").passed
    assert validate_workspace(workspace, check_hashes=True).ok


def test_assisted_issue_is_reported_without_semantic_mutation(tmp_path: Path) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    outline, version = runtime.read_artifact_snapshot("deck_outline")
    evidence_slides = [
        item
        for item in outline["slides"]
        if item["status"] != "excluded" and item["slide_type"] == "evidence"
    ]
    assert len(evidence_slides) >= 2
    evidence_slides[1]["takeaway"] = evidence_slides[0]["takeaway"]
    runtime.write_artifact(
        "deck_outline",
        outline,
        expected_version=version,
        status="approved",
        created_by="planning-repair-test",
    )
    review = PlanningReviewService(workspace).analyze()
    issue = next(item for item in review.report["issues"] if item["code"] == "near_duplicate_takeaway")
    outline_version_before = next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "deck_outline"
    )["version"]

    result = PlanningRepairService(workspace).apply(
        review.report["report_id"],
        issue_ids=(issue["issue_id"],),
        reason="需要人工判断合并还是重新分配页面职责",
    )

    assert result.report["status"] == "blocked"
    assert result.report["result_review"] is None
    assert result.report["remaining_issue_ids"] == [issue["issue_id"]]
    alternate = PlanningRepairService(workspace).apply(
        review.report["report_id"],
        issue_ids=(issue["issue_id"],),
        reason="需要人工判断合并还是重新分配页面职责",
        limits=PlanningLimits(max_provider_payload_bytes=1024 * 1024),
    )

    assert result.report["actions"][0]["operation"] == "route_manual"
    assert result.report["planning_limits"]["max_provider_payload_bytes"] == 2 * 1024 * 1024
    assert alternate.report["repair_id"] != result.report["repair_id"]
    assert next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "deck_outline"
    )["version"] == outline_version_before
    assert validate_workspace(workspace, check_hashes=True).ok


def test_stale_review_cannot_drive_automatic_repair(tmp_path: Path) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    slide_id, _version = _introduce_long_headline(workspace)
    runtime = ArtifactRuntime(workspace)
    review = PlanningReviewService(workspace).analyze()
    issue = next(
        item
        for item in review.report["issues"]
        if item["code"] == "headline_too_long" and item["slide_id"] == slide_id
    )
    outline, version = runtime.read_artifact_snapshot("deck_outline")
    slide = next(item for item in outline["slides"] if item["slide_id"] == slide_id)
    slide["notes"].append("concurrent edit")
    runtime.write_artifact(
        "deck_outline",
        outline,
        expected_version=version,
        status="approved",
        created_by="planning-repair-test",
    )

    with pytest.raises(PlanningReviewError, match="stale"):
        PlanningRepairService(workspace).apply(
            review.report["report_id"],
            issue_ids=(issue["issue_id"],),
            reason="不允许使用旧审计修改新版本",
        )


def test_repair_report_tampering_is_detected_by_workspace_validation(
    tmp_path: Path,
) -> None:
    workspace = _layout_ready_workspace(tmp_path)
    slide_id, _version = _introduce_long_headline(workspace)
    review = PlanningReviewService(workspace).analyze()
    issue = next(
        item
        for item in review.report["issues"]
        if item["code"] == "headline_too_long" and item["slide_id"] == slide_id
    )
    result = PlanningRepairService(workspace).apply(
        review.report["report_id"],
        issue_ids=(issue["issue_id"],),
        reason="验证修复报告完整性",
    )
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["result_summary"] = "tampered"
    result.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(item.code == "invalid_planning_repair_report" for item in validation.issues)
