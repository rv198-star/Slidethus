from __future__ import annotations

from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ArtifactConflictError, LayoutPlanningError
from slidethus.gates import evaluate_gate
from slidethus.layout_geometry import admit_authored_layout, build_layout_plan
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.protocols import BriefCompletionHints, PlanningProposal
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.layout import LayoutPlanningService
from slidethus.services.m2_application import M2ApplicationService
from slidethus.services.narrative import NarrativePlanningService
from slidethus.services.outline import OutlinePlanningService
from slidethus.services.slide_specs import SlideSpecPlanningService
from slidethus.state_machine import Phase
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


def _specs_ready_workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="Agent Operating Model")
    BriefCompletionService(workspace).complete(
        BriefCompletionHints(
            request_text="给管理层做一份 10 页企业 Agent 方案汇报，推动立项决策"
        )
    )
    source = tmp_path / "source.md"
    source.write_text(
        "# 企业建设重点\n\n企业应建设数据、知识、流程、规则、工具、权限和评价标准。\n\n"
        "# 交付原则\n\nAgent 的通用能力由平台持续推进，企业聚焦业务环境。\n\n"
        "# 风险\n\n多 Agent 数量增加并不自动提高任务质量。\n",
        encoding="utf-8",
    )
    assert M2ApplicationService(workspace).run((source,)).report["status"] == "ready"
    NarrativePlanningService(workspace).generate()
    OutlinePlanningService(workspace).generate()
    SlideSpecPlanningService(workspace).generate()
    EvidenceBindingService(workspace).complete_user_material_targeted_cycle()
    runtime = ArtifactRuntime(workspace)
    runtime.record_gate("G2", target_phase=Phase.EVIDENCE_READY)
    runtime.record_gate("G3", target_phase=Phase.NARRATIVE_READY)
    runtime.record_gate("G4", target_phase=Phase.OUTLINE_READY)
    runtime.record_gate("G5A", target_phase=Phase.SLIDE_SPECS_READY)
    assert evaluate_gate(workspace, "G5A").passed
    return workspace


def _overlap(first: dict, second: dict) -> bool:
    return not (
        first["x"] + first["w"] <= second["x"]
        or second["x"] + second["w"] <= first["x"]
        or first["y"] + first["h"] <= second["y"]
        or second["y"] + second["h"] <= first["y"]
    )


def test_layout_generation_maps_every_block_and_emits_immutable_wireframes(
    tmp_path: Path,
) -> None:
    workspace = _specs_ready_workspace(tmp_path)
    service = LayoutPlanningService(workspace)

    first = service.generate()
    second = service.generate()

    assert first.changed
    assert not second.changed
    assert first.version == second.version
    layout = first.layout_plans
    specs = ArtifactRuntime(workspace).show_artifact("slide_specs")
    specs_by_id = {item["slide_id"]: item for item in specs["slides"]}
    assert layout["status"] == "approved"
    assert [item["slide_id"] for item in layout["plans"]] == [
        item["slide_id"] for item in specs["slides"]
    ]
    assert len(layout["wireframes"]) == len(layout["plans"])
    for plan in layout["plans"]:
        slide = specs_by_id[plan["slide_id"]]
        assert {item["block_id"] for item in plan["regions"]} == {
            item["block_id"] for item in slide["content_blocks"]
        }
        assert plan["reading_order"] == [item["region_id"] for item in plan["regions"]]
        assert all(
            not _overlap(first_region, second_region)
            for index, first_region in enumerate(plan["regions"])
            for second_region in plan["regions"][index + 1 :]
        )
        assert plan["diagnostics"]["block_count"] == len(slide["content_blocks"])
        assert plan["diagnostics"]["capacity_units"] >= plan["diagnostics"]["content_units"]
    for reference in layout["wireframes"]:
        immutable = workspace / reference["path"]
        current = workspace / "outputs/wireframes" / f"{reference['slide_id']}.svg"
        assert immutable.is_file()
        assert current.is_file()
        assert immutable.read_bytes() == current.read_bytes()
    assert service.audit() == ()
    assert evaluate_gate(workspace, "G5B").passed
    assert validate_workspace(workspace, check_hashes=True).ok


def test_layout_families_follow_page_relationship_not_bento_default(tmp_path: Path) -> None:
    workspace = _specs_ready_workspace(tmp_path)
    layout = LayoutPlanningService(workspace).generate().layout_plans
    families = [item["layout_family"] for item in layout["plans"]]

    assert len(set(families)) >= 3
    assert families.count("bento") < len(families) / 2
    assert families[0] == "hero"


def test_layout_provider_cannot_override_declared_family_with_unrelated_choice(
    tmp_path: Path,
) -> None:
    workspace = _specs_ready_workspace(tmp_path)

    class WrongFamilyProvider(DeterministicPlanningProvider):
        name = "wrong-family-provider"

        def propose(self, artifact_type, context, limits):
            proposal = super().propose(artifact_type, context, limits)
            content = dict(proposal.content)
            plans = [dict(item) for item in content["plans"]]
            plans[0]["layout_family"] = "matrix"
            content["plans"] = plans
            return PlanningProposal(artifact_type, content)

    with pytest.raises(LayoutPlanningError, match="outside Slide Spec intent"):
        LayoutPlanningService(
            workspace,
            provider=WrongFamilyProvider(),
        ).generate()


