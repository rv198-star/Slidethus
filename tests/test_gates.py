from __future__ import annotations

import json
from pathlib import Path

from slidethus.constants import find_repository_root
from slidethus.gates import evaluate_gate
from slidethus.io_utils import sha256_file, sha256_json


def _sync_runtime_metadata(workspace: Path, artifact_type: str) -> None:
    """Keep an intentional low-level Gate fixture internally consistent."""

    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    entry = next(item for item in state["artifacts"] if item["artifact_type"] == artifact_type)
    artifact_path = workspace / entry["path"]
    artifact_hash = sha256_file(artifact_path)
    entry["sha256"] = artifact_hash
    entry["content_hash"] = f"sha256:{sha256_json(json.loads(artifact_path.read_text(encoding='utf-8')))}"

    gate_path = workspace / "gates/gate_results.json"
    gate_data = json.loads(gate_path.read_text(encoding="utf-8"))
    for record in gate_data["records"]:
        for reference in record["artifact_versions"]:
            if reference["path"] == entry["path"]:
                reference["sha256"] = artifact_hash
    gate_path.write_text(json.dumps(gate_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for summary in state["completed_gates"]:
        for reference in summary["artifact_versions"]:
            if reference["path"] == entry["path"]:
                reference["sha256"] = artifact_hash
        summary["artifact_hashes"] = [item["sha256"] for item in summary["artifact_versions"]]

    gate_entry = next(item for item in state["artifacts"] if item["artifact_type"] == "gate_results")
    gate_entry["sha256"] = sha256_file(gate_path)
    gate_entry["content_hash"] = f"sha256:{sha256_json(gate_data)}"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_example_passes_planning_and_visual_gates() -> None:
    workspace = find_repository_root() / "examples/minimal_project"
    for gate_id in ["G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6"]:
        result = evaluate_gate(workspace, gate_id)
        assert result.passed, (gate_id, result.reasons)


def test_example_does_not_claim_completed_render() -> None:
    workspace = find_repository_root() / "examples/minimal_project"
    result = evaluate_gate(workspace, "G7")
    assert result.status == "fail"
    assert "render did not complete successfully" in result.reasons


def test_gate_fails_when_registered_artifact_hash_is_stale(tmp_path) -> None:
    import json
    import shutil

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    brief_path = workspace / "brief/project_brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    brief["intent"]["purpose"] = "Changed without registry update"
    brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = evaluate_gate(workspace, "G0")
    assert result.status == "fail"
    assert "validation:artifact_hash_mismatch" in result.reasons


def test_review_gate_cannot_pass_before_render_gate() -> None:
    workspace = find_repository_root() / "examples/minimal_project"
    result = evaluate_gate(workspace, "G8")
    assert result.status == "fail"
    assert "render gate has not passed" in result.reasons


def test_review_gate_rejects_a_planning_quality_report_after_render(tmp_path) -> None:
    import hashlib
    import json
    import shutil

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)

    output_path = workspace / "outputs/final.svg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('<svg viewBox="0 0 1280 720"></svg>\n', encoding="utf-8")
    output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()

    render_path = workspace / "renders/render_manifest.json"
    render = json.loads(render_path.read_text(encoding="utf-8"))
    render["status"] = "success"
    render["editability_level"] = "E4"
    render["outputs"] = [
        {
            "path": "outputs/final.svg",
            "sha256": output_hash,
            "mime_type": "image/svg+xml",
            "slide_count": 3,
        }
    ]
    render_path.write_text(json.dumps(render, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _sync_runtime_metadata(workspace, "render_manifest")

    result = evaluate_gate(workspace, "G8")
    assert result.status == "fail"
    assert "quality report does not record a passing G8 review" in result.reasons


def test_successful_render_requires_measured_editability(tmp_path) -> None:
    import json
    import shutil

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    render_path = workspace / "renders/render_manifest.json"
    render = json.loads(render_path.read_text(encoding="utf-8"))
    output_path = workspace / "outputs/wireframes/S-001.svg"
    import hashlib
    render["status"] = "success"
    render["editability_level"] = "not_measured"
    render["outputs"] = [
        {
            "path": "outputs/wireframes/S-001.svg",
            "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "mime_type": "image/svg+xml",
            "slide_count": 1,
        }
    ]
    render_path.write_text(json.dumps(render, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(render_path.read_bytes()).hexdigest()
    for artifact in state["artifacts"]:
        if artifact["artifact_type"] == "render_manifest":
            artifact["sha256"] = digest
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = evaluate_gate(workspace, "G7")
    assert result.status == "fail"
    assert "validation:unmeasured_render_editability" in result.reasons


def test_g2_requires_completed_orientation_cycle(tmp_path) -> None:
    import json
    import shutil

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    evidence_path = workspace / "evidence/evidence_ledger.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["research_cycles"][0]["status"] = "pending"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sync_runtime_metadata(workspace, "evidence_ledger")

    result = evaluate_gate(workspace, "G2")
    assert result.status == "fail"
    assert "orientation research cycle is not complete or waived" in result.reasons


def test_g5a_requires_targeted_cycle_for_current_outline_version(tmp_path) -> None:
    import json
    import shutil

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)

    evidence_path = workspace / "evidence/evidence_ledger.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    targeted = next(cycle for cycle in evidence["research_cycles"] if cycle["kind"] == "targeted")
    targeted["status"] = "pending"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_phase"] = "OUTLINE_READY"
    state["completed_gates"] = [
        gate for gate in state["completed_gates"] if gate["gate_id"] in {"G0", "G1", "G2", "G3", "G4"}
    ]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sync_runtime_metadata(workspace, "evidence_ledger")

    result = evaluate_gate(workspace, "G5A")
    assert result.status == "fail"
    assert "targeted research is incomplete for outline version 1" in result.reasons


def test_successful_render_cannot_claim_less_editability_than_target(tmp_path) -> None:
    import hashlib
    import json
    import shutil

    root = find_repository_root()
    workspace = tmp_path / "project"
    shutil.copytree(root / "examples/minimal_project", workspace)
    output_path = workspace / "outputs/final.svg"
    output_path.write_text('<svg viewBox="0 0 1280 720"></svg>\n', encoding="utf-8")
    render_path = workspace / "renders/render_manifest.json"
    render = json.loads(render_path.read_text(encoding="utf-8"))
    render["status"] = "success"
    render["target_editability_level"] = "E4"
    render["editability_level"] = "E1"
    render["outputs"] = [
        {
            "path": "outputs/final.svg",
            "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "mime_type": "image/svg+xml",
            "slide_count": 3,
        }
    ]
    render_path.write_text(json.dumps(render, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path = workspace / "project_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(render_path.read_bytes()).hexdigest()
    for artifact in state["artifacts"]:
        if artifact["artifact_type"] == "render_manifest":
            artifact["sha256"] = digest
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = evaluate_gate(workspace, "G7")
    assert result.status == "fail"
    assert "validation:editability_below_target" in result.reasons
