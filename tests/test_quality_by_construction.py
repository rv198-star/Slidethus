from __future__ import annotations

import copy
from pathlib import Path

import pytest

from slidethus.errors import HostCreateRecordError, RenderBackendError, RenderingError
from slidethus.host_create_records import load_host_create_session
from slidethus.io_utils import atomic_write_json, read_json, sha256_file
from slidethus.protocols import BriefCompletionHints
from slidethus.render_backends.artifact_tool import ArtifactToolRenderBackend
from slidethus.services.host_create import HostCreateService
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.render_compile import _strict_region_content
from slidethus.visual_quality import (
    build_visual_admission_policy,
    derive_visual_quality_decision,
    persist_review_adjudication,
    persist_visual_quality_review,
)
from slidethus.workspace import init_workspace


class _Reviewer:
    version = "1"
    capabilities = ("semantic_preview",)

    def __init__(self, name: str) -> None:
        self.name = name


def _ready_workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="Quality construction")
    source = tmp_path / "source.md"
    source.write_text(
        "# Evidence\n\nA is 2 and B is 5.\n\n# Decision\n\nChoose one path.\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="Create an 8-page management decision presentation",
            purpose="Explain the evidence and recommend a decision",
            desired_outcome="Approve the recommended path",
            call_to_action="Approve the recommendation",
            delivery_context="Management decision meeting",
            audience_role="Executive management",
            page_target=8,
        ),
    )
    assert result.report["status"] == "ready"
    return workspace


def _finding(severity: str) -> dict[str, str]:
    return {
        "slide_id": "S-001",
        "dimension": "hierarchy",
        "normalized_issue": "headline and proof have equal visual weight",
        "severity": severity,
        "earliest_owner": "P5B",
        "location": "whole_page",
        "finding": "The headline and proof compete for attention.",
        "impact": "The intended reading order is not visible.",
        "recommended_fix": "Reallocate space and contrast in P5B.",
    }


def test_policy_rejects_legacy_planning_and_direct_m4_bypass(tmp_path: Path) -> None:
    workspace = _ready_workspace(tmp_path)
    _path, policy = build_visual_admission_policy(workspace)
    assert policy["risk_class"] == "reviewed"

    from slidethus.gates import evaluate_gate

    g5a = evaluate_gate(workspace, "G5A")
    assert not g5a.passed
    assert any("Slide Specs 0.2" in reason for reason in g5a.reasons)
    with pytest.raises(RenderingError, match="calibration authorization"):
        M4ApplicationService(workspace).run()


def test_unchanged_page_cannot_clear_major_by_omission_downgrade_or_reviewer_switch(
    tmp_path: Path,
) -> None:
    workspace = _ready_workspace(tmp_path)
    image = workspace / "review-page.png"
    image.write_bytes(b"same-office-page")
    image_set = [
        {
            "slide_id": "S-001",
            "kind": "semantic_preview",
            "path": image.relative_to(workspace).as_posix(),
            "sha256": sha256_file(image),
        }
    ]
    dependency = "sha256:" + "1" * 64
    first_path, first = persist_visual_quality_review(
        workspace,
        stage="planning",
        dependency_key=dependency,
        provider=_Reviewer("reviewer-a"),
        image_set=image_set,
        coverage=("slide_s001",),
        proposal={"findings": [_finding("major")]},
    )
    _path, first_decision = derive_visual_quality_decision(
        workspace, review_path=first_path, required_coverage=("slide_s001",)
    )
    assert first_decision["outcome"] == "rework"

    for reviewer, findings in (
        ("reviewer-a", []),
        ("reviewer-a", [_finding("minor")]),
        ("reviewer-b", []),
    ):
        review_path, _review = persist_visual_quality_review(
            workspace,
            stage="planning",
            dependency_key=dependency,
            provider=_Reviewer(reviewer),
            image_set=image_set,
            coverage=("slide_s001",),
            proposal={"findings": findings},
        )
        _decision_path, decision = derive_visual_quality_decision(
            workspace,
            review_path=review_path,
            required_coverage=("slide_s001",),
        )
        assert decision["outcome"] == "rework"
        assert first["findings"][0]["finding_id"] in decision["open_finding_ids"]

    persist_review_adjudication(
        workspace,
        review_path=first_path,
        finding_id=first["findings"][0]["finding_id"],
        resolution="false_positive",
        reason="The verified brand lockup intentionally uses equal weight.",
        authority_kind="human",
        authority_identity="design-director",
    )
    clean_path, _clean = persist_visual_quality_review(
        workspace,
        stage="planning",
        dependency_key=dependency,
        provider=_Reviewer("reviewer-b"),
        image_set=image_set,
        coverage=("slide_s001",),
        proposal={"findings": []},
    )
    _decision_path, adjudicated = derive_visual_quality_decision(
        workspace, review_path=clean_path, required_coverage=("slide_s001",)
    )
    assert adjudicated["outcome"] == "approved"


