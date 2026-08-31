"""File bridge for reasoning performed by the host, never a model impersonator."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.art_direction import TasteSkillArtDirectionProvider
from slidethus.errors import PlanningError
from slidethus.io_utils import atomic_create_json, canonical_json_bytes, read_json, sha256_json
from slidethus.protocols import (
    ArtDirectionLimits,
    ArtDirectionProposal,
    PlanningLimits,
    PlanningProposal,
)
from slidethus.schema_registry import SchemaRegistry


class HostDesignRequired(PlanningError):
    """A current stage awaits an explicit host response, not a fallback."""


class HostDesignBridge:
    """Persist content-bound stage requests and read bounded host proposals."""

    def __init__(self, workspace: Path) -> None:
        self.root = workspace.resolve() / ".slidethus/host-design"
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

    def __init__(self, bridge: HostDesignBridge) -> None:
        self.bridge = bridge

    def propose(
        self, artifact_type: str, context: dict[str, Any], limits: PlanningLimits
    ) -> PlanningProposal:
        raw = self.bridge.exchange(artifact_type, context, limits)
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
        )


class HostArtDirectionProvider:
    """Admit host art direction; a pinned resource is not proof of a native prototype."""

    name = "host-authored-art-direction"
    version = "1.0.0"
    mode = "host-authored"

    def __init__(self, bridge: HostDesignBridge) -> None:
        self.bridge = bridge

    def resource_identity(self) -> dict[str, Any]:
        return TasteSkillArtDirectionProvider().resource_identity()

    def propose(
        self, context: dict[str, Any], limits: ArtDirectionLimits
    ) -> ArtDirectionProposal:
        self.resource_identity()
        raw = self.bridge.exchange("art_direction", context, limits)
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
