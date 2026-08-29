from __future__ import annotations

from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ArtifactConflictError, OutlinePlanningError
from slidethus.gates import evaluate_gate
from slidethus.planning_provider import DeterministicPlanningProvider, _page_proposition
from slidethus.protocols import BriefCompletionHints, PlanningLimits, PlanningProposal
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.m2_application import M2ApplicationService
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _narrative_ready_workspace(tmp_path: Path) -> Path:
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
    assert evaluate_gate(workspace, "G3").passed
    return workspace


def test_outline_generation_creates_stable_digital_sticky_notes(tmp_path: Path) -> None:
    workspace = _narrative_ready_workspace(tmp_path)
    service = OutlinePlanningService(workspace)

    first = service.generate()
    second = service.generate()

    assert first.changed
    assert not second.changed
    assert first.version == second.version
    outline = first.outline
    active = [item for item in outline["slides"] if item["status"] != "excluded"]
    page_contract = ArtifactRuntime(workspace).show_artifact("project_brief")["constraints"]["page_count"]
    assert page_contract["min"] <= len(active) <= page_contract["target"]
    assert outline["target_page_count"] == len(active)
    assert [item["ordinal"] for item in active] == list(range(1, len(active) + 1))
    assert [item["slide_id"] for item in active] == [
        f"S-{index:03d}" for index in range(1, len(active) + 1)
    ]
    assert active[0]["slide_type"] == "cover"
    assert active[-1]["slide_type"] == "action"
    assert all(item["narrative_section_ref"] == item["section_id"] for item in active)
    assert outline["planning_lineage"]["engine"] == "production-planning-engine"
    assert {
        item["artifact_type"]
        for item in outline["planning_lineage"]["input_refs"]
    } == {"project_brief", "evidence_ledger", "narrative_blueprint"}
    assert evaluate_gate(workspace, "G4").passed
    assert service.audit() == ()
    assert validate_workspace(workspace, check_hashes=True).ok


def test_outline_rejects_required_slide_without_usable_evidence(tmp_path: Path) -> None:
    workspace = _narrative_ready_workspace(tmp_path)

    class MissingEvidenceProvider(DeterministicPlanningProvider):
        name = "missing-evidence-outline"

        def propose(self, artifact_type, context, limits):
            proposal = super().propose(artifact_type, context, limits)
            content = dict(proposal.content)
            slides = [dict(item) for item in content["slides"]]
            slides[1]["evidence_requirement"] = "required"
            slides[1]["evidence_ids"] = ["EVD-999"]
            content["slides"] = slides
            return PlanningProposal(artifact_type, content)

    with pytest.raises(OutlinePlanningError, match="requires Evidence"):
        OutlinePlanningService(
            workspace,
            provider=MissingEvidenceProvider(),
        ).generate()


def test_outline_regeneration_preserves_matching_ids_and_excludes_superseded_slides(
    tmp_path: Path,
) -> None:
    workspace = _narrative_ready_workspace(tmp_path)
    first = OutlinePlanningService(workspace).generate().outline

    class RevisedOutlineProvider(DeterministicPlanningProvider):
        name = "revised-outline-provider"

        def propose(self, artifact_type, context, limits):
            proposal = super().propose(artifact_type, context, limits)
            content = dict(proposal.content)
            slides = [dict(item) for item in content["slides"]]
            slides[2]["headline"] = "重新定义关键问题"
            slides[2]["purpose"] = "用新的页面任务替换原有第三页。"
            slides[2]["takeaway"] = "第三页现在承担新的独立论证任务。"
            content["slides"] = slides
            return PlanningProposal(artifact_type, content)

    second = OutlinePlanningService(
        workspace,
        provider=RevisedOutlineProvider(),
    ).generate().outline

    first_ids = {item["headline"]: item["slide_id"] for item in first["slides"]}
    second_active = [item for item in second["slides"] if item["status"] != "excluded"]
    unchanged = [item for item in second_active if item["headline"] in first_ids]
    assert unchanged
    assert all(item["slide_id"] == first_ids[item["headline"]] for item in unchanged)
    excluded = [item for item in second["slides"] if item["status"] == "excluded"]
    assert excluded
    assert all("Superseded" in item["revision_note"] for item in excluded)
    assert evaluate_gate(workspace, "G4").passed


