from __future__ import annotations

import json
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import (
    ArtifactConflictError,
    M2ApplicationError,
    PlanningError,
    PlanningLimitError,
    SourceIngestionError,
)
from slidethus.io_utils import read_json, sha256_json
from slidethus.m3_application_reports import (
    inspect_m3_application_report,
    list_m3_application_reports,
    m3_finding_id,
    m3_report_file_key,
    m3_report_id,
)
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.protocols import (
    BriefCompletionHints,
    PlanningLimits,
    PlanningProposal,
    SourceParseLimits,
)
from slidethus.services.m2_application import M2ApplicationLimits, M2ApplicationService
from slidethus.services.m3_application import (
    M3ApplicationService,
    evaluate_m3_workspace_gate,
)
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _source(path: Path) -> Path:
    path.write_text(
        "# 企业建设重点\n\n企业应建设数据、知识、流程、规则、工具、权限和评价标准。\n\n"
        "# 交付原则\n\nAgent 的通用能力由平台持续推进，企业聚焦业务环境。\n\n"
        "# 风险\n\n多 Agent 数量增加并不自动提高任务质量。\n",
        encoding="utf-8",
    )
    return path


def _write_forged_report(workspace: Path, data: dict) -> Path:
    data["report_id"] = m3_report_id(data)
    path = workspace / ".slidethus/m3/runs" / f"{m3_report_file_key(data)}.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _hints() -> BriefCompletionHints:
    return BriefCompletionHints(
        request_text="给管理层做一份 10 页企业 Agent 方案汇报，推动立项决策"
    )


def test_m3_user_material_application_reaches_reviewed_g5b_and_is_idempotent(
    tmp_path: Path,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Agent Operating Model")
    source = _source(tmp_path / "source.md")
    service = M3ApplicationService(workspace)

    first = service.run((source,), brief_hints=_hints())
    semantic_refs = first.report["outputs"]["artifact_refs"]
    second = service.run((source,), brief_hints=_hints())
    third = service.run((source,), brief_hints=_hints())

    assert first.report["status"] == "ready"
    assert first.report["planning_level"] == "P5B"
    assert first.report["outputs"]["final_phase"] == "LAYOUT_READY"
    assert first.report["outputs"]["planning_review"]["critical_count"] == 0
    assert first.report["outputs"]["planning_review"]["major_count"] == 0
    assert first.report["outputs"]["wireframes"]
    assert second.report["outputs"]["artifact_refs"] == semantic_refs
    assert third.report == second.report
    assert third.path == second.path
    assert first.changed
    assert second.changed
    assert not third.changed
    assert evaluate_m3_workspace_gate(workspace)["status"] == "pass"
    assert validate_workspace(workspace, check_hashes=True).ok

    listed = list_m3_application_reports(workspace)
    assert {item["report_id"] for item in listed} >= {
        first.report["report_id"],
        second.report["report_id"],
    }
    assert inspect_m3_application_report(workspace, first.report["report_id"]) == first.report


def _m2_report_cache(workspace: Path, result) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for reference in result.report["outputs"]["m2_reports"]:
        report = read_json(workspace / reference["path"])
        stage = (
            "targeted"
            if report["inputs"]["config"]["advance_existing_planning"]
            else "orientation"
        )
        cache[stage] = reference
    return cache


def test_m3_reuses_only_current_exact_m2_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Current M2 reuse")
    source = _source(tmp_path / "source.md")
    first = M3ApplicationService(workspace).run((source,), brief_hints=_hints())
    cache = _m2_report_cache(workspace, first)

    def unexpected_m2_run(*args, **kwargs):
        del args, kwargs
        raise AssertionError("Current M2 facts should have been reused")

    monkeypatch.setattr(M2ApplicationService, "run", unexpected_m2_run)
    resumed = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=_hints(),
        reusable_m2_reports=cache,
    )

    assert resumed.report["status"] == "ready"
    actions = {
        item["stage"]: item["detail"]
        for item in resumed.report["actions"]
        if item["stage"] in {"m2_orientation", "m2_targeted"}
    }
    assert "Reused" in actions["m2_orientation"]
    assert "Reused" in actions["m2_targeted"]


