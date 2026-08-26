from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import find_repository_root
from slidethus.errors import ArtifactConflictError, ArtifactError, GateError
from slidethus.io_utils import read_json, sha256_file
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def test_write_versions_artifact_and_preserves_history(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "project", title="Runtime")
    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["intent"]["purpose"] = "Demonstrate versioned artifact writes"

    entry = runtime.write_artifact("project_brief", brief, expected_version=1, created_by="test")

    assert entry["version"] == 2
    assert runtime.show_artifact("project_brief")["intent"]["purpose"].startswith("Demonstrate")
    assert runtime.show_artifact("project_brief", version=1)["intent"]["purpose"] == "待补充"
    assert validate_workspace(workspace, check_hashes=True).ok


def test_optimistic_lock_rejects_stale_and_manual_edits(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "project", title="Locking")
    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["intent"]["purpose"] = "First update"
    runtime.write_artifact("project_brief", brief, expected_version=1)

    with pytest.raises(ArtifactConflictError, match="Version conflict"):
        runtime.write_artifact("project_brief", brief, expected_version=1)

    brief_path = workspace / "brief/project_brief.json"
    manually_edited = read_json(brief_path)
    manually_edited["intent"]["purpose"] = "Out-of-band edit"
    brief_path.write_text(json.dumps(manually_edited, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ArtifactConflictError, match="hash conflict"):
        runtime.write_artifact("project_brief", manually_edited, expected_version=2)


def test_fault_injection_leaves_recoverable_journal(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "project", title="Recovery")
    original = read_json(workspace / "brief/project_brief.json")

    def crash_after_artifact(_event: str, path: Path, _index: int) -> None:
        if path == workspace / "brief/project_brief.json":
            raise KeyboardInterrupt("simulated process interruption")

    runtime = ArtifactRuntime(workspace, fault_injector=crash_after_artifact)
    changed = runtime.show_artifact("project_brief")
    changed["intent"]["purpose"] = "Half-written candidate"
    with pytest.raises(KeyboardInterrupt):
        runtime.write_artifact("project_brief", changed, expected_version=1)

    assert read_json(workspace / "brief/project_brief.json") != original
    recovered = ArtifactRuntime(workspace).recover()
    assert recovered and recovered[0].endswith(":rolled-back")
    assert read_json(workspace / "brief/project_brief.json") == original
    assert ArtifactRuntime(workspace).list_artifacts()[0]


def test_recovery_confirms_fully_written_valid_transaction(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "project", title="Commit Recovery")

    def crash_after_state(_event: str, path: Path, _index: int) -> None:
        if path == workspace / "project_state.json":
            raise KeyboardInterrupt("simulated crash before journal archive")

    runtime = ArtifactRuntime(workspace, fault_injector=crash_after_state)
    brief = runtime.show_artifact("project_brief")
    brief["intent"]["purpose"] = "Durable candidate"
    with pytest.raises(KeyboardInterrupt):
        runtime.write_artifact("project_brief", brief, expected_version=1)

    recovered = ArtifactRuntime(workspace).recover()
    assert recovered and recovered[0].endswith(":commit-confirmed")
    state = read_json(workspace / "project_state.json")
    assert next(item for item in state["artifacts"] if item["artifact_type"] == "project_brief")["version"] == 2
    assert validate_workspace(workspace, check_hashes=True).ok


def test_recovery_rolls_back_fully_written_invalid_transaction(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "project", title="Invalid Recovery")

    def crash_after_state(_event: str, path: Path, _index: int) -> None:
        if path == workspace / "project_state.json":
            raise KeyboardInterrupt("simulated crash before validation")

    runtime = ArtifactRuntime(workspace, fault_injector=crash_after_state)
    source_ledger = runtime.show_artifact("source_ledger")
    duplicate = {
        "source_id": "SRC-001",
        "kind": "user_file",
        "title": "Duplicate",
        "path_or_url": "input.txt",
        "ownership": "user_owned",
        "confidentiality": "internal",
        "allowed_use": "internal_only",
        "authority_tier": "user",
        "parse_status": "parsed",
        "notes": [],
    }
    source_ledger["sources"] = [duplicate, duplicate]
    with pytest.raises(KeyboardInterrupt):
        runtime.write_artifact("source_ledger", source_ledger, expected_version=1)

    recovered = ArtifactRuntime(workspace).recover()
    assert recovered and recovered[0].endswith(":rolled-back")
    assert ArtifactRuntime(workspace).show_artifact("source_ledger")["sources"] == []
    assert validate_workspace(workspace, check_hashes=True).ok


def test_cross_reference_failure_rolls_back_transaction(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "project", title="Rollback")
    runtime = ArtifactRuntime(workspace)
    source_ledger = runtime.show_artifact("source_ledger")
    duplicate = {
        "source_id": "SRC-001",
        "kind": "user_file",
        "title": "Duplicate",
        "path_or_url": "input.txt",
        "ownership": "user_owned",
        "confidentiality": "internal",
        "allowed_use": "internal_only",
        "authority_tier": "user",
        "parse_status": "parsed",
        "notes": [],
    }
    source_ledger["sources"] = [duplicate, duplicate]

    with pytest.raises(ArtifactError, match="invalid workspace"):
        runtime.write_artifact("source_ledger", source_ledger, expected_version=1)

    assert ArtifactRuntime(workspace).show_artifact("source_ledger")["sources"] == []
    assert ArtifactRuntime(workspace).list_artifacts()


def test_gate_and_project_logs_are_versioned_artifacts(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "project", title="Logs")
    runtime = ArtifactRuntime(workspace)

    gate = runtime.record_gate("G0")
    decision = runtime.record_decision(
        "Use a checkpoint approval mode",
        rationale="The initial workspace is user-facing.",
        expected_version=1,
    )
    assumption = runtime.record_assumption(
        "External research remains disabled",
        risk="low",
        expected_version=1,
    )

    assert gate.status == "blocked"
    assert decision["decision_id"] == "DEC-001"
    assert assumption["assumption_id"] == "ASM-001"
    state = read_json(workspace / "project_state.json")
    assert state["completed_gates"][0]["gate_record_id"] == "GTR-0001"
    assert next(item for item in state["artifacts"] if item["artifact_type"] == "gate_results")["version"] == 2
    assert validate_workspace(workspace, check_hashes=True).ok


def test_failed_gate_is_persisted_without_advancing_phase(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)

    result = ArtifactRuntime(workspace).record_gate("G7", target_phase=None)

    assert result.status == "fail"
    state = read_json(workspace / "project_state.json")
    assert state["current_phase"] == "VISUAL_SYSTEM_READY"
    assert next(item for item in state["completed_gates"] if item["gate_id"] == "G7")["status"] == "fail"
    assert validate_workspace(workspace, check_hashes=True).ok


def test_upstream_write_rolls_back_phase_and_invalidates_downstream_gates(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    runtime = ArtifactRuntime(workspace)
    evidence = runtime.show_artifact("evidence_ledger")
    evidence["claims"][0]["reasoning"] = "Updated evidence review"

    runtime.write_artifact("evidence_ledger", evidence, expected_version=1, created_by="test")

    state = read_json(workspace / "project_state.json")
    assert state["current_phase"] == "SOURCES_READY"
    assert {item["gate_id"] for item in state["completed_gates"]} == {"G0", "G1"}
    assert next(item for item in state["artifacts"] if item["artifact_type"] == "deck_outline")["status"] == "draft"
    assert validate_workspace(workspace, check_hashes=True).ok


def test_migrates_legacy_workspace_and_supports_dry_run(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "legacy"
    shutil.copytree(root / "examples/minimal_project", workspace)
    legacy_state = read_json(workspace / ".slidethus/history/project_state/000001.json")
    shutil.rmtree(workspace / ".slidethus")
    (workspace / "gates/gate_results.json").unlink()
    (workspace / "decisions/decision_log.json").unlink()
    (workspace / "decisions/assumption_log.json").unlink()
    (workspace / "project_state.json").write_text(
        json.dumps(legacy_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    runtime = ArtifactRuntime(workspace)
    planned = runtime.migrate_workspace(dry_run=True)
    migrated = runtime.migrate_workspace()

    assert planned["status"] == "planned"
    assert migrated["status"] == "migrated"
    assert read_json(workspace / "project_state.json")["schema_version"] == "0.2.0"
    assert validate_workspace(workspace, check_hashes=True).ok


def test_critical_gate_issue_cannot_be_waived_but_major_can(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    runtime = ArtifactRuntime(workspace)
    output_path = workspace / "outputs/final.svg"
    output_path.write_text('<svg viewBox="0 0 1280 720"></svg>\n', encoding="utf-8")
    render = runtime.show_artifact("render_manifest")
    render["status"] = "success"
    render["editability_level"] = "E4"
    render["outputs"] = [
        {
            "path": "outputs/final.svg",
            "sha256": sha256_file(output_path),
            "mime_type": "image/svg+xml",
            "slide_count": 3,
        }
    ]
    runtime.write_artifact("render_manifest", render, expected_version=1, created_by="test")
    report = runtime.show_artifact("quality_report")
    report["status"] = "fail"
    report["gate_result"] = {"gate_id": "G6", "status": "fail", "reasons": ["Injected waiver test"]}
    report["issues"] = [
        {
            "issue_id": "ISS-901",
            "severity": "critical",
            "category": "integrity",
            "phase": "P7",
            "finding": "Critical fixture",
            "impact": "Blocks delivery",
            "recommended_fix": "Fix the output",
            "verification": "Rerun G7",
            "status": "open",
        },
        {
            "issue_id": "ISS-902",
            "severity": "major",
            "category": "integrity",
            "phase": "P7",
            "finding": "Major fixture",
            "impact": "Requires explicit waiver",
            "recommended_fix": "Fix or authorize",
            "verification": "Rerun G7",
            "status": "open",
        },
    ]
    runtime.write_artifact("quality_report", report, expected_version=1, created_by="test")

    with pytest.raises(GateError, match="Critical issues cannot be waived"):
        runtime.record_gate(
            "G8",
            waive=True,
            waiver_reason="Not permitted",
            approved_by="user:test",
            issue_refs=("ISS-901",),
        )

    report = runtime.show_artifact("quality_report")
    report["issues"][0]["status"] = "fixed"
    runtime.write_artifact("quality_report", report, expected_version=2, created_by="test")
    result = runtime.record_gate(
        "G8",
        waive=True,
        waiver_reason="Accepted for a planning-only handoff",
        approved_by="user:test",
        issue_refs=("ISS-902",),
    )
    assert result.status == "waived"
    assert validate_workspace(workspace, check_hashes=True).ok
