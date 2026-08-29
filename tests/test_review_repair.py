from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from slidethus.gates import evaluate_gate
from slidethus.protocols import BriefCompletionHints
from slidethus.services.deterministic_review import DeterministicReviewService
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.review_repair import (
    ReviewRepairExecutionService,
    ReviewRepairPlanService,
)
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def _font_match(tmp_path: Path) -> Path:
    path = tmp_path / "fc-match"
    path.write_text("#!/bin/sh\nprintf '%s\\n/fonts/test.ttf\\n' \"$3\"\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _build_workspace(tmp_path: Path) -> Path:
    root = _renderer_root()
    if root is None:
        pytest.skip("real M4 sidecar is required for M5 repair integration")
    workspace = init_workspace(tmp_path / "workspace", title="M5 Repair")
    source = tmp_path / "source.md"
    source.write_text(
        "# Enterprise operating model\n\n"
        "Enterprises build data, knowledge, process, rules, tools, permissions and evaluation standards.\n\n"
        "# Risk\n\nAdding more agents does not automatically improve task quality.\n",
        encoding="utf-8",
    )
    m3 = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="Create an 8-page management decision deck about an enterprise agent operating model",
            purpose="Present the enterprise agent operating model",
            desired_outcome="Approve implementation",
            call_to_action="Approve project initiation",
            delivery_context="Management decision meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert m3.report["status"] == "ready"
    m4 = M4ApplicationService(
        workspace,
        renderer_root=root,
        font_match=str(_font_match(tmp_path)),
    ).run()
    assert m4.report["status"] == "ready"
    return workspace


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build_workspace(tmp_path_factory.mktemp("m5-repair-baseline"))


def _copy_workspace(baseline: Path, tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    shutil.copytree(baseline, target)
    return target


def _first_output(workspace: Path, role: str = "export_png") -> Path:
    manifest = json.loads((workspace / "renders/render_manifest.json").read_text(encoding="utf-8"))
    output = next(item for item in manifest["outputs"] if item["role"] == role)
    return workspace / output["path"]


def test_downstream_render_failure_does_not_reverse_early_gates(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    _first_output(workspace).unlink()

    assert all(evaluate_gate(workspace, gate).status == "pass" for gate in ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6"))
    assert evaluate_gate(workspace, "G7").status == "fail"


def test_missing_generated_output_is_rerendered_at_p7(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    missing = _first_output(workspace)
    missing.unlink()
    deterministic = DeterministicReviewService(workspace).analyze()
    assert deterministic.report["status"] == "issues"

    plan = ReviewRepairPlanService(workspace).plan(deterministic)
    assert plan.plan["status"] == "planned"
    assert plan.plan["target_phase"] == "VISUAL_SYSTEM_READY"
    assert plan.plan["actions"][0]["operation"] == "rerender_missing_outputs"
    assert plan.plan["actions"][0]["automatic"] is True

    result = ReviewRepairExecutionService(
        workspace,
        renderer_root=_renderer_root(),
        font_match=str(_font_match(tmp_path)),
    ).execute(plan)

    assert result.report["status"] == "applied"
    assert result.report["rerendered"] is True
    assert result.report["result_deterministic"]["status"] == "pass"
    assert missing.is_file()
    assert validate_workspace(workspace, check_hashes=True).ok


def test_existing_corrupt_output_is_not_overwritten_automatically(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    corrupt = _first_output(workspace)
    original = corrupt.read_bytes()
    corrupt.write_bytes(original + b"tamper")
    deterministic = DeterministicReviewService(workspace).analyze()

    plan = ReviewRepairPlanService(workspace).plan(deterministic)
    assert plan.plan["issues"][0]["repairability"] == "assisted"
    assert all(item["automatic"] is False for item in plan.plan["actions"])

    result = ReviewRepairExecutionService(
        workspace,
        renderer_root=_renderer_root(),
        font_match=str(_font_match(tmp_path)),
    ).execute(plan)

    assert result.report["status"] == "blocked"
    assert result.report["rerendered"] is False
    assert corrupt.read_bytes() == original + b"tamper"


def test_clean_review_requires_no_repair(baseline: Path, tmp_path: Path) -> None:
    workspace = _copy_workspace(baseline, tmp_path)
    deterministic = DeterministicReviewService(workspace).analyze()
    assert deterministic.report["status"] == "pass"

    plan = ReviewRepairPlanService(workspace).plan(deterministic)
    result = ReviewRepairExecutionService(workspace).execute(plan)

    assert plan.plan["status"] == "not_required"
    assert result.report["status"] == "not_required"
    assert result.report["actions"] == []
