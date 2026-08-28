from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import RenderCompileError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import atomic_create_json, read_json
from slidethus.render_ir import (
    renderer_ir_file_key,
    renderer_ir_id,
    validate_renderer_ir_data,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.font_resolution import FontResolution


@dataclass(frozen=True)
class RenderCompileResult:
    ir: dict[str, Any]
    path: Path
    changed: bool


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


def _generated_at(runtime: ArtifactRuntime, artifact_types: set[str]) -> str:
    values = [
        str(item.get("updated_at"))
        for item in runtime.list_artifacts()
        if item.get("artifact_type") in artifact_types and item.get("updated_at")
    ]
    return max(values) if values else "1970-01-01T00:00:00Z"


def _style_for(
    block: dict[str, Any],
    slide_type: str,
    visual: dict[str, Any],
    font_map: dict[str, str],
) -> dict[str, Any]:
    role = str(block.get("semantic_role", "body"))
    if role == "headline":
        text_style = visual["typography"]["display" if slide_type == "cover" else "title"]
    elif role in {"caption", "footer", "label"}:
        text_style = visual["typography"]["caption"]
    else:
        text_style = visual["typography"]["body"]
    surface = role in {"body", "evidence", "diagram", "table", "chart", "quote"}
    return {
        "font_family": font_map.get(
            str(text_style["font_family"]),
            str(text_style["font_family"]),
        ),
        "font_size": float(text_style["font_size"]),
        "font_weight": int(text_style["font_weight"]),
        "line_height": float(text_style["line_height"]),
        "color": str(text_style["color"]),
        "fill": str(visual["colors"]["surface"]) if surface else None,
        "border_color": str(visual["shape_rules"].get("surface_border", "#D8D2C6")) if surface else None,
        "border_width": float(visual["shape_rules"].get("border_width", 1)) if surface else 0,
    }


def _decorations(slide_id: str, family: str, visual: dict[str, Any]) -> list[dict[str, Any]]:
    accent = str(visual["colors"]["accent"])
    primary = str(visual["colors"]["primary"])
    output: list[dict[str, Any]] = [
        {
            "decoration_id": f"DEC-{slide_id.replace('-', '')}-01",
            "kind": "rect",
            "x": 0,
            "y": 0,
            "w": 12,
            "h": 720,
            "fill": accent,
            "stroke": None,
            "z": 0,
        }
    ]
    if family == "hero":
        output.append(
            {
                "decoration_id": f"DEC-{slide_id.replace('-', '')}-02",
                "kind": "ellipse",
                "x": 1080,
                "y": -90,
                "w": 300,
                "h": 300,
                "fill": primary,
                "stroke": None,
                "z": 0,
            }
        )
    elif family == "split":
        output.append(
            {
                "decoration_id": f"DEC-{slide_id.replace('-', '')}-02",
                "kind": "round_rect",
                "x": 72,
                "y": 178,
                "w": 420,
                "h": 398,
                "fill": primary,
                "stroke": None,
                "z": 0,
            }
        )
    elif family == "case":
        output.append(
            {
                "decoration_id": f"DEC-{slide_id.replace('-', '')}-02",
                "kind": "ellipse",
                "x": 72,
                "y": 205,
                "w": 76,
                "h": 76,
                "fill": accent,
                "stroke": None,
                "z": 0,
            }
        )
    elif family in {"process", "timeline"}:
        output.append(
            {
                "decoration_id": f"DEC-{slide_id.replace('-', '')}-02",
                "kind": "line",
                "x": 96,
                "y": 580,
                "w": 1088,
                "h": 0,
                "fill": None,
                "stroke": primary,
                "z": 0,
            }
        )
    return output


class RenderCompileService:
    """Compile current M3+Visual System artifacts into one immutable backend-neutral IR."""

    def __init__(
        self,
        workspace: Path,
        *,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.output_dir = self.workspace / ".slidethus/render/ir"

    def compile(
        self,
        *,
        font_resolutions: tuple[FontResolution, ...] = (),
    ) -> RenderCompileResult:
        gate = evaluate_gate(self.workspace, "G6")
        if not gate.passed:
            raise RenderCompileError("Renderer IR requires current G6: " + "; ".join(gate.reasons))
        graph = self.runtime.read_artifact_graph_snapshot(
            (
                "project_brief",
                "asset_manifest",
                "deck_outline",
                "slide_specs",
                "layout_plans",
                "visual_system",
            )
        )
        resolution_by_requested = {
            item.requested: item for item in font_resolutions
        }
        font_map = {
            requested: resolution.actual
            for requested, resolution in resolution_by_requested.items()
        }
        brief = graph["project_brief"]["data"]
        assets = graph["asset_manifest"]["data"]
        outline = graph["deck_outline"]["data"]
        specs = graph["slide_specs"]["data"]
        layouts = graph["layout_plans"]["data"]
        visual = graph["visual_system"]["data"]

        expected_visual_inputs = [
            _artifact_ref(graph[artifact_type], artifact_type)
            for artifact_type in (
                "project_brief",
                "deck_outline",
                "slide_specs",
                "layout_plans",
                "asset_manifest",
            )
        ]
        lineage = visual.get("render_lineage", {})
        if lineage.get("engine") != "deterministic-visual-system":
            raise RenderCompileError("Visual System is not a Production M4 visual-system artifact")
        if lineage.get("inputs") != expected_visual_inputs:
            raise RenderCompileError("Visual System lineage is stale against current M3/asset artifacts")

        active_outline = [item for item in outline.get("slides", []) if item.get("status") != "excluded"]
        outline_by_id = {str(item["slide_id"]): item for item in active_outline}
        specs_by_id = {str(item["slide_id"]): item for item in specs.get("slides", [])}
        layout_by_id = {str(item["slide_id"]): item for item in layouts.get("plans", [])}
        expected_ids = [str(item["slide_id"]) for item in active_outline]
        if set(expected_ids) != set(specs_by_id) or set(expected_ids) != set(layout_by_id):
            raise RenderCompileError("Renderer inputs do not cover the same active slide set")

        asset_map = {str(item["asset_id"]): item for item in assets.get("assets", [])}
        used_assets: set[str] = set(str(item) for item in visual.get("brand_assets", []))
        fonts: set[str] = set()
        slides: list[dict[str, Any]] = []
        for ordinal, slide_id in enumerate(expected_ids, start=1):
            outline_slide = outline_by_id[slide_id]
            slide_spec = specs_by_id[slide_id]
            layout = layout_by_id[slide_id]
            blocks = {str(item["block_id"]): item for item in slide_spec.get("content_blocks", [])}
            regions: list[dict[str, Any]] = []
            for region in layout.get("regions", []):
                block_id = str(region["block_id"])
                block = blocks.get(block_id)
                if block is None:
                    raise RenderCompileError(f"Layout region references unknown block: {block_id}")
                style = _style_for(
                    block,
                    str(outline_slide["slide_type"]),
                    visual,
                    font_map,
                )
                fonts.add(style["font_family"])
                block_assets = [str(item) for item in block.get("asset_refs", [])]
                used_assets.update(block_assets)
                regions.append(
                    {
                        "region_id": str(region["region_id"]),
                        "block_id": block_id,
                        "semantic_role": str(block["semantic_role"]),
                        "content_type": str(block["content_type"]),
                        "priority": str(block["priority"]),
                        "content": copy.deepcopy(block.get("content")),
                        "claim_mode": str(block.get("claim_mode", "label")),
                        "evidence_qualification": block.get("evidence_qualification"),
                        "evidence_ids": list(block.get("evidence_ids", [])),
                        "asset_refs": block_assets,
                        "x": region["x"],
                        "y": region["y"],
                        "w": region["w"],
                        "h": region["h"],
                        "z": int(region["z"]),
                        "align": str(region["align"]),
                        "valign": str(region["valign"]),
                        "overflow_strategy": str(region["overflow_strategy"]),
                        "style": style,
                    }
                )
            slides.append(
                {
                    "slide_id": slide_id,
                    "ordinal": ordinal,
                    "layout_family": str(layout["layout_family"]),
                    "regions": sorted(regions, key=lambda item: (item["z"], item["region_id"])),
                    "decorations": _decorations(slide_id, str(layout["layout_family"]), visual),
                }
            )

        invalid_assets = sorted(
            asset_id
            for asset_id in used_assets
            if asset_id not in asset_map
            or asset_map[asset_id].get("status") != "available"
            or asset_map[asset_id].get("allowed_use") in {"reference_only", "do_not_use"}
        )
        if invalid_assets:
            raise RenderCompileError(
                "Renderer IR references unavailable or disallowed assets: " + ", ".join(invalid_assets)
            )

        input_artifacts = sorted(
            [_artifact_ref(graph[artifact_type], artifact_type) for artifact_type in graph],
            key=lambda item: item["artifact_type"],
        )
        ir: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(brief["project_id"]),
            "deck_id": str(outline["deck_id"]),
            "ir_id": "",
            "generated_at": _generated_at(self.runtime, set(graph)),
            "input_artifacts": input_artifacts,
            "canvas": {
                "width": int(layouts["canvas"]["width"]),
                "height": int(layouts["canvas"]["height"]),
                "background": str(visual["colors"]["background"]),
            },
            "safe_area": copy.deepcopy(layouts["safe_area"]),
            "slides": slides,
            "fonts": sorted(fonts),
            "font_substitutions": [
                {
                    "requested": item.requested,
                    "actual": item.actual,
                    "status": item.status,
                    "reason": item.reason,
                }
                for item in sorted(font_resolutions, key=lambda value: value.requested)
            ],
            "asset_ids": sorted(used_assets),
            "warnings": [
                f"Font substituted: {item.requested} -> {item.actual} ({item.reason})"
                for item in sorted(font_resolutions, key=lambda value: value.requested)
                if item.status == "substituted"
            ],
        }
        ir["ir_id"] = renderer_ir_id(ir)
        errors = validate_renderer_ir_data(ir, self.schemas.schema_dir)
        if errors:
            raise RenderCompileError("Invalid Renderer IR: " + "; ".join(errors))
        path = self.output_dir / f"{renderer_ir_file_key(ir)}.json"
        created = atomic_create_json(path, ir)
        if not created and read_json(path) != ir:
            raise RenderCompileError(f"Immutable Renderer IR path contains different content: {path}")
        return RenderCompileResult(ir=copy.deepcopy(ir), path=path, changed=created)
