from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import PlanningLimitError, PlanningReviewError
from slidethus.io_utils import read_json, sha256_json
from slidethus.planning_limits import validate_planning_limits
from slidethus.protocols import PlanningLimits
from slidethus.schema_registry import SchemaRegistry

OUTLINE_CHANGE_PROVIDER_NAME = "deterministic-outline-change-service"
OUTLINE_CHANGE_PROVIDER_VERSION = "1.0.0"


def planning_change_request_hash(
    project_id: str,
    operation: str,
    payload: dict[str, Any],
    reason: str,
    *,
    limits: PlanningLimits,
    idempotency_key: str | None = None,
) -> str:
    """Return the stable request hash for one explicit sticky-note operation."""

    return "sha256:" + sha256_json(
        {
            "project_id": project_id,
            "operation": operation,
            "payload": payload,
            "reason": " ".join(reason.split()).strip(),
            "planning_limits": asdict(limits),
            "idempotency_key": idempotency_key,
        }
    )


def planning_change_id(project_id: str, request_hash: str) -> str:
    """Return the stable PCH identity for one idempotent request."""

    return "PCH-" + sha256_json(
        {"project_id": project_id, "request_hash": request_hash}
    )[:16].upper()


def planning_change_file_key(data: dict[str, Any]) -> str:
    """Return the content-addressed filename key for one Change Report."""

    return sha256_json(data)


