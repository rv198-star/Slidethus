from __future__ import annotations

from pathlib import Path
from typing import Any

from slidethus.art_direction import art_direction_packet_validator
from slidethus.io_utils import read_json, sha256_json
from slidethus.render_manifest import production_render_manifest_reference_errors
from slidethus.schema_registry import SchemaRegistry


def _art_direction_reasons(
    workspace: Path,
    state: dict[str, Any],
    visual_system: dict[str, Any],
) -> tuple[str, ...]:
    reference = visual_system.get("art_direction")
    if not isinstance(reference, dict):
        return ("visual system lacks a frozen Art Direction Packet reference",)
    raw_path = str(reference.get("path", ""))
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        return ("visual system contains an unsafe Art Direction Packet path",)
    root = workspace.resolve()
    packet_path = (root / relative).resolve()
    if packet_path != root and root not in packet_path.parents:
        return ("visual system Art Direction Packet path escapes the workspace",)
    if not packet_path.is_file():
        return ("visual system Art Direction Packet is missing",)
    try:
        packet = read_json(packet_path)
    except Exception as exc:  # noqa: BLE001
        return (f"visual system Art Direction Packet cannot be read: {exc}",)
    reasons: list[str] = []
    actual_hash = f"sha256:{sha256_json(packet)}"
    if actual_hash != reference.get("content_hash"):
        reasons.append("visual system Art Direction Packet content hash mismatch")
    if packet.get("packet_id") != reference.get("packet_id"):
        reasons.append("visual system Art Direction Packet identity mismatch")
    packet_provider = packet.get("provider", {})
    packet_provider_ref = {
        key: packet_provider.get(key)
        for key in ("name", "version", "mode")
    }
    if packet_provider_ref != reference.get("provider"):
        reasons.append("visual system Art Direction provider identity mismatch")
    schema_errors = sorted(
        art_direction_packet_validator().iter_errors(packet),
        key=lambda item: list(item.absolute_path),
    )
    if schema_errors:
        reasons.append("visual system Art Direction Packet is schema-invalid")
        return tuple(reasons)
    if visual_system.get("page_designs") != packet["direction"].get("page_designs"):
        reasons.append("visual system page appearance differs from admitted Art Direction Packet")
    expected_types = {
        "project_brief",
        "deck_outline",
        "slide_specs",
        "layout_plans",
        "asset_manifest",
    }
    packet_refs = {
        str(item.get("artifact_type")): item
        for item in packet.get("input_lineage", [])
        if isinstance(item, dict)
    }
    entries = {
        str(item.get("artifact_type")): item
        for item in state.get("artifacts", [])
    }
    if set(packet_refs) != expected_types:
        reasons.append("Art Direction Packet does not bind the complete P6 input set")
        return tuple(reasons)
    for artifact_type in sorted(expected_types):
        entry = entries.get(artifact_type)
        packet_ref = packet_refs[artifact_type]
        if entry is None:
            reasons.append(f"Art Direction Packet input is missing: {artifact_type}")
            continue
        if int(packet_ref.get("version", 0)) != int(entry.get("version", -1)):
            reasons.append(f"Art Direction Packet is stale for {artifact_type}")
        elif str(packet_ref.get("content_hash")) != str(entry.get("content_hash")):
            reasons.append(f"Art Direction Packet content hash is stale for {artifact_type}")
    return tuple(reasons)


def visual_system_gate_reasons(
    *,
    state: dict[str, Any],
    visual_system: dict[str, Any] | None,
    workspace: Path | None = None,
) -> tuple[str, ...]:
    """Return G6 reasons for a current Production visual-system artifact."""

    if visual_system is None:
        return ("visual system is missing",)
    lineage = visual_system.get("render_lineage")
    if not isinstance(lineage, dict):
        if visual_system.get("theme_id") in {
            "THEME-MVP1-EDITORIAL",
            "THEME-ENGINEERING-WIREFRAME",
        }:
            return ()
        return ("visual system lacks Production render lineage",)
    if lineage.get("engine") != "deterministic-visual-system":
        return ("visual system is not a Production M4 visual-system artifact",)
    required = {
        "project_brief",
        "deck_outline",
        "slide_specs",
        "layout_plans",
        "asset_manifest",
    }
    refs = {
        str(item.get("artifact_type")): item
        for item in lineage.get("inputs", [])
        if isinstance(item, dict)
    }
    if set(refs) != required:
        return ("visual system lineage does not bind the complete M4 input set",)
    entries = {
        str(item.get("artifact_type")): item
        for item in state.get("artifacts", [])
    }
    reasons: list[str] = []
    for artifact_type in sorted(required):
        entry = entries.get(artifact_type)
        ref = refs.get(artifact_type)
        if entry is None or ref is None:
            reasons.append(f"visual system lineage is missing {artifact_type}")
            continue
        if int(ref.get("version", 0)) != int(entry.get("version", -1)):
            reasons.append(f"visual system lineage is stale for {artifact_type}")
            continue
        if str(ref.get("content_hash")) != str(entry.get("content_hash")):
            reasons.append(f"visual system content hash is stale for {artifact_type}")
    if workspace is not None:
        reasons.extend(_art_direction_reasons(workspace, state, visual_system))
    return tuple(reasons)


def production_render_gate_reasons(
    workspace: Path,
    render_manifest: dict[str, Any],
) -> tuple[str, ...]:
    """Return G7 reasons for the current Production multi-backend render."""

    if render_manifest.get("pipeline_mode") != "production_multi_backend":
        return ()
    reasons = list(
        production_render_manifest_reference_errors(
            workspace.resolve(),
            render_manifest,
            SchemaRegistry().schema_dir,
        )
    )
    if render_manifest.get("preview_status", {}).get("svg_export") != "available":
        reasons.append("Production Final SVG did not produce independent PNG/PDF exports")
    runs = {
        str(item.get("backend")): item
        for item in render_manifest.get("backend_runs", [])
    }
    for backend in ("final-svg", "pptxgenjs-native", "pptxgenjs-hybrid"):
        if runs.get(backend, {}).get("status") != "success":
            reasons.append(f"Production renderer did not succeed: {backend}")
    required_roles = {
        "final_svg",
        "native_pptx",
        "hybrid_pptx",
        "export_png",
        "export_pdf",
        "backend_measurement",
    }
    roles = {str(item.get("role", "")) for item in render_manifest.get("outputs", [])}
    missing = sorted(required_roles - roles)
    if missing:
        reasons.append("Production render outputs are missing roles: " + ", ".join(missing))
    return tuple(dict.fromkeys(reasons))
