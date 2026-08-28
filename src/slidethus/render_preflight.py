from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import RenderManifestError, WorkspaceError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.render_ir import validate_renderer_ir_data
from slidethus.schema_registry import SchemaRegistry


def render_preflight_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("preflight_id", None)
    return payload


def render_preflight_id(data: dict[str, Any]) -> str:
    return "RPF-" + sha256_json(render_preflight_identity_payload(data))[:16].upper()


def render_preflight_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def render_check_id(check: dict[str, Any]) -> str:
    payload = {
        "code": check.get("code"),
        "backend": check.get("backend"),
        "slide_id": check.get("slide_id"),
        "block_id": check.get("block_id"),
        "region_id": check.get("region_id"),
    }
    return "RPC-" + sha256_json(payload)[:16].upper()


def _schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "render_preflight_report.schema.json"
    if not path.is_file():
        raise RenderManifestError(f"Missing Render Preflight schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_render_preflight_data(
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
    if data.get("preflight_id") != render_preflight_id(data):
        errors.append("Render Preflight identity mismatch")
    if data.get("backends") != sorted(data.get("backends", [])):
        errors.append("Render Preflight backends must be sorted")
    capabilities = [str(item.get("capability", "")) for item in data.get("capabilities", [])]
    if len(capabilities) != len(set(capabilities)):
        errors.append("Render Preflight contains duplicate capabilities")
    if capabilities != sorted(capabilities):
        errors.append("Render Preflight capabilities must be sorted")
    check_ids = [str(item.get("check_id", "")) for item in data.get("checks", [])]
    if len(check_ids) != len(set(check_ids)):
        errors.append("Render Preflight contains duplicate check IDs")
    for check in data.get("checks", []):
        if check.get("check_id") != render_check_id(check):
            errors.append(f"Render Preflight check identity mismatch: {check.get('check_id')}")
    failed = [item for item in data.get("checks", []) if item.get("status") == "fail"]
    summary = data.get("summary", {})
    expected = {
        "critical_count": sum(item.get("severity") == "critical" for item in failed),
        "major_count": sum(item.get("severity") == "major" for item in failed),
        "minor_count": sum(item.get("severity") == "minor" for item in failed),
        "failed_count": len(failed),
    }
    for key, value in expected.items():
        if int(summary.get(key, -1)) != value:
            errors.append(f"Render Preflight {key} mismatch")
    blocking = any(item.get("severity") in {"critical", "major"} for item in failed)
    expected_status = "blocked" if blocking else "pass"
    if data.get("status") != expected_status:
        errors.append("Render Preflight status disagrees with failed checks")
    return tuple(errors)


def render_preflight_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Render Preflight cannot be read: {exc}",)
    errors.extend(validate_render_preflight_data(report, schema_dir))
    if report_path.name != f"{render_preflight_file_key(report)}.json":
        errors.append("Render Preflight filename mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if report.get("project_id") != state.get("project_id"):
        errors.append("Render Preflight project_id mismatch")
    raw_path = str(report.get("renderer_ir", {}).get("path", ""))
    try:
        relative = Path(raw_path)
        if relative.is_absolute():
            raise WorkspaceError("absolute Renderer IR path is not allowed")
        ir_path = ensure_within(workspace, workspace / relative)
        ir_root = ensure_within(workspace, workspace / ".slidethus/render/ir")
        if ir_path.parent != ir_root:
            raise WorkspaceError("Renderer IR must be directly under .slidethus/render/ir")
    except (OSError, ValueError, WorkspaceError) as exc:
        errors.append(f"Render Preflight Renderer IR path is unsafe: {exc}")
        return tuple(errors)
    if not ir_path.is_file():
        errors.append("Render Preflight Renderer IR is missing")
        return tuple(errors)
    if sha256_file(ir_path) != report.get("renderer_ir", {}).get("sha256"):
        errors.append("Render Preflight Renderer IR hash mismatch")
    ir = read_json(ir_path)
    if ir.get("ir_id") != report.get("renderer_ir", {}).get("ir_id"):
        errors.append("Render Preflight Renderer IR identity mismatch")
    errors.extend(f"Renderer IR: {item}" for item in validate_renderer_ir_data(ir, schema_dir))
    return tuple(errors)


def render_preflight_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/render/preflight"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Render Preflight directory"))
            continue
        for error in render_preflight_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