def test_authored_layout_accepts_provider_neutral_semantic_family() -> None:
    slide = {
        "slide_id": "S-001",
        "density_budget": {"min_body_pt": 18},
        "content_blocks": [
            {
                "block_id": "BLK-S001-01",
                "semantic_role": "headline",
                "content_type": "text",
                "content": "Decision headline",
                "content_hash": "sha256:" + "a" * 64,
            },
            {
                "block_id": "BLK-S001-02",
                "semantic_role": "evidence",
                "content_type": "text",
                "content": "Evidence support",
                "content_hash": "sha256:" + "b" * 64,
            },
        ],
    }
    plan = admit_authored_layout(
        slide,
        {
            "slide_id": "S-001",
            "layout_family": "editorial-ledger",
            "rationale": "The semantic family describes an editorial evidence relationship.",
            "regions": [
                {
                    "block_id": "BLK-S001-01",
                    "x": 80,
                    "y": 60,
                    "w": 1120,
                    "h": 140,
                    "z": 0,
                    "align": "left",
                    "valign": "top",
                    "overflow_strategy": "fail",
                },
                {
                    "block_id": "BLK-S001-02",
                    "x": 80,
                    "y": 224,
                    "w": 1120,
                    "h": 416,
                    "z": 1,
                    "align": "left",
                    "valign": "top",
                    "overflow_strategy": "fail",
                },
            ],
        },
    )
    payload = {
        "schema_version": "0.1.0",
        "project_id": "LAYOUT_TEST",
        "deck_id": "DECK-LAYOUT_TEST",
        "canvas": {"width": 1280, "height": 720},
        "safe_area": {"top": 60, "right": 80, "bottom": 60, "left": 80},
        "plans": [plan],
    }

    assert plan["layout_family"] == "editorial-ledger"
    assert list(SchemaRegistry().validator("layout_plans").iter_errors(payload)) == []


def test_authored_layout_rejects_unbounded_family_name() -> None:
    slide = {
        "slide_id": "S-001",
        "density_budget": {"min_body_pt": 18},
        "content_blocks": [
            {
                "block_id": "BLK-S001-01",
                "semantic_role": "headline",
                "content_type": "text",
                "content": "Decision headline",
                "content_hash": "sha256:" + "a" * 64,
            }
        ],
    }

    with pytest.raises(LayoutPlanningError, match="bounded semantic name"):
        admit_authored_layout(
            slide,
            {
                "slide_id": "S-001",
                "layout_family": "Editorial Ledger / custom",
                "rationale": "Invalid semantic family syntax.",
                "regions": [
                    {
                        "block_id": "BLK-S001-01",
                        "x": 80,
                        "y": 60,
                        "w": 1120,
                        "h": 580,
                        "z": 0,
                        "align": "left",
                        "valign": "top",
                        "overflow_strategy": "fail",
                    }
                ],
            },
        )


def test_high_cardinality_process_preserves_ordered_topology_and_setup_space() -> None:
    blocks = [
        {
            "block_id": "BLK-S001-01",
            "semantic_role": "headline",
            "content_type": "text",
            "content": "Process decision",
            "content_hash": "sha256:" + "a" * 64,
        },
        {
            "block_id": "BLK-S001-02",
            "semantic_role": "subhead",
            "content_type": "text",
            "content": "A longer setup statement that explains the purpose before the ordered steps begin.",
            "content_hash": "sha256:" + "b" * 64,
        },
    ]
    blocks.extend(
        {
            "block_id": f"BLK-S001-{index:02d}",
            "semantic_role": "body",
            "content_type": "text",
            "content": f"Step {index - 2}",
            "content_hash": "sha256:" + f"{index:x}" * 64,
        }
        for index in range(3, 10)
    )
    slide = {
        "slide_id": "S-001",
        "density_budget": {"min_body_pt": 18},
        "visual_intent": {"relationship": "sequence"},
        "content_blocks": blocks,
    }

    plan = build_layout_plan(
        slide,
        family="process",
        canvas={"width": 1280, "height": 720},
        safe_area={"top": 60, "right": 80, "bottom": 60, "left": 80},
    )

    regions = {item["block_id"]: item for item in plan["regions"]}
    setup = regions["BLK-S001-02"]
    step_regions = [regions[f"BLK-S001-{index:02d}"] for index in range(3, 10)]
    assert setup["w"] == 1120.0
    assert setup["h"] >= 140.0
    assert all(item["y"] > setup["y"] + setup["h"] for item in step_regions)
    assert len({item["y"] for item in step_regions}) == 2
    assert [item["region_id"] for item in plan["regions"]] == plan["reading_order"]


