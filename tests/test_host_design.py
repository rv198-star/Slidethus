from __future__ import annotations

import copy
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from slidethus.art_direction import TasteSkillArtDirectionProvider
from slidethus.art_direction_seed import compile_art_direction_seed
from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.cli import main
from slidethus.errors import (
    ArtifactError,
    PlanningError,
    RenderAttemptError,
    RenderBackendError,
    RenderCapabilityError,
)
from slidethus.gates import evaluate_gate
from slidethus.host_design import (
    HostArtDirectionProvider,
    HostDesignBridge,
    HostDesignRequired,
    HostPlanningProvider,
)
from slidethus.io_utils import atomic_create_json, atomic_write_json, read_json, sha256_file
from slidethus.layout_geometry import admit_authored_layout
from slidethus.page_design import validate_page_designs
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.protocols import (
    ArtDirectionLimits,
    ArtDirectionSeedProposal,
    BriefCompletionHints,
    PlanningLimits,
)
from slidethus.render_backends.artifact_tool import ArtifactToolRenderBackend
from slidethus.render_backends.artifact_tool_runtime import (
    resolve_artifact_tool_runtime,
)
from slidethus.services.host_create import HostCreateService
from slidethus.services.render_compile import RenderCompileService
from slidethus.services.render_preflight import RenderPreflightService
from tests.fontconfig_fakes import write_fontconfig_tools


def _respond(pending: dict, proposal: dict) -> None:
    atomic_create_json(Path(pending["response_path"]), {
        "schema_version": "0.1.0", "request_hash": pending["request_hash"],
        "stage": pending["stage"], "proposal": proposal,
    })


def test_host_bridge_missing_stale_and_invalid_responses_never_fall_back(tmp_path: Path) -> None:
    bridge = HostDesignBridge(tmp_path)
    provider = HostPlanningProvider(bridge)
    with pytest.raises(HostDesignRequired):
        provider.propose("narrative_blueprint", {"title": "A"}, PlanningLimits())
    pending = dict(bridge.pending)
    _respond(pending, {"content": {"sections": []}})
    assert provider.propose("narrative_blueprint", {"title": "A"}, PlanningLimits()).content == {"sections": []}
    with pytest.raises(HostDesignRequired):
        provider.propose("narrative_blueprint", {"title": "B"}, PlanningLimits())
    Path(bridge.pending["response_path"]).write_bytes(Path(pending["response_path"]).read_bytes())
    with pytest.raises(PlanningError, match="stale"):
        provider.propose("narrative_blueprint", {"title": "B"}, PlanningLimits())
    assert not (tmp_path / "outputs").exists()


def test_legacy_create_requires_explicit_baseline(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "no-workspace"
    assert main(["workflow", "run", "create", str(workspace)]) == 2
    assert "--deterministic-baseline" in capsys.readouterr().err
    assert not workspace.exists()


@pytest.mark.parametrize("stage,proposal", [
    ("narrative_blueprint", {"content": None}),
    ("narrative_blueprint", {"content": {}, "warnings": "not a list"}),
    ("narrative_blueprint", {"content": {}, "assumptions": None}),
    ("narrative_blueprint", {"content": {"value": float("nan")}}),
    ("layout_plans", {"content": {"plans": [None]}}),
    ("layout_plans", {"content": {"plans": {"regions": []}}}),
    ("art_direction_seed", {"design_read": "invalid fixture", "dials": {}, "foundation": None, "direction": None}),
    ("art_direction", {"design_read": "invalid fixture", "dials": {}, "direction": None}),
])
def test_malformed_host_proposals_fail_explicitly(tmp_path: Path, stage: str, proposal: dict) -> None:
    bridge = HostDesignBridge(tmp_path)
    limits = ArtDirectionLimits() if stage in {"art_direction_seed", "art_direction"} else PlanningLimits()
    with pytest.raises(HostDesignRequired):
        bridge.exchange(stage, {}, limits)
    _respond(bridge.pending, proposal)
    with pytest.raises(PlanningError):
        if stage == "art_direction_seed":
            HostArtDirectionProvider(bridge).propose_seed({}, limits)
        elif stage == "art_direction":
            HostArtDirectionProvider(bridge).propose({}, limits)
        else:
            HostPlanningProvider(bridge).propose(stage, {}, limits)


def test_artifact_tool_missing_capability_does_not_install_or_fallback(tmp_path: Path) -> None:
    with pytest.raises(RenderCapabilityError):
        ArtifactToolRenderBackend(node=str(tmp_path / "no-node"), modules=tmp_path).check_available()


def _fake_artifact_tool_runtime(tmp_path: Path) -> tuple[Path, Path]:
    node = tmp_path / "node"
    node.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo v20.11.0; exit 0; fi\n"
        "echo synthetic-adapter-failure \"$@\" >&2\n"
        "exit 9\n",
        encoding="utf-8",
    )
    node.chmod(0o755)
    modules = tmp_path / "node_modules"
    package = modules / "@oai/artifact-tool/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"0.0.0-test"}\n', encoding="utf-8")
    return node, modules


