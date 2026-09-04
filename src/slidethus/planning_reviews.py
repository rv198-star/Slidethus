from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import PlanningReviewError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.schema_registry import SchemaRegistry
from slidethus.state_machine import PLANNING_REWORK_TARGETS

_PHASE_TARGETS = {
    phase: target.value for phase, target in PLANNING_REWORK_TARGETS.items()
}
_PHASE_ORDER = {phase: index for index, phase in enumerate(_PHASE_TARGETS)}


def planning_issue_id(issue: dict[str, Any]) -> str:
    """Return stable identity for one planning issue independent of message wording."""

    payload = {
        "code": issue.get("code"),
        "artifact_type": issue.get("artifact_type"),
        "slide_id": issue.get("slide_id"),
        "block_id": issue.get("block_id"),
        "region_id": issue.get("region_id"),
        "earliest_phase": issue.get("earliest_phase"),
    }
    return "PRI-" + sha256_json(payload)[:16].upper()


def planning_review_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def planning_review_id(data: dict[str, Any]) -> str:
    """Return stable identity for one complete planning review payload."""

    return "PRV-" + sha256_json(planning_review_identity_payload(data))[:16].upper()


def planning_review_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def planning_review_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "planning_review_report.schema.json"
    if not path.is_file():
        raise PlanningReviewError(f"Missing Planning Review Report schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def target_phase_for_issues(issues: list[dict[str, Any]]) -> str | None:
    blocking = [
        item
        for item in issues
        if item.get("status") == "open"
        and item.get("severity") in {"critical", "major"}
    ]
    if not blocking:
        return None
    earliest = min(
        (str(item["earliest_phase"]) for item in blocking),
        key=lambda phase: _PHASE_ORDER[phase],
    )
    return _PHASE_TARGETS[earliest]


def validate_planning_review_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate review Schema, identities, counts, scores and rework routing."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(planning_review_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != planning_review_id(data):
        errors.append("Planning Review identity mismatch")
    input_types = [str(item.get("artifact_type", "")) for item in data.get("inputs", [])]
    if input_types != sorted(input_types):
        errors.append("Planning Review inputs must be sorted by artifact_type")
    if len(input_types) != len(set(input_types)):
        errors.append("Planning Review contains duplicate input artifact types")
    issue_ids = [str(item.get("issue_id", "")) for item in data.get("issues", [])]
    if len(issue_ids) != len(set(issue_ids)):
        errors.append("Planning Review contains duplicate issue IDs")
    for issue in data.get("issues", []):
        if issue.get("issue_id") != planning_issue_id(issue):
            errors.append(f"Planning issue identity mismatch: {issue.get('issue_id')}")
    known = set(issue_ids)
    dimensions = [str(item.get("dimension", "")) for item in data.get("dimensions", [])]
    if len(dimensions) != len(set(dimensions)):
        errors.append("Planning Review contains duplicate dimensions")
    for dimension in data.get("dimensions", []):
        if not set(dimension.get("issue_ids", [])).issubset(known):
            errors.append(
                f"Planning dimension references unknown issue: {dimension.get('dimension')}"
            )
    open_issues = [item for item in data.get("issues", []) if item.get("status") == "open"]
    summary = data.get("summary", {})
    expected_counts = {
        "critical_count": sum(item.get("severity") == "critical" for item in open_issues),
        "major_count": sum(item.get("severity") == "major" for item in open_issues),
        "minor_count": sum(item.get("severity") == "minor" for item in open_issues),
        "open_count": len(open_issues),
    }
    for key, expected in expected_counts.items():
        if int(summary.get(key, -1)) != expected:
            errors.append(f"Planning Review {key} mismatch")
    scores = [int(item.get("score", 0)) for item in data.get("dimensions", [])]
    expected_overall = round(sum(scores) / len(scores), 2) if scores else 0.0
    if float(summary.get("overall_score", -1)) != expected_overall:
        errors.append("Planning Review overall_score mismatch")
    expected_status = "issues" if open_issues else "pass"
    if data.get("status") != expected_status:
        errors.append("Planning Review status disagrees with open issues")
    expected_target = target_phase_for_issues(open_issues)
    if data.get("target_phase") != expected_target:
        errors.append("Planning Review target_phase mismatch")
    if bool(data.get("requires_rework")) != (expected_target is not None):
        errors.append("Planning Review requires_rework mismatch")
    return tuple(errors)


def _artifact_for_ref(
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
        raise PlanningReviewError(
            f"Planning Review references unregistered artifact: {artifact_type}"
        )
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise PlanningReviewError(
            f"Planning Review references unknown {artifact_type} version {version}"
        )
    if not path.is_file():
        raise PlanningReviewError(f"Planning Review artifact version is missing: {path}")
    data = read_json(path)
    if f"sha256:{sha256_json(data)}" != reference.get("content_hash"):
        raise PlanningReviewError(
            f"Planning Review artifact hash mismatch: {artifact_type} v{version}"
        )
    return data


def planning_review_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted Planning Review against historical artifact versions."""

    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Planning Review cannot be read: {exc}",)
    errors.extend(validate_planning_review_data(report, schema_dir))
    if report_path.name != f"{planning_review_file_key(report)}.json":
        errors.append("Planning Review filename mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if report.get("project_id") != state.get("project_id"):
        errors.append("Planning Review project_id mismatch")
    for reference in report.get("inputs", []):
        try:
            _artifact_for_ref(workspace, state, reference)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    for kind, reference in report.get("visual_admission", {}).items():
        try:
            path = ensure_within(workspace, workspace / str(reference["path"]))
            if not path.is_file() or sha256_file(path) != reference.get("sha256"):
                errors.append(f"Planning Review visual admission ref mismatch: {kind}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Planning Review visual admission ref is invalid: {kind}: {exc}")
    return tuple(errors)


def find_planning_review_report(
    workspace: Path,
    report_id: str,
    *,
    schema_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Return one verified Planning Review Report by stable ID."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/planning/reviews"
    if not root.exists():
        return None
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    for path in sorted(root.glob("*.json")):
        try:
            data = read_json(path)
        except Exception:
            continue
        if data.get("report_id") != report_id:
            continue
        errors = planning_review_reference_errors(
            workspace,
            path,
            admitted_schema_dir,
        )
        if errors:
            raise PlanningReviewError(
                "Invalid Planning Review Report: " + "; ".join(errors)
            )
        return path, copy.deepcopy(data)
    return None


def list_planning_review_reports(
    workspace: Path,
    *,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """List verified Planning Review Report summaries."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/planning/reviews"
    if not root.exists():
        return ()
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    summaries: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        errors = planning_review_reference_errors(
            workspace,
            path,
            admitted_schema_dir,
        )
        if errors:
            raise PlanningReviewError(
                f"Invalid Planning Review Report {path.name}: " + "; ".join(errors)
            )
        data = read_json(path)
        summaries.append(
            {
                "report_id": str(data["report_id"]),
                "status": str(data["status"]),
                "review_mode": str(data["review_mode"]),
                "generated_at": str(data["generated_at"]),
                "critical_count": int(data["summary"]["critical_count"]),
                "major_count": int(data["summary"]["major_count"]),
                "minor_count": int(data["summary"]["minor_count"]),
                "path": path.relative_to(workspace).as_posix(),
            }
        )
    summaries.sort(
        key=lambda item: (str(item["generated_at"]), str(item["report_id"]))
    )
    return tuple(summaries)


def planning_review_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for every persisted Planning Review Report."""

    root = workspace / ".slidethus/planning/reviews"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Planning Review directory"))
            continue
        for error in planning_review_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
