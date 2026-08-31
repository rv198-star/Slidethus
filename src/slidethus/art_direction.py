from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.art_direction_seed import (
    validate_seed_fulfillment,
    validate_seed_reference_for_graph,
)
from slidethus.constants import SCHEMA_VERSION
from slidethus.distribution import skill_source_root
from slidethus.errors import ArtifactError
from slidethus.io_utils import canonical_json_bytes, read_json, sha256_file, sha256_json
from slidethus.protocols import (
    ArtDirectionLimits,
    ArtDirectionProposal,
    ArtDirectionProvider,
    ArtDirectionSeedProposal,
)
from slidethus.schema_registry import SchemaRegistry

_TASTE_COMMIT = "ccbc15639c97057cbfcf32ecebc38ef716e4bb37"
_TASTE_SKILL_SHA256 = "aa194351b246b8b4799099d4ed7b033d29eab6e6e3d58d8d2172978be7b3ec89"
_TASTE_RELATIVE_PATH = "providers/art-direction/taste/SKILL.md"
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
_INPUT_TYPES = (
    "project_brief",
    "deck_outline",
    "slide_specs",
    "layout_plans",
    "asset_manifest",
)


@dataclass(frozen=True)
class CompiledArtDirection:
    """One admitted packet and its immutable workspace location."""

    packet: dict[str, Any]
    content_hash: str
    relative_path: Path


def art_direction_packet_validator(
    schema_registry: SchemaRegistry | None = None,
) -> Draft202012Validator:
    """Load the supporting runtime-fact schema without cataloging it as a mutable artifact."""

    registry = schema_registry or SchemaRegistry()
    schema_path = registry.schema_dir / "art_direction_packet.schema.json"
    if not schema_path.is_file():
        raise ArtifactError(f"Missing Art Direction Packet schema: {schema_path}")
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _brand_color(requirements: list[str]) -> str | None:
    for requirement in requirements:
        match = _HEX.search(requirement)
        if match:
            return match.group(0).upper()
    return None


def _generated_at(graph: dict[str, dict[str, Any]]) -> str:
    values = [
        str(graph[artifact_type].get("updated_at"))
        for artifact_type in _INPUT_TYPES
        if graph[artifact_type].get("updated_at")
    ]
    return max(values) if values else "1970-01-01T00:00:00Z"


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


