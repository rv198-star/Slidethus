from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import find_repository_root
from slidethus.errors import ArtifactConflictError, EvidenceBindingError, ResearchPlanningError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import read_json
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.research import plan_explicit_targeted_research
from slidethus.state_machine import Phase
from slidethus.validation import validate_workspace


def _workspace(tmp_path: Path) -> Path:
    target = tmp_path / "project"
    shutil.copytree(find_repository_root() / "examples/minimal_project", target)
    return target


def _write_artifact(
    workspace: Path,
    artifact_type: str,
    data: dict,
    *,
    status: str = "approved",
) -> None:
    runtime = ArtifactRuntime(workspace)
    _current, version = runtime.read_artifact_snapshot(artifact_type)
    runtime.write_artifact(
        artifact_type,
        data,
        expected_version=version,
        status=status,
        created_by="evidence-binding-test",
    )


def _required_empty_block(workspace: Path) -> str:
    runtime = ArtifactRuntime(workspace)
    specs = runtime.show_artifact("slide_specs")
    block = specs["slides"][2]["content_blocks"][0]
    block["evidence_requirement"] = "required"
    block["evidence_ids"] = []
    _write_artifact(workspace, "slide_specs", specs)
    return str(block["block_id"])


def test_example_binding_report_passes_and_is_content_addressed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    service = EvidenceBindingService(workspace)

    first = service.analyze()
    second = service.analyze()

    assert first.report["status"] == "pass"
    assert not first.report["requires_rework"]
    assert first.report["summary"]["blocking_issue_count"] == 0
    assert first.path == second.path
    assert first.changed
    assert not second.changed
    assert validate_workspace(workspace, check_hashes=True).ok


