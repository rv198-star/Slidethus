from __future__ import annotations

from pathlib import Path

from slidethus.cli import main
from slidethus.constants import find_repository_root
from slidethus.workspace import init_workspace


class _CliPreviewRenderer:
    def preview(self, document_path: Path, output_dir: Path) -> tuple[Path, ...]:
        from pptx import Presentation

        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = []
        for index in range(1, len(Presentation(document_path).slides) + 1):
            path = output_dir / f"slide-{index}.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\ncli-preview")
            outputs.append(path)
        return tuple(outputs)


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


def test_mvp_cli_builds_real_pptx(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# CLI MVP\n\n真实来源内容。\n", encoding="utf-8")
    monkeypatch.setattr(
        "slidethus.mvp.LibreOfficeDocumentRenderer",
        lambda: _CliPreviewRenderer(),
    )

    assert (
        main(
            [
                "mvp",
                str(tmp_path / "workspace"),
                "--source",
                str(source),
                "--title",
                "CLI MVP",
                "--max-slides",
                "3",
                "--require-preview",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"status": "ready"' in output
    assert (tmp_path / "workspace/outputs/cli-mvp.pptx").exists()