class TasteSkillArtDirectionProvider:
    """Translate the bundled Taste Skill into a bounded static-deck direction."""

    name = "taste-skill"
    version = _TASTE_COMMIT
    mode = "bundled-skill-derived"

    def resource_identity(self) -> dict[str, Any]:
        """Return and verify the pinned upstream Skill identity."""

        root = skill_source_root()
        skill_path = root / _TASTE_RELATIVE_PATH
        provenance_path = skill_path.parent / "PROVENANCE.json"
        license_path = skill_path.parent / "LICENSE"
        missing = [
            path.relative_to(root).as_posix()
            for path in (skill_path, provenance_path, license_path)
            if not path.is_file()
        ]
        if missing:
            raise ArtifactError("Bundled Taste provider is incomplete: " + ", ".join(missing))
        provenance = read_json(provenance_path)
        actual_sha = sha256_file(skill_path)
        if actual_sha != _TASTE_SKILL_SHA256:
            raise ArtifactError(
                "Bundled Taste Skill hash drift: "
                f"expected {_TASTE_SKILL_SHA256}, got {actual_sha}"
            )
        if provenance.get("upstream_commit") != _TASTE_COMMIT:
            raise ArtifactError("Bundled Taste provenance commit does not match provider version")
        if provenance.get("files", {}).get("SKILL.md") != f"sha256:{actual_sha}":
            raise ArtifactError("Bundled Taste provenance does not match SKILL.md")
        return {
            "path": _TASTE_RELATIVE_PATH,
            "sha256": f"sha256:{actual_sha}",
            "upstream_url": "https://github.com/Leonxlnx/taste-skill",
            "upstream_commit": _TASTE_COMMIT,
            "license": "MIT",
        }

    def propose_seed(
        self,
        context: dict[str, Any],
        limits: ArtDirectionLimits,
    ) -> ArtDirectionSeedProposal:
        """Provide an explicit, bounded Taste-informed fallback before page planning.

        The bundled resource is a fixed instructional dependency, not a model-backed native
        prototype generator.  This proposal is therefore deliberately marked
        ``taste-informed`` and makes no claim of Taste-generated visual work.
        """

        self.resource_identity()
        brief = context["project_brief"]
        outline = context["deck_outline"]
        intent = brief.get("intent", {})
        mode = str(intent.get("presentation_mode", "both"))
        purpose = str(intent.get("purpose") or brief.get("title") or "decision support")
        active = [
            slide for slide in outline.get("slides", []) if slide.get("status") != "excluded"
        ]
        density = {"live": 4, "read": 7, "both": 6}.get(mode, 6)
        carriers = []
        for slide in active:
            slide_type = str(slide.get("slide_type", "statement"))
            kind = "typographic" if slide_type in {"cover", "section", "statement"} else "textual"
            treatment = "field" if slide_type in {"cover", "section"} else "tonal"
            carriers.append(
                {
                    "slide_id": str(slide["slide_id"]),
                    "kind": kind,
                    "requirement": "optional",
                    "surface_treatment": treatment,
                    "rationale": "A deterministic fallback records a visual option but does not invent media or data.",
                }
            )
        return ArtDirectionSeedProposal(
            design_read=(
                f"Taste-informed fallback for a {mode} presentation supporting {purpose}; "
                "requires explicit host reasoning before it may be called Taste-generated."
            )[: limits.max_design_read_chars],
            dials={
                "design_variance": 7 if len(active) >= 6 else 6,
                "motion_intensity": 2,
                "visual_density": density,
            },
            foundation={"kind": "taste-informed"},
            direction={
                "carriers": carriers,
                "image_direction": {
                    "style": "editorial, evidence-led, restrained, no decorative filler",
                    "fit": "cover",
                    "missing_asset": "replan",
                    "prompt_keywords": [
                        "editorial composition",
                        "clear focal hierarchy",
                        "presentation-safe negative space",
                    ],
                },
                "deck_rhythm": "alternate field, tonal and content-led surfaces by page role",
                "surface_rhythm": {"max_consecutive_plain": 0},
                "forbidden_patterns": [
                    "bento-as-default",
                    "same-layout-family-over-three-consecutive-slides",
                    "unmanifested-external-asset",
                    "global-font-shrink-to-hide-overflow",
                ],
            },
            warnings=(
                "This is Taste-informed deterministic guidance, not a Taste-generated native visual prototype.",
            ),
            assumptions=(
                "No host-authored visual foundation was supplied; media and chart carriers remain optional.",
            ),
        )

    def propose(
        self,
        context: dict[str, Any],
        limits: ArtDirectionLimits,
    ) -> ArtDirectionProposal:
        """Produce a deterministic Taste-derived proposal for a static deck."""

        self.resource_identity()
        brief = context["project_brief"]
        outline = context["deck_outline"]
        layouts = context["layout_plans"]
        language = str(brief.get("language", "en")).lower()
        intent = brief.get("intent", {})
        presentation_mode = str(intent.get("presentation_mode", "both"))
        audience_roles = [
            str(item.get("role"))
            for item in brief.get("audiences", [])
            if item.get("role")
        ]
        audience = ", ".join(audience_roles[:3]) or "the stated audience"
        purpose = str(intent.get("purpose") or brief.get("title") or "decision support")
        design_read = (
            f"Reading this as: a {presentation_mode} presentation for {audience}, "
            f"supporting {purpose}, with an evidence-led editorial language and restrained "
            "asymmetry rather than a template-first card grid."
        )
        design_read = design_read[: limits.max_design_read_chars]

        requirements = [
            str(item)
            for item in brief.get("constraints", {}).get("brand_requirements", [])
        ]
        primary = _brand_color(requirements) or "#154C5A"
        if language.startswith("zh"):
            preferred_font = "Noto Sans CJK SC"
            fallbacks = [
                "Microsoft YaHei",
                "PingFang SC",
                "Hiragino Sans GB",
                "Arial Unicode MS",
            ]
        else:
            preferred_font = "Aptos"
            fallbacks = ["Arial", "Helvetica", "Liberation Sans", "Noto Sans"]

        slide_count = len(
            [
                item
                for item in outline.get("slides", [])
                if item.get("status") != "excluded"
            ]
        )
        density = {"live": 4, "read": 7, "both": 6}.get(presentation_mode, 6)
        region_gap = max(20, float(layouts.get("safe_area", {}).get("left", 56)) / 2)
        assumptions: list[str] = []
        if _brand_color(requirements) is None:
            assumptions.append(
                "No explicit hexadecimal brand color was supplied; the default editorial palette is used."
            )
        return ArtDirectionProposal(
            design_read=design_read,
            dials={
                "design_variance": 7 if slide_count >= 6 else 6,
                "motion_intensity": 2,
                "visual_density": density,
            },
            direction={
                "theme_id": "THEME-PRODUCTION-EDITORIAL",
                "tone": ["editorial", "clear", "professional", "restrained", "evidence-led"],
                "palette": {
                    "background": "#F7F4ED",
                    "surface": "#FFFFFF",
                    "text_primary": "#17233C",
                    "text_secondary": "#667085",
                    "primary": primary,
                    "accent": "#D76745",
                    "surface_muted": "#E8EFEE",
                    "primary_soft": "#DDE9E8",
                    "accent_soft": "#F4DDD4",
                },
                "typography": {
                    "preferred_font": preferred_font,
                    "fallbacks": fallbacks,
                    "display_size": 42,
                    "title_size": 28,
                    "body_size": 20,
                    "caption_size": 12,
                },
                "composition": {
                    "corner_radius": 12,
                    "region_gap": region_gap,
                    "max_same_family_consecutive": 3,
                    "max_bento_ratio": 0.35,
                    "min_gap": 20,
                    "page_role_treatments": {
                        "cover": "primary-field",
                        "section": "primary-field",
                        "evidence": "spotlight-and-support",
                        "matrix": "framework-rail",
                        "process": "lead-and-steps",
                        "timeline": "staggered-progression",
                        "action": "decision-and-commitment",
                    },
                    "component_variants": [
                        "dark-spotlight",
                        "soft-evidence",
                        "numbered-step",
                        "framework-item",
                        "quiet-support",
                    ],
                    "deck_rhythm": "alternate-field-spotlight-framework-action",
                    "variation_rule": (
                        "Vary composition by semantic page role; keep palette, typography, "
                        "spacing and shape language locked across the deck."
                    ),
                },
                "image_direction": {
                    "style": "editorial, evidence-led, restrained, no decorative filler",
                    "fit": "cover",
                    "missing_asset": "fail",
                    "prompt_keywords": [
                        "editorial composition",
                        "clear focal hierarchy",
                        "restrained palette",
                        "presentation-safe negative space",
                    ],
                },
                "forbidden_patterns": [
                    "bento-as-default",
                    "same-layout-family-over-three-consecutive-slides",
                    "one-card-per-paragraph",
                    "decorative-micro-labels",
                    "random-accent-color",
                    "mixed-corner-radius-systems",
                    "body-text-below-planning-floor",
                    "unmanifested-external-asset",
                    "global-font-shrink-to-hide-overflow",
                ],
            },
            warnings=(
                "Taste is frontend-oriented; this adapter admits only static presentation principles.",
            ),
            assumptions=tuple(assumptions),
        )


