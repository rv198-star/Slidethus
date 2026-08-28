from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import RenderCompileError
from slidethus.io_utils import read_json, sha256_json
from slidethus.schema_registry import SchemaRegistry


def renderer_ir_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("ir_id", None)
    return payload


def renderer_ir_id(data: dict[str, Any]) -> str:
    return "RIR-" + sha256_json(renderer_ir_identity_payload(data))[:16].upper()


def renderer_ir_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def renderer_ir_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "renderer_ir.schema.json"
    if not path.is_file():
        raise RenderCompileError(f"Missing Renderer IR schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_renderer_ir_data(
    data: dict[str, Any],
    schema_dir: Path | None = None,
) -> tuple[str, ...]:
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(renderer_ir_schema(admitted_schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("ir_id") != renderer_ir_id(data):
        errors.append("Renderer IR identity mismatch")
    input_types = [str(item.get("artifact_type", "")) for item in data.get("input_artifacts", [])]
    if input_types != sorted(input_types):
        errors.append("Renderer IR input_artifacts must be sorted by artifact_type")
    if len(input_types) != len(set(input_types)):
        errors.append("Renderer IR contains duplicate input artifact types")
    required_types = {
        "project_brief",
        "asset_manifest",
        "deck_outline",
        "slide_specs",
        "layout_plans",
        "visual_system",
    }
    if set(input_types) != required_types:
        errors.append("Renderer IR does not bind the complete current render input set")
    substitutions = list(data.get("font_substitutions", []))
    requested_fonts = [str(item.get("requested", "")) for item in substitutions]
    if len(requested_fonts) != len(set(requested_fonts)):
        errors.append("Renderer IR contains duplicate font substitutions")
    if requested_fonts != sorted(requested_fonts):
        errors.append("Renderer IR font substitutions must be sorted by requested family")
    fonts = set(str(item) for item in data.get("fonts", []))
    if any(str(item.get("actual", "")) not in fonts for item in substitutions):
        errors.append("Renderer IR font substitution actual family is absent from fonts")
    slide_ids = [str(item.get("slide_id", "")) for item in data.get("slides", [])]
    if len(slide_ids) != len(set(slide_ids)):
        errors.append("Renderer IR contains duplicate slide IDs")
    if [int(item.get("ordinal", 0)) for item in data.get("slides", [])] != list(
        range(1, len(slide_ids) + 1)
    ):
        errors.append("Renderer IR slide ordinals must be contiguous from 1")
    region_ids: set[str] = set()
    block_ids: set[str] = set()
    for slide in data.get("slides", []):
        local_regions = [str(item.get("region_id", "")) for item in slide.get("regions", [])]
        local_blocks = [str(item.get("block_id", "")) for item in slide.get("regions", [])]
        if len(local_regions) != len(set(local_regions)):
            errors.append(f"Renderer IR slide {slide.get('slide_id')} contains duplicate region IDs")
        if len(local_blocks) != len(set(local_blocks)):
            errors.append(f"Renderer IR slide {slide.get('slide_id')} maps one block more than once")
        region_ids.update(local_regions)
        block_ids.update(local_blocks)
    if len(region_ids) != sum(len(item.get("regions", [])) for item in data.get("slides", [])):
        errors.append("Renderer IR region IDs are not globally unique")
    if len(block_ids) != sum(len(item.get("regions", [])) for item in data.get("slides", [])):
        errors.append("Renderer IR block IDs are not globally unique")
    return tuple(errors)


def _artifact_for_ref(
    workspace: Path,
    state: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    artifact_type = str(reference["artifact_type"])
    version = int(reference["version"])
    entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == artifact_type
        ),
        None,
    )
    if entry is None:
        raise RenderCompileError(f"Renderer IR references unregistered artifact: {artifact_type}")
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise RenderCompileError(
            f"Renderer IR references unknown {artifact_type} version {version}"
        )
    if not path.is_file():
        raise RenderCompileError(f"Renderer IR artifact version is missing: {path}")
    data = read_json(path)
    if f"sha256:{sha256_json(data)}" != reference.get("content_hash"):
        raise RenderCompileError(
            f"Renderer IR artifact hash mismatch: {artifact_type} v{version}"
        )
    return data


def renderer_ir_reference_errors(
    workspace: Path,
    ir_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted Renderer IR against historical artifact lineage."""

    errors: list[str] = []
    try:
        data = read_json(ir_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Renderer IR cannot be read: {exc}",)
    errors.extend(validate_renderer_ir_data(data, schema_dir))
    if ir_path.name != f"{renderer_ir_file_key(data)}.json":
        errors.append("Renderer IR filename does not match content hash")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if data.get("project_id") != state.get("project_id"):
        errors.append("Renderer IR project_id mismatch")

    historical: dict[str, dict[str, Any]] = {}
    for reference in data.get("input_artifacts", []):
        artifact_type = str(reference.get("artifact_type", ""))
        try:
            historical[artifact_type] = _artifact_for_ref(workspace, state, reference)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    outline = historical.get("deck_outline")
    specs = historical.get("slide_specs")
    layouts = historical.get("layout_plans")
    if outline is not None:
        expected_ids = [
            str(item["slide_id"])
            for item in outline.get("slides", [])
            if item.get("status") != "excluded"
        ]
        if [str(item.get("slide_id")) for item in data.get("slides", [])] != expected_ids:
            errors.append("Renderer IR slide order disagrees with bound Deck Outline")
    if specs is not None and layouts is not None:
        blocks = {
            str(block["block_id"])
            for slide in specs.get("slides", [])
            for block in slide.get("content_blocks", [])
        }
        layout_regions = {
            str(region["region_id"]): str(region["block_id"])
            for plan in layouts.get("plans", [])
            for region in plan.get("regions", [])
        }
        ir_regions = {
            str(region["region_id"]): str(region["block_id"])
            for slide in data.get("slides", [])
            for region in slide.get("regions", [])
        }
        if ir_regions != layout_regions:
            errors.append("Renderer IR region/block mapping disagrees with bound Layout Plans")
        if not set(ir_regions.values()).issubset(blocks):
            errors.append("Renderer IR references blocks absent from bound Slide Specs")
    return tuple(errors)


def renderer_ir_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for every persisted Renderer IR fact."""

    root = workspace / ".slidethus/render/ir"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Renderer IR directory"))
            continue
        for error in renderer_ir_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
