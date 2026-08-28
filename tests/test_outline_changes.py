from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import OutlinePlanningError, PlanningReviewError
from slidethus.gates import evaluate_gate
from slidethus.planning_changes import planning_change_reference_errors
from slidethus.protocols import BriefCompletionHints, PlanningLimits
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.m2_application import M2ApplicationService
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.outline_changes import OutlineChangeService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _outline_ready_workspace(tmp_path: Path) -> Path:
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
    assert evaluate_gate(workspace, "G4").passed
    return workspace


def _active(outline: dict) -> list[dict]:
    return sorted(
        (item for item in outline["slides"] if item["status"] != "excluded"),
        key=lambda item: item["ordinal"],
    )


def _interior_slide(outline: dict) -> dict:
    active = _active(outline)
    counts = Counter(item["section_id"] for item in active)
    return next(
        item
        for item in active[1:-1]
        if counts[item["section_id"]] > 1 and item["status"] != "frozen"
    )


def test_insert_and_reorder_are_idempotent_and_preserve_stable_ids(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    service = OutlineChangeService(workspace)
    before = ArtifactRuntime(workspace).show_artifact("deck_outline")
    section_id = _active(before)[2]["section_id"]

    inserted = service.insert(
        {
            "section_id": section_id,
            "slide_type": "statement",
            "headline": "企业真正需要长期建设什么",
            "takeaway": "企业应长期建设 Agent 可调用的业务环境，而不是自行优化通用智能。",
            "purpose": "把企业责任和平台责任明确分层。",
            "audience_question": "企业应该把长期投入放在哪里？",
            "evidence_ids": [],
            "evidence_requirement": "none",
        },
        position=3,
        reason="补充企业建设责任边界",
        idempotency_key="insert-business-environment",
    )
    created_id = inserted.report["created_slide_ids"][0]
    assert inserted.changed
    assert _active(inserted.outline)[2]["slide_id"] == created_id
    assert set(item["slide_id"] for item in _active(before)).issubset(
        set(item["slide_id"] for item in _active(inserted.outline))
    )
    assert planning_change_reference_errors(
        workspace,
        inserted.path,
        SchemaRegistry().schema_dir,
    ) == ()

    repeated = service.insert(
        {
            "section_id": section_id,
            "slide_type": "statement",
            "headline": "企业真正需要长期建设什么",
            "takeaway": "企业应长期建设 Agent 可调用的业务环境，而不是自行优化通用智能。",
            "purpose": "把企业责任和平台责任明确分层。",
            "audience_question": "企业应该把长期投入放在哪里？",
            "evidence_ids": [],
            "evidence_requirement": "none",
        },
        position=3,
        reason="补充企业建设责任边界",
        idempotency_key="insert-business-environment",
    )
    assert not repeated.changed
    assert repeated.path == inserted.path
    with pytest.raises(PlanningReviewError, match="idempotency key"):
        service.insert(
            {
                "section_id": section_id,
                "slide_type": "statement",
                "headline": "企业真正需要长期建设什么",
                "takeaway": "企业应长期建设 Agent 可调用的业务环境，而不是自行优化通用智能。",
                "purpose": "把企业责任和平台责任明确分层。",
                "audience_question": "企业应该把长期投入放在哪里？",
                "evidence_ids": [],
                "evidence_requirement": "none",
            },
            position=3,
            reason="补充企业建设责任边界",
            idempotency_key="insert-business-environment",
            limits=PlanningLimits(max_provider_payload_bytes=1024 * 1024),
        )

    reordered = service.reorder(
        created_id,
        position=4,
        reason="先建立问题，再给出责任边界",
        idempotency_key="move-business-environment",
    )
    assert _active(reordered.outline)[3]["slide_id"] == created_id
    assert reordered.report["created_slide_ids"] == []
    assert reordered.report["excluded_slide_ids"] == []
    assert evaluate_gate(workspace, "G4").passed
    assert validate_workspace(workspace, check_hashes=True).ok


def test_outline_change_request_budget_fails_before_semantic_mutation(
    tmp_path: Path,
) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    outline = runtime.show_artifact("deck_outline")
    target = _interior_slide(outline)
    version_before = next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "deck_outline"
    )["version"]

    with pytest.raises(OutlinePlanningError, match="max_provider_payload_bytes"):
        OutlineChangeService(workspace).update(
            str(target["slide_id"]),
            {"notes": ["x" * 5000]},
            reason="验证显式操作资源边界",
            idempotency_key="oversized-update",
            limits=PlanningLimits(max_provider_payload_bytes=1024),
        )

    version_after = next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "deck_outline"
    )["version"]
    assert version_after == version_before
    assert not (workspace / ".slidethus/planning/changes").exists()