def _fake_successful_artifact_tool_runtime(tmp_path: Path) -> tuple[Path, Path]:
    node = tmp_path / "node-success"
    node.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys, zipfile\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('v20.11.0')\n"
        "    raise SystemExit(0)\n"
        "payload = json.loads(pathlib.Path(sys.argv[2]).read_text())\n"
        "output = pathlib.Path(sys.argv[3])\n"
        "output.mkdir(parents=True, exist_ok=True)\n"
        "with zipfile.ZipFile(output / 'candidate.pptx', 'w') as archive:\n"
        "    archive.writestr('[Content_Types].xml', '<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>')\n"
        "    for index, _slide_id in enumerate(payload['slide_ids'], 1):\n"
        "        archive.writestr(f'ppt/slides/slide{index}.xml', '<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>')\n"
        "for slide_id in payload['slide_ids']:\n"
        "    (output / f'{slide_id}.png').write_bytes(b'\\x89PNG\\r\\n\\x1a\\nfixture')\n"
        "    (output / f'{slide_id}.layout.json').write_text('{}\\n')\n",
        encoding="utf-8",
    )
    node.chmod(0o755)
    modules = tmp_path / "node_modules-success"
    package = modules / "@oai/artifact-tool/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"0.0.0-test"}\n', encoding="utf-8")
    return node, modules


def test_same_host_request_records_distinct_response_and_proposal_hashes(
    tmp_path: Path,
) -> None:
    bridge = HostDesignBridge(tmp_path)
    provider = HostPlanningProvider(bridge)
    context = {"title": "Stable request"}
    with pytest.raises(HostDesignRequired):
        provider.propose("narrative_blueprint", context, PlanningLimits())
    pending = copy.deepcopy(bridge.pending)

    first_response = {
        "schema_version": "0.1.0",
        "request_hash": pending["request_hash"],
        "stage": pending["stage"],
        "proposal": {"content": {"version": "first"}, "warnings": [], "assumptions": []},
    }
    atomic_write_json(Path(pending["response_path"]), first_response)
    assert provider.propose(
        "narrative_blueprint", context, PlanningLimits()
    ).content == {"version": "first"}
    first = copy.deepcopy(bridge.last_submission)

    second_response = copy.deepcopy(first_response)
    second_response["proposal"]["content"]["version"] = "second"
    atomic_write_json(Path(pending["response_path"]), second_response)
    assert provider.propose(
        "narrative_blueprint", context, PlanningLimits()
    ).content == {"version": "second"}
    second = bridge.last_submission

    assert first["request_hash"] == second["request_hash"]
    assert first["response_hash"] != second["response_hash"]
    assert first["proposal_hash"] != second["proposal_hash"]
    assert len(list((tmp_path / ".slidethus/host-design/received").glob("*.json"))) == 2


