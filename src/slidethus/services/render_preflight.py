from __future__ import annotations

import copy
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
from slidethus.render_backends.artifact_tool_contract import (
    ARTIFACT_TOOL_TEXT_HORIZONTAL_PADDING,
    ARTIFACT_TOOL_TEXT_VERTICAL_PADDING,
    artifact_tool_admission_issues,
)
from slidethus.render_backends.artifact_tool_runtime import (
    resolve_artifact_tool_runtime,
)
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
from slidethus.text_capacity import (
    DEFAULT_HORIZONTAL_PADDING,
    DEFAULT_VERTICAL_PADDING,
)

_BACKENDS = {"final-svg", "pptxgenjs-native", "pptxgenjs-hybrid", "artifact-tool"}
_SUPPORTED_CONTENT = {
    "artifact-tool": {"text", "list", "metric", "quote", "spacer", "table", "chart", "image", "icon", "diagram"},
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


def _overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return not (
        float(left["x"]) + float(left["w"]) <= float(right["x"])
        or float(right["x"]) + float(right["w"]) <= float(left["x"])
        or float(left["y"]) + float(left["h"]) <= float(right["y"])
        or float(right["y"]) + float(right["h"]) <= float(left["y"])
    )


def _line_crosses_region(line: dict[str, Any], region: dict[str, Any]) -> bool:
    x1 = float(line["x"])
    y1 = float(line["y"])
    x2 = x1 + float(line["w"])
    y2 = y1 + float(line["h"])
    left = float(region["x"])
    right = left + float(region["w"])
    top = float(region["y"])
    bottom = top + float(region["h"])
    tolerance = 0.5
    if abs(y2 - y1) <= tolerance:
        return top + tolerance < y1 < bottom - tolerance and max(x1, left) < min(x2, right)
    if abs(x2 - x1) <= tolerance:
        return left + tolerance < x1 < right - tolerance and max(y1, top) < min(y2, bottom)
    return True


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
    asset_id: str | None = None,
    details: dict[str, float | int | str | None] | None = None,
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
    if asset_id is not None:
        item["asset_id"] = asset_id
    if details is not None:
        item["details"] = copy.deepcopy(details)
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
        artifact_tool_modules: Path | None = None,
        font_match: str | None = None,
        font_query: str | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.renderer_root = resolve_renderer_root(renderer_root)
        self.node = node
        self.artifact_tool_modules = artifact_tool_modules
        self.fonts = FontResolutionService(
            font_match=font_match,
            font_query=font_query,
        )
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
                    "detail": "Fontconfig family/file resolution and glyph coverage are available.",
                }
            )
        else:
            capabilities.append(
                {
                    "capability": "fontconfig",
                    "status": "missing",
                    "detail": "Fontconfig fc-match/fc-query coverage capability is unavailable.",
                }
            )
            checks.append(
                _check(
                    code="font_resolution_capability_missing",
                    status="fail",
                    severity="major",
                    message=(
                        "Production rendering requires font family/file resolution through fc-match "
                        "and glyph coverage through fc-query."
                    ),
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
        if "artifact-tool" in backends:
            try:
                runtime = resolve_artifact_tool_runtime(
                    node=self.node,
                    modules=self.artifact_tool_modules,
                )
            except RenderCapabilityError as exc:
                capabilities.append(
                    {
                        "capability": "artifact_tool",
                        "status": "missing",
                        "detail": str(exc),
                    }
                )
                checks.append(
                    _check(
                        code="artifact_tool_capability_missing",
                        status="fail",
                        severity="major",
                        backend="artifact-tool",
                        message=str(exc),
                    )
                )
            else:
                capabilities.append(
                    {
                        "capability": "artifact_tool",
                        "status": "available",
                        "detail": runtime.capability_detail(),
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
        if visual.get("page_designs"):
            for backend in admitted_backends:
                if backend != "artifact-tool":
                    checks.append(
                        _check(
                            code="explicit_page_design_backend_unsupported",
                            status="fail",
                            severity="major",
                            backend=backend,
                            message=(
                                "Explicit page appearance currently requires the Artifact Tool "
                                "adapter; no baseline fallback is admitted."
                            ),
                        )
                    )
        compiler = RenderCompileService(self.workspace)
        font_requirements = compiler.required_font_characters()
        resolutions: tuple[FontResolution, ...] = ()
        if self.fonts.available:
            try:
                resolutions = self.fonts.resolve_visual_system(
                    visual,
                    required_characters_by_family=font_requirements,
                )
            except (FontResolutionError, RenderCapabilityError) as exc:
                checks.append(
                    _check(
                        code="font_resolution_failed",
                        status="fail",
                        severity="major",
                        message=str(exc),
                    )
                )
        compiled = compiler.compile(
            font_resolutions=resolutions,
            collect_readiness_failures=True,
            # Artifact Tool explicitly emits zero text insets. Keep the generic
            # Office-conservative profile for every other or mixed backend run.
            text_horizontal_padding=(
                ARTIFACT_TOOL_TEXT_HORIZONTAL_PADDING
                if admitted_backends == ("artifact-tool",)
                else DEFAULT_HORIZONTAL_PADDING
            ),
            text_vertical_padding=(
                ARTIFACT_TOOL_TEXT_VERTICAL_PADDING
                if admitted_backends == ("artifact-tool",)
                else DEFAULT_VERTICAL_PADDING
            ),
        )
        assets: dict[str, ResolvedRenderAsset] = {}
        asset_service = RenderAssetService(self.workspace)
        for asset_id in sorted(str(item) for item in compiled.ir.get("asset_ids", [])):
            try:
                assets.update(asset_service.resolve((asset_id,)))
            except (RenderAssetError, RenderCapabilityError) as exc:
                checks.append(
                    _check(
                        code="render_asset_resolution_failed",
                        status="fail",
                        severity="major",
                        asset_id=asset_id,
                        message=f"{asset_id}: {exc}",
                    )
                )
        for binding in compiled.text_fits:
            fit = binding.result
            if fit.fits:
                continue
            checks.append(
                _check(
                    code="render_text_overflow",
                    status="fail",
                    severity="major",
                    message=(
                        f"Text requires {fit.required_height:.1f}px at the approved floor "
                        f"{fit.floor_font_pt:g}pt but region height is "
                        f"{fit.available_height:.1f}px; increase height by at least "
                        f"{fit.required_height_increase:.1f}px or return to P5A/P5B."
                    ),
                    slide_id=binding.slide_id,
                    block_id=binding.block_id,
                    region_id=binding.region_id,
                    details=fit.as_preflight_details(),
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
            for decoration in slide.get("decorations", []):
                if decoration.get("kind") != "line":
                    continue
                crossed = next(
                    (
                        region
                        for region in regions
                        if _line_crosses_region(decoration, region)
                    ),
                    None,
                )
                if crossed is not None:
                    checks.append(
                        _check(
                            code="render_decoration_collision",
                            status="fail",
                            severity="major",
                            message=(
                                f"Decoration {decoration['decoration_id']} crosses approved "
                                f"region {crossed['region_id']}; derive connectors from region anchors."
                            ),
                            slide_id=str(slide["slide_id"]),
                            block_id=str(crossed["block_id"]),
                            region_id=str(crossed["region_id"]),
                        )
                    )
        if "artifact-tool" in admitted_backends:
            for issue in artifact_tool_admission_issues(compiled.ir, assets):
                checks.append(
                    _check(
                        code=issue.code,
                        status="fail",
                        severity="major",
                        backend="artifact-tool",
                        message=issue.message,
                        slide_id=issue.slide_id,
                        block_id=issue.block_id,
                        region_id=issue.region_id,
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
