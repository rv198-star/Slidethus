from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import (
    FontResolutionError,
    RenderAssetError,
    RenderCapabilityError,
    RenderCompileError,
)
from slidethus.io_utils import atomic_create_json, read_json, sha256_file
from slidethus.render_backends.node_toolchain import node_executable, validate_sidecar
from slidethus.render_backends.node_toolchain import renderer_root as resolve_renderer_root
from slidethus.render_preflight import (
    render_check_id,
    render_preflight_file_key,
    render_preflight_id,
    validate_render_preflight_data,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.font_resolution import FontResolution, FontResolutionService
from slidethus.services.render_assets import RenderAssetService, ResolvedRenderAsset
from slidethus.services.render_compile import RenderCompileResult, RenderCompileService

_BACKENDS = {"final-svg", "pptxgenjs-native", "pptxgenjs-hybrid"}
_SUPPORTED_CONTENT = {
    "final-svg": {"text", "list", "metric", "quote", "spacer", "table", "chart", "image", "icon", "diagram"},
    "pptxgenjs-native": {"text", "list", "metric", "quote", "spacer", "table", "chart", "image", "icon", "diagram"},
    "pptxgenjs-hybrid": {"text", "list", "metric", "quote", "spacer", "table", "chart", "image", "icon", "diagram"},
}


@dataclass(frozen=True)
class RenderPreflightResult:
    report: dict[str, Any]
    path: Path
    compiled: RenderCompileResult
    fonts: tuple[FontResolution, ...]
    assets: dict[str, ResolvedRenderAsset]
    changed: bool


def _text_values(content: Any, content_type: str) -> list[str]:
    if isinstance(content, list):
        values = [str(item) for item in content]
        return [f"• {item}" for item in values] if content_type == "list" else values
    if isinstance(content, dict):
        return [f"{key}: {value}" for key, value in content.items()]
    return [str(content or "")]


def _glyph_units(value: str) -> float:
    return sum(0.56 if ord(char) < 128 else 1.0 for char in value)


def _estimated_lines(region: dict[str, Any]) -> int:
    style = region["style"]
    font_size = max(1.0, float(style["font_size"]))
    max_units = max(1.0, (float(region["w"]) - 32.0) / font_size)
    lines = 0
    for value in _text_values(region.get("content"), str(region.get("content_type"))):
        lines += max(1, math.ceil(_glyph_units(value) / max_units))
    return lines


def _overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return not (
        float(left["x"]) + float(left["w"]) <= float(right["x"])
        or float(right["x"]) + float(right["w"]) <= float(left["x"])
        or float(left["y"]) + float(left["h"]) <= float(right["y"])
        or float(right["y"]) + float(right["h"]) <= float(left["y"])
    )


def _check(
    *,
    code: str,
    status: str,
    severity: str,
    message: str,
    backend: str | None = None,
    slide_id: str | None = None,
    block_id: str | None = None,
    region_id: str | None = None,
) -> dict[str, Any]:
    item = {
        "check_id": "",
        "code": code,
        "status": status,
        "severity": severity,
        "backend": backend,
        "slide_id": slide_id,
        "block_id": block_id,
        "region_id": region_id,
        "message": " ".join(message.split()).strip()[:4000],
    }
    item["check_id"] = render_check_id(item)
    return item


class RenderPreflightService:
    """Run one backend-aware geometry, font, asset, and host-capability preflight."""

    def __init__(
        self,
        workspace: Path,
        *,
        renderer_root: Path | None = None,
        node: str | None = None,
        font_match: str | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.renderer_root = resolve_renderer_root(renderer_root)
        self.node = node
        self.fonts = FontResolutionService(font_match=font_match)
        self.schemas = schema_registry or SchemaRegistry()
        self.output_dir = self.workspace / ".slidethus/render/preflight"

    def _capabilities(
        self,
        backends: tuple[str, ...],
        *,
        include_exports: bool,
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        capabilities: list[dict[str, str]] = []
        checks: list[dict[str, Any]] = []
        if self.fonts.available:
            capabilities.append(
                {
                    "capability": "fontconfig",
                    "status": "available",
                    "detail": "Fontconfig family/file resolution is available.",
                }
            )
        else:
            capabilities.append(
                {
                    "capability": "fontconfig",
                    "status": "missing",
                    "detail": "Fontconfig fc-match is unavailable.",
                }
            )
            checks.append(
                _check(
                    code="font_resolution_capability_missing",
                    status="fail",
                    severity="major",
                    message="Production rendering requires font detection/substitution through fc-match.",
                )
            )
        if any(item.startswith("pptxgenjs-") for item in backends):
            try:
                node_executable(self.node)
                validate_sidecar(
                    self.renderer_root,
                    script_name="render.mjs",
                    dependencies={"pptxgenjs": "4.0.1"},
                )
            except RenderCapabilityError as exc:
                capabilities.append(
                    {
                        "capability": "pptxgenjs",
                        "status": "missing",
                        "detail": str(exc),
                    }
                )
                checks.append(
                    _check(
                        code="pptxgenjs_capability_missing",
                        status="fail",
                        severity="major",
                        message=str(exc),
                    )
                )
            else:
                capabilities.append(
                    {
                        "capability": "pptxgenjs",
                        "status": "available",
                        "detail": "Node.js and PptxGenJS 4.0.1 are available.",
                    }
                )
        if include_exports:
            try:
                node_executable(self.node)
                validate_sidecar(
                    self.renderer_root,
                    script_name="preview.mjs",
                    dependencies={"@resvg/resvg-js": "2.6.2", "pdf-lib": "1.17.1"},
                )
            except RenderCapabilityError as exc:
                capabilities.append(
                    {
                        "capability": "svg_png_pdf_export",
                        "status": "missing",
                        "detail": str(exc),
                    }
                )
                checks.append(
                    _check(
                        code="svg_export_capability_missing",
                        status="fail",
                        severity="major",
                        message=str(exc),
                    )
                )
            else:
                capabilities.append(
                    {
                        "capability": "svg_png_pdf_export",
                        "status": "available",
                        "detail": "Independent resvg PNG and pdf-lib PDF export are available.",
                    }
                )
        return capabilities, checks

    def run(
        self,
        backends: tuple[str, ...] | list[str],
        *,
        include_exports: bool = True,
    ) -> RenderPreflightResult:
        admitted_backends = tuple(sorted(set(str(item) for item in backends)))
        if not admitted_backends or not set(admitted_backends).issubset(_BACKENDS):
            raise RenderCompileError(
                "Render preflight requires admitted backend names: "
                + ", ".join(sorted(_BACKENDS))
            )
        capabilities, checks = self._capabilities(
            admitted_backends,
            include_exports=include_exports,
        )
        visual = read_json(self.workspace / "design/visual_system.json")
        resolutions: tuple[FontResolution, ...] = ()
        if self.fonts.available:
            try:
                resolutions = self.fonts.resolve_visual_system(visual)
            except (FontResolutionError, RenderCapabilityError) as exc:
                checks.append(
                    _check(
                        code="font_resolution_failed",
                        status="fail",
                        severity="major",
                        message=str(exc),
                    )
                )
        compiled = RenderCompileService(self.workspace).compile(
            font_resolutions=resolutions,
        )
        try:
            assets = RenderAssetService(self.workspace).resolve(
                tuple(compiled.ir.get("asset_ids", []))
            )
        except (RenderAssetError, RenderCapabilityError) as exc:
            assets = {}
            checks.append(
                _check(
                    code="render_asset_resolution_failed",
                    status="fail",
                    severity="major",
                    message=str(exc),
                )
            )
        width = float(compiled.ir["canvas"]["width"])
        height = float(compiled.ir["canvas"]["height"])
        safe = compiled.ir["safe_area"]
        for slide in compiled.ir["slides"]:
            regions = list(slide["regions"])
            for region in regions:
                slide_id = str(slide["slide_id"])
                block_id = str(region["block_id"])
                region_id = str(region["region_id"])
                within_canvas = (
                    float(region["x"]) >= 0
                    and float(region["y"]) >= 0
                    and float(region["x"]) + float(region["w"]) <= width
                    and float(region["y"]) + float(region["h"]) <= height
                )
                within_safe = (
                    float(region["x"]) >= float(safe["left"])
                    and float(region["y"]) >= float(safe["top"])
                    and float(region["x"]) + float(region["w"]) <= width - float(safe["right"])
                    and float(region["y"]) + float(region["h"]) <= height - float(safe["bottom"])
                )
                if not within_canvas or not within_safe:
                    checks.append(
                        _check(
                            code="render_region_out_of_bounds",
                            status="fail",
                            severity="major",
                            message="Region leaves the logical canvas or approved safe area.",
                            slide_id=slide_id,
                            block_id=block_id,
                            region_id=region_id,
                        )
                    )
                content_type = str(region["content_type"])
                if content_type in {"text", "list", "metric", "quote"}:
                    lines = _estimated_lines(region)
                    line_height = float(region["style"]["font_size"]) * float(
                        region["style"]["line_height"]
                    )
                    qualification_height = 24.0 if region.get("evidence_qualification") else 0.0
                    required_height = lines * line_height + qualification_height + 24.0
                    if required_height > float(region["h"]):
                        checks.append(
                            _check(
                                code="render_text_overflow",
                                status="fail",
                                severity="major",
                                message=(
                                    f"Estimated text height {required_height:.1f} exceeds "
                                    f"region height {float(region['h']):.1f}; return to P5A/P5B."
                                ),
                                slide_id=slide_id,
                                block_id=block_id,
                                region_id=region_id,
                            )
                        )
                for backend in admitted_backends:
                    if content_type not in _SUPPORTED_CONTENT[backend]:
                        checks.append(
                            _check(
                                code="backend_content_type_unsupported",
                                status="fail",
                                severity="major",
                                message=f"{backend} does not support content_type={content_type}.",
                                backend=backend,
                                slide_id=slide_id,
                                block_id=block_id,
                                region_id=region_id,
                            )
                        )
            for index, left in enumerate(regions):
                for right in regions[index + 1 :]:
                    if int(left["z"]) == int(right["z"]) and _overlap(left, right):
                        checks.append(
                            _check(
                                code="render_region_collision",
                                status="fail",
                                severity="major",
                                message=(
                                    f"Regions {left['region_id']} and {right['region_id']} collide at z={left['z']}."
                                ),
                                slide_id=str(slide["slide_id"]),
                                region_id=str(left["region_id"]),
                            )
                        )
        failed = [item for item in checks if item["status"] == "fail"]
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(compiled.ir["project_id"]),
            "preflight_id": "",
            "generated_at": str(compiled.ir["generated_at"]),
            "status": (
                "blocked"
                if any(item["severity"] in {"critical", "major"} for item in failed)
                else "pass"
            ),
            "renderer_ir": {
                "ir_id": str(compiled.ir["ir_id"]),
                "path": compiled.path.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(compiled.path),
            },
            "backends": list(admitted_backends),
            "capabilities": sorted(capabilities, key=lambda item: item["capability"]),
            "fonts": [
                item.as_manifest_value()
                for item in sorted(resolutions, key=lambda value: value.requested)
            ],
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "kind": asset.kind,
                    "path": asset.path.relative_to(self.workspace).as_posix(),
                    "sha256": asset.content_hash,
                    "media_type": asset.media_type,
                    "editable_as": asset.editable_as,
                }
                for asset in sorted(assets.values(), key=lambda value: value.asset_id)
            ],
            "checks": sorted(
                checks,
                key=lambda item: (
                    {"critical": 0, "major": 1, "minor": 2, "info": 3}[item["severity"]],
                    str(item.get("backend") or ""),
                    str(item.get("slide_id") or ""),
                    str(item["code"]),
                ),
            ),
            "summary": {
                "critical_count": sum(item["severity"] == "critical" for item in failed),
                "major_count": sum(item["severity"] == "major" for item in failed),
                "minor_count": sum(item["severity"] == "minor" for item in failed),
                "failed_count": len(failed),
            },
        }
        report["preflight_id"] = render_preflight_id(report)
        errors = validate_render_preflight_data(report, self.schemas.schema_dir)
        if errors:
            raise RenderCompileError("Invalid Render Preflight report: " + "; ".join(errors))
        path = self.output_dir / f"{render_preflight_file_key(report)}.json"
        created = atomic_create_json(path, report)
        if not created and read_json(path) != report:
            raise RenderCompileError(
                f"Immutable Render Preflight path contains different content: {path}"
            )
        return RenderPreflightResult(
            report=copy.deepcopy(report),
            path=path,
            compiled=compiled,
            fonts=resolutions,
            assets=assets,
            changed=created,
        )