def test_required_block_gap_blocks_g5a_and_routes_rework(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    block_id = _required_empty_block(workspace)
    service = EvidenceBindingService(workspace)

    analysis = service.analyze()

    assert analysis.report["status"] == "gaps"
    assert any(
        issue["code"] == "required_block_evidence_missing"
        and issue["block_id"] == block_id
        for issue in analysis.report["issues"]
    )
    gate = evaluate_gate(workspace, "G5A")
    assert not gate.passed
    assert f"required block evidence is missing: {block_id}" in gate.reasons

    state = service.route_rework(reason="Required block proof is missing")
    assert state["current_phase"] == "EVIDENCE_READY"
    assert {item["gate_id"] for item in state["completed_gates"]} == {"G0", "G1", "G2"}
    statuses = {item["artifact_type"]: item["status"] for item in state["artifacts"]}
    assert statuses["evidence_ledger"] == "approved"
    assert statuses["narrative_blueprint"] == "draft"
    assert statuses["deck_outline"] == "draft"
    assert statuses["slide_specs"] == "draft"
    decision = ArtifactRuntime(workspace).show_artifact("decision_log")["decisions"][-1]
    assert decision["rationale"] == "Required block proof is missing"


def test_gap_suggestions_build_stable_targeted_research_plan(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["source_policy"]["external_research"] = True
    brief["source_policy"]["allowed_source_tiers"] = ["primary", "secondary"]
    _write_artifact(workspace, "project_brief", brief)
    block_id = _required_empty_block(workspace)
    service = EvidenceBindingService(workspace)

    analysis = service.analyze()
    plan_first = service.build_targeted_plan()
    plan_second = service.build_targeted_plan()

    assert analysis.report["query_suggestions"]
    assert plan_first.plan_id == plan_second.plan_id
    assert plan_first.cycle_kind == "targeted"
    assert plan_first.outline_version == analysis.report["query_suggestions"][0][
        "outline_version"
    ]
    assert any(query.slide_id == "S-003" for query in plan_first.queries)
    assert any(block_id in suggestion.get("block_id", "") for suggestion in analysis.report["query_suggestions"])


def test_user_material_targeted_cycle_completes_idempotently(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    evidence = runtime.show_artifact("evidence_ledger")
    targeted = next(item for item in evidence["research_cycles"] if item["kind"] == "targeted")
    targeted["status"] = "pending"
    targeted["basis"] = "none_required"
    targeted["source_ids"] = []
    targeted["query_count"] = 0
    _write_artifact(workspace, "evidence_ledger", evidence)
    ArtifactRuntime(workspace).record_gate("G2", target_phase=Phase.EVIDENCE_READY)
    service = EvidenceBindingService(workspace)

    completed = service.complete_user_material_targeted_cycle()
    ArtifactRuntime(workspace).record_gate("G2", target_phase=Phase.EVIDENCE_READY)
    version_before = ArtifactRuntime(workspace).read_artifact_snapshot("evidence_ledger")[1]
    repeated = service.complete_user_material_targeted_cycle()
    version_after = ArtifactRuntime(workspace).read_artifact_snapshot("evidence_ledger")[1]

    cycle = next(item for item in completed["research_cycles"] if item["kind"] == "targeted")
    assert cycle["status"] == "complete"
    assert cycle["basis"] == "user_materials"
    assert cycle["query_count"] == 0
    assert cycle["source_ids"]
    assert repeated == completed
    assert version_after == version_before
    assert evaluate_gate(workspace, "G5A").passed


def test_web_backed_user_material_completion_requires_run_lineage(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    source_ledger = runtime.show_artifact("source_ledger")
    source_ledger["sources"][0]["kind"] = "web"
    _write_artifact(workspace, "source_ledger", source_ledger)
    evidence = ArtifactRuntime(workspace).show_artifact("evidence_ledger")
    targeted = next(item for item in evidence["research_cycles"] if item["kind"] == "targeted")
    targeted["status"] = "pending"
    targeted["basis"] = "none_required"
    _write_artifact(workspace, "evidence_ledger", evidence)
    ArtifactRuntime(workspace).record_gate("G1", target_phase=Phase.SOURCES_READY)
    ArtifactRuntime(workspace).record_gate("G2", target_phase=Phase.EVIDENCE_READY)

    with pytest.raises(EvidenceBindingError, match="requires Research Run lineage"):
        EvidenceBindingService(workspace).complete_user_material_targeted_cycle()


def test_required_qualified_evidence_needs_explicit_block_qualification(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    specs = runtime.show_artifact("slide_specs")
    block = specs["slides"][2]["content_blocks"][1]
    block["evidence_requirement"] = "required"
    assert block["evidence_ids"] == ["EVD-003"]
    _write_artifact(workspace, "slide_specs", specs)
    service = EvidenceBindingService(workspace)

    first = service.analyze(persist=False)
    assert any(
        item["code"] == "block_qualification_missing"
        and item["severity"] == "major"
        for item in first.report["issues"]
    )
    assert not evaluate_gate(workspace, "G5A").passed

    specs = ArtifactRuntime(workspace).show_artifact("slide_specs")
    specs["slides"][2]["content_blocks"][1]["evidence_qualification"] = (
        "Architecture conclusion; qualified as an internal inference."
    )
    _write_artifact(workspace, "slide_specs", specs)
    second = service.analyze(persist=False)
    assert not any(
        item["code"] == "block_qualification_missing"
        and item["block_id"] == block["block_id"]
        for item in second.report["issues"]
    )
    assert evaluate_gate(workspace, "G5A").passed


def test_historical_gap_report_remains_valid_after_artifact_update(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    first = EvidenceBindingService(workspace).analyze()
    specs = ArtifactRuntime(workspace).show_artifact("slide_specs")
    specs["slides"][0]["speaker_notes"] = "Updated after the first gap audit."
    _write_artifact(workspace, "slide_specs", specs)

    assert first.path is not None
    assert first.path.exists()
    assert validate_workspace(workspace, check_hashes=True).ok


def test_rework_rejects_changed_report_inputs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _required_empty_block(workspace)
    service = EvidenceBindingService(workspace)
    analysis = service.analyze()
    expected = {
        str(ref["artifact_type"]): int(ref["version"])
        for ref in analysis.report["inputs"].values()
        if ref is not None
    }
    outline = ArtifactRuntime(workspace).show_artifact("deck_outline")
    outline["slides"][0]["notes"].append("Concurrent outline edit")
    _write_artifact(workspace, "deck_outline", outline)

    with pytest.raises(ArtifactConflictError, match="Rework input changed"):
        ArtifactRuntime(workspace).route_rework(
            target_phase=Phase.EVIDENCE_READY,
            reason="stale report",
            expected_artifact_versions=expected,
        )


def test_explicit_targeted_plan_rejects_unknown_slide(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["source_policy"]["external_research"] = True
    brief["source_policy"]["allowed_source_tiers"] = ["primary"]
    _write_artifact(workspace, "project_brief", brief)

    with pytest.raises(ResearchPlanningError, match="unknown active slides"):
        plan_explicit_targeted_research(
            workspace,
            [("query", "purpose", "S-999")],
        )


def test_required_slide_requires_outline_evidence_to_reach_a_block(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    outline = runtime.show_artifact("deck_outline")
    outline["slides"][1]["evidence_requirement"] = "required"
    _write_artifact(workspace, "deck_outline", outline)
    specs = ArtifactRuntime(workspace).show_artifact("slide_specs")
    for block in specs["slides"][1]["content_blocks"]:
        block["evidence_ids"] = []
    _write_artifact(workspace, "slide_specs", specs)

    result = EvidenceBindingService(workspace).analyze(persist=False)

    assert any(
        item["code"] == "outline_evidence_not_bound_to_block"
        and item["severity"] == "major"
        for item in result.report["issues"]
    )
    assert any(
        reason.startswith("required slide evidence is not bound to a block: S-002")
        for reason in evaluate_gate(workspace, "G5A").reasons
    )


def test_gap_report_tampering_is_detected_by_workspace_validation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    result = EvidenceBindingService(workspace).analyze()
    assert result.path is not None
    report = read_json(result.path)
    report["summary"]["blocking_issue_count"] = 999
    result.path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(item.code == "invalid_evidence_gap_report" for item in validation.issues)
