from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from slidethus.errors import PlanningError
from slidethus.io_utils import read_json, sha256_json

PLANNING_ENGINE_NAME = "production-planning-engine"
PLANNING_ENGINE_VERSION = "1.0.0"


def planning_lineage_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic payload used for one stable Planning lineage ID."""

    payload = copy.deepcopy(data)
    payload.pop("lineage_id", None)
    return payload


def planning_lineage_id(data: dict[str, Any]) -> str:
    """Return the stable identity for a complete planning lineage record."""

    return "PLN-" + sha256_json(planning_lineage_identity_payload(data))[:16].upper()


def artifact_semantic_hash(snapshot: dict[str, Any], artifact_type: str) -> tuple[str, str] | None:
    """Return an admitted semantic projection for artifacts with operational metadata."""

    if artifact_type == "evidence_ledger":
        return "claims", "sha256:" + sha256_json(snapshot["data"].get("claims", []))
    return None


def artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    """Build a content-bound Artifact Runtime reference from one graph snapshot."""

    reference = {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }
    semantic = artifact_semantic_hash(snapshot, artifact_type)
    if semantic is not None:
        scope, semantic_hash = semantic
        reference["semantic_scope"] = scope
        reference["semantic_hash"] = semantic_hash
    return reference


def build_planning_lineage(
    snapshots: dict[str, dict[str, Any]],
    *,
    provider_name: str,
    provider_version: str,
    proposal: dict[str, Any],
    policy: dict[str, Any],
    generated_at: str,
    warnings: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build one deterministic planning lineage record from admitted inputs."""

    provider_name = " ".join(str(provider_name).split()).strip()
    provider_version = " ".join(str(provider_version).split()).strip()
    if not provider_name or len(provider_name) > 128:
        raise PlanningError("Planning provider must declare a bounded name")
    if not provider_version or len(provider_version) > 128:
        raise PlanningError("Planning provider must declare a bounded version")
    if not isinstance(policy, dict) or not policy:
        raise PlanningError("Planning lineage requires a non-empty policy payload")
    policy_payload = copy.deepcopy(policy)
    refs = [
        artifact_ref(snapshot, artifact_type)
        for artifact_type, snapshot in sorted(snapshots.items())
    ]
    lineage: dict[str, Any] = {
        "lineage_id": "",
        "engine": PLANNING_ENGINE_NAME,
        "engine_version": PLANNING_ENGINE_VERSION,
        "provider": {"name": provider_name, "version": provider_version},
        "generated_at": generated_at,
        "proposal_hash": "sha256:" + sha256_json(proposal),
        "policy": policy_payload,
        "policy_hash": "sha256:" + sha256_json(policy_payload),
        "input_refs": refs,
        "warnings": list(dict.fromkeys(str(item) for item in warnings if str(item).strip())),
        "assumptions": list(
            dict.fromkeys(str(item) for item in assumptions if str(item).strip())
        ),
    }
    lineage["lineage_id"] = planning_lineage_id(lineage)
    return lineage


def accepted_gate_current(state: dict[str, Any], gate_id: str) -> bool:
    """Return whether an accepted Gate still binds the current registry versions."""

    summary = next(
        (
            item
            for item in state.get("completed_gates", [])
            if item.get("gate_id") == gate_id
            and item.get("status") in {"pass", "waived"}
        ),
        None,
    )
    if summary is None:
        return False
    entries = {
        str(item.get("artifact_type")): item
        for item in state.get("artifacts", [])
    }
    for reference in summary.get("artifact_versions", []):
        entry = entries.get(str(reference.get("artifact_type")))
        if entry is None:
            return False
        if int(entry.get("version", 0)) != int(reference.get("version", -1)):
            return False
        if entry.get("sha256") != reference.get("sha256"):
            return False
    return True


def planning_artifact_reusable(
    artifact: dict[str, Any] | None,
    graph: dict[str, dict[str, Any]],
    *,
    artifact_status: str,
    gate_current: bool,
    required_inputs: tuple[str, ...],
    provider_name: str,
    provider_version: str,
    policy: dict[str, Any],
    accepted_provider_names: tuple[str, ...] = (),
) -> bool:
    """Return whether one approved/frozen planning artifact can be reused as current."""

    if (
        artifact is None
        or artifact.get("status") != "approved"
        or (
            artifact_status not in {"approved", "frozen"}
            and not gate_current
        )
    ):
        return False
    lineage = artifact.get("planning_lineage")
    if not isinstance(lineage, dict):
        return False
    if planning_lineage_reference_errors(
        lineage,
        graph,
        required_inputs=required_inputs,
        require_current=True,
    ):
        return False
    provider = lineage.get("provider", {})
    provider_matches = (
        provider.get("name") == provider_name
        and provider.get("version") == provider_version
    ) or provider.get("name") in set(accepted_provider_names)
    if not provider_matches:
        return False
    return (
        lineage.get("policy") == policy
        and lineage.get("policy_hash") == "sha256:" + sha256_json(policy)
    )