def test_stale_targeted_m2_fact_is_rejected_after_specs_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Stale M2 rejection")
    source = _source(tmp_path / "source.md")
    first = M3ApplicationService(workspace).run((source,), brief_hints=_hints())
    cache = _m2_report_cache(workspace, first)
    runtime = ArtifactRuntime(workspace)
    specs, version = runtime.read_artifact_snapshot("slide_specs")
    specs["slides"][0]["revision_note"] = "Intentional semantic revision"
    runtime.write_artifact(
        "slide_specs",
        specs,
        expected_version=version,
        status="approved",
        created_by="m2-currentness-test",
    )
    original_run = M2ApplicationService.run
    calls: list[bool] = []

    def tracked_run(self, source_paths=(), **kwargs):
        calls.append(bool(kwargs.get("advance_existing_planning")))
        return original_run(self, source_paths, **kwargs)

    monkeypatch.setattr(M2ApplicationService, "run", tracked_run)
    resumed = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=_hints(),
        reusable_m2_reports=cache,
    )

    assert resumed.report["status"] == "ready"
    assert calls == [True]
    targeted = next(
        item
        for item in resumed.report["actions"]
        if item["stage"] == "m2_targeted"
    )
    assert "Reused" not in targeted["detail"]


def test_m3_stops_at_p0_when_material_brief_input_is_missing(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Unresolved Planning")

    result = M3ApplicationService(workspace).run()

    assert result.report["status"] == "needs_input"
    assert result.report["planning_level"] == "P0"
    assert result.report["outputs"]["m2_reports"] == []
    assert any(item["code"] == "brief_needs_input" for item in result.report["blockers"])
    assert validate_workspace(workspace, check_hashes=True).ok


def test_m3_source_preinspection_obeys_m2_resource_limits_before_mutation(
    tmp_path: Path,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Bounded Preinspection")
    source = _source(tmp_path / "source.md")

    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=_hints(),
        m2_limits=M2ApplicationLimits(max_total_source_bytes=10),
    )

    assert result.report["status"] == "blocked"
    assert result.report["planning_level"] == "P0"
    assert any(
        item["code"] == "source_total_bytes_exceeded"
        for item in result.report["blockers"]
    )
    assert ArtifactRuntime(workspace).show_artifact("source_ledger")["sources"] == []


def test_m3_rejects_invalid_nested_limits_before_semantic_mutation(
    tmp_path: Path,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Limit Preflight")
    runtime = ArtifactRuntime(workspace)
    before = runtime.show_artifact("project_state")["revision"]

    with pytest.raises(PlanningLimitError, match="max_sections"):
        M3ApplicationService(workspace).run(
            brief_hints=_hints(),
            planning_limits=PlanningLimits(max_sections=0),
        )
    assert runtime.show_artifact("project_state")["revision"] == before

    with pytest.raises(PlanningError, match="request_text"):
        M3ApplicationService(workspace).run(
            (_source(tmp_path / "source.md"),),
            brief_hints=BriefCompletionHints(request_text="x" * 20_001),
        )
    assert runtime.show_artifact("project_state")["revision"] == before
    assert runtime.show_artifact("source_ledger")["sources"] == []

    with pytest.raises(SourceIngestionError, match="max_chunks"):
        M3ApplicationService(workspace).run(
            brief_hints=_hints(),
            m2_limits=M2ApplicationLimits(
                source=SourceParseLimits(max_chunks=0),
            ),
        )
    assert runtime.show_artifact("project_state")["revision"] == before
    assert not (workspace / ".slidethus/m3/runs").exists()


def test_m3_rejects_planning_provider_identity_drift_before_generation(
    tmp_path: Path,
) -> None:
    provider = DeterministicPlanningProvider()
    workspace = init_workspace(tmp_path / "workspace", title="Provider Identity")
    service = M3ApplicationService(workspace, planning_provider=provider)
    provider.version = "2.0.0"

    result = service.run(
        (_source(tmp_path / "source.md"),),
        brief_hints=_hints(),
    )

    assert result.report["status"] == "failed"
    assert any(
        item["code"] == "planning_generation_failed"
        for item in result.report["blockers"]
    )
    assert "PlanningProvider identity changed" in result.report["blockers"][0]["message"]


def test_m3_checkpoints_m2_and_artifact_runtime_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m2_workspace = init_workspace(tmp_path / "m2-workspace", title="M2 Failure")
    source = _source(tmp_path / "source.md")

    def fail_m2(*args, **kwargs):
        del args, kwargs
        raise M2ApplicationError("simulated M2 runtime failure")

    monkeypatch.setattr(
        "slidethus.services.m3_application.M2ApplicationService.run",
        fail_m2,
    )
    m2_result = M3ApplicationService(m2_workspace).run(
        (source,),
        brief_hints=_hints(),
    )
    assert m2_result.report["status"] == "failed"
    assert any(
        item["code"] == "m2_orientation_failed"
        for item in m2_result.report["blockers"]
    )
    assert validate_workspace(m2_workspace, check_hashes=True).ok

    monkeypatch.undo()
    conflict_workspace = init_workspace(
        tmp_path / "conflict-workspace",
        title="Artifact Conflict",
    )

    def fail_narrative(*args, **kwargs):
        del args, kwargs
        raise ArtifactConflictError("simulated narrative optimistic-lock conflict")

    monkeypatch.setattr(
        "slidethus.services.m3_application.NarrativePlanningService.generate",
        fail_narrative,
    )
    conflict_result = M3ApplicationService(conflict_workspace).run(
        (source,),
        brief_hints=_hints(),
    )
    assert conflict_result.report["status"] == "failed"
    assert conflict_result.report["planning_level"] == "P2"
    assert any(
        item["code"] == "planning_generation_failed"
        for item in conflict_result.report["blockers"]
    )
    assert validate_workspace(conflict_workspace, check_hashes=True).ok


def test_m3_blocks_at_p2_when_required_external_research_is_unavailable(
    tmp_path: Path,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Current Agent Market")
    runtime = ArtifactRuntime(workspace)
    brief, version = runtime.read_artifact_snapshot("project_brief")
    brief["source_policy"]["external_research"] = True
    brief["source_policy"]["allowed_source_tiers"] = ["primary", "secondary"]
    runtime.write_artifact(
        "project_brief",
        brief,
        expected_version=version,
        status="draft",
        created_by="m3-application-test",
    )

    result = M3ApplicationService(workspace).run(
        (_source(tmp_path / "source.md"),),
        brief_hints=_hints(),
    )

    assert result.report["status"] == "blocked"
    assert result.report["planning_level"] == "P2"
    assert result.report["outputs"]["m2_reports"]
    assert any(item["code"] == "m2_orientation_not_ready" for item in result.report["blockers"])
    assert not (workspace / "narrative/narrative_blueprint.json").exists()


def test_m3_automatic_repair_closes_provider_long_headline_issue(tmp_path: Path) -> None:
    class LongHeadlineProvider(DeterministicPlanningProvider):
        name = "long-headline-provider"

        def propose(self, artifact_type, context, limits):
            proposal = super().propose(artifact_type, context, limits)
            if artifact_type != "deck_outline":
                return proposal
            content = dict(proposal.content)
            slides = [dict(item) for item in content["slides"]]
            target = next(
                item
                for item in slides
                if item["slide_type"] not in {"cover", "section", "action"}
            )
            target["headline"] = "超长标题用于验证稳定页面身份与局部自动修复" * 5
            content["slides"] = slides
            return PlanningProposal(
                artifact_type=proposal.artifact_type,
                content=content,
                warnings=proposal.warnings,
                assumptions=proposal.assumptions,
            )

    workspace = init_workspace(tmp_path / "workspace", title="Automatic Repair")
    result = M3ApplicationService(
        workspace,
        planning_provider=LongHeadlineProvider(),
    ).run(
        (_source(tmp_path / "source.md"),),
        brief_hints=_hints(),
        auto_repair=True,
    )

    assert result.report["status"] == "ready"
    assert result.report["outputs"]["planning_repairs"]
    assert all(
        item["status"] == "applied"
        for item in result.report["outputs"]["planning_repairs"]
    )
    assert result.report["outputs"]["planning_review"]["critical_count"] == 0
    assert result.report["outputs"]["planning_review"]["major_count"] == 0


def test_m3_checkpoints_automatic_repair_failure_as_an_application_report(
    tmp_path: Path,
) -> None:
    class RepairFailureProvider(DeterministicPlanningProvider):
        name = "repair-failure-provider"

        def __init__(self) -> None:
            super().__init__()
            self.slide_spec_calls = 0

        def propose(self, artifact_type, context, limits):
            if artifact_type == "slide_specs":
                self.slide_spec_calls += 1
                if self.slide_spec_calls >= 2:
                    raise RuntimeError("simulated repair regeneration failure")
            proposal = super().propose(artifact_type, context, limits)
            if artifact_type != "deck_outline":
                return proposal
            content = dict(proposal.content)
            slides = [dict(item) for item in content["slides"]]
            target = next(
                item
                for item in slides
                if item["slide_type"] not in {"cover", "section", "action"}
            )
            target["headline"] = "超长标题用于验证稳定页面身份与局部自动修复" * 5
            content["slides"] = slides
            return PlanningProposal(
                artifact_type=proposal.artifact_type,
                content=content,
                warnings=proposal.warnings,
                assumptions=proposal.assumptions,
            )

    workspace = init_workspace(tmp_path / "workspace", title="Repair Failure")
    result = M3ApplicationService(
        workspace,
        planning_provider=RepairFailureProvider(),
    ).run(
        (_source(tmp_path / "source.md"),),
        brief_hints=_hints(),
        auto_repair=True,
    )

    assert result.report["status"] == "failed"
    assert result.report["planning_level"] == "P4"
    assert result.report["outputs"]["final_phase"] == "OUTLINE_READY"
    assert any(
        item["code"] == "planning_repair_failed"
        for item in result.report["blockers"]
    )
    assert validate_workspace(workspace, check_hashes=True).ok


def test_m3_assisted_planning_issue_routes_formal_rework(tmp_path: Path) -> None:
    class CompetingPrimaryBlocksProvider(DeterministicPlanningProvider):
        name = "competing-primary-blocks-provider"

        def propose(self, artifact_type, context, limits):
            proposal = super().propose(artifact_type, context, limits)
            if artifact_type != "slide_specs":
                return proposal
            content = dict(proposal.content)
            slides = [dict(item) for item in content["slides"]]
            target = next(item for item in slides if len(item["content_blocks"]) >= 2)
            blocks = [dict(item) for item in target["content_blocks"]]
            for block in blocks:
                block["priority"] = "primary"
            blocks.append(
                {
                    "semantic_role": "body",
                    "content_type": "text",
                    "priority": "primary",
                    "content": "另一项需要与核心命题竞争注意力的解释内容",
                    "evidence_ids": [],
                    "evidence_requirement": "none",
                    "claim_mode": "interpretation",
                    "evidence_qualification": None,
                }
            )
            target["content_blocks"] = blocks
            content["slides"] = slides
            return PlanningProposal(
                artifact_type=proposal.artifact_type,
                content=content,
                warnings=proposal.warnings,
                assumptions=proposal.assumptions,
            )

    workspace = init_workspace(tmp_path / "workspace", title="Assisted Repair")
    result = M3ApplicationService(
        workspace,
        planning_provider=CompetingPrimaryBlocksProvider(),
    ).run(
        (_source(tmp_path / "source.md"),),
        brief_hints=_hints(),
        auto_repair=True,
    )

    assert result.report["status"] == "rework_required"
    assert result.report["planning_level"] == "P5A"
    assert result.report["outputs"]["final_phase"] == "SLIDE_SPECS_READY"
    assert any(
        item["code"] == "planning_review_requires_rework"
        for item in result.report["blockers"]
    )


def test_rehashed_m3_report_cannot_forge_provider_sources_or_planning_level(
    tmp_path: Path,
) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="M3 Rehash Integrity")
    source = _source(tmp_path / "source.md")
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=_hints(),
    )

    provider_forgery = json.loads(json.dumps(result.report))
    provider_forgery["inputs"]["config"]["planning_provider"]["name"] = "forged-provider"
    provider_forgery["inputs"]["config_hash"] = (
        "sha256:" + sha256_json(provider_forgery["inputs"]["config"])
    )
    _write_forged_report(workspace, provider_forgery)

    source_forgery = json.loads(json.dumps(result.report))
    source_forgery["inputs"]["requested_sources"][0]["sha256"] = "0" * 64
    _write_forged_report(workspace, source_forgery)

    level_forgery = json.loads(json.dumps(result.report))
    level_forgery["status"] = "blocked"
    level_forgery["planning_level"] = "P5A"
    level_forgery["outputs"]["artifact_refs"] = [
        item
        for item in level_forgery["outputs"]["artifact_refs"]
        if item["artifact_type"] != "layout_plans"
    ]
    level_forgery["outputs"]["wireframes"] = []
    message = "Forged lower planning level"
    level_forgery["blockers"] = [
        {
            "finding_id": m3_finding_id("blocker", "forged_level", message),
            "code": "forged_level",
            "message": message,
        }
    ]
    _write_forged_report(workspace, level_forgery)

    validation = validate_workspace(workspace, check_hashes=True)
    messages = [
        item.message
        for item in validation.issues
        if item.code == "invalid_m3_application_report"
    ]
    assert any("PlanningProvider config disagrees" in message for message in messages)
    assert any("requested Source hash disagrees" in message for message in messages)
    assert any("planning_level disagrees" in message for message in messages)


def test_m3_report_tampering_is_detected_by_workspace_validation(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="M3 Integrity")
    result = M3ApplicationService(workspace).run(
        (_source(tmp_path / "source.md"),),
        brief_hints=_hints(),
    )
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["outputs"]["final_phase"] = "COMPLETED"
    result.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(item.code == "invalid_m3_application_report" for item in validation.issues)
