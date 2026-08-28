from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import ArtifactError
from slidethus.gates import evaluate_gate

_ENGINE = "deterministic-visual-system"
_ENGINE_VERSION = "1.0.0"
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


def _pick_brand_color(requirements: list[str]) -> str | None:
    for requirement in requirements:
        match = _HEX.search(str(requirement))
        if match:
            return match.group(0).upper()
    return None


def _generated_at(runtime: ArtifactRuntime, artifact_types: set[str]) -> str:
    values = [
        str(item.get("updated_at"))
        for item in runtime.list_artifacts()
        if item.get("artifact_type") in artifact_types and item.get("updated_at")
    ]
    return max(values) if values else "1970-01-01T00:00:00Z"


class VisualSystemService:
    """Compile a deterministic Production visual system from frozen M3 planning artifacts."""

    def __init__(self, workspace: Path, *, runtime: ArtifactRuntime | None = None) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)

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
        language = str(brief.get("language", "en")).lower()
        brand_requirements = [str(item) for item in brief.get("constraints", {}).get("brand_requirements", [])]
        primary = _pick_brand_color(brand_requirements) or "#154C5A"
        accent = "#D76745"
        background = "#F7F4ED"
        surface = "#FFFFFF"
        text_primary = "#17233C"
        text_secondary = "#667085"
        if language.startswith("zh"):
            preferred_font = "Noto Sans CJK SC"
            fallbacks = ["Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"]
        else:
            preferred_font = "Aptos"
            fallbacks = ["Arial", "Helvetica", "Liberation Sans", "Noto Sans"]
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
            "theme_id": "THEME-PRODUCTION-EDITORIAL",
            "tone": ["editorial", "clear", "professional", "restrained"],
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
            },
            "typography": {
                "display": {
                    "font_family": preferred_font,
                    "font_size": 40,
                    "font_weight": 700,
                    "line_height": 1.12,
                    "color": text_primary,
                    "letter_spacing": 0,
                },
                "title": {
                    "font_family": preferred_font,
                    "font_size": 30,
                    "font_weight": 700,
                    "line_height": 1.18,
                    "color": text_primary,
                    "letter_spacing": 0,
                },
                "body": {
                    "font_family": preferred_font,
                    "font_size": 20,
                    "font_weight": 400,
                    "line_height": 1.28,
                    "color": text_primary,
                    "letter_spacing": 0,
                },
                "caption": {
                    "font_family": preferred_font,
                    "font_size": 12,
                    "font_weight": 400,
                    "line_height": 1.2,
                    "color": text_secondary,
                    "letter_spacing": 0,
                },
            },
            "spacing": {
                "base": 8,
                "region_gap": max(20, float(layouts.get("safe_area", {}).get("left", 56)) / 2),
                "safe_area": copy.deepcopy(layouts["safe_area"]),
            },
            "shape_rules": {
                "corner_radius": 12,
                "border_width": 1,
                "surface_border": "#D8D2C6",
                "accent_bar": "left",
                "section_marker": "ordinal",
                "page_types": sorted(page_types),
            },
            "chart_rules": {
                "axis_color": text_secondary,
                "label_color": text_primary,
                "primary_series": primary,
                "accent_series": accent,
                "minimum_label_pt": 12,
            },
            "image_rules": {
                "fit": "cover",
                "corner_radius": 10,
                "missing_asset": "fail",
            },
            "icon_rules": {
                "style": "geometric",
                "stroke_width": 2,
                "color": primary,
            },
            "layout_policy": {
                "max_same_family_consecutive": 3,
                "max_bento_ratio": 0.35,
                "min_gap": 20,
            },
            "forbidden_patterns": [
                "bento-as-default",
                "body-text-below-planning-floor",
                "unmanifested-external-asset",
                "global-font-shrink-to-hide-overflow",
            ],
            "font_fallbacks": {preferred_font: fallbacks},
            "brand_assets": brand_assets,
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
        if current == candidate:
            return copy.deepcopy(candidate)
        self.runtime.write_artifact(
            "visual_system",
            candidate,
            expected_version=version,
            status="approved",
            created_by="visual-system-service",
        )
        return copy.deepcopy(candidate)