def test_layout_geometry_fails_when_content_cannot_fit_font_floor() -> None:
    slide = {
        "slide_id": "S-001",
        "density_budget": {"min_body_pt": 24},
        "visual_intent": {"relationship": "hierarchy"},
        "content_blocks": [
            {
                "block_id": "BLK-S001-01",
                "semantic_role": "headline",
                "content_type": "text",
                "content": "标题",
                "content_hash": "sha256:" + "a" * 64,
            },
            {
                "block_id": "BLK-S001-02",
                "semantic_role": "body",
                "content_type": "text",
                "content": "超长内容" * 3000,
                "content_hash": "sha256:" + "b" * 64,
            },
        ],
    }

    with pytest.raises(
        LayoutPlanningError,
        match="after bounded space reallocation",
    ):
        build_layout_plan(
            slide,
            family="split",
            canvas={"width": 1280, "height": 720},
            safe_area={"top": 60, "right": 80, "bottom": 60, "left": 80},
        )


def test_relationship_families_have_observably_distinct_primary_geometries() -> None:
    def block(index: int, role: str, content_type: str = "text") -> dict:
        return {
            "block_id": f"BLK-S001-{index:02d}",
            "semantic_role": role,
            "content_type": content_type,
            "content": ["A", "B", "C", "D", "E", "F"] if content_type == "list" else f"Content {index}",
            "content_hash": "sha256:" + f"{index:x}" * 64,
        }

    def plan(family: str, blocks: list[dict]) -> dict:
        return build_layout_plan(
            {
                "slide_id": "S-001",
                "density_budget": {"min_body_pt": 18},
                "visual_intent": {"relationship": family},
                "content_blocks": blocks,
            },
            family=family,
            canvas={"width": 1280, "height": 720},
            safe_area={"top": 60, "right": 80, "bottom": 60, "left": 80},
        )

    headline = block(1, "headline")
    timeline = plan("timeline", [headline, *(block(i, "body") for i in range(2, 6))])
    timeline_body = timeline["regions"][1:]
    assert len({item["y"] for item in timeline_body}) == 2

    case = plan("case", [headline, *(block(i, "evidence") for i in range(2, 5))])
    assert case["regions"][1]["h"] > case["regions"][2]["h"]
    assert case["regions"][1]["w"] > case["regions"][2]["w"]

    process = plan("process", [headline, block(2, "subhead", "list"), block(3, "body", "list")])
    assert process["regions"][1]["y"] == process["regions"][2]["y"]
    assert process["regions"][1]["x"] < process["regions"][2]["x"]

    matrix = plan(
        "matrix",
        [headline, block(2, "evidence"), block(3, "evidence"), block(4, "evidence", "list")],
    )
    list_region = matrix["regions"][3]
    assert list_region["h"] > matrix["regions"][1]["h"]
    assert list_region["x"] > matrix["regions"][1]["x"]


def test_wireframe_tamper_and_region_collision_fail_g5b(tmp_path: Path) -> None:
    workspace = _specs_ready_workspace(tmp_path)
    result = LayoutPlanningService(workspace).generate()
    reference = result.layout_plans["wireframes"][0]
    immutable = workspace / reference["path"]
    immutable.write_text("<svg>tampered</svg>\n", encoding="utf-8")

    tampered_gate = evaluate_gate(workspace, "G5B")
    assert not tampered_gate.passed
    assert any("Wireframe hash mismatch" in reason for reason in tampered_gate.reasons)

    # Restore by regenerating immutable/current wireframes, then create a geometry collision.
    immutable.unlink()
    LayoutPlanningService(workspace).generate()
    runtime = ArtifactRuntime(workspace)
    layout, version = runtime.read_artifact_snapshot("layout_plans")
    plan = next(item for item in layout["plans"] if len(item["regions"]) >= 2)
    plan["regions"][1]["x"] = plan["regions"][0]["x"]
    plan["regions"][1]["y"] = plan["regions"][0]["y"]
    runtime.write_artifact(
        "layout_plans",
        layout,
        expected_version=version,
        status="approved",
        created_by="layout-test",
    )
    collision_gate = evaluate_gate(workspace, "G5B")
    assert not collision_gate.passed
    assert any("collision" in reason for reason in collision_gate.reasons)


def test_layout_generation_rejects_stale_snapshot_on_concurrent_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _specs_ready_workspace(tmp_path)
    service = LayoutPlanningService(workspace)
    original_write = service.runtime.write_artifact
    raced = False

    def racing_write(artifact_type, data, **kwargs):
        nonlocal raced
        if artifact_type == "layout_plans" and not raced:
            raced = True
            LayoutPlanningService(workspace).generate()
        return original_write(artifact_type, data, **kwargs)

    monkeypatch.setattr(service.runtime, "write_artifact", racing_write)

    with pytest.raises(ArtifactConflictError, match="Version conflict for layout_plans"):
        service.generate()