def test_exclude_preserves_historical_slide_object_and_report_mapping(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    outline = ArtifactRuntime(workspace).show_artifact("deck_outline")
    target = _interior_slide(outline)

    result = OutlineChangeService(workspace).exclude(
        target["slide_id"],
        reason="该页面与相邻论证重复",
        idempotency_key="exclude-duplicate-page",
    )

    output = next(
        item for item in result.outline["slides"] if item["slide_id"] == target["slide_id"]
    )
    assert output["status"] == "excluded"
    assert output["operation_id"] == result.report["change_id"]
    assert result.report["mappings"] == [
        {"from_slide_ids": [target["slide_id"]], "to_slide_ids": []}
    ]
    assert result.outline["target_page_count"] == outline["target_page_count"] - 1
    assert evaluate_gate(workspace, "G4").passed


def test_split_creates_new_ids_and_keeps_original_as_excluded_history(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    outline = ArtifactRuntime(workspace).show_artifact("deck_outline")
    target = _interior_slide(outline)

    result = OutlineChangeService(workspace).split(
        target["slide_id"],
        [
            {
                "headline": target["headline"] + "：事实",
                "takeaway": target["takeaway"] + "，先说明事实边界。",
                "purpose": "单独呈现事实与来源。",
                "audience_question": "当前事实是什么？",
            },
            {
                "headline": target["headline"] + "：含义",
                "takeaway": target["takeaway"] + "，再解释对决策的含义。",
                "purpose": "单独解释管理含义。",
                "audience_question": "这一事实意味着什么？",
            },
        ],
        reason="一页同时承担事实和含义，拆分降低认知负担",
        idempotency_key="split-fact-implication",
    )

    created = result.report["created_slide_ids"]
    assert len(created) == 2
    assert target["slide_id"] not in created
    original = next(
        item for item in result.outline["slides"] if item["slide_id"] == target["slide_id"]
    )
    assert original["status"] == "excluded"
    assert all(
        next(item for item in result.outline["slides"] if item["slide_id"] == slide_id)[
            "derived_from_slide_ids"
        ]
        == [target["slide_id"]]
        for slide_id in created
    )
    assert result.report["mappings"] == [
        {"from_slide_ids": [target["slide_id"]], "to_slide_ids": created}
    ]
    assert evaluate_gate(workspace, "G4").passed


def test_merge_replaces_contiguous_slides_with_one_new_identity(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    outline = ArtifactRuntime(workspace).show_artifact("deck_outline")
    active = _active(outline)
    counts = Counter(item["section_id"] for item in active)
    pair = next(
        active[index : index + 2]
        for index in range(1, len(active) - 2)
        if active[index]["section_id"] == active[index + 1]["section_id"]
        and counts[active[index]["section_id"]] > 2
    )
    slide_ids = [item["slide_id"] for item in pair]

    result = OutlineChangeService(workspace).merge(
        slide_ids,
        {
            "headline": "合并后的关键判断",
            "takeaway": "把两个相邻页面收敛为一个可独立理解的判断。",
            "purpose": "减少重复并保持证据与行动之间的连续性。",
            "audience_question": "这两个页面共同支持什么判断？",
        },
        reason="两个相邻页面承担同一论证任务",
        idempotency_key="merge-adjacent-argument",
    )

    new_id = result.report["created_slide_ids"][0]
    assert new_id not in slide_ids
    assert result.report["excluded_slide_ids"] == slide_ids
    assert result.report["mappings"] == [
        {"from_slide_ids": slide_ids, "to_slide_ids": [new_id]}
    ]
    assert all(
        next(item for item in result.outline["slides"] if item["slide_id"] == slide_id)[
            "status"
        ]
        == "excluded"
        for slide_id in slide_ids
    )
    merged = next(
        item for item in result.outline["slides"] if item["slide_id"] == new_id
    )
    assert merged["derived_from_slide_ids"] == slide_ids
    assert evaluate_gate(workspace, "G4").passed


def test_freeze_blocks_reorder_until_explicit_unfreeze(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    outline = ArtifactRuntime(workspace).show_artifact("deck_outline")
    target = _active(outline)[2]
    service = OutlineChangeService(workspace)

    frozen = service.freeze(
        target["slide_id"],
        fields=("position", "headline"),
        reason="该页顺序和标题已获用户确认",
        idempotency_key="freeze-confirmed-slide",
    )
    frozen_slide = next(
        item for item in frozen.outline["slides"] if item["slide_id"] == target["slide_id"]
    )
    assert frozen_slide["status"] == "frozen"
    assert frozen_slide["locked_fields"] == ["headline", "position"]

    with pytest.raises(OutlinePlanningError, match="locks fields"):
        service.reorder(
            target["slide_id"],
            position=4,
            reason="未经解冻尝试移动",
            idempotency_key="blocked-move",
        )

    unfrozen = service.unfreeze(
        target["slide_id"],
        reason="用户批准重新调整顺序",
        idempotency_key="unfreeze-confirmed-slide",
    )
    slide = next(
        item for item in unfrozen.outline["slides"] if item["slide_id"] == target["slide_id"]
    )
    assert slide["status"] == "approved"
    assert slide["locked_fields"] == []
    moved = service.reorder(
        target["slide_id"],
        position=4,
        reason="解冻后调整顺序",
        idempotency_key="allowed-move",
    )
    assert _active(moved.outline)[3]["slide_id"] == target["slide_id"]


def test_change_report_tampering_is_detected(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    outline = ArtifactRuntime(workspace).show_artifact("deck_outline")
    target = _interior_slide(outline)
    active_count = len(_active(outline))
    new_position = min(active_count - 1, int(target["ordinal"]) + 1)
    if new_position == int(target["ordinal"]):
        new_position = max(2, int(target["ordinal"]) - 1)
    result = OutlineChangeService(workspace).reorder(
        target["slide_id"],
        position=new_position,
        reason="测试变更报告完整性",
        idempotency_key="tamper-change-report",
    )
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["result_summary"] = "tampered"
    result.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = validate_workspace(workspace, check_hashes=True)

    assert not report.ok
    assert any(item.code == "invalid_planning_change_report" for item in report.issues)
