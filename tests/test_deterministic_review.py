from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from slidethus.errors import DeterministicReviewError
from slidethus.protocols import BriefCompletionHints
from slidethus.services.deterministic_review import DeterministicReviewService
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _renderer_root() -> Path | None:
    raw = os.environ.get("SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return Path(raw).resolve() if raw else None


def _font_match(tmp_path: Path) -> Path:
    path = tmp_path / "fc-match"
    path.write_text(
        "#!/bin/sh\nprintf '%s\\n/fonts/test.ttf\\n' \"$3\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _build_m4_workspace(tmp_path: Path) -> Path:
    root = _renderer_root()
    assert root is not None
    workspace = init_workspace(tmp_path / "workspace", title="M5 Deterministic Review")
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
            request_text="Create an 8-page management decision deck about an agent operating model",
            purpose="Present the enterprise agent operating model",
            desired_outcome="Approve the implementation project",
            call_to_action="Approve project initiation and assign executive ownership",
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


@pytest.fixture(scope="session")
def m4_baseline(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if _renderer_root() is None:
        pytest.skip("real M5.1 integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT")
    return _build_m4_workspace(tmp_path_factory.mktemp("m5-deterministic-baseline"))


def _m4_workspace(m4_baseline: Path, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    shutil.copytree(m4_baseline, workspace)
    return workspace


def test_deterministic_review_requires_current_m4_inputs(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "workspace", title="Review Prerequisite")

    with pytest.raises(DeterministicReviewError, match="requires current M2-M4 artifacts"):
        DeterministicReviewService(workspace).analyze()


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M5.1 integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_deterministic_review_passes_and_is_idempotent(
    m4_baseline: Path,
    tmp_path: Path,
) -> None:
    workspace = _m4_workspace(m4_baseline, tmp_path)
    service = DeterministicReviewService(workspace)

    first = service.analyze()
    second = service.analyze()

    assert first.report["status"] == "pass"
    assert first.report["target_phase"] is None
    assert first.report["summary"]["failed_count"] == 0
    assert first.report["summary"]["passed_count"] == len(first.report["checks"])
    assert {item["category"] for item in first.report["checks"]} == {
        "workspace_integrity",
        "gate_regression",
        "render_lineage",
        "output_integrity",
        "cross_backend_consistency",
        "editability_truthfulness",
        "preview_coverage",
        "capability_disclosure",
    }
    assert first.changed
    assert second.report == first.report
    assert second.path == first.path
    assert not second.changed


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M5.1 integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_deterministic_review_routes_tampered_render_output_to_p7(
    m4_baseline: Path,
    tmp_path: Path,
) -> None:
    workspace = _m4_workspace(m4_baseline, tmp_path)
    manifest = (workspace / "renders/render_manifest.json").read_text(encoding="utf-8")
    data = json.loads(manifest)
    native = next(item for item in data["outputs"] if item["role"] == "native_pptx")
    output = workspace / native["path"]
    output.write_bytes(output.read_bytes() + b"tamper")

    result = DeterministicReviewService(workspace).analyze()

    assert result.report["status"] == "issues"
    assert result.report["target_phase"] == "VISUAL_SYSTEM_READY"
    assert result.report["summary"]["critical_count"] >= 1
    failed = {item["code"]: item for item in result.report["checks"] if item["status"] == "fail"}
    assert "workspace_integrity" in failed
    assert failed["workspace_integrity"]["earliest_phase"] == "P7"
    assert "production_render_lineage" in failed
    assert "real_output_signatures" in failed


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M5.1 integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_deterministic_review_rejects_unsafe_manifest_paths_without_reading_them(
    m4_baseline: Path,
    tmp_path: Path,
) -> None:
    workspace = _m4_workspace(m4_baseline, tmp_path)
    manifest_path = workspace / "renders/render_manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    native = next(item for item in data["outputs"] if item["role"] == "native_pptx")
    native["path"] = "/etc/passwd"
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = DeterministicReviewService(workspace).analyze()

    assert result.report["status"] == "issues"
    assert result.report["target_phase"] == "VISUAL_SYSTEM_READY"
    failed = {item["code"] for item in result.report["checks"] if item["status"] == "fail"}
    assert "production_render_lineage" in failed
    assert "real_output_signatures" in failed
    assert "pptx_reopen_consistency" in failed
    validation = validate_workspace(workspace, check_hashes=True)
    assert not any(
        item.code == "invalid_deterministic_review_report"
        for item in validation.issues
    )


@pytest.mark.skipif(
    _renderer_root() is None,
    reason="real M5.1 integration requires SLIDETHUS_PPTXGENJS_TEST_ROOT",
)
def test_persisted_deterministic_review_tampering_is_detected(
    m4_baseline: Path,
    tmp_path: Path,
) -> None:
    workspace = _m4_workspace(m4_baseline, tmp_path)
    result = DeterministicReviewService(workspace).analyze()
    data = json.loads(result.path.read_text(encoding="utf-8"))
    data["status"] = "issues"
    result.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(workspace, check_hashes=True)

    assert not validation.ok
    assert any(
        item.code == "invalid_deterministic_review_report"
        for item in validation.issues
    )
