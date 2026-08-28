from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import RenderManifestError, WorkspaceError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.render_ir import validate_renderer_ir_data
from slidethus.render_preflight import validate_render_preflight_data
from slidethus.schema_registry import SchemaRegistry

_PRODUCTION_BACKENDS = {"final-svg", "pptxgenjs-native", "pptxgenjs-hybrid"}
_PRODUCTION_ROLES = {
    "final_svg",
    "native_pptx",
    "hybrid_pptx",
    "export_pdf",
    "export_png",
    "backend_measurement",
}
_EDITABILITY_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}


def render_manifest_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("render_id", None)
    return payload


def production_render_id(data: dict[str, Any]) -> str:
    return "RND-" + sha256_json(render_manifest_identity_payload(data))[:16].upper()


def _schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "render_manifest.schema.json"
    if not path.is_file():
        raise RenderManifestError(f"Missing Render Manifest schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_render_manifest_data(
    data: dict[str, Any],
    schema_dir: Path | None = None,
) -> tuple[str, ...]:
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(admitted)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("pipeline_mode") != "production_multi_backend":
        return ()
    if data.get("render_id") != production_render_id(data):
        errors.append("Production Render Manifest identity mismatch")
    if data.get("backend") != "production-multi-backend":
        errors.append("Production Render Manifest backend must be production-multi-backend")
    if data.get("target_format") != "multi":
        errors.append("Production Render Manifest target_format must be multi")
    if data.get("status") != "success":
        errors.append("Production Render Manifest must represent a successful render")
    if data.get("preflight", {}).get("status") != "pass":
        errors.append("Production Render Manifest requires a passing preflight")

    backends = [str(item.get("backend", "")) for item in data.get("backend_runs", [])]
    if set(backends) != _PRODUCTION_BACKENDS or len(backends) != len(set(backends)):
        errors.append("Production Render Manifest must contain exactly the three Production backends")
    if backends != sorted(backends):
        errors.append("Production backend_runs must be sorted by backend")
    for run in data.get("backend_runs", []):
        backend = str(run.get("backend", ""))
        if run.get("status") != "success":
            errors.append(f"Production backend is not successful: {backend}")
        target = run.get("target_editability_level")
        actual = run.get("editability_level")
        if target in _EDITABILITY_ORDER and actual in _EDITABILITY_ORDER:
            if _EDITABILITY_ORDER[actual] < _EDITABILITY_ORDER[target]:
                errors.append(f"Production backend editability below target: {backend}")
    expected_levels = {
        "final-svg": {"E1"},
        "pptxgenjs-native": {"E2", "E3"},
        "pptxgenjs-hybrid": {"E2"},
    }
    for run in data.get("backend_runs", []):
        expected = expected_levels.get(str(run.get("backend")), set())
        if expected and run.get("editability_level") not in expected:
            errors.append(
                "Production backend editability is outside its independently measurable range: "
                f"{run.get('backend')}={run.get('editability_level')}"
            )
    if data.get("target_editability_level") != "E2" or data.get("editability_level") != "E2":
        errors.append("Production primary Hybrid output must declare target/actual E2")

    output_paths = [str(item.get("path", "")) for item in data.get("outputs", [])]
    if len(output_paths) != len(set(output_paths)):
        errors.append("Production Render Manifest contains duplicate output paths")
    roles = {str(item.get("role", "")) for item in data.get("outputs", [])}
    if not _PRODUCTION_ROLES.issubset(roles):
        errors.append(
            "Production Render Manifest is missing required roles: "
            + ", ".join(sorted(_PRODUCTION_ROLES - roles))
        )
    slide_count = max(
        (int(item.get("slide_count", 0)) for item in data.get("outputs", [])),
        default=0,
    )
    svg_count = sum(item.get("role") == "final_svg" for item in data.get("outputs", []))
    png_count = sum(item.get("role") == "export_png" for item in data.get("outputs", []))
    if slide_count < 1 or svg_count != slide_count or png_count != slide_count:
        errors.append("Production SVG/PNG page coverage disagrees with deck slide count")

    requested = [str(item.get("requested", "")) for item in data.get("font_substitutions", [])]
    if len(requested) != len(set(requested)):
        errors.append("Production Render Manifest contains duplicate font resolutions")
    capabilities = [str(item.get("capability", "")) for item in data.get("capabilities", [])]
    if len(capabilities) != len(set(capabilities)):
        errors.append("Production Render Manifest contains duplicate capabilities")
    if capabilities != sorted(capabilities):
        errors.append("Production Render Manifest capabilities must be sorted")
    return tuple(errors)


def _safe_runtime_path(
    workspace: Path,
    raw_path: str,
    admitted_root: str,
) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute():
        raise WorkspaceError(f"absolute runtime path is not allowed: {raw_path}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / admitted_root)
    if root != path and root not in path.parents:
        raise WorkspaceError(f"runtime path is outside {admitted_root}: {raw_path}")
    return path


def production_render_manifest_reference_errors(
    workspace: Path,
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate Production Render Manifest runtime refs and output hashes."""

    errors = list(validate_render_manifest_data(data, schema_dir))
    if data.get("pipeline_mode") != "production_multi_backend":
        return tuple(errors)
    ir_ref = data.get("renderer_ir", {})
    try:
        ir_path = _safe_runtime_path(
            workspace,
            str(ir_ref.get("path", "")),
            ".slidethus/render/ir",
        )
    except (OSError, ValueError, WorkspaceError) as exc:
        errors.append(f"Production Renderer IR path is unsafe: {exc}")
    else:
        if not ir_path.is_file():
            errors.append("Production Renderer IR is missing")
        elif sha256_file(ir_path) != ir_ref.get("sha256"):
            errors.append("Production Renderer IR hash mismatch")
        else:
            ir = read_json(ir_path)
            if ir.get("ir_id") != ir_ref.get("ir_id"):
                errors.append("Production Renderer IR identity mismatch")
            errors.extend(f"Renderer IR: {item}" for item in validate_renderer_ir_data(ir, schema_dir))

    preflight_ref = data.get("preflight", {})
    try:
        preflight_path = _safe_runtime_path(
            workspace,
            str(preflight_ref.get("path", "")),
            ".slidethus/render/preflight",
        )
    except (OSError, ValueError, WorkspaceError) as exc:
        errors.append(f"Production Render Preflight path is unsafe: {exc}")
    else:
        if not preflight_path.is_file():
            errors.append("Production Render Preflight is missing")
        elif sha256_file(preflight_path) != preflight_ref.get("sha256"):
            errors.append("Production Render Preflight hash mismatch")
        else:
            preflight = read_json(preflight_path)
            if preflight.get("preflight_id") != preflight_ref.get("preflight_id"):
                errors.append("Production Render Preflight identity mismatch")
            errors.extend(
                f"Render Preflight: {item}"
                for item in validate_render_preflight_data(preflight, schema_dir)
            )
            if preflight.get("renderer_ir", {}).get("ir_id") != ir_ref.get("ir_id"):
                errors.append("Production Preflight and Manifest bind different Renderer IRs")

    for output in data.get("outputs", []):
        raw_path = str(output.get("path", ""))
        try:
            path = _safe_runtime_path(workspace, raw_path, "outputs")
        except (OSError, ValueError, WorkspaceError) as exc:
            errors.append(f"Production render output path is unsafe: {raw_path}: {exc}")
            continue
        if not path.is_file():
            errors.append(f"Production render output is missing: {raw_path}")
        elif sha256_file(path) != output.get("sha256"):
            errors.append(f"Production render output hash mismatch: {raw_path}")
    return tuple(errors)