def planning_change_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "planning_change_report.schema.json"
    if not path.is_file():
        raise PlanningReviewError(f"Missing Planning Change Report schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_planning_change_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate Change Report schema and stable identity invariants."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(planning_change_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    try:
        limits = PlanningLimits(**dict(data.get("planning_limits", {})))
        validate_planning_limits(limits)
    except (TypeError, ValueError, PlanningLimitError) as exc:
        errors.append(f"Planning Change limits are invalid: {exc}")
        limits = PlanningLimits()
    expected_request_hash = planning_change_request_hash(
        str(data.get("project_id", "")),
        str(data.get("operation", "")),
        dict(data.get("request_payload", {})),
        str(data.get("reason", "")),
        limits=limits,
        idempotency_key=data.get("idempotency_key"),
    )
    if data.get("request_hash") != expected_request_hash:
        errors.append("Planning Change request hash mismatch")
    expected_id = planning_change_id(
        str(data.get("project_id", "")),
        str(data.get("request_hash", "")),
    )
    if data.get("change_id") != expected_id:
        errors.append("Planning Change identity mismatch")
    if data.get("status") == "applied":
        if int(data["output_outline"]["version"]) != int(data["input_outline"]["version"]) + 1:
            errors.append("Applied Planning Change must advance Deck Outline by one version")
    for field in (
        "target_slide_ids",
        "created_slide_ids",
        "excluded_slide_ids",
        "preserved_slide_ids",
        "changed_fields",
        "downstream_invalidated",
    ):
        values = list(data.get(field, []))
        if values != list(dict.fromkeys(values)):
            errors.append(f"Planning Change {field} contains duplicates")
    mapping_pairs = [
        (
            tuple(item.get("from_slide_ids", [])),
            tuple(item.get("to_slide_ids", [])),
        )
        for item in data.get("mappings", [])
    ]
    if len(mapping_pairs) != len(set(mapping_pairs)):
        errors.append("Planning Change contains duplicate mappings")
    return tuple(errors)


def _outline_for_ref(
    workspace: Path,
    state: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    version = int(reference["version"])
    entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == "deck_outline"
        ),
        None,
    )
    if entry is None:
        raise PlanningReviewError("Planning Change references unregistered deck_outline")
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history/deck_outline" / f"{version:06d}.json"
    else:
        raise PlanningReviewError(f"Unknown Deck Outline version: {version}")
    if not path.is_file():
        raise PlanningReviewError(f"Deck Outline version is missing: {path}")
    data = read_json(path)
    if f"sha256:{sha256_json(data)}" != reference.get("content_hash"):
        raise PlanningReviewError(f"Deck Outline content hash mismatch for version {version}")
    return data


def planning_change_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted Change Report against Artifact Runtime history."""

    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Planning Change Report cannot be read: {exc}",)
    errors.extend(validate_planning_change_data(report, schema_dir))
    if report_path.name != f"{planning_change_file_key(report)}.json":
        errors.append("Planning Change Report filename mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if report.get("project_id") != state.get("project_id"):
        errors.append("Planning Change Report project_id mismatch")
        return tuple(errors)
    try:
        input_outline = _outline_for_ref(workspace, state, report["input_outline"])
        output_outline = _outline_for_ref(workspace, state, report["output_outline"])
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        return tuple(errors)
    input_ids = {str(item["slide_id"]) for item in input_outline.get("slides", [])}
    output_ids = {str(item["slide_id"]) for item in output_outline.get("slides", [])}
    unknown_targets = sorted(set(report.get("target_slide_ids", [])) - input_ids)
    if unknown_targets:
        errors.append("Planning Change targets absent input slides: " + ", ".join(unknown_targets))
    unknown_created = sorted(set(report.get("created_slide_ids", [])) - output_ids)
    if unknown_created:
        errors.append("Planning Change created slides absent output: " + ", ".join(unknown_created))
    output_by_id = {
        str(item["slide_id"]): item for item in output_outline.get("slides", [])
    }
    nonexcluded = [
        slide_id
        for slide_id in report.get("excluded_slide_ids", [])
        if output_by_id.get(slide_id, {}).get("status") != "excluded"
    ]
    if nonexcluded:
        errors.append("Planning Change excluded slides remain active: " + ", ".join(nonexcluded))
    if report.get("change_id") not in output_outline.get("operations_applied", []):
        errors.append("Planning Change ID is absent from output Outline operations_applied")
    lineage = output_outline.get("planning_lineage", {})
    expected_provider = {
        "name": OUTLINE_CHANGE_PROVIDER_NAME,
        "version": OUTLINE_CHANGE_PROVIDER_VERSION,
    }
    if lineage.get("provider") != expected_provider:
        errors.append("Planning Change output Outline has unexpected provider lineage")
    expected_policy = {
        "service": "outline",
        "limits": report.get("planning_limits", {}),
    }
    if lineage.get("policy") != expected_policy:
        errors.append("Planning Change output Outline policy disagrees with report limits")
    expected_proposal_hash = "sha256:" + sha256_json(
        {
            "operation": report.get("operation"),
            "payload": report.get("request_payload", {}),
        }
    )
    if lineage.get("proposal_hash") != expected_proposal_hash:
        errors.append("Planning Change output Outline proposal hash disagrees with request")
    if lineage.get("generated_at") != report.get("generated_at"):
        errors.append("Planning Change output Outline timestamp disagrees with report")
    for mapping in report.get("mappings", []):
        if not set(mapping.get("from_slide_ids", [])).issubset(input_ids):
            errors.append("Planning Change mapping references unknown input slide")
        if not set(mapping.get("to_slide_ids", [])).issubset(output_ids):
            errors.append("Planning Change mapping references unknown output slide")
    return tuple(errors)


def find_planning_change_by_idempotency_key(
    workspace: Path,
    idempotency_key: str,
    *,
    schema_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Return one verified Change Report that already owns an idempotency key."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/planning/changes"
    if not root.exists():
        return None
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = read_json(path)
        except Exception:
            continue
        if data.get("idempotency_key") != idempotency_key:
            continue
        errors = planning_change_reference_errors(workspace, path, admitted_schema_dir)
        if errors:
            raise PlanningReviewError(
                "Invalid Planning Change Report: " + "; ".join(errors)
            )
        matches.append((path, copy.deepcopy(data)))
    if len(matches) > 1:
        raise PlanningReviewError(
            f"Planning Change idempotency key is bound more than once: {idempotency_key}"
        )
    return matches[0] if matches else None


def find_planning_change_report(
    workspace: Path,
    change_id: str,
    *,
    schema_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Return one verified Change Report by stable ID, when present."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/planning/changes"
    if not root.exists():
        return None
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    for path in sorted(root.glob("*.json")):
        try:
            data = read_json(path)
        except Exception:
            continue
        if data.get("change_id") != change_id:
            continue
        errors = planning_change_reference_errors(workspace, path, admitted_schema_dir)
        if errors:
            raise PlanningReviewError(
                "Invalid Planning Change Report: " + "; ".join(errors)
            )
        return path, copy.deepcopy(data)
    return None


def planning_change_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for all persisted Planning Change Reports."""

    root = workspace / ".slidethus/planning/changes"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Planning Change directory"))
            continue
        for error in planning_change_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
