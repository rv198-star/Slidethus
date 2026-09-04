from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import RenderCompileError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import atomic_create_json, read_json, sha256_json
from slidethus.page_design import authored_styles, validate_page_designs
from slidethus.render_backends.artifact_tool_contract import artifact_tool_host_contract
from slidethus.render_ir import (
    renderer_ir_file_key,
    renderer_ir_id,
    validate_renderer_ir_data,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.font_resolution import FontResolution
from slidethus.text_capacity import (
    DEFAULT_HORIZONTAL_PADDING,
    DEFAULT_VERTICAL_PADDING,
    TextFitResult,
    fit_text,
)


@dataclass(frozen=True)
class RenderCompileResult:
    ir: dict[str, Any]
    path: Path
    changed: bool
    text_fits: tuple[RegionTextFit, ...]


@dataclass(frozen=True)
class RegionTextFit:
    """Bind one canonical text-fit result to its stable slide/block/region IDs."""

    slide_id: str
    block_id: str
    region_id: str
    result: TextFitResult


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
    *,
    family: str,
    region_index: int,
) -> dict[str, Any]:
    text_style = _text_style_for(block, slide_type, visual)
    role = str(block.get("semantic_role", "body"))
    surface = role in {"body", "evidence", "diagram", "table", "chart", "quote"}
    colors = visual["colors"]
    fill = str(colors["surface"]) if surface else None
    text_color = str(text_style["color"])
    border_color = str(visual["shape_rules"].get("surface_border", "#D8D2C6")) if surface else None
    border_width = float(visual["shape_rules"].get("border_width", 1)) if surface else 0
    if family == "hero":
        fill = None
        text_color = str(colors["surface"])
        border_color = None
        border_width = 0
    elif family == "case" and region_index == 1:
        fill = str(colors["primary"])
        text_color = str(colors["surface"])
        border_color = None
        border_width = 0
    elif family == "matrix" and str(block.get("content_type")) == "list":
        fill = str(colors.get("primary_soft", colors["surface"]))
        border_color = None
        border_width = 0
    elif family == "timeline" and surface:
        fill = str(
            colors.get(
                "primary_soft" if region_index % 2 else "accent_soft",
                colors["surface"],
            )
        )
        border_color = None
        border_width = 0
    elif family == "process" and region_index == 1:
        fill = str(colors["primary"])
        text_color = str(colors["surface"])
        border_color = None
        border_width = 0
    elif family == "process" and surface:
        fill = str(colors.get("surface_muted", colors["surface"]))
        border_color = None
        border_width = 0
    font_size = float(text_style["font_size"])
    if family == "hero" and role == "headline":
        font_size = max(font_size, 42.0)
    elif family == "hero" and role == "body":
        font_size = max(font_size, 22.0)
    elif family == "case" and region_index == 1:
        font_size = max(font_size, 24.0)
    return {
        "font_family": font_map.get(
            str(text_style["font_family"]),
            str(text_style["font_family"]),
        ),
        "font_size": font_size,
        "font_weight": int(text_style["font_weight"]),
        "line_height": float(text_style["line_height"]),
        "color": text_color,
        "fill": fill,
        "border_color": border_color,
        "border_width": border_width,
    }


def _text_style_for(
    block: dict[str, Any],
    slide_type: str,
    visual: dict[str, Any],
) -> dict[str, Any]:
    role = str(block.get("semantic_role", "body"))
    if role == "headline":
        return visual["typography"]["display" if slide_type == "cover" else "title"]
    elif role in {"caption", "footer", "label"}:
        return visual["typography"]["caption"]
    return visual["typography"]["body"]


def _visible_text(content: Any, content_type: str) -> str:
    if isinstance(content, list):
        prefix = "• " if content_type == "list" else ""
        return "\n".join(prefix + str(item) for item in content)
    if isinstance(content, dict):
        return "\n".join(f"{key}: {value}" for key, value in content.items())
    return str(content or "")