def reuse_semantically_current_lineage(
    candidate: dict[str, Any],
    existing: dict[str, Any] | None,
    graph: dict[str, dict[str, Any]],
    *,
    required_inputs: tuple[str, ...],
) -> dict[str, Any]:
    """Reuse existing lineage when only non-semantic input metadata advanced."""

    if existing is None:
        return candidate
    if planning_lineage_reference_errors(
        existing,
        graph,
        required_inputs=required_inputs,
        require_current=True,
    ):
        return candidate
    comparable = (
        "engine",
        "engine_version",
        "provider",
        "proposal_hash",
        "policy",
        "policy_hash",
        "warnings",
        "assumptions",
    )
    if any(existing.get(field) != candidate.get(field) for field in comparable):
        return candidate
    return copy.deepcopy(existing)


def validate_planning_lineage_data(data: dict[str, Any]) -> tuple[str, ...]:
    """Validate stable identity and local ordering invariants independent of Schema."""

    errors: list[str] = []
    if data.get("lineage_id") != planning_lineage_id(data):
        errors.append("planning lineage identity mismatch")
    if data.get("policy_hash") != "sha256:" + sha256_json(data.get("policy", {})):
        errors.append("planning lineage policy hash mismatch")
    refs = list(data.get("input_refs", []))
    ref_types = [str(item.get("artifact_type", "")) for item in refs]
    if ref_types != sorted(ref_types):
        errors.append("planning lineage input_refs must be sorted by artifact_type")
    if len(ref_types) != len(set(ref_types)):
        errors.append("planning lineage contains duplicate artifact types")
    if len(data.get("warnings", [])) != len(set(data.get("warnings", []))):
        errors.append("planning lineage contains duplicate warnings")
    if len(data.get("assumptions", [])) != len(set(data.get("assumptions", []))):
        errors.append("planning lineage contains duplicate assumptions")
    return tuple(errors)


def workspace_planning_graph(
    workspace: Path,
    artifact_types: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Read current artifact bodies and registry lineage without ArtifactRuntime imports."""

    workspace = workspace.resolve()
    state = read_json(workspace / "project_state.json")
    entries = {
        str(item.get("artifact_type")): item for item in state.get("artifacts", [])
    }
    graph: dict[str, dict[str, Any]] = {}
    for artifact_type in artifact_types:
        entry = entries.get(artifact_type)
        if entry is None:
            continue
        graph[artifact_type] = {
            "data": read_json(workspace / str(entry["path"])),
            "version": int(entry["version"]),
            "content_hash": str(entry["content_hash"]),
            "updated_at": str(entry.get("updated_at") or entry.get("created_at") or ""),
            "status": str(entry.get("status", "draft")),
        }
    return graph


def planning_lineage_reference_errors(
    lineage: dict[str, Any],
    graph: dict[str, dict[str, Any]],
    *,
    required_inputs: tuple[str, ...],
    require_current: bool = True,
) -> tuple[str, ...]:
    """Validate that lineage binds required and, when requested, current artifacts."""

    errors = list(validate_planning_lineage_data(lineage))
    refs = {
        str(item.get("artifact_type", "")): item
        for item in lineage.get("input_refs", [])
    }
    missing = sorted(set(required_inputs) - set(refs))
    if missing:
        errors.append("planning lineage lacks required inputs: " + ", ".join(missing))
    for artifact_type in required_inputs:
        snapshot = graph.get(artifact_type)
        reference = refs.get(artifact_type)
        if snapshot is None or reference is None:
            continue
        if require_current and (
            int(reference.get("version", -1)) != int(snapshot["version"])
            or reference.get("content_hash") != snapshot["content_hash"]
        ):
            semantic = artifact_semantic_hash(snapshot, artifact_type)
            semantic_current = (
                semantic is not None
                and reference.get("semantic_scope") == semantic[0]
                and reference.get("semantic_hash") == semantic[1]
            )
            if not semantic_current:
                errors.append(f"planning lineage is stale for {artifact_type}")
    return tuple(errors)