def test_frozen_outline_requires_explicit_operations(tmp_path: Path) -> None:
    workspace = _narrative_ready_workspace(tmp_path)
    OutlinePlanningService(workspace).generate()
    runtime = ArtifactRuntime(workspace)
    outline, version = runtime.read_artifact_snapshot("deck_outline")
    outline["status"] = "frozen"
    runtime.write_artifact(
        "deck_outline",
        outline,
        expected_version=version,
        status="approved",
        created_by="outline-test",
    )

    with pytest.raises(OutlinePlanningError, match="Frozen Deck Outline"):
        OutlinePlanningService(workspace).generate()


def test_outline_lineage_becomes_stale_after_narrative_change(tmp_path: Path) -> None:
    workspace = _narrative_ready_workspace(tmp_path)
    OutlinePlanningService(workspace).generate()
    runtime = ArtifactRuntime(workspace)
    narrative, version = runtime.read_artifact_snapshot("narrative_blueprint")
    narrative["notes"].append("Manual narrative change")
    narrative.pop("planning_lineage", None)
    runtime.write_artifact(
        "narrative_blueprint",
        narrative,
        expected_version=version,
        status="approved",
        created_by="outline-test",
    )

    gate = evaluate_gate(workspace, "G4")
    assert not gate.passed
    assert any("stale for narrative_blueprint" in reason for reason in gate.reasons)


def test_outline_rejects_stale_snapshot_on_concurrent_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _narrative_ready_workspace(tmp_path)
    service = OutlinePlanningService(workspace)
    original_write = service.runtime.write_artifact
    raced = False

    def racing_write(artifact_type, data, **kwargs):
        nonlocal raced
        if artifact_type == "deck_outline" and not raced:
            raced = True
            OutlinePlanningService(workspace).generate()
        return original_write(artifact_type, data, **kwargs)

    monkeypatch.setattr(service.runtime, "write_artifact", racing_write)

    with pytest.raises(ArtifactConflictError, match="Version conflict for deck_outline"):
        service.generate()


def test_page_proposition_synthesizes_sequence_job_instead_of_selecting_clause() -> None:
    claims = [
        {
            "claim": (
                "First stage records incoming requests. Second stage routes exceptions "
                "to an owner. Third stage measures resolution quality."
            )
        }
    ]

    headline = _page_proposition(
        {"title": "Service operations"},
        "How should the operating path mature?",
        claims,
    )

    clauses = {
        "First stage records incoming requests",
        "Second stage routes exceptions to an owner",
        "Third stage measures resolution quality",
    }
    assert headline not in clauses
    assert headline == "3 stages form a progressive path"
    assert "…" not in headline


def test_structural_outline_uses_headline_only_framing_without_navigation_meta_copy(
    tmp_path: Path,
) -> None:
    workspace = _narrative_ready_workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    narrative = runtime.show_artifact("narrative_blueprint")
    narrative["sections"][0]["slide_budget"] = 8
    outline = DeterministicPlanningProvider().propose(
        "deck_outline",
        {
            "project_brief": runtime.show_artifact("project_brief"),
            "narrative_blueprint": narrative,
            "evidence_ledger": runtime.show_artifact("evidence_ledger"),
        },
        PlanningLimits(),
    ).content
    structural = [
        item
        for item in outline["slides"]
        if item.get("status") != "excluded" and item["slide_type"] == "section"
    ]

    assert structural
    assert all(item["takeaway"] == item["headline"] for item in structural)
    assert all("本节将回答" not in item["takeaway"] for item in structural)
    assert all(not item["takeaway"].startswith("进入") for item in structural)