def _strict_region_content(
    block: dict[str, Any],
    representation: dict[str, Any],
    view: dict[str, Any],
    *,
    region_id: str,
) -> tuple[Any, dict[str, Any]]:
    """Materialize admitted semantics and view decisions without carrier fallback."""

    content = copy.deepcopy(block.get("content"))
    if region_id != view["primary_region_id"]:
        return content, {}
    kind = str(representation["kind"])
    semantics = representation["semantics"]
    details = copy.deepcopy(view["details"])
    if kind == "chart":
        content = {
            "type": semantics["chart_type"],
            "categories": copy.deepcopy(semantics["categories"]),
            "series": copy.deepcopy(semantics["series"]),
        }
    elif kind == "diagram":
        geometry = {
            str(item["node_id"]): item for item in details["node_geometry"]
        }
        content = {
            "nodes": [
                {
                    "id": node["id"],
                    "label": node["label"],
                    **{
                        key: geometry[str(node["id"])][key]
                        for key in ("x", "y", "w", "h")
                    },
                }
                for node in semantics["nodes"]
            ],
            "edges": [
                {
                    "id": edge["id"],
                    "from": edge["from"],
                    "to": edge["to"],
                    "label": edge["meaning"],
                }
                for edge in semantics["edges"]
            ],
        }
    return content, details


def _connector_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (
            item
            for item in regions
            if str(item.get("semantic_role"))
            not in {"headline", "subhead", "caption", "footer", "label"}
        ),
        key=lambda item: (float(item["y"]), float(item["x"]), str(item["region_id"])),
    )


def _connector_lines(
    slide_id: str,
    regions: list[dict[str, Any]],
    stroke: str,
    *,
    family: str,
) -> list[dict[str, Any]]:
    candidates = _connector_regions(regions)
    if len(candidates) < 2:
        return []
    if family == "timeline":
        candidates = sorted(candidates, key=lambda item: (int(item["z"]), str(item["region_id"])))
        segments: list[tuple[float, float, float, float]] = []
        for current, following in zip(candidates, candidates[1:], strict=False):
            start_x = float(current["x"]) + float(current["w"]) + 2.0
            start_y = float(current["y"]) + float(current["h"]) / 2
            end_x = float(following["x"]) - 2.0
            end_y = float(following["y"]) + float(following["h"]) / 2
            if end_x <= start_x:
                continue
            turn_x = (start_x + end_x) / 2
            segments.extend(
                [
                    (start_x, start_y, turn_x - start_x, 0.0),
                    (turn_x, min(start_y, end_y), 0.0, abs(end_y - start_y)),
                    (turn_x, end_y, end_x - turn_x, 0.0),
                ]
            )
        return [
            {
                "decoration_id": f"DEC-{slide_id.replace('-', '')}-{index:02d}",
                "kind": "line",
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "fill": None,
                "stroke": stroke,
                "z": 0,
            }
            for index, (x, y, w, h) in enumerate(segments, start=2)
        ]
    rows: list[list[dict[str, Any]]] = []
    for region in candidates:
        matching = next(
            (
                row
                for row in rows
                if abs(float(row[0]["y"]) - float(region["y"])) <= 1.0
            ),
            None,
        )
        if matching is None:
            rows.append([region])
        else:
            matching.append(region)
    for row in rows:
        row.sort(key=lambda item: (float(item["x"]), str(item["region_id"])))

    segments: list[tuple[float, float, float, float]] = []
    for row in rows:
        for left, right in zip(row, row[1:], strict=False):
            start_x = float(left["x"]) + float(left["w"])
            end_x = float(right["x"])
            overlap_top = max(float(left["y"]), float(right["y"]))
            overlap_bottom = min(
                float(left["y"]) + float(left["h"]),
                float(right["y"]) + float(right["h"]),
            )
            if end_x > start_x and overlap_bottom >= overlap_top:
                anchor_y = (overlap_top + overlap_bottom) / 2
                segments.append((start_x, anchor_y, end_x - start_x, 0.0))
    for upper, lower in zip(rows, rows[1:], strict=False):
        start = upper[-1]
        end = lower[0]
        start_x = float(start["x"]) + float(start["w"])
        start_y = float(start["y"]) + float(start["h"])
        end_x = float(end["x"])
        end_y = float(end["y"])
        if end_y <= start_y:
            continue
        turn_y = (start_y + end_y) / 2
        segments.extend(
            [
                (start_x, start_y, 0.0, turn_y - start_y),
                (min(start_x, end_x), turn_y, abs(end_x - start_x), 0.0),
                (end_x, turn_y, 0.0, end_y - turn_y),
            ]
        )
    return [
        {
            "decoration_id": f"DEC-{slide_id.replace('-', '')}-{index:02d}",
            "kind": "line",
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "fill": None,
            "stroke": stroke,
            "z": 0,
        }
        for index, (x, y, w, h) in enumerate(segments, start=2)
    ]


