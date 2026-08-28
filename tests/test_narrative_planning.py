from __future__ import annotations

from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import (
    ArtifactConflictError,
    NarrativePlanningError,
    PlanningLimitError,
)
from slidethus.gates import evaluate_gate
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.protocols import (
    BriefCompletionHints,
    PlanningLimits,
    PlanningProposal,
)
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.m2_application import M2ApplicationService
from slidethus.services.narrative import NarrativePlanningService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _evidence_ready_workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="Enterprise Agent Strategy")
    BriefCompletionService(workspace).complete(
        BriefCompletionHints(
            request_text="给管理层做企业 Agent 方案汇报，推动立项决策"
        )
    )
    source = tmp_path / "source.md"
    source.write_text(
        "# 现状\n\n企业需要先建设可供 Agent 使用的数据、流程、规则和评价标准。\n\n"
        "# 风险\n\n增加 Agent 数量并不自动提升任务质量。\n",
        encoding="utf-8",
    )
    result = M2ApplicationService(workspace).run((source,))
    assert result.report["status"] == "ready"
    assert evaluate_gate(workspace, "G2").passed
    return workspace


def test_narrative_generation_is_current_traceable_and_idempotent(tmp_path: Path) -> None:
    workspace = _evidence_ready_workspace(tmp_path)
    service = NarrativePlanningService(workspace)

    first = service.generate()
    second = service.generate()

    assert first.changed
    assert not second.changed
    assert first.version == second.version
    narrative = first.narrative
    assert narrative["status"] == "approved"
    assert narrative["story_arc"] == "problem-solution-proof-action"
    assert [item["section_id"] for item in narrative["sections"]] == [
        f"SEC-{index:02d}" for index in range(1, len(narrative["sections"]) + 1)
    ]
    assert narrative["planning_lineage"]["engine"] == "production-planning-engine"
    assert {
        item["artifact_type"]
        for item in narrative["planning_lineage"]["input_refs"]
    } == {"project_brief", "evidence_ledger"}
    assert evaluate_gate(workspace, "G3").passed
    assert service.audit() == ()
    assert validate_workspace(workspace, check_hashes=True).ok


def test_narrative_rejects_provider_that_drops_all_required_evidence(tmp_path: Path) -> None:
    workspace = _evidence_ready_workspace(tmp_path)

    class EmptyProofProvider(DeterministicPlanningProvider):
        name = "empty-proof"

        def propose(self, artifact_type, context, limits):
            base = super().propose(artifact_type, context, limits)
            content = dict(base.content)
            content["sections"] = [
                {**item, "evidence_ids": ["EVD-999"]}
                for item in content["sections"]
            ]
            content["objections"] = []
            return PlanningProposal(artifact_type, content)

    with pytest.raises(NarrativePlanningError, match="contains no Evidence strategy"):
        NarrativePlanningService(workspace, provider=EmptyProofProvider()).generate()


def test_complete_provider_proposal_is_bounded_not_only_content(tmp_path: Path) -> None:
    workspace = _evidence_ready_workspace(tmp_path)

    class OversizedMessagesProvider(DeterministicPlanningProvider):
        name = "oversized-messages-provider"

        def propose(self, artifact_type, context, limits):
            base = super().propose(artifact_type, context, limits)
            return PlanningProposal(
                artifact_type=base.artifact_type,
                content=base.content,
                warnings=tuple(f"{index:02d}-" + "w" * 3997 for index in range(24)),
                assumptions=base.assumptions,
            )

    with pytest.raises(PlanningLimitError, match="max_provider_payload_bytes"):
        NarrativePlanningService(
            workspace,
            provider=OversizedMessagesProvider(),
        ).generate(
            limits=PlanningLimits(max_provider_payload_bytes=64 * 1024),
        )
    assert not (workspace / "narrative/narrative_blueprint.json").exists()


def test_narrative_provider_identity_mutation_is_rejected(tmp_path: Path) -> None:
    workspace = _evidence_ready_workspace(tmp_path)

    class MutatingProvider(DeterministicPlanningProvider):
        name = "mutating-provider"

        def propose(self, artifact_type, context, limits):
            result = super().propose(artifact_type, context, limits)
            self.version = "2.0.0"
            return result

    with pytest.raises(NarrativePlanningError, match="identity changed"):
        NarrativePlanningService(workspace, provider=MutatingProvider()).generate()
    assert not (workspace / "narrative/narrative_blueprint.json").exists()


def test_narrative_lineage_becomes_stale_after_brief_change(tmp_path: Path) -> None:
    workspace = _evidence_ready_workspace(tmp_path)
    NarrativePlanningService(workspace).generate()
    assert evaluate_gate(workspace, "G3").passed

    runtime = ArtifactRuntime(workspace)
    brief, version = runtime.read_artifact_snapshot("project_brief")
    brief.pop("completion", None)
    brief["constraints"]["brand_requirements"].append("New brand requirement")
    runtime.write_artifact(
        "project_brief",
        brief,
        expected_version=version,
        status="approved",
        created_by="narrative-test",
    )

    gate = evaluate_gate(workspace, "G3")
    assert not gate.passed
    assert any("stale for project_brief" in reason for reason in gate.reasons)


def test_narrative_rejects_stale_snapshot_on_concurrent_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _evidence_ready_workspace(tmp_path)
    service = NarrativePlanningService(workspace)
    original_write = service.runtime.write_artifact
    raced = False

    def racing_write(artifact_type, data, **kwargs):
        nonlocal raced
        if artifact_type == "narrative_blueprint" and not raced:
            raced = True
            other = NarrativePlanningService(workspace)
            other.generate()
        return original_write(artifact_type, data, **kwargs)

    monkeypatch.setattr(service.runtime, "write_artifact", racing_write)

    with pytest.raises(ArtifactConflictError, match="Version conflict for narrative_blueprint"):
        service.generate(limits=PlanningLimits(max_sections=8))

    current = ArtifactRuntime(workspace).show_artifact("narrative_blueprint")
    assert current["planning_lineage"]["provider"]["name"] == "deterministic-planning-provider"