def test_doctor_and_renderer_share_explicit_artifact_runtime(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    node, modules = _fake_artifact_tool_runtime(tmp_path)
    resolved = resolve_artifact_tool_runtime(node=str(node), modules=modules)

    assert ArtifactToolRenderBackend(
        node=str(node), modules=modules
    ).check_available() == {"name": "artifact-tool", "version": resolved.version}
    assert main(
        ["doctor", "--node", str(node), "--node-modules", str(modules)]
    ) == 0
    output = capsys.readouterr().out
    assert f"node={node}" in output
    assert f"node_modules={modules}" in output


def test_artifact_runtime_resolver_uses_host_bundle_after_args_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import slidethus.render_backends.artifact_tool_runtime as runtime_module

    bundle = tmp_path / "bundled-node"
    node = bundle / "bin/node"
    node.parent.mkdir(parents=True)
    node.write_text(
        "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo v20.11.0; fi\n",
        encoding="utf-8",
    )
    node.chmod(0o755)
    modules = bundle / "node_modules"
    package = modules / "@oai/artifact-tool/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"0.0.0-bundled"}\n', encoding="utf-8")
    monkeypatch.delenv("RUNTIME_NODE", raising=False)
    monkeypatch.delenv("RUNTIME_NODE_MODULES", raising=False)
    monkeypatch.setattr(
        runtime_module,
        "_host_bundled_node_roots",
        lambda: (bundle,),
    )

    resolved = resolve_artifact_tool_runtime()

    assert resolved.node == str(node)
    assert resolved.modules == modules
    assert resolved.version == "0.0.0-bundled"


def test_deterministic_taste_seed_is_never_claimed_as_taste_generated() -> None:
    proposal = TasteSkillArtDirectionProvider().propose_seed(
        {
            "project_brief": {"title": "Fixture", "intent": {"presentation_mode": "both"}},
            "deck_outline": {
                "slides": [
                    {"slide_id": "S-001", "slide_type": "cover", "status": "approved"},
                    {"slide_id": "S-002", "slide_type": "evidence", "status": "approved"},
                ]
            },
        },
        ArtDirectionLimits(),
    )

    assert proposal.foundation == {"kind": "taste-informed"}
    assert all(item["requirement"] == "optional" for item in proposal.direction["carriers"])


def test_designed_host_seed_rejects_taste_informed_fallback(tmp_path: Path) -> None:
    bridge = HostDesignBridge(tmp_path)
    provider = HostArtDirectionProvider(bridge, require_taste_generated=True)
    with pytest.raises(HostDesignRequired):
        provider.propose_seed({}, ArtDirectionLimits())
    _respond(
        bridge.pending,
        {
            "design_read": "Fallback is not sufficient for designed Create.",
            "dials": {"design_variance": 6, "motion_intensity": 2, "visual_density": 6},
            "foundation": {"kind": "taste-informed"},
            "direction": {
                "carriers": [],
                "image_direction": {},
                "deck_rhythm": "fixture",
                "surface_rhythm": {"max_consecutive_plain": 0},
                "forbidden_patterns": ["fixture"],
            },
        },
    )

    with pytest.raises(PlanningError, match="Taste-generated"):
        provider.propose_seed({}, ArtDirectionLimits())


def test_taste_generated_seed_rejects_missing_native_prototype(authored_workspace: Path) -> None:
    class MissingPrototypeProvider:
        name = "fixture-art-direction"
        version = "1.0.0"
        mode = "fixture"

        def resource_identity(self):
            return None

        def propose_seed(self, context, limits):
            carriers = [
                {
                    "slide_id": item["slide_id"],
                    "kind": "textual",
                    "requirement": "optional",
                    "surface_treatment": "tonal",
                    "rationale": "Fixture only.",
                }
                for item in context["deck_outline"]["slides"]
                if item.get("status") != "excluded"
            ]
            return ArtDirectionSeedProposal(
                design_read="Fixture with a missing native prototype.",
                dials={"design_variance": 6, "motion_intensity": 2, "visual_density": 6},
                foundation={
                    "kind": "taste-generated",
                    "prototype": {
                        "medium": "html-css",
                        "path": "design/prototypes/missing.html",
                        "content_hash": "sha256:" + "0" * 64,
                    },
                },
                direction={
                    "carriers": carriers,
                    "image_direction": {"style": "fixture", "fit": "cover", "missing_asset": "replan", "prompt_keywords": ["fixture"]},
                    "deck_rhythm": "fixture",
                    "surface_rhythm": {"max_consecutive_plain": 0},
                    "forbidden_patterns": ["fixture"],
                },
            )

    graph = ArtifactRuntime(authored_workspace).read_artifact_graph_snapshot(
        ("project_brief", "deck_outline")
    )
    with pytest.raises(ArtifactError, match="prototype is missing"):
        compile_art_direction_seed(
            authored_workspace,
            graph,
            provider=MissingPrototypeProvider(),
        )


def _fixture_proposal(
    stage: str,
    context: dict,
    limits: dict,
    *,
    prototype: dict | None = None,
) -> dict:
    """Synthetic test host only; never used by the production entry."""
    if stage == "art_direction_seed":
        if prototype is None:
            raise AssertionError("Taste-generated fixture requires a native prototype")
        carriers = []
        for index, slide in enumerate(context["deck_outline"]["slides"]):
            if slide.get("status") == "excluded":
                continue
            kind = {0: "typographic", 1: "chart", 2: "image"}.get(index, "textual")
            carriers.append(
                {
                    "slide_id": slide["slide_id"],
                    "kind": kind,
                    "requirement": "required" if kind in {"chart", "image"} else "optional",
                    "surface_treatment": "image-led" if kind == "image" else "field",
                    "rationale": "Synthetic propagation fixture uses a declared carrier, never a deck template.",
                }
            )
        return {
            "design_read": "Synthetic Taste-generated propagation fixture, not a visual acceptance case.",
            "dials": {"design_variance": 7, "motion_intensity": 2, "visual_density": 6},
            "foundation": {"kind": "taste-generated", "prototype": prototype},
            "direction": {
                "carriers": carriers,
                "image_direction": {"style": "fixture editorial", "fit": "cover", "missing_asset": "replan", "prompt_keywords": ["fixture"]},
                "deck_rhythm": "vary surfaces by semantic carrier",
                "surface_rhythm": {"max_consecutive_plain": 0},
                "forbidden_patterns": ["bento-as-default"],
            },
            "warnings": [],
            "assumptions": [],
        }
    if stage == "art_direction":
        proposal = asdict(TasteSkillArtDirectionProvider().propose(context, ArtDirectionLimits(**limits)))
        proposal["design_read"] = "Synthetic propagation fixture bound to a Taste-generated Seed, not a visual acceptance case."
        proposal["direction"]["typography"]["preferred_font"] = "Arial"
        carrier_by_slide = {
            item["slide_id"]: item
            for item in context["art_direction_seed"]["direction"]["carriers"]
        }
        pages = []
        for plan in context["layout_plans"]["plans"]:
            rows = []
            for r in plan["regions"]:
                rows.append({"block_id": r["block_id"], "style": {
                    "font_family": "Arial", "font_size": r["min_font_pt"], "font_weight": 400,
                    "line_height": 1.2, "color": "#123456", "fill": None,
                    "border_color": None, "border_width": 0,
                    "image_fit": "contain", "chart_colors": ["#7A3355"],
                }})
            treatment = carrier_by_slide[plan["slide_id"]]["surface_treatment"]
            decorations = []
            if treatment == "field":
                decorations = [{
                    "decoration_id": f"DEC-{plan['slide_id'].replace('-', '')}-01",
                    "kind": "rect", "x": 60, "y": 44, "w": 42, "h": 4,
                    "fill": "#7A3355", "stroke": None, "z": 0,
                }]
            pages.append({"slide_id": plan["slide_id"], "surface_treatment": treatment, "background": "#EFF2F8", "regions": rows, "decorations": decorations})
        proposal["direction"]["page_designs"] = pages
        return proposal
    if stage == "layout_plans":
        plans = []
        for slide in context["slide_specs"]["slides"]:
            blocks = slide["content_blocks"]
            h = 576 / len(blocks)
            plans.append({"slide_id": slide["slide_id"], "layout_family": "custom", "rationale": "Synthetic unequal-margin geometry to detect template overwrite", "regions": [
                {"block_id": b["block_id"], "x": 95, "y": 64 + i * h, "w": 1080, "h": h - 8,
                 "z": i, "align": "left", "valign": "top", "overflow_strategy": "fail"}
                for i, b in enumerate(blocks)
            ]})
        return {"content": {"plans": plans}, "warnings": [], "assumptions": []}
    proposal = asdict(DeterministicPlanningProvider().propose(stage, context, PlanningLimits(**limits)))
    proposal.pop("artifact_type")
    proposal.pop("art_direction_seed")
    if stage == "slide_specs":
        for index, slide in enumerate(proposal["content"]["slides"]):
            slide["visual_intent"]["suggested_layout_families"] = ["custom"]
            if index in {1, 2}:
                body = copy.deepcopy(slide["content_blocks"][1])
                slide["content_blocks"].append(body)
                slide["density_budget"]["max_blocks"] = len(slide["content_blocks"])
                slide["density_budget"]["max_words"] = 240
                body.update({"claim_mode": "label", "evidence_ids": [], "evidence_requirement": "none", "evidence_qualification": None})
                if index == 1:
                    body.update({"content_type": "chart", "content": {"type": "bar", "categories": ["A", "B"], "series": [{"name": "Synthetic", "values": [2, 5]}]}})
                else:
                    body.update({"claim_mode": "asset", "content_type": "image", "content": "Engineering fixture", "asset_refs": ["AST-001"]})
    return proposal


@pytest.fixture(scope="module")
def authored_workspace(tmp_path_factory) -> Path:
    """Exercise actual pause/resume admission for every stage, without a model API."""
    import base64

    root = tmp_path_factory.mktemp("host-design")
    source = root / "source.txt"
    source.write_text("# Evidence\nSynthetic A is 2 and B is 5.\n\n# Decision\nReview the controlled fixture before adoption.", encoding="utf-8")
    workspace = root / "workspace"
    service = HostCreateService(workspace)
    hints = BriefCompletionHints(request_text="Create a four-page engineering fixture", purpose="Check propagation", desired_outcome="Inspect candidate", call_to_action="Review the fixture", audience_role="Engineers", delivery_context="Engineering test", page_target=4)
    result = service.run((source,), hints=hints)
    runtime = ArtifactRuntime(workspace)
    image = workspace / "assets/test.png"
    image.parent.mkdir(exist_ok=True)
    # Fixed transparent PNG bytes are test data, not generated visual design.
    image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
    manifest, version = runtime.read_artifact_snapshot("asset_manifest")
    manifest["assets"] = [{"asset_id": "AST-001", "kind": "image", "source_type": "internal", "path_or_url": "assets/test.png", "license": "test fixture", "allowed_use": "full", "status": "available"}]
    runtime.write_artifact("asset_manifest", manifest, expected_version=version)
    visited = []
    for _ in range(8):
        assert result["status"] == "host_input_required", result
        pending = result["pending"]
        visited.append(pending["stage"])
        request = read_json(Path(pending["request_path"]))
        prototype = None
        if pending["stage"] == "art_direction_seed":
            prototype_path = workspace / "design/prototypes/fixture.html"
            prototype_path.parent.mkdir(parents=True, exist_ok=True)
            prototype_path.write_text("<main>fixture visual prototype</main>\n", encoding="utf-8")
            prototype = {
                "medium": "html-css",
                "path": "design/prototypes/fixture.html",
                "content_hash": f"sha256:{sha256_file(prototype_path)}",
            }
        _respond(
            pending,
            _fixture_proposal(
                request["stage"], request["context"], request["limits"], prototype=prototype
            ),
        )
        result = service.run((source,), hints=hints)
        if result["status"] == "design_ready":
            break
    assert visited == ["narrative_blueprint", "deck_outline", "art_direction_seed", "slide_specs", "layout_plans", "art_direction"]
    assert result["status"] == "design_ready", result
    return workspace


def test_host_decisions_reach_ir_without_family_restyling(authored_workspace: Path) -> None:
    runtime = ArtifactRuntime(authored_workspace)
    ir = RenderCompileService(authored_workspace).compile().ir
    visual = runtime.show_artifact("visual_system")
    page_by_id = {page["slide_id"]: page for page in visual["page_designs"]}
    for slide in ir["slides"]:
        assert slide["background"] == "#EFF2F8"
        assert slide["decorations"] == page_by_id[slide["slide_id"]]["decorations"]
        assert all(r["x"] == 95 and r["style"]["color"] == "#123456" for r in slide["regions"])
    specs = runtime.show_artifact("slide_specs")
    seed = read_json(authored_workspace / specs["art_direction_seed"]["path"])
    assert seed["foundation"]["kind"] == "taste-generated"
    assert visual["art_direction"]["pre_layout_seed"] == specs["art_direction_seed"]
    layouts = runtime.show_artifact("layout_plans")
    broken = copy.deepcopy(visual["page_designs"])
    broken[0]["regions"].pop()
    with pytest.raises(ArtifactError, match="every Block"):
        validate_page_designs(broken, specs, layouts)
    raw = _fixture_proposal("layout_plans", {"slide_specs": specs}, {})["content"]["plans"][0]
    raw["regions"][0]["w"] = -1
    with pytest.raises(PlanningError, match="geometry"):
        admit_authored_layout(specs["slides"][0], raw)


def test_host_create_can_request_seed_revision_without_outline_perturbation(
    authored_workspace: Path,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "seed-revision"
    shutil.copytree(authored_workspace, workspace)
    current_seed = ArtifactRuntime(workspace).show_artifact("slide_specs")[
        "art_direction_seed"
    ]

    result = HostCreateService(workspace).run(
        revise_stage="art_direction_seed"
    )

    assert result["status"] == "host_input_required"
    assert result["pending"]["stage"] == "art_direction_seed"
    request = read_json(Path(result["pending"]["request_path"]))
    assert request["context"]["revision_request"] == {
        "requested": True,
        "supersedes": current_seed,
    }
    assert ArtifactRuntime(workspace).show_artifact("deck_outline") == ArtifactRuntime(
        authored_workspace
    ).show_artifact("deck_outline")


def test_artifact_tool_failure_writes_terminal_receipt(
    authored_workspace: Path,
    tmp_path: Path,
) -> None:
    node, modules = _fake_artifact_tool_runtime(tmp_path)
    fonts = write_fontconfig_tools(tmp_path)
    preflight = RenderPreflightService(
        authored_workspace,
        node=str(node),
        artifact_tool_modules=modules,
        font_match=str(fonts),
    ).run(("artifact-tool",), include_exports=False)
    assert preflight.report["status"] == "pass", preflight.report

    with pytest.raises(RenderAttemptError) as failure:
        ArtifactToolRenderBackend(
            node=str(node),
            modules=modules,
        ).render(authored_workspace, preflight)

    receipt = read_json(Path(failure.value.receipt_path))
    assert receipt["status"] == "render_failed"
    assert receipt["diagnostics"]["stage"] == "adapter"
    assert receipt["diagnostics"]["exit_code"] == 9
    assert receipt["diagnostics"]["timed_out"] is False
    assert "synthetic-adapter-failure" in receipt["diagnostics"]["stderr"]
    assert str(authored_workspace) not in receipt["diagnostics"]["stderr"]
    assert str(modules) not in receipt["diagnostics"]["stderr"]
    assert "<candidate>" in receipt["diagnostics"]["stderr"]
    assert "<node_modules>" in receipt["diagnostics"]["stderr"]
    assert receipt["input"]["sha256"] == sha256_file(Path(receipt["input"]["path"]))


def test_host_create_success_closes_candidate_receipt(
    authored_workspace: Path,
    tmp_path: Path,
) -> None:
    node, modules = _fake_successful_artifact_tool_runtime(tmp_path)
    fonts = write_fontconfig_tools(tmp_path)

    result = HostCreateService(
        authored_workspace,
        node=str(node),
        modules=modules,
        font_match=str(fonts),
    ).run(render=True)

    assert result["status"] == "candidate_office_review_pending", result
    assert result["scope"] == "full"
    assert result["office_review"] == "pending"
    assert result["release_approved"] is False
    receipt_path = Path(result["receipt_path"])
    receipt = read_json(receipt_path)
    assert receipt["status"] == "candidate_office_review_pending"
    assert receipt["diagnostics"]["stage"] == "complete"
    assert all(
        Path(item["path"]).is_file()
        and item["sha256"] == sha256_file(Path(item["path"]))
        for item in receipt["outputs"]
    )


def test_artifact_tool_timeout_writes_terminal_receipt(
    authored_workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node, modules = _fake_artifact_tool_runtime(tmp_path)
    fonts = write_fontconfig_tools(tmp_path)
    preflight = RenderPreflightService(
        authored_workspace,
        node=str(node),
        artifact_tool_modules=modules,
        font_match=str(fonts),
    ).run(("artifact-tool",), include_exports=False)
    assert preflight.report["status"] == "pass", preflight.report

    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd="node",
            timeout=300,
            output="partial-output",
            stderr="synthetic-timeout",
        )

    backend = ArtifactToolRenderBackend(
        node=str(node),
        modules=modules,
    )
    resolved_runtime = backend._runtime()
    monkeypatch.setattr(backend, "_runtime", lambda: resolved_runtime)
    monkeypatch.setattr(
        "slidethus.render_backends.artifact_tool.subprocess.run",
        time_out,
    )
    with pytest.raises(RenderAttemptError) as failure:
        backend.render(authored_workspace, preflight)

    receipt = read_json(Path(failure.value.receipt_path))
    assert receipt["status"] == "render_timed_out"
    assert receipt["diagnostics"]["stage"] == "adapter"
    assert receipt["diagnostics"]["timed_out"] is True
    assert "300 seconds" in receipt["diagnostics"]["error"]


def test_tampered_taste_prototype_invalidates_the_final_visual_system(
    authored_workspace: Path,
    tmp_path: Path,
) -> None:
    """Provenance remains a current input to G6, without becoming an aesthetic score."""

    workspace = tmp_path / "tampered-prototype"
    shutil.copytree(authored_workspace, workspace)
    prototype = workspace / "design/prototypes/fixture.html"
    prototype.write_text("<main>tampered prototype</main>\n", encoding="utf-8")

    gate = evaluate_gate(workspace, "G6")

    assert not gate.passed
    assert any("prototype hash mismatch" in reason for reason in gate.reasons)


@pytest.mark.skipif(not os.environ.get("RUNTIME_NODE_MODULES"), reason="optional host Artifact Tool runtime")
def test_real_artifact_sample_and_full_share_ir_and_embed_media(authored_workspace: Path, tmp_path: Path) -> None:
    fonts = write_fontconfig_tools(tmp_path)
    preflight = RenderPreflightService(authored_workspace, font_match=str(fonts)).run(("artifact-tool",), include_exports=False)
    assert preflight.report["status"] == "pass", preflight.report
    backend = ArtifactToolRenderBackend()
    full = HostCreateService(authored_workspace, font_match=str(fonts)).run(render=True)
    assert full["status"] == "candidate_office_review_pending", full
    sample = backend.render(authored_workspace, preflight, slide_ids=("S-003", "S-002"))
    assert full["scope"] == "full" and sample["scope"] == "sample"
    assert sample["slide_ids"] == ["S-002", "S-003"]
    assert full["renderer_ir"] == sample["renderer_ir"]
    assert full["renderer"] == sample["renderer"]
    assert full["release_approved"] is sample["release_approved"] is False
    for slide_id in sample["slide_ids"]:
        full_png = Path(full["receipt_path"]).parent / f"{slide_id}.png"
        sample_png = Path(sample["receipt_path"]).parent / f"{slide_id}.png"
        assert full_png.read_bytes() == sample_png.read_bytes()
    for receipt in (full, sample):
        pptx = Path(receipt["outputs"][0]["path"])
        assert sha256_file(pptx) == receipt["outputs"][0]["sha256"]
        with ZipFile(pptx) as z:
            assert any(name.startswith("ppt/media/") for name in z.namelist())
            # Verify serialized font authority, not just the IR or PNG fallback.
            drawing_ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            slide_parts = [name for name in z.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
            for part in slide_parts:
                slide_root = ET.fromstring(z.read(part))
                runs = slide_root.findall(".//a:r[a:t]", drawing_ns)
                assert runs
                for run in runs:
                    font = run.find("a:rPr/a:latin", drawing_ns)
                    assert font is not None and font.get("typeface") == "Arial"
            charts = [name for name in z.namelist() if "/charts/chart" in name and name.endswith(".xml")]
            assert len(charts) == 1
            root = ET.fromstring(z.read(charts[0]))
            ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
            values = root.findall(".//c:ser/c:val/c:numLit/c:pt/c:v", ns)
            assert [v.text for v in values] == ["2", "5"]
            categories = root.findall(".//c:ser/c:cat/c:strLit/c:pt/c:v", ns)
            assert [v.text for v in categories] == ["A", "B"]
    with pytest.raises(RenderBackendError, match="selection"):
        backend.render(authored_workspace, preflight, slide_ids=("S-999",))
    changed = copy.deepcopy(preflight)
    changed.compiled.ir["slides"][0]["background"] = "#FFFFFF"
    with pytest.raises(RenderBackendError, match="snapshots"):
        backend.render(authored_workspace, changed)