def _decorations(
    slide_id: str,
    family: str,
    visual: dict[str, Any],
    regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    accent = str(visual["colors"]["accent"])
    primary = str(visual["colors"]["primary"])
    output: list[dict[str, Any]] = []
    if family == "hero":
        output.extend(
            [
                {
                    "decoration_id": f"DEC-{slide_id.replace('-', '')}-01",
                    "kind": "rect",
                    "x": 0,
                    "y": 0,
                    "w": 1280,
                    "h": 720,
                    "fill": primary,
                    "stroke": None,
                    "z": 0,
                },
                {
                    "decoration_id": f"DEC-{slide_id.replace('-', '')}-02",
                    "kind": "ellipse",
                    "x": 1010,
                    "y": 440,
                    "w": 420,
                    "h": 420,
                    "fill": accent,
                    "stroke": None,
                    "z": 0,
                },
            ]
        )
    else:
        output.append(
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
        )
    if family == "split":
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
    elif family in {"process", "timeline"}:
        output.extend(_connector_lines(slide_id, regions, primary, family=family))
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

    def required_font_characters(self) -> dict[str, str]:
        """Return visible renderer characters grouped by requested typography family."""

        gate = evaluate_gate(self.workspace, "G6")
        if not gate.passed:
            raise RenderCompileError(
                "Font requirements require current G6: " + "; ".join(gate.reasons)
            )
        graph = self.runtime.read_artifact_graph_snapshot(
            ("deck_outline", "slide_specs", "visual_system")
        )
        outline = graph["deck_outline"]["data"]
        specs = graph["slide_specs"]["data"]
        visual = graph["visual_system"]["data"]
        explicit_styles = authored_styles(visual)
        outline_by_id = {
            str(item["slide_id"]): item
            for item in outline.get("slides", [])
            if item.get("status") != "excluded"
        }
        characters: dict[str, set[str]] = {}
        for slide in specs.get("slides", []):
            slide_id = str(slide["slide_id"])
            outline_slide = outline_by_id.get(slide_id)
            if outline_slide is None:
                continue
            for block in slide.get("content_blocks", []):
                text_style = explicit_styles.get(str(block["block_id"])) or _text_style_for(
                    block,
                    str(outline_slide["slide_type"]),
                    visual,
                )
                family = str(text_style["font_family"])
                visible = _visible_text(
                    block.get("content"),
                    str(block.get("content_type")),
                )
                qualification = block.get("evidence_qualification")
                if qualification:
                    visible += "\n" + str(qualification)
                characters.setdefault(family, set()).update(visible)
        return {
            family: "".join(sorted(values, key=ord))
            for family, values in sorted(characters.items())
        }

    def compile(
        self,
        *,
        font_resolutions: tuple[FontResolution, ...] = (),
        collect_readiness_failures: bool = False,
        text_horizontal_padding: float = DEFAULT_HORIZONTAL_PADDING,
        text_vertical_padding: float = DEFAULT_VERTICAL_PADDING,
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
        strict_versions = {
            str(specs.get("schema_version", "")).startswith("0.2."),
            str(layouts.get("schema_version", "")).startswith("0.2."),
            str(visual.get("schema_version", "")).startswith("0.2."),
        }
        if len(strict_versions) != 1:
            raise RenderCompileError(
                "Renderer inputs mix legacy and quality-by-construction generations"
            )
        strict_grammar = True in strict_versions
        explicit_styles = authored_styles(visual)
        page_designs = {p["slide_id"]: p for p in visual.get("page_designs", [])}
        if "page_designs" in visual:
            validate_page_designs(visual["page_designs"], specs, layouts)
        if strict_grammar:
            if set(page_designs) != {str(item["slide_id"]) for item in specs["slides"]}:
                raise RenderCompileError(
                    "Renderer IR 0.2 requires complete authored page designs"
                )
            capability = visual.get("capability_contract")
            expected_contract = artifact_tool_host_contract()
            if capability != {
                "backend": expected_contract["backend"],
                "contract_version": expected_contract["contract_version"],
                "capability_id": expected_contract["capability_id"],
                "contract_hash": "sha256:" + sha256_json(expected_contract),
            }:
                raise RenderCompileError(
                    "Visual System producer capability is absent or differs from the closed grammar"
                )

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
        # The substitution ledger describes every admitted font resolution, not
        # only the families reached by the final authored page styles. Keep its
        # actual families in the IR inventory so the two fields remain a closed
        # and independently verifiable contract.
        fonts: set[str] = {item.actual for item in font_resolutions}
        slides: list[dict[str, Any]] = []
        text_fits: list[RegionTextFit] = []
        for ordinal, slide_id in enumerate(expected_ids, start=1):
            outline_slide = outline_by_id[slide_id]
            slide_spec = specs_by_id[slide_id]
            layout = layout_by_id[slide_id]
            representation = slide_spec.get("representation")
            if strict_grammar and not isinstance(representation, dict):
                raise RenderCompileError(f"{slide_id} lacks admitted representation semantics")
            page_design = page_designs.get(slide_id, {})
            authored_regions = {
                str(item["block_id"]): item
                for item in page_design.get("regions", [])
            }
            blocks = {str(item["block_id"]): item for item in slide_spec.get("content_blocks", [])}
            regions: list[dict[str, Any]] = []
            for region in layout.get("regions", []):
                block_id = str(region["block_id"])
                block = blocks.get(block_id)
                if block is None:
                    raise RenderCompileError(f"Layout region references unknown block: {block_id}")
                if strict_grammar:
                    authored = authored_regions.get(block_id)
                    if authored is None or not authored.get("style_id"):
                        raise RenderCompileError(
                            f"Closed grammar omitted style authority for {block_id}"
                        )
                    style = copy.deepcopy(authored["style"])
                else:
                    style = copy.deepcopy(explicit_styles.get(block_id)) or _style_for(
                        block,
                        str(outline_slide["slide_type"]),
                        visual,
                        font_map,
                        family=str(layout["layout_family"]),
                        region_index=int(region["z"]),
                    )
                style["font_family"] = font_map.get(style["font_family"], style["font_family"])
                content_type = str(block.get("content_type"))
                if content_type in {"text", "list", "metric", "quote"}:
                    overflow_strategy = str(region.get("overflow_strategy"))
                    preferred = float(style["font_size"])
                    floor = (
                        float(region.get("min_font_pt", preferred))
                        if overflow_strategy == "shrink_with_floor"
                        else preferred
                    )
                    fit = fit_text(
                        block.get("content"),
                        content_type,
                        width=float(region["w"]),
                        height=float(region["h"]),
                        preferred=preferred,
                        floor=floor,
                        line_height=float(style["line_height"]),
                        qualification=block.get("evidence_qualification"),
                        horizontal_padding=text_horizontal_padding,
                        vertical_padding=text_vertical_padding,
                    )
                    text_fits.append(
                        RegionTextFit(
                            slide_id=slide_id,
                            block_id=block_id,
                            region_id=str(region["region_id"]),
                            result=fit,
                        )
                    )
                    if fit.fitted_font_pt is not None:
                        style["font_size"] = fit.fitted_font_pt
                    else:
                        # Preflight needs a complete IR to aggregate every deterministic
                        # blocker. It must never pass this floor-sized region to a backend.
                        style["font_size"] = fit.floor_font_pt
                fonts.add(style["font_family"])
                block_assets = [str(item) for item in block.get("asset_refs", [])]
                used_assets.update(block_assets)
                strict_content = copy.deepcopy(block.get("content"))
                render_options: dict[str, Any] = {}
                if strict_grammar:
                    strict_content, render_options = _strict_region_content(
                        block,
                        representation,
                        layout["view"],
                        region_id=str(region["region_id"]),
                    )
                    if representation["kind"] == "image" and render_options:
                        if style.get("image_fit") != render_options.get("fit"):
                            raise RenderCompileError(
                                f"Image style/view fit mismatch on {slide_id}"
                            )
                regions.append(
                    {
                        "region_id": str(region["region_id"]),
                        "block_id": block_id,
                        "semantic_role": str(block["semantic_role"]),
                        "content_type": str(block["content_type"]),
                        "priority": str(block["priority"]),
                        "content": strict_content,
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
                        **(
                            {
                                "style_id": str(authored_regions[block_id]["style_id"]),
                                "representation_id": str(representation["representation_id"]),
                                "render_options": render_options,
                                "consumption_trace": {
                                    "decision_ids": [
                                        str(representation["representation_id"]),
                                        str(layout["representation_ref"]["content_hash"]),
                                        str(page_design["page_family_id"]),
                                        str(page_design["component_variant_id"]),
                                        str(authored_regions[block_id]["style_id"]),
                                    ],
                                    "output_ids": [str(region["region_id"])],
                                },
                            }
                            if strict_grammar
                            else {}
                        ),
                    }
                )
            slides.append(
                {
                    "slide_id": slide_id,
                    "ordinal": ordinal,
                    **({"background": page_designs[slide_id]["background"]} if page_designs else {}),
                    "layout_family": str(layout["layout_family"]),
                    "regions": sorted(regions, key=lambda item: (item["z"], item["region_id"])),
                    "decorations": (
                        copy.deepcopy(page_designs[slide_id]["decorations"])
                        if page_designs
                        else _decorations(
                            slide_id,
                            str(layout["layout_family"]),
                            visual,
                            regions,
                        )
                    ),
                    **(
                        {
                            "page_family_id": str(page_design["page_family_id"]),
                            "component_variant_id": str(page_design["component_variant_id"]),
                            "representation_ref": copy.deepcopy(layout["representation_ref"]),
                            "focal_order": copy.deepcopy(layout["focal_order"]),
                            "view": copy.deepcopy(layout["view"]),
                            "consumption_trace": {
                                "decision_ids": [
                                    str(representation["representation_id"]),
                                    str(layout["representation_ref"]["content_hash"]),
                                    str(page_design["page_family_id"]),
                                    str(page_design["component_variant_id"]),
                                ],
                                "output_ids": [slide_id],
                            },
                        }
                        if strict_grammar
                        else {}
                    ),
                }
            )

        invalid_assets = sorted(
            asset_id
            for asset_id in used_assets
            if asset_id not in asset_map
            or asset_map[asset_id].get("status") != "available"
            or asset_map[asset_id].get("allowed_use") in {"reference_only", "do_not_use"}
        )
        if invalid_assets and not collect_readiness_failures:
            raise RenderCompileError(
                "Renderer IR references unavailable or disallowed assets: " + ", ".join(invalid_assets)
            )

        failed_text = [item for item in text_fits if not item.result.fits]
        if failed_text and not collect_readiness_failures:
            detail = "; ".join(
                f"{item.region_id} floor={item.result.floor_font_pt:g}pt "
                f"required={item.result.required_height:.1f}px "
                f"available={item.result.available_height:.1f}px"
                for item in failed_text
            )
            raise RenderCompileError(
                "Office-conservative text capacity failed: " + detail
            )

        input_artifacts = sorted(
            [_artifact_ref(graph[artifact_type], artifact_type) for artifact_type in graph],
            key=lambda item: item["artifact_type"],
        )
        ir: dict[str, Any] = {
            "schema_version": "0.2.0" if strict_grammar else SCHEMA_VERSION,
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
            **(
                {
                    "producer_capability": copy.deepcopy(visual["capability_contract"]),
                    "compiler": {
                        "name": "slidethus-render-compile",
                        "version": "2.0.0",
                    },
                }
                if strict_grammar
                else {}
            ),
        }
        ir["ir_id"] = renderer_ir_id(ir)
        errors = validate_renderer_ir_data(ir, self.schemas.schema_dir)
        if errors:
            raise RenderCompileError("Invalid Renderer IR: " + "; ".join(errors))
        path = self.output_dir / f"{renderer_ir_file_key(ir)}.json"
        created = atomic_create_json(path, ir)
        if not created and read_json(path) != ir:
            raise RenderCompileError(f"Immutable Renderer IR path contains different content: {path}")
        return RenderCompileResult(
            ir=copy.deepcopy(ir),
            path=path,
            changed=created,
            text_fits=tuple(text_fits),
        )