def _candidate_receipt(workspace: Path) -> tuple[Path, dict]:
    candidate = workspace / "outputs/host-candidates/candidate-test"
    candidate.mkdir(parents=True)
    files = {
        "ir": candidate / "ir.json",
        "preflight": candidate / "preflight.json",
        "input": candidate / "input.json",
        "pptx": candidate / "candidate.pptx",
        "png": candidate / "S-001.png",
        "layout": candidate / "S-001.layout.json",
    }
    for index, path in enumerate(files.values()):
        path.write_bytes(f"file-{index}".encode())
    receipt = {
        "schema_version": "0.3.0",
        "attempt_id": "HCA-0123456789ABCDEF",
        "status": "candidate_office_review_pending",
        "scope": "sample",
        "slide_ids": ["S-001"],
        "renderer": {
            "name": "artifact-tool",
            "version": "1",
            "adapter_sha256": "1" * 64,
        },
        "dependency_key": "sha256:" + "2" * 64,
        "producer_identity": {
            "backend": "artifact-tool",
            "version": "1",
            "adapter_sha256": "1" * 64,
            "capability_id": "artifact-tool-closed-grammar-v2",
            "capability_hash": "sha256:" + "3" * 64,
        },
        "calibration_authorization": None,
        "artifacts": [
            {"artifact_type": "project_brief", "version": 1, "content_hash": "sha256:" + "4" * 64}
        ],
        "renderer_ir": {"path": str(files["ir"]), "sha256": sha256_file(files["ir"])},
        "preflight": {"path": str(files["preflight"]), "sha256": sha256_file(files["preflight"])},
        "input": {"path": str(files["input"]), "sha256": sha256_file(files["input"])},
        "outputs": [
            {"path": str(files[key]), "sha256": sha256_file(files[key])}
            for key in ("pptx", "png", "layout")
        ],
        "office_review": "evidence_pending",
        "office": {
            "status": "evidence_pending",
            "application": None,
            "build": None,
            "profile": None,
            "export_parameters": None,
            "pages": [],
        },
        "release_approved": False,
        "diagnostics": {
            "stage": "complete",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "duration_seconds": 1,
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "error": None,
        },
    }
    path = candidate / "receipt.json"
    ArtifactToolRenderBackend._write_receipt(path, receipt)
    return path, receipt


def test_office_evidence_cannot_reuse_artifact_preview_and_is_append_only(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path, original = _candidate_receipt(workspace)
    backend = ArtifactToolRenderBackend()
    preview = Path(original["outputs"][1]["path"])
    with pytest.raises(RenderBackendError, match="cannot be registered"):
        backend.record_office_evidence(
            workspace,
            path,
            pages=({"slide_id": "S-001", "path": str(preview)},),
            application="Microsoft PowerPoint",
            build="16.99",
            profile="macOS PNG export",
            export_parameters={"scale": 2},
        )

    office = workspace / "office/S-001.png"
    office.parent.mkdir()
    office.write_bytes(b"office-rendered-page")
    updated = backend.record_office_evidence(
        workspace,
        path,
        pages=({"slide_id": "S-001", "path": str(office)},),
        application="Microsoft PowerPoint",
        build="16.99",
        profile="macOS PNG export",
        export_parameters={"scale": 2},
    )
    assert Path(updated["receipt_path"]) != path
    assert read_json(path) == original
    assert updated["office"]["status"] == "available"


def test_session_01_requires_explicit_migration(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    service = HostCreateService(workspace)
    source = tmp_path / "source.md"
    source.write_text("# Fact\nOne fact.\n", encoding="utf-8")
    service.run(
        (source,),
        hints=BriefCompletionHints(
            request_text="Create a controlled fixture", quality_profile="draft"
        ),
    )
    path = workspace / ".slidethus/host-create/session.json"
    legacy = copy.deepcopy(read_json(path))
    legacy["schema_version"] = "0.1.0"
    atomic_write_json(path, legacy)
    with pytest.raises(HostCreateRecordError, match="explicit session migration"):
        load_host_create_session(workspace)


def test_material_representation_and_view_mutations_change_compiled_region() -> None:
    block = {
        "content": {"type": "bar", "categories": ["old"], "series": []}
    }
    representation = {
        "kind": "chart",
        "semantics": {
            "chart_type": "bar",
            "categories": ["A", "B"],
            "series": [{"name": "Value", "values": [2, 5]}],
        },
    }
    view = {
        "primary_region_id": "REG-S001-02",
        "details": {
            "orientation": "vertical",
            "label_position": "direct",
            "legend_position": "top",
        },
    }
    content, options = _strict_region_content(
        block, representation, view, region_id="REG-S001-02"
    )
    changed_representation = copy.deepcopy(representation)
    changed_representation["semantics"]["series"][0]["values"] = [3, 8]
    changed_content, _ = _strict_region_content(
        block, changed_representation, view, region_id="REG-S001-02"
    )
    changed_view = copy.deepcopy(view)
    changed_view["details"]["label_position"] = "axis"
    _, changed_options = _strict_region_content(
        block, representation, changed_view, region_id="REG-S001-02"
    )
    assert content != changed_content
    assert options != changed_options
