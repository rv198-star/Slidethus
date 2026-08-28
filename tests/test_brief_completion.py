from __future__ import annotations

from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ArtifactConflictError, BriefCompletionError
from slidethus.gates import evaluate_gate
from slidethus.protocols import BriefCompletionHints, PlanningLimits
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.source_ingestion import SourceIngestionService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def test_request_completion_resolves_brief_and_is_idempotent(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Agent strategy")
    service = BriefCompletionService(workspace)
    hints = BriefCompletionHints(
        request_text="给管理层做一份 12 页、20 分钟的企业 Agent 方案汇报 PPTX，推动立项决策",
    )

    first = service.complete(hints)
    second = service.complete(hints)

    assert first.status == "resolved"
    assert not first.blocking_questions
    assert first.brief["audiences"][0]["role"] == "企业管理层"
    assert first.brief["intent"]["delivery_context"] == "现场汇报"
    assert first.brief["constraints"]["page_count"]["target"] == 12
    assert first.brief["constraints"]["duration_minutes"] == 20
    assert first.brief["constraints"]["output_formats"] == ["pptx"]
    assert first.brief["completion"]["status"] == "resolved"
    assert first.changed
    assert not second.changed
    assert second.version == first.version
    assert second.brief == first.brief
    assert evaluate_gate(workspace, "G0").passed
    assert validate_workspace(workspace, check_hashes=True).ok


def test_explicit_audience_needs_and_objections_override_role_defaults(
    tmp_path: Path,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Audience Contract")

    result = BriefCompletionService(workspace).complete(
        BriefCompletionHints(
            request_text="给管理层做一份方案汇报，推动立项决策",
            audience_needs=("投资回报", "组织风险"),
            audience_objections=("投入过大", "责任不清"),
        )
    )

    audience = result.brief["audiences"][0]
    assert audience["needs"] == ["投资回报", "组织风险"]
    assert audience["objections"] == ["投入过大", "责任不清"]
    assert "audiences.0.needs" in result.brief["completion"]["resolved_fields"]
    assert "audiences.0.objections" in result.brief["completion"]["resolved_fields"]
    assert not any(item["assumption_id"] == "ASM-904" for item in result.brief["assumptions"])


def test_completion_asks_only_material_audience_question(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Quarterly review")

    result = BriefCompletionService(workspace).complete()

    assert result.status == "needs_input"
    assert [item["question_id"] for item in result.blocking_questions] == ["Q-903"]
    assert result.blocking_questions[0]["field_paths"] == ["audiences.0.role"]
    assert result.brief["intent"]["purpose"].startswith("基于已入库") is False
    assert result.brief["intent"]["desired_outcome"]
    assert result.brief["intent"]["delivery_context"] == "现场演示与会后阅读"
    assert not evaluate_gate(workspace, "G0").passed


def test_source_inventory_allows_safe_purpose_inference(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Factory diagnosis")
    source = tmp_path / "source.md"
    source.write_text("# 现场问题\n\n设备停机原因需要梳理。\n", encoding="utf-8")
    SourceIngestionService(workspace).ingest(source)

    result = BriefCompletionService(workspace).complete(
        BriefCompletionHints(audience_role="现场管理者")
    )

    assert result.status == "resolved"
    assert "已入库的 1 份材料" in result.brief["intent"]["purpose"]
    assert "intent.purpose" in result.inferred_fields
    assert any(
        item["assumption_id"] == "ASM-901" for item in result.brief["assumptions"]
    )
    assert evaluate_gate(workspace, "G0").passed


def test_answer_maps_single_question_and_recomputes_completion(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Decision deck")
    service = BriefCompletionService(workspace)
    first = service.complete()
    assert first.status == "needs_input"

    answered = service.answer("Q-903", "董事会")

    assert answered.status == "resolved"
    assert answered.brief["audiences"][0]["role"] == "董事会"
    answered_question = next(
        item for item in answered.brief["open_questions"] if item["question_id"] == "Q-903"
    )
    assert answered_question["status"] == "answered"
    assert answered_question["answer"] == "董事会"
    assert evaluate_gate(workspace, "G0").passed


def test_question_limit_and_invalid_hints_fail_before_mutation(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Limits")
    runtime = ArtifactRuntime(workspace)
    before = runtime.show_artifact("project_state")["revision"]

    with pytest.raises(BriefCompletionError, match="page_target"):
        BriefCompletionService(workspace).complete(
            BriefCompletionHints(page_target=999),
            limits=PlanningLimits(max_slides=120),
        )

    after = runtime.show_artifact("project_state")["revision"]
    assert after == before


def test_brief_completion_rejects_stale_snapshot_on_concurrent_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Concurrent Brief")
    service = BriefCompletionService(workspace)
    original_write = service.runtime.write_artifact
    raced = False

    def racing_write(artifact_type, data, **kwargs):
        nonlocal raced
        if artifact_type == "project_brief" and not raced:
            raced = True
            other_runtime = ArtifactRuntime(workspace)
            other, version = other_runtime.read_artifact_snapshot("project_brief")
            other["constraints"]["brand_requirements"].append("Concurrent update")
            other_runtime.write_artifact(
                "project_brief",
                other,
                expected_version=version,
                status="draft",
                created_by="concurrent-test",
            )
        return original_write(artifact_type, data, **kwargs)

    monkeypatch.setattr(service.runtime, "write_artifact", racing_write)

    with pytest.raises(ArtifactConflictError, match="Version conflict for project_brief"):
        service.complete(BriefCompletionHints(audience_role="管理层"))

    current = ArtifactRuntime(workspace).show_artifact("project_brief")
    assert current["constraints"]["brand_requirements"] == ["Concurrent update"]
