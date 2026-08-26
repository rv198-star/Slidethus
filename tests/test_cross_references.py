from __future__ import annotations

import json
import shutil
from pathlib import Path

from slidethus.constants import find_repository_root
from slidethus.validation import validate_workspace


def test_unknown_block_reference_is_detected(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    layout_path = workspace / "layout/layout_plans.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    layout["plans"][0]["regions"][0]["block_id"] = "BLK-S001-99"
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    codes = {issue.code for issue in report.issues}
    assert "missing_block_ref" in codes


def test_unusable_evidence_cannot_enter_outline(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    evidence_path = workspace / "evidence/evidence_ledger.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["claims"][0]["support_status"] = "unsupported"
    evidence["claims"][0]["use_policy"] = "do_not_use"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "unusable_evidence" for issue in report.issues)


def test_duplicate_reading_order_is_detected(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    layout_path = workspace / "layout/layout_plans.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    layout["plans"][0]["reading_order"][1] = layout["plans"][0]["reading_order"][0]
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "reading_order_mismatch" for issue in report.issues)


def test_missing_asset_reference_is_detected(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    specs_path = workspace / "slides/slide_specs.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    specs["slides"][0]["content_blocks"][0]["asset_refs"] = ["AST-999"]
    specs_path.write_text(json.dumps(specs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "missing_asset_ref" for issue in report.issues)


def test_deck_id_mismatch_is_detected(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    visual_path = workspace / "design/visual_system.json"
    visual = json.loads(visual_path.read_text(encoding="utf-8"))
    visual["deck_id"] = "DECK-OTHER"
    visual_path.write_text(json.dumps(visual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "deck_id_mismatch" for issue in report.issues)


def test_unregistered_present_artifact_is_detected(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["artifacts"] = [item for item in state["artifacts"] if item["artifact_type"] != "visual_system"]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "unregistered_artifact" for issue in report.issues)


def test_unsafe_registered_path_is_rejected(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["artifacts"][0]["path"] = "../../outside.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "unsafe_workspace_path" for issue in report.issues)


def test_open_blocker_requires_blocked_status(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["blockers"] = [{"blocker_id": "BKR-999", "description": "test", "status": "open"}]
    state["status"] = "active"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "state_blocker_mismatch" for issue in report.issues)


def test_phase_requires_all_prior_gates(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["completed_gates"] = [item for item in state["completed_gates"] if item["gate_id"] != "G6"]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "missing_phase_gate" and "G6" in issue.message for issue in report.issues)


def test_reviewed_phase_requires_successful_render_and_quality_pass(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_phase"] = "REVIEWED"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    codes = {issue.code for issue in report.issues}
    assert "phase_render_mismatch" in codes
    assert "phase_review_mismatch" in codes
    assert "missing_phase_gate" in codes


def test_ready_delivery_requires_measured_editability(tmp_path: Path) -> None:
    import hashlib

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    delivery_path = workspace / "delivery/delivery_manifest.json"
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    output_path = workspace / "outputs/wireframes/S-001.svg"
    delivery["status"] = "ready"
    delivery["editability_level"] = "not_measured"
    delivery["outputs"] = [
        {
            "path": "outputs/wireframes/S-001.svg",
            "format": "svg",
            "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "validated": True,
        }
    ]
    delivery_path.write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    delivery_hash = hashlib.sha256(delivery_path.read_bytes()).hexdigest()
    for artifact in state["artifacts"]:
        if artifact["artifact_type"] == "delivery_manifest":
            artifact["sha256"] = delivery_hash
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = validate_workspace(workspace, check_hashes=True)
    assert not report.ok
    assert any(issue.code == "unmeasured_delivery_editability" for issue in report.issues)


def test_stale_targeted_research_cycle_blocks_downstream_phase(tmp_path: Path) -> None:
    import hashlib

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    evidence_path = workspace / "evidence/evidence_ledger.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    targeted = next(cycle for cycle in evidence["research_cycles"] if cycle["kind"] == "targeted")
    targeted["outline_version"] = 2
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    for artifact in state["artifacts"]:
        if artifact["artifact_type"] == "evidence_ledger":
            artifact["sha256"] = digest
    for gate in state["completed_gates"]:
        if gate["gate_id"] == "G2":
            gate["artifact_hashes"] = [digest]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = validate_workspace(workspace, check_hashes=True)
    assert not report.ok
    assert any(issue.code == "targeted_evidence_incomplete" for issue in report.issues)


def test_late_phase_cannot_drop_upstream_fact_artifact(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    (workspace / "evidence/evidence_ledger.json").unlink()
    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["artifacts"] = [item for item in state["artifacts"] if item["artifact_type"] != "evidence_ledger"]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "missing_artifact" and "evidence" in issue.path for issue in report.issues)


def test_layout_must_place_every_block_exactly_once(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    layout_path = workspace / "layout/layout_plans.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    removed = layout["plans"][0]["regions"].pop()
    layout["plans"][0]["reading_order"].remove(removed["region_id"])
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "block_coverage_mismatch" for issue in report.issues)


def test_outline_section_must_exist_in_narrative(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    outline_path = workspace / "outline/deck_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["slides"][0]["section_id"] = "SEC-99"
    outline_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "missing_section_ref" for issue in report.issues)


def test_narrative_objection_evidence_must_exist(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    narrative_path = workspace / "narrative/narrative_blueprint.json"
    narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
    narrative["objections"][0]["evidence_ids"] = ["EVD-999"]
    narrative_path.write_text(json.dumps(narrative, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "missing_evidence_ref" and "objection" in issue.message for issue in report.issues)


def test_page_count_contract_order_is_enforced(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    brief_path = workspace / "brief/project_brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    brief["constraints"]["page_count"] = {"min": 10, "target": 3, "max": 5}
    brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "invalid_page_count_range" for issue in report.issues)


def test_complete_research_cycle_with_material_basis_needs_sources(tmp_path: Path) -> None:
    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    evidence_path = workspace / "evidence/evidence_ledger.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["research_cycles"][0]["source_ids"] = []
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_workspace(workspace)
    assert any(issue.code == "schema_error" and "source_ids" in issue.path for issue in report.issues)
