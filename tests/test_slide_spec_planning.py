from __future__ import annotations

from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ArtifactConflictError, SlideSpecPlanningError
from slidethus.gates import evaluate_gate
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.planning_rules import block_content_hash
from slidethus.protocols import BriefCompletionHints, PlanningLimits, PlanningProposal
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.m2_application import M2ApplicationService
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.outline_changes import OutlineChangeService
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.state_machine import Phase
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


def _complete_targeted_and_advance(workspace: Path) -> None:
    EvidenceBindingService(workspace).complete_user_material_targeted_cycle()
    runtime = ArtifactRuntime(workspace)
    runtime.record_gate("G2", target_phase=Phase.EVIDENCE_READY)
    runtime.record_gate("G3", target_phase=Phase.NARRATIVE_READY)
    runtime.record_gate("G4", target_phase=Phase.OUTLINE_READY)
    runtime.record_gate("G5A", target_phase=Phase.SLIDE_SPECS_READY)


def test_slide_specs_are_block_traceable_and_idempotent(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    service = SlideSpecPlanningService(workspace)

    first = service.generate()
    second = service.generate()

    assert first.changed
    assert not second.changed
    assert first.version == second.version
    specs = first.slide_specs
    assert specs["status"] == "approved"
    assert service.audit() == ()
    for slide in specs["slides"]:
        assert slide["status"] == "approved"
        assert slide["outline_slide_ref"]["slide_id"] == slide["slide_id"]
        assert slide["content_blocks"]
        assert len(slide["content_blocks"]) <= slide["density_budget"]["max_blocks"]
        for block in slide["content_blocks"]:
            assert block["content_hash"] == block_content_hash(block)
            assert block["origin"] == "provider"
            if block["claim_mode"] == "fact":
                assert block["evidence_ids"]
                assert block["evidence_requirement"] == "required"
    qualified = [
        block
        for slide in specs["slides"]
        for block in slide["content_blocks"]
        if block["evidence_ids"] and block["evidence_qualification"]
    ]
    assert qualified
    assert not evaluate_gate(workspace, "G5A").passed
    assert validate_workspace(workspace, check_hashes=True).ok


def test_targeted_cycle_metadata_does_not_make_planning_claim_lineage_stale(
    tmp_path: Path,
) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    SlideSpecPlanningService(workspace).generate()
    before = ArtifactRuntime(workspace).show_artifact("slide_specs")

    _complete_targeted_and_advance(workspace)

    assert evaluate_gate(workspace, "G3").passed
    assert evaluate_gate(workspace, "G4").passed
    assert evaluate_gate(workspace, "G5A").passed
    assert ArtifactRuntime(workspace).show_artifact("slide_specs") == before
    assert validate_workspace(workspace, check_hashes=True).ok


def test_slide_specs_reject_factual_block_without_evidence(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)

    class UnsupportedFactProvider(DeterministicPlanningProvider):
        name = "unsupported-fact-provider"

        def propose(self, artifact_type, context, limits):
            proposal = super().propose(artifact_type, context, limits)
            content = dict(proposal.content)
            slides = [dict(item) for item in content["slides"]]
            target = dict(slides[1])
            blocks = [dict(item) for item in target["content_blocks"]]
            blocks.append(
                {
                    "semantic_role": "metric",
                    "content_type": "metric",
                    "priority": "secondary",
                    "content": "99%",
                    "evidence_ids": [],
                    "evidence_requirement": "required",
                    "claim_mode": "fact",
                    "evidence_qualification": None,
                }
            )
            target["content_blocks"] = blocks
            slides[1] = target
            content["slides"] = slides
            return PlanningProposal(artifact_type, content)

    with pytest.raises(SlideSpecPlanningError, match="Factual block|Required block"):
        SlideSpecPlanningService(
            workspace,
            provider=UnsupportedFactProvider(),
        ).generate()


def test_outline_local_change_preserves_unaffected_block_ids(tmp_path: Path) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    first = SlideSpecPlanningService(workspace).generate().slide_specs
    outline = ArtifactRuntime(workspace).show_artifact("deck_outline")
    active = [item for item in outline["slides"] if item["status"] != "excluded"]
    target = active[3]
    unaffected = active[2]["slide_id"]
    before_ids = {
        item["slide_id"]: [block["block_id"] for block in item["content_blocks"]]
        for item in first["slides"]
    }

    OutlineChangeService(workspace).update(
        target["slide_id"],
        {
            "headline": target["headline"] + "：更新",
            "takeaway": target["takeaway"] + "，并补充一个更明确的决策含义。",
            "purpose": target["purpose"] + " 聚焦新的决策问题。",
            "audience_question": "更新后，这一页要回答什么新的决策问题？",
        },
        reason="用户要求局部修改该页命题",
        idempotency_key="update-one-slide-task",
    )
    second = SlideSpecPlanningService(workspace).generate().slide_specs

    after_ids = {
        item["slide_id"]: [block["block_id"] for block in item["content_blocks"]]
        for item in second["slides"]
    }
    assert after_ids[unaffected] == before_ids[unaffected]
    affected_spec = next(
        item for item in second["slides"] if item["slide_id"] == target["slide_id"]
    )
    assert affected_spec["core_message"].endswith("更明确的决策含义。")
    assert SlideSpecPlanningService(workspace).audit() == ()


def test_frozen_slide_spec_blocks_regeneration_after_outline_semantic_change(
    tmp_path: Path,
) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    SlideSpecPlanningService(workspace).generate()
    runtime = ArtifactRuntime(workspace)
    specs, version = runtime.read_artifact_snapshot("slide_specs")
    target = specs["slides"][2]
    target["status"] = "frozen"
    runtime.write_artifact(
        "slide_specs",
        specs,
        expected_version=version,
        status="approved",
        created_by="spec-test",
    )
    outline = runtime.show_artifact("deck_outline")
    outline_target = next(
        item for item in outline["slides"] if item["slide_id"] == target["slide_id"]
    )
    OutlineChangeService(workspace).update(
        target["slide_id"],
        {"takeaway": outline_target["takeaway"] + "，发生语义变化。"},
        reason="测试冻结页面规格",
        idempotency_key="change-frozen-spec-upstream",
    )

    with pytest.raises(SlideSpecPlanningError, match="Frozen Slide Spec"):
        SlideSpecPlanningService(workspace).generate()


def test_slide_spec_generation_rejects_stale_snapshot_on_concurrent_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _outline_ready_workspace(tmp_path)
    service = SlideSpecPlanningService(workspace)
    original_write = service.runtime.write_artifact
    raced = False

    def racing_write(artifact_type, data, **kwargs):
        nonlocal raced
        if artifact_type == "slide_specs" and not raced:
            raced = True
            SlideSpecPlanningService(workspace).generate()
        return original_write(artifact_type, data, **kwargs)

    monkeypatch.setattr(service.runtime, "write_artifact", racing_write)

    with pytest.raises(ArtifactConflictError, match="Version conflict for slide_specs"):
        service.generate()


def test_structural_and_action_blocks_keep_distinct_visible_responsibilities() -> None:
    specs = DeterministicPlanningProvider().propose(
        "slide_specs",
        {
            "deck_outline": {
                "slides": [
                    {
                        "slide_id": "S-001",
                        "slide_type": "section",
                        "headline": "Operating boundary",
                        "takeaway": "Responsibility follows the control boundary",
                        "purpose": "Separate policy from execution",
                        "audience_question": "Where should ownership sit?",
                        "evidence_ids": [],
                    },
                    {
                        "slide_id": "S-002",
                        "slide_type": "action",
                        "headline": "Decision and next step",
                        "takeaway": "Decision request: authorize the quarterly inventory cycle",
                        "purpose": "Close with an executable decision",
                        "audience_question": "What must be authorized now?",
                        "evidence_ids": [],
                    },
                ]
            },
            "evidence_ledger": {"claims": []},
            "project_brief": {"constraints": {"editability_target": "E3"}},
        },
        PlanningLimits(),
    ).content
    section_specs = [specs["slides"][0]]
    action = specs["slides"][1]

    assert section_specs
    assert all(
        [block["semantic_role"] for block in item["content_blocks"]] == ["headline"]
        for item in section_specs
    )
    non_headline = [
        block for block in action["content_blocks"] if block["semantic_role"] != "headline"
    ]
    decision = next(block for block in non_headline if block["content_type"] == "text")
    support = next(block for block in non_headline if block["content_type"] == "list")
    assert decision["content"] not in support["content"]
    assert len(support["content"]) == 3
    assert len({item.split(":", 1)[0] for item in support["content"]}) == 3


def test_high_cardinality_claim_stays_one_semantic_list_block() -> None:
    specs = DeterministicPlanningProvider().propose(
        "slide_specs",
        {
            "deck_outline": {
                "slides": [
                    {
                        "slide_id": "S-001",
                        "slide_type": "matrix",
                        "headline": "Seven controls define operational readiness",
                        "takeaway": "The operating model depends on seven explicit controls.",
                        "purpose": "Keep one classified claim coherent.",
                        "audience_question": "Which controls are required?",
                        "evidence_ids": ["EVD-001", "EVD-002"],
                    }
                ]
            },
            "evidence_ledger": {
                "claims": [
                    {
                        "evidence_id": "EVD-001",
                        "claim": "1. Intake: normalize requests 2. Policy: enforce rules 3. Routing: assign owners 4. Tools: expose actions 5. Access: limit permissions 6. Quality: measure outcomes 7. Recovery: handle exceptions",
                        "support_status": "verified",
                        "use_policy": "allowed",
                        "freshness_decision": {"status": "current"},
                    },
                    {
                        "evidence_id": "EVD-002",
                        "claim": "The controls form one operating system.",
                        "support_status": "verified",
                        "use_policy": "allowed",
                        "freshness_decision": {"status": "current"},
                    },
                ]
            },
            "project_brief": {"constraints": {"editability_target": "E3"}},
        },
        PlanningLimits(),
    ).content

    list_blocks = [
        block
        for block in specs["slides"][0]["content_blocks"]
        if block["content_type"] == "list"
    ]
    assert len(list_blocks) == 1
    assert len(list_blocks[0]["content"]) == 7
