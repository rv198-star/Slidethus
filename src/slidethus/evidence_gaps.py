from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import EvidenceGapError
from slidethus.io_utils import read_json, sha256_json


def gap_report_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic payload used for one stable Evidence Gap Report ID."""

    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def gap_report_id(data: dict[str, Any]) -> str:
    """Return the stable report ID for one complete report payload."""

    return "EGR-" + sha256_json(gap_report_identity_payload(data))[:16].upper()


def gap_report_file_key(data: dict[str, Any]) -> str:
    """Return the content-addressed filename key for one report."""

    return sha256_json(data)


def gap_issue_id(issue: dict[str, Any]) -> str:
    """Return the stable identity for one Evidence Gap issue."""

    payload = {
        "code": issue.get("code"),
        "slide_id": issue.get("slide_id"),
        "block_id": issue.get("block_id"),
        "evidence_ids": sorted(set(issue.get("evidence_ids", []))),
        "earliest_phase": issue.get("earliest_phase"),
    }
    return "EGI-" + sha256_json(payload)[:16].upper()


def gap_query_id(suggestion: dict[str, Any]) -> str:
    """Return the stable identity for one targeted query suggestion."""

    payload = {
        "slide_id": suggestion.get("slide_id"),
        "block_id": suggestion.get("block_id"),
        "query": suggestion.get("query"),
        "reason_code": suggestion.get("reason_code"),
        "outline_version": suggestion.get("outline_version"),
    }
    return "EGQ-" + sha256_json(payload)[:16].upper()


def gap_report_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "evidence_gap_report.schema.json"
    if not path.is_file():
        raise EvidenceGapError(f"Missing Evidence Gap Report schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_gap_report_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate report schema plus stable identity and deterministic ordering."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(gap_report_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != gap_report_id(data):
        errors.append("report identity mismatch")

    try:
        datetime.fromisoformat(str(data.get("generated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("generated_at is not a valid ISO-8601 timestamp")

    expected_input_types = {
        "project_brief": "project_brief",
        "source_ledger": "source_ledger",
        "evidence_ledger": "evidence_ledger",
        "deck_outline": "deck_outline",
        "slide_specs": "slide_specs",
    }
    for name, expected_type in expected_input_types.items():
        reference = data.get("inputs", {}).get(name)
        if reference is not None and reference.get("artifact_type") != expected_type:
            errors.append(f"input artifact type mismatch: {name}")

    issue_ids = [str(item.get("issue_id", "")) for item in data.get("issues", [])]
    if len(issue_ids) != len(set(issue_ids)):
        errors.append("duplicate Evidence Gap issue ID")
    for issue in data.get("issues", []):
        if issue.get("issue_id") != gap_issue_id(issue):
            errors.append(f"issue identity mismatch: {issue.get('issue_id')}")
    query_ids = [
        str(item.get("query_id", "")) for item in data.get("query_suggestions", [])
    ]
    if len(query_ids) != len(set(query_ids)):
        errors.append("duplicate Evidence Gap query suggestion ID")
    for suggestion in data.get("query_suggestions", []):
        if suggestion.get("query_id") != gap_query_id(suggestion):
            errors.append(
                f"query suggestion identity mismatch: {suggestion.get('query_id')}"
            )
    slide_ids = [str(item.get("slide_id", "")) for item in data.get("slides", [])]
    if len(slide_ids) != len(set(slide_ids)):
        errors.append("duplicate Evidence Gap slide ID")

    known_issues = set(issue_ids)
    known_queries = set(query_ids)
    for slide in data.get("slides", []):
        if not set(slide.get("issue_ids", [])).issubset(known_issues):
            errors.append(f"slide references unknown issue: {slide.get('slide_id')}")
        if not set(slide.get("query_suggestion_ids", [])).issubset(known_queries):
            errors.append(
                f"slide references unknown query suggestion: {slide.get('slide_id')}"
            )
    blocking_count = sum(
        1
        for item in data.get("issues", [])
        if item.get("severity") in {"critical", "major"}
        and item.get("status") == "open"
    )
    warning_count = sum(
        1
        for item in data.get("issues", [])
        if item.get("severity") == "minor" and item.get("status") == "open"
    )
    summary = data.get("summary", {})
    if summary.get("blocking_issue_count") != blocking_count:
        errors.append("blocking issue count mismatch")
    if summary.get("warning_count") != warning_count:
        errors.append("warning count mismatch")
    if summary.get("query_suggestion_count") != len(query_ids):
        errors.append("query suggestion count mismatch")
    if bool(data.get("requires_rework")) != (blocking_count > 0):
        errors.append("requires_rework does not match blocking issues")
    expected_status = "gaps" if blocking_count else "pass"
    if data.get("status") != expected_status:
        errors.append("report status does not match issue severity")
    expected_target = "EVIDENCE_READY" if blocking_count else None
    if data.get("target_phase") != expected_target:
        errors.append("report target_phase does not match rework requirement")
    return tuple(errors)


def _artifact_data_for_ref(
    workspace: Path,
    state: dict[str, Any],
    artifact_ref: dict[str, Any],
) -> dict[str, Any]:
    artifact_type = str(artifact_ref["artifact_type"])
    version = int(artifact_ref["version"])
    entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == artifact_type
        ),
        None,
    )
    if entry is None:
        raise EvidenceGapError(f"Gap report references unregistered artifact: {artifact_type}")
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise EvidenceGapError(
            f"Gap report references unknown {artifact_type} version: {version}"
        )
    if not path.is_file():
        raise EvidenceGapError(f"Gap report artifact version is missing: {path}")
    return read_json(path)


def gap_report_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted report and all versioned artifact references."""

    errors: list[str] = []
    try:
        data = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"report JSON cannot be read: {exc}",)
    errors.extend(validate_gap_report_data(data, schema_dir))
    if report_path.name != f"{gap_report_file_key(data)}.json":
        errors.append("content-addressed report filename mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        errors.append("project_state.json is missing")
        return tuple(errors)
    state = read_json(state_path)
    if data.get("project_id") != state.get("project_id"):
        errors.append("report project_id mismatch")
    for raw_ref in data.get("inputs", {}).values():
        if raw_ref is None:
            continue
        try:
            artifact_data = _artifact_data_for_ref(workspace, state, raw_ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        if f"sha256:{sha256_json(artifact_data)}" != raw_ref.get("content_hash"):
            errors.append(
                f"artifact content hash mismatch: {raw_ref.get('artifact_type')} v{raw_ref.get('version')}"
            )
    return tuple(errors)


def evidence_gap_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for every persisted Evidence Gap Report."""

    root = workspace / ".slidethus/evidence/gaps"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for path in sorted(root.glob("*.json")):
        relative = path.relative_to(workspace).as_posix()
        for error in gap_report_reference_errors(workspace, path, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
