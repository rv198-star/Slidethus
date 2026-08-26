from __future__ import annotations

from pathlib import Path

from slidethus.cli import main
from slidethus.constants import find_repository_root
from slidethus.workspace import init_workspace


def test_cli_accepts_split_planning_gates(capsys) -> None:
    workspace = find_repository_root() / "examples/minimal_project"
    assert main(["gate", str(workspace), "G5A"]) == 0
    assert '"status": "pass"' in capsys.readouterr().out
    assert main(["gate", str(workspace), "G5B"]) == 0


def test_artifact_cli_list_show_validate_migrate_and_recover(tmp_path: Path, capsys) -> None:
    workspace = init_workspace(tmp_path / "project", title="CLI Runtime")

    assert main(["artifact", "list", str(workspace)]) == 0
    assert '"artifact_type": "project_state"' in capsys.readouterr().out
    assert main(["artifact", "show", str(workspace), "project_brief"]) == 0
    assert '"title": "CLI Runtime"' in capsys.readouterr().out
    assert main(["artifact", "validate", str(workspace)]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["artifact", "migrate", str(workspace), "--dry-run"]) == 0
    assert '"status": "current"' in capsys.readouterr().out
    assert main(["artifact", "recover", str(workspace)]) == 0
    assert '"recovered": []' in capsys.readouterr().out
