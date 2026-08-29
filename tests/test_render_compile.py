from __future__ import annotations

import copy
import json
from pathlib import Path

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.gates import evaluate_gate
from slidethus.protocols import BriefCompletionHints
from slidethus.render_ir import validate_renderer_ir_data
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.render_compile import RenderCompileService, _decorations
from slidethus.services.render_preflight import _line_crosses_region
from slidethus.services.visual_system import VisualSystemService
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="M4 Render Compile")
    source = tmp_path / "source.md"
    source.write_text(
        "# Responsibility\n\nEnterprises should build data, knowledge, process, rules, tools, permissions and evaluation standards.\n\n"
        "# Risk\n\nAdding more agents does not automatically improve task quality.\n",
        encoding="utf-8",
    )
    result = M3ApplicationService(workspace).run(
        (source,),
        brief_hints=BriefCompletionHints(
            request_text="给管理层做一份 8 页企业 Agent 方案汇报，推动立项决策"
        ),
    )
    assert result.report["status"] == "ready"
    return workspace


def _semantic_refs(runtime: ArtifactRuntime) -> dict[str, tuple[int, str]]:
    return {
        str(item["artifact_type"]): (int(item["version"]), str(item["content_hash"]))
        for item in runtime.list_artifacts()
        if item.get("artifact_type") in {"deck_outline", "slide_specs", "layout_plans"}
    }


def test_visual_system_and_renderer_ir_are_idempotent_and_preserve_m3(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    before = _semantic_refs(runtime)

    visual_service = VisualSystemService(workspace)
    first_visual = visual_service.compile()
    visual_entry = next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "visual_system"
    )
    second_visual = visual_service.compile()
    second_visual_entry = next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == "visual_system"
    )

    assert first_visual == second_visual
    assert visual_entry["version"] == second_visual_entry["version"] == 1
    assert evaluate_gate(workspace, "G6").passed

    compile_service = RenderCompileService(workspace)
    first = compile_service.compile()
    second = compile_service.compile()

    assert first.changed
    assert not second.changed
    assert first.path == second.path
    assert first.ir == second.ir
    assert first.ir["ir_id"].startswith("RIR-")
    assert len(first.ir["slides"]) == len(runtime.show_artifact("deck_outline")["slides"])
    assert {item["artifact_type"] for item in first.ir["input_artifacts"]} == {
        "project_brief",
        "asset_manifest",
        "deck_outline",
        "slide_specs",
        "layout_plans",
        "visual_system",
    }
    assert _semantic_refs(runtime) == before


def test_g6_rejects_visual_system_after_bound_asset_manifest_changes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    VisualSystemService(workspace).compile()
    assert evaluate_gate(workspace, "G6").passed

    assets, version = runtime.read_artifact_snapshot("asset_manifest")
    runtime.write_artifact(
        "asset_manifest",
        assets,
        expected_version=version,
        status="approved",
        created_by="m4-test",
    )

    result = evaluate_gate(workspace, "G6")
    assert result.status == "fail"
    assert any("visual system lineage is stale for asset_manifest" in reason for reason in result.reasons)


def test_renderer_ir_identity_detects_semantic_tampering(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    VisualSystemService(workspace).compile()
    compiled = RenderCompileService(workspace).compile()
    tampered = copy.deepcopy(compiled.ir)
    tampered["slides"][0]["layout_family"] = "custom"

    errors = validate_renderer_ir_data(tampered)

    assert "Renderer IR identity mismatch" in errors


def test_workspace_validation_detects_persisted_renderer_ir_tampering(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    VisualSystemService(workspace).compile()
    compiled = RenderCompileService(workspace).compile()
    tampered = copy.deepcopy(compiled.ir)
    tampered["warnings"].append("tampered")
    compiled.path.write_text(
        json.dumps(tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = validate_workspace(workspace, check_hashes=True)

    assert not report.ok
    assert any(item.code == "invalid_renderer_ir" for item in report.issues)


def test_historical_renderer_ir_remains_valid_after_visual_system_refresh(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = ArtifactRuntime(workspace)
    visual = VisualSystemService(workspace)
    visual.compile()
    first = RenderCompileService(workspace).compile()

    assets, version = runtime.read_artifact_snapshot("asset_manifest")
    runtime.write_artifact(
        "asset_manifest",
        assets,
        expected_version=version,
        status="approved",
        created_by="m4-test",
    )
    visual.compile()
    second = RenderCompileService(workspace).compile()

    assert first.path != second.path
    assert validate_workspace(workspace, check_hashes=True).ok


def test_process_connectors_follow_region_anchors_without_crossing_cards() -> None:
    visual = {"colors": {"accent": "#00AA88", "primary": "#112233"}}
    regions = [
        {
            "region_id": "REG-S007-01",
            "semantic_role": "headline",
            "x": 72,
            "y": 48,
            "w": 1112,
            "h": 120,
        },
        *[
            {
                "region_id": f"REG-S007-{index + 2:02d}",
                "semantic_role": "body",
                "x": 72 + column * 284,
                "y": 210 + row * 225,
                "w": 260,
                "h": 190,
            }
            for index, (row, column) in enumerate(
                ((0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2))
            )
        ],
    ]

    decorations = _decorations("S-007", "process", visual, regions)
    lines = [item for item in decorations if item["kind"] == "line"]

    assert lines
    assert all(float(item["y"]) != 580 for item in lines)
    assert len({item["decoration_id"] for item in decorations}) == len(decorations)
    assert not any(
        _line_crosses_region(line, region)
        for line in lines
        for region in regions
    )