def compile_art_direction(
    graph: dict[str, dict[str, Any]],
    *,
    provider: ArtDirectionProvider | None = None,
    limits: ArtDirectionLimits | None = None,
    schema_registry: SchemaRegistry | None = None,
    workspace: Path | None = None,
) -> CompiledArtDirection:
    """Admit one provider proposal into an immutable, schema-backed packet."""

    active_provider = provider or TasteSkillArtDirectionProvider()
    active_limits = limits or ArtDirectionLimits()
    missing = [artifact_type for artifact_type in _INPUT_TYPES if artifact_type not in graph]
    if missing:
        raise ArtifactError("Art Direction requires complete P6 inputs: " + ", ".join(missing))
    for field_name in ("name", "version", "mode"):
        value = str(getattr(active_provider, field_name, "")).strip()
        if not value or len(value) > 128:
            raise ArtifactError(f"Art Direction provider must declare bounded {field_name}")

    context = {
        artifact_type: graph[artifact_type]["data"]
        for artifact_type in _INPUT_TYPES
    }
    pre_layout_seed = context["slide_specs"].get("art_direction_seed")
    seed = None
    if pre_layout_seed is not None:
        if workspace is None:
            raise ArtifactError("Art Direction Seed requires a workspace for validation")
        seed = validate_seed_reference_for_graph(
            workspace,
            pre_layout_seed,
            graph,
            schema_registry=schema_registry,
        )
        context["art_direction_seed"] = seed
    proposal = active_provider.propose(context, active_limits)
    proposal_payload = {
        "design_read": proposal.design_read,
        "dials": proposal.dials,
        "direction": proposal.direction,
        "warnings": list(proposal.warnings),
        "assumptions": list(proposal.assumptions),
    }
    if len(canonical_json_bytes(proposal_payload)) > active_limits.max_provider_payload_bytes:
        raise ArtifactError("Art Direction provider payload exceeds the admission limit")
    if len(proposal.design_read) > active_limits.max_design_read_chars:
        raise ArtifactError("Art Direction design read exceeds the admission limit")

    provider_identity: dict[str, Any] = {
        "name": str(active_provider.name),
        "version": str(active_provider.version),
        "mode": str(active_provider.mode),
    }
    resource = active_provider.resource_identity()
    if resource is not None:
        provider_identity["resource"] = resource
    packet_without_id: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": str(context["project_brief"]["project_id"]),
        "deck_id": str(context["deck_outline"]["deck_id"]),
        "status": "frozen",
        "provider": provider_identity,
        **proposal_payload,
        **({"pre_layout_seed": pre_layout_seed} if pre_layout_seed is not None else {}),
        "input_lineage": [
            _artifact_ref(graph[artifact_type], artifact_type)
            for artifact_type in _INPUT_TYPES
        ],
        "generated_at": _generated_at(graph),
    }
    packet = {
        "packet_id": "ADP-" + sha256_json(packet_without_id)[:16].upper(),
        **packet_without_id,
    }
    errors = sorted(
        art_direction_packet_validator(schema_registry).iter_errors(packet),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        details = "; ".join(f"{error.json_path}: {error.message}" for error in errors)
        raise ArtifactError("Invalid Art Direction Packet: " + details)
    lineage_types = [item["artifact_type"] for item in packet["input_lineage"]]
    if tuple(lineage_types) != _INPUT_TYPES:
        raise ArtifactError("Art Direction Packet input lineage order is invalid")
    if seed is not None:
        page_designs = packet["direction"].get("page_designs")
        validate_seed_fulfillment(
            seed,
            context["slide_specs"],
            page_designs,
            base_background=packet["direction"]["palette"]["background"],
        )
    digest = sha256_json(packet)
    return CompiledArtDirection(
        packet=packet,
        content_hash=f"sha256:{digest}",
        relative_path=Path(".slidethus/art-direction/packets") / f"{digest}.json",
    )
