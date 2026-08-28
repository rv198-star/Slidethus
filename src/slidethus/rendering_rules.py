from __future__ import annotations

from pathlib import Path
from typing import Any

from slidethus.render_manifest import production_render_manifest_reference_errors
from slidethus.schema_registry import SchemaRegistry


def visual_system_gate_reasons(
    *,
    state: dict[str, Any],
    visual_system: dict[str, Any] | None,
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
