from __future__ import annotations

from pathlib import Path

import pytest

from slidethus.errors import WorkspaceError
from slidethus.gates import evaluate_gate
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace, normalize_project_id


def test_initialize_workspace_is_schema_valid_but_g0_blocked(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "demo", title="演示项目")
    report = validate_workspace(workspace, check_hashes=True)
    assert report.ok, report.issues
    gate = evaluate_gate(workspace, "G0")
    assert gate.status == "blocked"
    assert "blocking questions remain open" in gate.reasons


def test_project_id_fallback_is_stable() -> None:
    assert normalize_project_id("中文标题").startswith("ST-")
    assert normalize_project_id("中文标题") != normalize_project_id("另一个中文标题")
    assert normalize_project_id("Slidethus Demo") == "SLIDETHUS-DEMO"
    assert normalize_project_id("___").startswith("ST-")
    assert normalize_project_id("__Agent")[0].isalnum()


def test_force_refuses_non_stage_zero_files(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "demo", title="Safe")
    (workspace / "outline/deck_outline.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        init_workspace(workspace, title="Reset", force=True)


def test_blank_title_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        init_workspace(tmp_path / "blank", title="   ")
