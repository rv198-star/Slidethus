"""File bridge for reasoning performed by the host, never a model impersonator."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.art_direction import TasteSkillArtDirectionProvider
from slidethus.art_direction_seed import (
    compile_art_direction_seed,
    load_art_direction_seed,
)
from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import PlanningError
from slidethus.io_utils import atomic_create_json, canonical_json_bytes, read_json, sha256_json
from slidethus.protocols import (
    ArtDirectionLimits,
    ArtDirectionProposal,
    ArtDirectionSeedProposal,
    PlanningLimits,
    PlanningProposal,
    PreLayoutArtDirection,
)
from slidethus.schema_registry import SchemaRegistry


class HostDesignRequired(PlanningError):
    """A current stage awaits an explicit host response, not a fallback."""


class HostDesignBridge:
    """Persist content-bound stage requests and read bounded host proposals."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".slidethus/host-design"
        self.pending: dict[str, Any] | None = None

    def exchange(self, stage: str, context: dict[str, Any], limits: Any) -> dict[str, Any]:
        request = {
            "schema_version": "0.1.0",
            "stage": stage,
            "context": copy.deepcopy(context),
            "limits": asdict(limits),
        }
        digest = sha256_json(request)
        request_path = self.root / "requests" / f"{digest}.json"
        response_path = self.root / "responses" / f"{digest}.json"
        atomic_create_json(request_path, request)
        if read_json(request_path) != request:
            raise PlanningError("Host request content hash mismatch")
        self.pending = {
            "stage": stage,
            "request_hash": f"sha256:{digest}",
            "request_path": str(request_path),
            "response_path": str(response_path),
        }
        if not response_path.is_file():
            raise HostDesignRequired(
                f"Host design required for {stage}: read {request_path}; "
                f"submit a response bound to sha256:{digest} at {response_path}. "
                "No deterministic design fallback was used."
            )
        if response_path.stat().st_size > limits.max_provider_payload_bytes:
            raise PlanningError("Host response exceeds stage payload limit")
        try:
            response = read_json(response_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PlanningError(f"Cannot read host response: {exc}") from exc
        try:
            json.dumps(response, allow_nan=False)
        except ValueError as exc:
            raise PlanningError("Host response contains non-finite numbers") from exc
        schema = read_json(SchemaRegistry().schema_dir / "host_design_response.schema.json")
        errors = list(Draft202012Validator(schema).iter_errors(response))
        if errors:
            raise PlanningError("Invalid host response: " + errors[0].message)
        if response["request_hash"] != f"sha256:{digest}" or response["stage"] != stage:
            raise PlanningError("Host response is stale or belongs to a different stage")
        if len(canonical_json_bytes(response)) > limits.max_provider_payload_bytes:
            raise PlanningError("Host response exceeds stage payload limit")
        proposal = copy.deepcopy(response["proposal"])
        # Submission history is inspectable; stage admission has not happened yet.
        atomic_create_json(self.root / "received" / f"{sha256_json(response)}.json", response)
        self.pending = None
        return proposal


def _messages(raw: dict[str, Any], field: str) -> tuple[str, ...]:
    values = raw.get(field, [])
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise PlanningError(f"Host proposal {field} must be a list of strings")
    return tuple(values)


class HostPlanningProvider:
    """Use current host-authored proposals through the existing planning services."""

    name = "host-authored-planning"
    version = "1.0.0"

    def __init__(
        self,
        bridge: HostDesignBridge,
        *,
        art_direction_provider: HostArtDirectionProvider | None = None,
    ) -> None:
        self.bridge = bridge
        self.art_direction_provider = art_direction_provider

    def prepare_art_direction_seed(
        self,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> PreLayoutArtDirection | None:
        """Freeze host-authored visual direction before Slide Specs choose their carriers."""

        if self.art_direction_provider is None:
            return None
        graph = ArtifactRuntime(self.bridge.workspace).read_artifact_graph_snapshot(
            ("project_brief", "deck_outline")
        )
        compiled = compile_art_direction_seed(
            self.bridge.workspace,
            graph,
            provider=self.art_direction_provider,
            limits=ArtDirectionLimits(
                max_provider_payload_bytes=min(
                    ArtDirectionLimits().max_provider_payload_bytes,
                    limits.max_provider_payload_bytes,
                )
            ),
        )
        return PreLayoutArtDirection(reference=compiled.reference, seed=compiled.seed)

    def propose(
        self, artifact_type: str, context: dict[str, Any], limits: PlanningLimits
    ) -> PlanningProposal:
        request_context = copy.deepcopy(context)
        seed_reference = None
        if artifact_type == "slide_specs" and self.art_direction_provider is not None:
            prepared = self.prepare_art_direction_seed(request_context, limits)
            if prepared is None:
                raise PlanningError("Host planning has no Art Direction Seed provider")
            if request_context.get("art_direction_seed") != prepared.seed:
                raise PlanningError(
                    "Slide Specs request is missing the current frozen Art Direction Seed"
                )
            seed_reference = prepared.reference
        raw = self.bridge.exchange(artifact_type, request_context, limits)
        if set(raw) - {"content", "warnings", "assumptions"} or "content" not in raw:
            raise PlanningError("Planning response requires content, warnings and assumptions only")
        if not isinstance(raw["content"], dict):
            raise PlanningError("Host planning content must be an object")
        if artifact_type == "layout_plans":
            plans = raw["content"].get("plans", [])
            if not isinstance(plans, list) or not plans or any(
                not isinstance(plan, dict) or "regions" not in plan for plan in plans
            ):
                raise PlanningError("Host Layout proposals require explicit regions for every slide")
        return PlanningProposal(
            artifact_type=artifact_type,
            content=raw["content"],
            warnings=_messages(raw, "warnings"),
            assumptions=_messages(raw, "assumptions"),
            art_direction_seed=seed_reference,
        )


class HostArtDirectionProvider:
    """Admit host art direction; a pinned resource is not proof of a native prototype."""

    name = "host-authored-art-direction"
    version = "1.0.0"
    mode = "host-authored"

    def __init__(
        self,
        bridge: HostDesignBridge,
        *,
        require_taste_generated: bool = False,
    ) -> None:
        self.bridge = bridge
        self.require_taste_generated = require_taste_generated

    def resource_identity(self) -> dict[str, Any]:
        return TasteSkillArtDirectionProvider().resource_identity()

    def propose_seed(
        self,
        context: dict[str, Any],
        limits: ArtDirectionLimits,
    ) -> ArtDirectionSeedProposal:
        """Request a real pre-layout design direction from the host."""

        self.resource_identity()
        raw = self.bridge.exchange("art_direction_seed", context, limits)
        required = {"design_read", "dials", "foundation", "direction"}
        if not required.issubset(raw) or set(raw) - required - {"warnings", "assumptions"}:
            raise PlanningError(
                "Art Direction Seed requires design_read, dials, foundation and direction"
            )
        if (
            not isinstance(raw["design_read"], str)
            or not isinstance(raw["dials"], dict)
            or not isinstance(raw["foundation"], dict)
            or not isinstance(raw["direction"], dict)
        ):
            raise PlanningError("Art Direction Seed fields have invalid types")
        if (
            self.require_taste_generated
            and raw["foundation"].get("kind") != "taste-generated"
        ):
            raise PlanningError(
                "Host Create requires a Taste-generated native visual prototype; "
                "taste-informed fallback is not admitted on this path"
            )
        return ArtDirectionSeedProposal(
            design_read=raw["design_read"],
            dials=raw["dials"],
            foundation=raw["foundation"],
            direction=raw["direction"],
            warnings=_messages(raw, "warnings"),
            assumptions=_messages(raw, "assumptions"),
        )

    def propose(
        self, context: dict[str, Any], limits: ArtDirectionLimits
    ) -> ArtDirectionProposal:
        self.resource_identity()
        request_context = copy.deepcopy(context)
        seed_ref = request_context.get("slide_specs", {}).get("art_direction_seed")
        if seed_ref is not None:
            request_context["art_direction_seed"] = load_art_direction_seed(
                self.bridge.workspace,
                seed_ref,
            )
        raw = self.bridge.exchange("art_direction", request_context, limits)
        required = {"design_read", "dials", "direction"}
        if not required.issubset(raw) or set(raw) - required - {"warnings", "assumptions"}:
            raise PlanningError("Art direction requires design_read, dials and direction")
        if not isinstance(raw["direction"], dict) or not raw["direction"].get("page_designs"):
            raise PlanningError("Host art direction requires explicit page_designs, not only tokens")
        return ArtDirectionProposal(
            design_read=raw["design_read"],
            dials=raw["dials"],
            direction=raw["direction"],
            warnings=_messages(raw, "warnings"),
            assumptions=_messages(raw, "assumptions"),
        )
