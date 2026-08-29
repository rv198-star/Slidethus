from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import DeterministicReviewError
from slidethus.io_utils import read_json, sha256_json

_PHASE_ORDER = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
    "P4": 4,
    "P5A": 5,
    "P5B": 6,
    "P6": 7,
    "P7": 8,
    "P8": 9,
}
_PHASE_TARGETS = {
    "P0": "CREATED",
    "P1": "BRIEF_READY",
    "P2": "SOURCES_READY",
    "P3": "EVIDENCE_READY",
    "P4": "NARRATIVE_READY",
    "P5A": "OUTLINE_READY",
    "P5B": "SLIDE_SPECS_READY",
    "P6": "LAYOUT_READY",
    "P7": "VISUAL_SYSTEM_READY",
    "P8": "DRAFT_RENDERED",
}


def deterministic_check_id(check: dict[str, Any]) -> str:
    """Return stable identity for one deterministic review check."""

    payload = {
        "code": check.get("code"),
        "category": check.get("category"),
        "earliest_phase": check.get("earliest_phase"),
        "refs": sorted(str(item) for item in check.get("refs", [])),
    }
    return "DRC-" + sha256_json(payload)[:16].upper()


def deterministic_review_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("review_id", None)
    return payload


def deterministic_review_id(data: dict[str, Any]) -> str:
    """Return stable identity for one complete deterministic review payload."""

    return "DVR-" + sha256_json(deterministic_review_identity_payload(data))[:16].upper()


def deterministic_review_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def deterministic_review_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "deterministic_review_report.schema.json"
    if not path.is_file():
        raise DeterministicReviewError(f"Missing Deterministic Review schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def target_phase_for_checks(checks: list[dict[str, Any]]) -> str | None:
    failed = [item for item in checks if item.get("status") == "fail"]
    if not failed:
        return None
    earliest = min(
        (str(item["earliest_phase"]) for item in failed),
        key=lambda phase: _PHASE_ORDER[phase],
    )
    return _PHASE_TARGETS[earliest]


def validate_deterministic_review_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate deterministic review Schema, identities, counts, and routing."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(deterministic_review_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("review_id") != deterministic_review_id(data):
        errors.append("Deterministic Review identity mismatch")
    input_types = [str(item.get("artifact_type", "")) for item in data.get("inputs", [])]
    if input_types != sorted(input_types):
        errors.append("Deterministic Review inputs must be sorted by artifact_type")
    if len(input_types) != len(set(input_types)):
        errors.append("Deterministic Review contains duplicate input artifact types")
    check_ids = [str(item.get("check_id", "")) for item in data.get("checks", [])]
    if len(check_ids) != len(set(check_ids)):
        errors.append("Deterministic Review contains duplicate check IDs")
    for check in data.get("checks", []):
        if check.get("check_id") != deterministic_check_id(check):
            errors.append(f"Deterministic check identity mismatch: {check.get('check_id')}")
    failed = [item for item in data.get("checks", []) if item.get("status") == "fail"]
    passed = [item for item in data.get("checks", []) if item.get("status") == "pass"]
    summary = data.get("summary", {})
    expected = {
        "passed_count": len(passed),
        "failed_count": len(failed),
        "critical_count": sum(item.get("severity") == "critical" for item in failed),
        "major_count": sum(item.get("severity") == "major" for item in failed),
        "minor_count": sum(item.get("severity") == "minor" for item in failed),
    }
    for key, count in expected.items():
        if int(summary.get(key, -1)) != count:
            errors.append(f"Deterministic Review {key} mismatch")
    expected_status = "issues" if failed else "pass"
    if data.get("status") != expected_status:
        errors.append("Deterministic Review status disagrees with failed checks")
    expected_target = target_phase_for_checks(list(data.get("checks", [])))
    if data.get("target_phase") != expected_target:
        errors.append("Deterministic Review target_phase mismatch")
    return tuple(errors)


def _artifact_for_input(
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
        raise DeterministicReviewError(
            f"Deterministic Review references unregistered artifact: {artifact_type}"
        )
    if str(reference.get("path")) != str(entry.get("path")):
        raise DeterministicReviewError(
            f"Deterministic Review artifact path mismatch: {artifact_type}"
        )
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise DeterministicReviewError(
            f"Deterministic Review references unknown {artifact_type} version {version}"
        )
    if not path.is_file():
        raise DeterministicReviewError(
            f"Deterministic Review artifact version is missing: {artifact_type} v{version}"
        )
    data = read_json(path)
    observed_hash = f"sha256:{sha256_json(data)}"
    if observed_hash != reference.get("observed_content_hash"):
        raise DeterministicReviewError(
            f"Deterministic Review observed artifact hash mismatch: {artifact_type} v{version}"
        )
    if version == current_version and reference.get("content_hash") != entry.get("content_hash"):
        raise DeterministicReviewError(
            f"Deterministic Review expected artifact hash drift: {artifact_type} v{version}"
        )
    return data


def deterministic_review_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted deterministic review and all artifact version refs."""

    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Deterministic Review is unreadable: {exc}",)
    errors.extend(validate_deterministic_review_data(report, schema_dir))
    if report_path.stem != deterministic_review_file_key(report):
        errors.append("Deterministic Review filename/content hash mismatch")
    try:
        state = read_json(workspace / "project_state.json")
    except Exception as exc:  # noqa: BLE001
        return tuple([*errors, f"Project State is unreadable: {exc}"])
    if report.get("project_id") != state.get("project_id"):
        errors.append("Deterministic Review project_id mismatch")
    for reference in report.get("inputs", []):
        try:
            _artifact_for_input(workspace, state, reference)
        except DeterministicReviewError as exc:
            errors.append(str(exc))
    return tuple(errors)


def deterministic_review_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for all persisted M5.1 deterministic review facts."""

    report_dir = workspace / ".slidethus/review/deterministic"
    if not report_dir.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(report_dir.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Deterministic Review directory"))
            continue
        for error in deterministic_review_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
