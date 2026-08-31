"""Immutable pre-layout art-direction facts and native-prototype provenance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import ArtifactError
from slidethus.io_utils import atomic_create_json, read_json, sha256_file, sha256_json
from slidethus.protocols import ArtDirectionLimits, ArtDirectionProvider
from slidethus.schema_registry import SchemaRegistry

_INPUT_TYPES = ("project_brief", "deck_outline")


@dataclass(frozen=True)
class CompiledArtDirectionSeed:
    """A frozen Seed and its immutable workspace location."""

    seed: dict[str, Any]
    content_hash: str
    relative_path: Path

    @property
    def reference(self) -> dict[str, Any]:
        """Return the bounded reference that may be carried by planning artifacts."""

        return {
            "seed_id": self.seed["seed_id"],
            "path": self.relative_path.as_posix(),
            "content_hash": self.content_hash,
            "provider": {
                key: self.seed["provider"][key]
                for key in ("name", "version", "mode")
            },
        }


def art_direction_seed_validator(
    schema_registry: SchemaRegistry | None = None,
) -> Draft202012Validator:
    """Load the Seed runtime-fact schema without making it a mutable artifact."""

    registry = schema_registry or SchemaRegistry()
    schema_path = registry.schema_dir / "art_direction_seed.schema.json"
    if not schema_path.is_file():
        raise ArtifactError(f"Missing Art Direction Seed schema: {schema_path}")
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


def _generated_at(graph: dict[str, dict[str, Any]]) -> str:
    values = [
        str(graph[artifact_type].get("updated_at"))
        for artifact_type in _INPUT_TYPES
        if graph[artifact_type].get("updated_at")
    ]
    return max(values) if values else "1970-01-01T00:00:00Z"


def _provider_identity(provider: ArtDirectionProvider) -> dict[str, Any]:
    identity = {
        field: str(getattr(provider, field, "")).strip()
        for field in ("name", "version", "mode")
    }
    if any(not value or len(value) > 128 for value in identity.values()):
        raise ArtifactError("Art Direction provider must declare bounded name, version and mode")
    resource = provider.resource_identity()
    if resource is not None:
        identity["resource"] = resource
    return identity


def _schema_error(prefix: str, payload: dict[str, Any], validator: Draft202012Validator) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if errors:
        details = "; ".join(f"{error.json_path}: {error.message}" for error in errors)
        raise ArtifactError(f"{prefix}: {details}")


def _prototype_path(workspace: Path, prototype: dict[str, Any]) -> Path:
    raw_path = Path(str(prototype.get("path", "")))
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ArtifactError("Art Direction Seed prototype path must be workspace-relative")
    root = workspace.resolve()
    candidate = (root / raw_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ArtifactError("Art Direction Seed prototype path escapes the workspace")
    return candidate


def _verify_native_prototype(workspace: Path, seed: dict[str, Any]) -> None:
    foundation = seed["foundation"]
    if foundation["kind"] != "taste-generated":
        return
    prototype = foundation.get("prototype")
    if not isinstance(prototype, dict):
        raise ArtifactError("Taste-generated Art Direction Seed requires native prototype provenance")
    path = _prototype_path(workspace, prototype)
    if not path.is_file():
        raise ArtifactError("Taste-generated Art Direction Seed prototype is missing")
    actual_hash = f"sha256:{sha256_file(path)}"
    if actual_hash != prototype.get("content_hash"):
        raise ArtifactError("Taste-generated Art Direction Seed prototype hash mismatch")


def validate_seed_carriers(seed: dict[str, Any], outline: dict[str, Any]) -> None:
    """Validate that one pre-layout carrier decision covers each active slide once."""

    active_ids = [
        str(slide["slide_id"])
        for slide in outline.get("slides", [])
        if slide.get("status") != "excluded"
    ]
    carriers = list(seed.get("direction", {}).get("carriers", []))
    carrier_ids = [str(item.get("slide_id", "")) for item in carriers]
    if carrier_ids != active_ids or len(carrier_ids) != len(set(carrier_ids)):
        raise ArtifactError(
            "Art Direction Seed carriers must cover active Deck Outline slides in order"
        )
    rhythm = seed.get("direction", {}).get("surface_rhythm", {})
    max_plain = int(rhythm.get("max_consecutive_plain", 0))
    run = 0
    for carrier in carriers:
        if carrier.get("surface_treatment") == "plain":
            run += 1
            if run > max_plain:
                raise ArtifactError(
                    "Art Direction Seed exceeds its declared max_consecutive_plain surface rhythm"
                )
        else:
            run = 0


def validate_seed_fulfillment(
    seed: dict[str, Any],
    slide_specs: dict[str, Any],
    page_designs: list[dict[str, Any]] | None,
    *,
    base_background: str | None = None,
) -> None:
    """Ensure declared required carriers and surface rhythm reach formal page artifacts."""

    specs_by_id = {str(item["slide_id"]): item for item in slide_specs.get("slides", [])}
    pages_by_id = {
        str(item["slide_id"]): item for item in (page_designs or [])
    }
    expected_types = {
        "image": {"image"},
        "chart": {"chart"},
        "diagram": {"diagram"},
        "table": {"table"},
        "typographic": {"text", "quote", "metric"},
        "textual": {"text", "list", "quote", "metric"},
    }
    for carrier in seed["direction"]["carriers"]:
        slide_id = str(carrier["slide_id"])
        spec = specs_by_id.get(slide_id)
        if spec is None:
            raise ArtifactError(f"Art Direction Seed references missing Slide Spec {slide_id}")
        kind = str(carrier["kind"])
        block_types = {
            str(block.get("content_type", ""))
            for block in spec.get("content_blocks", [])
        }
        if carrier["requirement"] == "required" and not (
            block_types & expected_types[kind]
        ):
            raise ArtifactError(
                f"Art Direction Seed requires a {kind} carrier on {slide_id}, "
                "but Slide Specs do not own a matching Block"
            )
        if page_designs is not None:
            page = pages_by_id.get(slide_id)
            if page is None:
                raise ArtifactError(
                    f"Art Direction Seed page {slide_id} has no final page design"
                )
            if page.get("surface_treatment") != carrier["surface_treatment"]:
                raise ArtifactError(
                    f"Art Direction Seed surface treatment was not propagated for {slide_id}"
                )
            styled_regions = [
                item.get("style", {})
                for item in page.get("regions", [])
                if isinstance(item, dict)
            ]
            has_field = any(
                item.get("fill") is not None or item.get("border_color") is not None
                for item in styled_regions
            ) or any(
                item.get("fill") is not None or item.get("stroke") is not None
                for item in page.get("decorations", [])
                if isinstance(item, dict)
            )
            if carrier["surface_treatment"] == "field":
                if not has_field:
                    raise ArtifactError(
                        f"Field surface on {slide_id} has no rendered field treatment"
                    )
            if (
                carrier["surface_treatment"] == "tonal"
                and base_background is not None
                and page.get("background") == base_background
                and not has_field
            ):
                raise ArtifactError(
                    f"Tonal surface on {slide_id} collapses to the deck's plain background"
                )
            if carrier["surface_treatment"] == "image-led" and not (
                block_types & {"image"}
            ):
                raise ArtifactError(
                    f"Image-led surface on {slide_id} requires an image Block in Slide Specs"
                )


def compile_art_direction_seed(
    workspace: Path,
    graph: dict[str, dict[str, Any]],
    *,
    provider: ArtDirectionProvider,
    limits: ArtDirectionLimits | None = None,
    schema_registry: SchemaRegistry | None = None,
) -> CompiledArtDirectionSeed:
    """Admit a bounded provider proposal as a content-addressed pre-layout Seed."""

    missing = [artifact_type for artifact_type in _INPUT_TYPES if artifact_type not in graph]
    if missing:
        raise ArtifactError("Art Direction Seed requires: " + ", ".join(missing))
    active_limits = limits or ArtDirectionLimits()
    context = {artifact_type: graph[artifact_type]["data"] for artifact_type in _INPUT_TYPES}
    try:
        proposal = provider.propose_seed(context, active_limits)
    except AttributeError as exc:
        raise ArtifactError("Art Direction provider does not support a pre-layout Seed") from exc
    proposal_payload = {
        "design_read": proposal.design_read,
        "dials": proposal.dials,
        "foundation": proposal.foundation,
        "direction": proposal.direction,
        "warnings": list(proposal.warnings),
        "assumptions": list(proposal.assumptions),
    }
    from slidethus.io_utils import canonical_json_bytes

    if len(canonical_json_bytes(proposal_payload)) > active_limits.max_provider_payload_bytes:
        raise ArtifactError("Art Direction Seed provider payload exceeds the admission limit")
    if len(proposal.design_read) > active_limits.max_design_read_chars:
        raise ArtifactError("Art Direction Seed design read exceeds the admission limit")
    seed_without_id: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": str(context["project_brief"]["project_id"]),
        "deck_id": str(context["deck_outline"]["deck_id"]),
        "status": "frozen",
        "provider": _provider_identity(provider),
        **proposal_payload,
        "input_lineage": [
            _artifact_ref(graph[artifact_type], artifact_type)
            for artifact_type in _INPUT_TYPES
        ],
        "generated_at": _generated_at(graph),
    }
    seed = {
        "seed_id": "ADS-" + sha256_json(seed_without_id)[:16].upper(),
        **seed_without_id,
    }
    _schema_error("Invalid Art Direction Seed", seed, art_direction_seed_validator(schema_registry))
    validate_seed_carriers(seed, context["deck_outline"])
    _verify_native_prototype(workspace, seed)
    digest = sha256_json(seed)
    relative_path = Path(".slidethus/art-direction/seeds") / f"{digest}.json"
    absolute_path = workspace.resolve() / relative_path
    created = atomic_create_json(absolute_path, seed)
    if not created and read_json(absolute_path) != seed:
        raise ArtifactError("Immutable Art Direction Seed path contains different content")
    return CompiledArtDirectionSeed(
        seed=seed,
        content_hash=f"sha256:{digest}",
        relative_path=relative_path,
    )


def load_art_direction_seed(
    workspace: Path,
    reference: dict[str, Any],
    *,
    schema_registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    """Load and verify one workspace-local immutable Seed reference."""

    required = {"seed_id", "path", "content_hash", "provider"}
    if set(reference) != required:
        raise ArtifactError("Art Direction Seed reference has unexpected fields")
    raw_path = Path(str(reference["path"]))
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ArtifactError("Art Direction Seed reference path must be workspace-relative")
    root = workspace.resolve()
    path = (root / raw_path).resolve()
    if path != root and root not in path.parents:
        raise ArtifactError("Art Direction Seed reference path escapes the workspace")
    if not path.is_file():
        raise ArtifactError("Art Direction Seed is missing")
    seed = read_json(path)
    _schema_error("Invalid Art Direction Seed", seed, art_direction_seed_validator(schema_registry))
    if f"sha256:{sha256_json(seed)}" != reference["content_hash"]:
        raise ArtifactError("Art Direction Seed content hash mismatch")
    if seed.get("seed_id") != reference["seed_id"]:
        raise ArtifactError("Art Direction Seed identity mismatch")
    provider = {key: seed.get("provider", {}).get(key) for key in ("name", "version", "mode")}
    if provider != reference["provider"]:
        raise ArtifactError("Art Direction Seed provider identity mismatch")
    _verify_native_prototype(root, seed)
    return seed


def validate_seed_reference_for_graph(
    workspace: Path,
    reference: dict[str, Any],
    graph: dict[str, dict[str, Any]],
    *,
    schema_registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    """Load a Seed and ensure it still binds the current Brief and Outline."""

    seed = load_art_direction_seed(workspace, reference, schema_registry=schema_registry)
    refs = {item["artifact_type"]: item for item in seed["input_lineage"]}
    for artifact_type in _INPUT_TYPES:
        snapshot = graph.get(artifact_type)
        if snapshot is None:
            raise ArtifactError(f"Art Direction Seed graph input is missing: {artifact_type}")
        ref = refs.get(artifact_type, {})
        if int(ref.get("version", 0)) != int(snapshot["version"]) or ref.get(
            "content_hash"
        ) != snapshot["content_hash"]:
            raise ArtifactError(f"Art Direction Seed is stale for {artifact_type}")
    validate_seed_carriers(seed, graph["deck_outline"]["data"])
    return seed
