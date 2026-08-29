from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from slidethus.cli import main
from slidethus.protocols import BriefCompletionHints
from slidethus.services.m3_application import M3ApplicationService
from slidethus.workspace import init_workspace
from tests.fontconfig_fakes import write_fontconfig_tools


def _workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="M4 CLI")
    source = tmp_path / "source.md"
    source.write_text(
        "# Operating model\n\nEnterprises build data, knowledge, tools and evaluation standards.\n\n"
        "# Risk\n\nMore agents do not automatically improve quality.\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="Create an 8-page management decision deck about an agent operating model",
            purpose="Present the agent operating model",
            desired_outcome="Approve implementation",
            call_to_action="Approve project initiation",
            delivery_context="Management meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert result.report["status"] == "ready"
    return workspace


def _font_match(tmp_path: Path) -> Path:
    return write_fontconfig_tools(tmp_path)


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def test_m4_cli_persists_and_inspects_blocked_capability_report(
    tmp_path: Path,
    capsys,
) -> None:
    workspace = _workspace(tmp_path)
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    (renderer / "render.mjs").write_text("", encoding="utf-8")
    (renderer / "preview.mjs").write_text("", encoding="utf-8")
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\necho v22.0.0\n", encoding="utf-8")
    node.chmod(0o755)

    code = main(
        [
            "m4",
            "run",
            str(workspace),
            "--renderer-root",
            str(renderer),
            "--node",
            str(node),
            "--font-match",
            str(_font_match(tmp_path)),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    report_id = output["report_id"]

    assert code == 1
    assert output["report"]["status"] == "blocked"
    assert main(["m4", "list", str(workspace)]) == 0
    assert report_id in capsys.readouterr().out
    assert main(["m4", "show", str(workspace), report_id]) == 0
    assert '"status": "blocked"' in capsys.readouterr().out
    assert main(["m4", "gate", str(workspace)]) == 1
    assert '"status": "fail"' in capsys.readouterr().out


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M4 CLI integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_m4_cli_runs_complete_production_render(tmp_path: Path, capsys) -> None:
    workspace = _workspace(tmp_path)
    root = _renderer_root()
    assert root is not None

    assert (
        main(
            [
                "m4",
                "run",
                str(workspace),
                "--renderer-root",
                str(root),
                "--font-match",
                str(_font_match(tmp_path)),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["report"]["status"] == "ready"
    assert main(["m4", "gate", str(workspace)]) == 0
    assert '"status": "pass"' in capsys.readouterr().out
