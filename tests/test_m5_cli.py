from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from slidethus.cli import main
from slidethus.protocols import BriefCompletionHints
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.workspace import init_workspace


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def _font_match(tmp_path: Path) -> Path:
    path = tmp_path / "fc-match"
    path.write_text("#!/bin/sh\nprintf '%s\\n/fonts/test.ttf\\n' \"$3\"\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _workspace(tmp_path: Path) -> Path:
    renderer = _renderer_root()
    if renderer is None:
        pytest.skip("real M4 sidecar is required for M5 CLI integration")
    workspace = init_workspace(tmp_path / "workspace", title="M5 CLI")
    source = tmp_path / "source.md"
    source.write_text(
        "# Operating model\n\nEnterprises build data, knowledge, tools and evaluation standards.\n\n"
        "# Risk\n\nMore agents do not automatically improve quality.\n",
        encoding="utf-8",
    )
    m3 = M3ApplicationService(workspace).run(
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
    assert m3.report["status"] == "ready"
    m4 = M4ApplicationService(
        workspace,
        renderer_root=renderer,
        font_match=str(_font_match(tmp_path)),
    ).run()
    assert m4.report["status"] == "ready"
    return workspace


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M5 CLI integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_m5_cli_persists_capability_block_and_inspects_report(tmp_path: Path, capsys) -> None:
    workspace = _workspace(tmp_path)
    renderer = _renderer_root()
    assert renderer is not None

    code = main(
        [
            "m5",
            "run",
            str(workspace),
            "--renderer-root",
            str(renderer),
            "--font-match",
            str(_font_match(tmp_path)),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    report_id = output["report_id"]

    assert code == 1
    assert output["report"]["status"] == "blocked"
    assert output["report"]["blockers"][0]["code"] == "semantic_provider_missing"
    assert main(["m5", "list", str(workspace)]) == 0
    assert report_id in capsys.readouterr().out
    assert main(["m5", "show", str(workspace), report_id]) == 0
    assert '"status": "blocked"' in capsys.readouterr().out
    assert main(["m5", "gate", str(workspace)]) == 1
    assert '"status": "fail"' in capsys.readouterr().out
