from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from slidethus.art_direction import compile_art_direction
from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import ArtifactError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import read_json
from slidethus.protocols import ArtDirectionProvider

_ENGINE = "deterministic-visual-system"
_ENGINE_VERSION = "1.1.0"


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


class VisualSystemService:
    """Compile a deterministic Production visual system from frozen M3 planning artifacts."""

    def __init__(
        self,
        workspace: Path,
        *,
        runtime: ArtifactRuntime | None = None,
        art_direction_provider: ArtDirectionProvider | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.art_direction_provider = art_direction_provider

    def compile(self) -> dict[str, Any]:
        """Create or reuse the current visual-system artifact without changing M3 semantics."""

        gate = evaluate_gate(self.workspace, "G5B")
        if not gate.passed:
            raise ArtifactError("Visual System requires current G5B: " + "; ".join(gate.reasons))
        graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "deck_outline", "slide_specs", "layout_plans", "asset_manifest")
        )
        brief = graph["project_brief"]["data"]
        outline = graph["deck_outline"]["data"]
        layouts = graph["layout_plans"]["data"]
        assets = graph["asset_manifest"]["data"]
        compiled_direction = compile_art_direction(
            graph,
            provider=self.art_direction_provider,
            schema_registry=self.runtime.registry,
        )
        direction = compiled_direction.packet["direction"]
        palette = direction["palette"]
        typography = direction["typography"]
        composition = direction["composition"]
        primary = str(palette["primary"])
        accent = str(palette["accent"])
        background = str(palette["background"])
        surface = str(palette["surface"])
        text_primary = str(palette["text_primary"])
        text_secondary = str(palette["text_secondary"])
        preferred_font = str(typography["preferred_font"])
        fallbacks = [str(item) for item in typography["fallbacks"]]
        page_types = {
            str(item.get("slide_type"))
            for item in outline.get("slides", [])
            if item.get("status") != "excluded"
        }
        brand_assets = sorted(
            str(item["asset_id"])
            for item in assets.get("assets", [])
            if item.get("kind") in {"logo", "template"}
            and item.get("status") == "available"
            and item.get("allowed_use") not in {"reference_only", "do_not_use"}
        )
        inputs = [
            _artifact_ref(graph[artifact_type], artifact_type)
            for artifact_type in (
                "project_brief",
                "deck_outline",
                "slide_specs",
                "layout_plans",
                "asset_manifest",
            )
        ]
        candidate = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(brief["project_id"]),
            "deck_id": str(outline["deck_id"]),
            "theme_id": str(direction["theme_id"]),
            "tone": [str(item) for item in direction["tone"]],
            "canvas": {
                "background": background,
                "aspect_ratio": str(brief.get("constraints", {}).get("aspect_ratio", "16:9")),
            },
            "colors": {
                "background": background,
                "surface": surface,
                "text_primary": text_primary,
                "text_secondary": text_secondary,
                "primary": primary,
                "accent": accent,
                "surface_muted": str(palette["surface_muted"]),
                "primary_soft": str(palette["primary_soft"]),
                "accent_soft": str(palette["accent_soft"]),
            },
            "typography": {
                "display": {
                    "font_family": preferred_font,
                    "font_size": float(typography["display_size"]),
                    "font_weight": 700,
                    "line_height": 1.12,
                    "color": text_primary,
                    "letter_spacing": 0,
                },
                "title": {
                    "font_family": preferred_font,
                    "font_size": float(typography["title_size"]),
                    "font_weight": 700,
                    "line_height": 1.18,
                    "color": text_primary,
                    "letter_spacing": 0,
                },
                "body": {
                    "font_family": preferred_font,
                    "font_size": float(typography["body_size"]),
                    "font_weight": 400,
                    "line_height": 1.28,
                    "color": text_primary,
                    "letter_spacing": 0,
                },
                "caption": {
                    "font_family": preferred_font,
                    "font_size": float(typography["caption_size"]),
                    "font_weight": 400,
                    "line_height": 1.2,
                    "color": text_secondary,
                    "letter_spacing": 0,
                },
            },
            "spacing": {
                "base": 8,
                "region_gap": float(composition["region_gap"]),
                "safe_area": copy.deepcopy(layouts["safe_area"]),
            },
            "shape_rules": {
                "corner_radius": float(composition["corner_radius"]),
                "border_width": 1,
                "surface_border": "#D8D2C6",
                "accent_bar": "left",
                "section_marker": "ordinal",
                "page_types": sorted(page_types),
                "page_role_treatments": copy.deepcopy(composition["page_role_treatments"]),
                "component_variants": list(composition["component_variants"]),
                "deck_rhythm": str(composition["deck_rhythm"]),
                "variation_rule": str(composition["variation_rule"]),
            },
            "chart_rules": {
                "axis_color": text_secondary,
                "label_color": text_primary,
                "primary_series": primary,
                "accent_series": accent,
                "minimum_label_pt": 12,
            },
            "image_rules": {
                "fit": str(direction["image_direction"]["fit"]),
                "corner_radius": 10,
                "missing_asset": str(direction["image_direction"]["missing_asset"]),
                "style": str(direction["image_direction"]["style"]),
                "prompt_keywords": list(direction["image_direction"].get("prompt_keywords", [])),
            },
            "icon_rules": {
                "style": "geometric",
                "stroke_width": 2,
                "color": primary,
            },
            "layout_policy": {
                "max_same_family_consecutive": int(composition["max_same_family_consecutive"]),
                "max_bento_ratio": float(composition["max_bento_ratio"]),
                "min_gap": float(composition["min_gap"]),
            },
            "forbidden_patterns": list(direction["forbidden_patterns"]),
            "font_fallbacks": {preferred_font: fallbacks},
            "brand_assets": brand_assets,
            "art_direction": {
                "packet_id": str(compiled_direction.packet["packet_id"]),
                "path": compiled_direction.relative_path.as_posix(),
                "content_hash": compiled_direction.content_hash,
                "provider": {
                    "name": str(compiled_direction.packet["provider"]["name"]),
                    "version": str(compiled_direction.packet["provider"]["version"]),
                    "mode": str(compiled_direction.packet["provider"]["mode"]),
                },
            },
            "render_lineage": {
                "engine": _ENGINE,
                "engine_version": _ENGINE_VERSION,
                "generated_at": _generated_at(
                    self.runtime,
                    {"project_brief", "deck_outline", "slide_specs", "layout_plans", "asset_manifest"},
                ),
                "inputs": inputs,
            },
        }
        try:
            current, version = self.runtime.read_artifact_snapshot("visual_system")
        except ArtifactError:
            current = None
            version = 0
        fact_path = self.workspace / compiled_direction.relative_path
        if current == candidate and fact_path.is_file():
            if read_json(fact_path) != compiled_direction.packet:
                raise ArtifactError(
                    f"Immutable Art Direction Packet contains different content: {fact_path}"
                )
            return copy.deepcopy(candidate)
        self.runtime.write_artifact_with_runtime_fact(
            "visual_system",
            candidate,
            expected_version=version,
            fact_path=fact_path,
            fact_data=compiled_direction.packet,
            status="approved",
            created_by="visual-system-service",
        )
        return copy.deepcopy(candidate)
