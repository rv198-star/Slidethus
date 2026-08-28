from __future__ import annotations

import copy
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import ArtifactError, RenderManifestError
from slidethus.io_utils import read_json, sha256_file
from slidethus.protocols import RenderResult
from slidethus.render_backends.svg_export import SvgExportResult
from slidethus.render_manifest import (
    production_render_id,
    production_render_manifest_reference_errors,
    validate_render_manifest_data,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.render_preflight import RenderPreflightResult


@dataclass(frozen=True)
class RenderManifestPublishResult:
    manifest: dict[str, Any]
    changed: bool


def _mime_type(path: Path) -> str:
    if path.suffix.lower() == ".pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if path.suffix.lower() == ".svg":
        return "image/svg+xml"
    if path.suffix.lower() == ".png":
        return "image/png"
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    if path.suffix.lower() == ".json":
        return "application/json"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _artifact_inputs(runtime: ArtifactRuntime) -> list[dict[str, Any]]:
    admitted = {
        "project_brief",
        "asset_manifest",
        "deck_outline",
        "slide_specs",
        "layout_plans",
        "visual_system",
    }
    return [
        {
            "artifact_type": str(item["artifact_type"]),
            "path": str(item["path"]),
            "sha256": str(item["sha256"]),
            "version": int(item["version"]),
        }
        for item in sorted(
            runtime.list_artifacts(),
            key=lambda value: str(value.get("artifact_type", "")),
        )
        if item.get("artifact_type") in admitted
    ]


def _output(
    workspace: Path,
    path: Path,
    *,
    role: str,
    stage: str,
    backend: str | None,
    editability_level: str,
    slide_count: int,
    source_output: str | None = None,
) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise RenderManifestError(f"Render output is missing: {resolved}")
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise RenderManifestError(f"Render output is outside workspace: {resolved}") from exc
    return {
        "path": relative.as_posix(),
        "sha256": sha256_file(resolved),
        "mime_type": _mime_type(resolved),
        "slide_count": slide_count,
        "role": role,
        "stage": stage,
        "backend": backend,
        "editability_level": editability_level,
        "source_output": source_output,
    }


def _pptx_backend_run(
    backend: str,
    result: RenderResult,
    *,
    target: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(result.output_paths) != 2:
        raise RenderManifestError(
            f"{backend} must return one PPTX and one measurement report"
        )
    measurement = read_json(result.output_paths[1])
    counts = dict(measurement.get("object_counts", {}))
    counts.update(dict(measurement.get("structure_measurement", {})))
    run = {
        "backend": backend,
        "backend_version": "1.0.0",
        "target_format": "pptx",
        "target_editability_level": target,
        "editability_level": result.actual_editability_level,
        "status": result.status,
        "output_roles": [
            "native_pptx" if backend == "pptxgenjs-native" else "hybrid_pptx",
            "backend_measurement",
        ],
        "object_counts": {
            key: int(value)
            for key, value in counts.items()
            if key
            in {
                "text",
                "shape",
                "table",
                "chart",
                "image",
                "embedded_svg",
                "pictures",
                "native_shapes",
            }
        },
        "warnings": list(result.warnings),
    }
    return run, measurement


class ProductionRenderManifestService:
    """Publish one current multi-backend Production Render Manifest."""

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

    def publish(
        self,
        *,
        preflight: RenderPreflightResult,
        final_svg: RenderResult,
        native_pptx: RenderResult,
        hybrid_pptx: RenderResult,
        export: SvgExportResult,
        office_previews: tuple[Path, ...] = (),
        office_preview_detail: str = "Independent Office preview capability was unavailable.",
    ) -> RenderManifestPublishResult:
        slide_count = len(preflight.compiled.ir["slides"])
        if preflight.report.get("status") != "pass":
            raise RenderManifestError("Cannot publish a success Manifest from blocked preflight")
        if final_svg.status != "success" or len(final_svg.output_paths) != slide_count:
            raise RenderManifestError("Final SVG output does not cover every slide")
        native_run, native_measurement = _pptx_backend_run(
            "pptxgenjs-native",
            native_pptx,
            target=native_pptx.actual_editability_level,
        )
        hybrid_run, hybrid_measurement = _pptx_backend_run(
            "pptxgenjs-hybrid", hybrid_pptx, target="E2"
        )
        if final_svg.actual_editability_level != "E1":
            raise RenderManifestError("Final SVG editability must be measured as E1")
        if len(export.png_paths) != slide_count:
            raise RenderManifestError("PNG export does not cover every Final SVG page")

        outputs: list[dict[str, Any]] = []
        for path in final_svg.output_paths:
            outputs.append(
                _output(
                    self.workspace,
                    path,
                    role="final_svg",
                    stage="render",
                    backend="final-svg",
                    editability_level="E1",
                    slide_count=1,
                )
            )
        outputs.extend(
            [
                _output(
                    self.workspace,
                    native_pptx.output_paths[0],
                    role="native_pptx",
                    stage="render",
                    backend="pptxgenjs-native",
                    editability_level=native_pptx.actual_editability_level,
                    slide_count=slide_count,
                ),
                _output(
                    self.workspace,
                    native_pptx.output_paths[1],
                    role="backend_measurement",
                    stage="measure",
                    backend="pptxgenjs-native",
                    editability_level=native_pptx.actual_editability_level,
                    slide_count=slide_count,
                    source_output=native_pptx.output_paths[0]
                    .relative_to(self.workspace)
                    .as_posix(),
                ),
                _output(
                    self.workspace,
                    hybrid_pptx.output_paths[0],
                    role="hybrid_pptx",
                    stage="render",
                    backend="pptxgenjs-hybrid",
                    editability_level="E2",
                    slide_count=slide_count,
                ),
                _output(
                    self.workspace,
                    hybrid_pptx.output_paths[1],
                    role="backend_measurement",
                    stage="measure",
                    backend="pptxgenjs-hybrid",
                    editability_level="E2",
                    slide_count=slide_count,
                    source_output=hybrid_pptx.output_paths[0]
                    .relative_to(self.workspace)
                    .as_posix(),
                ),
            ]
        )
        svg_by_slide = {
            path.name.split("-", 2)[0] + "-" + path.name.split("-", 2)[1]: path
            for path in final_svg.output_paths
        }
        for path in export.png_paths:
            slide_id = path.name.split("-", 2)[0] + "-" + path.name.split("-", 2)[1]
            source = svg_by_slide.get(slide_id)
            outputs.append(
                _output(
                    self.workspace,
                    path,
                    role="export_png",
                    stage="export",
                    backend="final-svg",
                    editability_level="E0",
                    slide_count=1,
                    source_output=(
                        source.relative_to(self.workspace).as_posix() if source else None
                    ),
                )
            )
        outputs.extend(
            [
                _output(
                    self.workspace,
                    export.pdf_path,
                    role="export_pdf",
                    stage="export",
                    backend="final-svg",
                    editability_level="E0",
                    slide_count=slide_count,
                ),
                _output(
                    self.workspace,
                    export.report_path,
                    role="backend_measurement",
                    stage="measure",
                    backend="final-svg",
                    editability_level="E1",
                    slide_count=slide_count,
                ),
            ]
        )
        for path in office_previews:
            outputs.append(
                _output(
                    self.workspace,
                    path,
                    role="office_preview",
                    stage="review",
                    backend="pptxgenjs-hybrid",
                    editability_level="E0",
                    slide_count=1,
                    source_output=hybrid_pptx.output_paths[0]
                    .relative_to(self.workspace)
                    .as_posix(),
                )
            )
        outputs.sort(
            key=lambda item: (
                str(item.get("role", "")),
                str(item.get("backend") or ""),
                str(item["path"]),
            )
        )
        warnings = sorted(
            set(
                [
                    *preflight.compiled.ir.get("warnings", []),
                    *final_svg.warnings,
                    *native_pptx.warnings,
                    *hybrid_pptx.warnings,
                ]
                + ([] if office_previews else [office_preview_detail])
            )
        )
        capabilities = [copy.deepcopy(item) for item in preflight.report["capabilities"]]
        capabilities.append(
            {
                "capability": "pptx_office_preview",
                "status": "available" if office_previews else "missing",
                "detail": (
                    f"Independent Office preview produced {len(office_previews)} PNG page(s)."
                    if office_previews
                    else office_preview_detail
                ),
            }
        )
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(preflight.compiled.ir["project_id"]),
            "deck_id": str(preflight.compiled.ir["deck_id"]),
            "render_id": "",
            "generated_at": str(preflight.compiled.ir["generated_at"]),
            "backend": "production-multi-backend",
            "backend_version": "1.0.0",
            "pipeline_mode": "production_multi_backend",
            "target_format": "multi",
            "target_editability_level": "E2",
            "editability_level": "E2",
            "renderer_ir": {
                "ir_id": str(preflight.compiled.ir["ir_id"]),
                "path": preflight.compiled.path.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(preflight.compiled.path),
            },
            "preflight": {
                "preflight_id": str(preflight.report["preflight_id"]),
                "path": preflight.path.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(preflight.path),
                "status": str(preflight.report["status"]),
            },
            "input_artifacts": _artifact_inputs(self.runtime),
            "outputs": outputs,
            "backend_runs": sorted(
                [
                    {
                        "backend": "final-svg",
                        "backend_version": "1.1.0",
                        "target_format": "svg",
                        "target_editability_level": "E1",
                        "editability_level": final_svg.actual_editability_level,
                        "status": final_svg.status,
                        "output_roles": [
                            "final_svg",
                            "export_png",
                            "export_pdf",
                            "backend_measurement",
                        ],
                        "warnings": list(final_svg.warnings),
                    },
                    native_run,
                    hybrid_run,
                ],
                key=lambda item: item["backend"],
            ),
            "pipeline_stages": [
                {
                    "stage_id": "compile",
                    "action": "Compile current M3 and Visual System artifacts into immutable Renderer IR.",
                    "status": "success",
                    "output_roles": ["renderer_ir"],
                },
                {
                    "stage_id": "preflight",
                    "action": "Check backend capabilities, fonts, assets, bounds, collision and overflow.",
                    "status": "success",
                    "output_roles": ["render_preflight"],
                },
                {
                    "stage_id": "final_svg",
                    "action": "Render deterministic final SVG pages.",
                    "status": "success",
                    "output_roles": ["final_svg"],
                },
                {
                    "stage_id": "native_render",
                    "action": "Render and reopen native PptxGenJS PPTX.",
                    "status": native_pptx.status,
                    "output_roles": ["native_pptx", "backend_measurement"],
                },
                {
                    "stage_id": "hybrid_render",
                    "action": "Render and reopen Hybrid PptxGenJS PPTX.",
                    "status": hybrid_pptx.status,
                    "output_roles": ["hybrid_pptx", "backend_measurement"],
                },
                {
                    "stage_id": "svg_export",
                    "action": "Rasterize Final SVG pages independently and compile a PDF.",
                    "status": "success",
                    "output_roles": ["export_png", "export_pdf", "backend_measurement"],
                },
                {
                    "stage_id": "office_preview",
                    "action": "Render Hybrid PPTX through an independent Office-compatible path.",
                    "status": "success" if office_previews else "skipped",
                    "output_roles": ["office_preview"] if office_previews else [],
                },
                {
                    "stage_id": "measurement",
                    "action": "Measure real PPTX object structure and actual editability.",
                    "status": "success",
                    "output_roles": ["backend_measurement"],
                },
            ],
            "font_substitutions": [
                {
                    "requested": str(item["requested"]),
                    "actual": str(item["actual"]),
                    "reason": str(item["reason"]),
                    "status": str(item["status"]),
                }
                for item in preflight.report["fonts"]
            ],
            "asset_ids": list(preflight.compiled.ir.get("asset_ids", [])),
            "capabilities": sorted(capabilities, key=lambda item: item["capability"]),
            "preview_status": {
                "svg_export": "available",
                "pptx_office_preview": "available" if office_previews else "missing",
                "detail": (
                    "Final SVG was independently exported to PNG/PDF; Hybrid PPTX Office preview "
                    + ("completed." if office_previews else "was unavailable on this host.")
                ),
            },
            "warnings": warnings,
            "status": "success",
        }
        manifest["render_id"] = production_render_id(manifest)
        errors = validate_render_manifest_data(manifest, self.schemas.schema_dir)
        errors += production_render_manifest_reference_errors(
            self.workspace,
            manifest,
            self.schemas.schema_dir,
        )
        if errors:
            raise RenderManifestError(
                "Invalid Production Render Manifest: " + "; ".join(dict.fromkeys(errors))
            )
        try:
            current, version = self.runtime.read_artifact_snapshot("render_manifest")
        except ArtifactError:
            current = None
            version = 0
        if current == manifest:
            return RenderManifestPublishResult(
                manifest=copy.deepcopy(manifest),
                changed=False,
            )
        self.runtime.write_artifact(
            "render_manifest",
            manifest,
            expected_version=version,
            status="approved",
            created_by="production-render-manifest-service",
        )
        return RenderManifestPublishResult(
            manifest=copy.deepcopy(manifest),
            changed=True,
        )
