from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import PlanningLimitError, PlanningReviewError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.planning_changes import find_planning_change_report
from slidethus.planning_limits import validate_planning_limits
from slidethus.planning_reviews import planning_review_reference_errors
from slidethus.protocols import PlanningLimits
from slidethus.schema_registry import SchemaRegistry

_PHASE_TARGET = {
    "P0": "BRIEF_READY",
    "P2": "EVIDENCE_READY",
    "P3": "NARRATIVE_READY",
    "P4": "OUTLINE_READY",
    "P5A": "SLIDE_SPECS_READY",
    "P5B": "LAYOUT_READY",
}
_PHASE_ORDER = {phase: index for index, phase in enumerate(_PHASE_TARGET)}


def planning_repair_request_hash(
    project_id: str,
    review_id: str,
    issue_ids: tuple[str, ...],
    reason: str,
    limits: PlanningLimits,
    provider: dict[str, str],
) -> str:
    """Return a stable semantic repair request hash."""

    return "sha256:" + sha256_json(
        {
            "project_id": project_id,
            "review_id": review_id,
            "issue_ids": sorted(set(issue_ids)),
            "reason": " ".join(reason.split()).strip(),
            "planning_limits": asdict(limits),
            "planning_provider": provider,
        }
    )


def planning_repair_id(request_hash: str) -> str:
    """Return one stable PRP identity."""

    return "PRP-" + sha256_json({"request_hash": request_hash})[:16].upper()


def planning_repair_file_key(data: dict[str, Any]) -> str:
    """Return the content-addressed filename key for one Repair Report."""

    return sha256_json(data)


def planning_repair_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "planning_repair_report.schema.json"
    if not path.is_file():
        raise PlanningReviewError(f"Missing Planning Repair Report schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def target_phase_for_selected_issues(issues: list[dict[str, Any]]) -> str:
    """Return the earliest admitted repair target for selected issues."""

    if not issues:
        raise PlanningReviewError("Planning repair requires at least one issue")
    earliest = min(
        (str(item["earliest_phase"]) for item in issues),
        key=lambda phase: _PHASE_ORDER[phase],
    )
    return _PHASE_TARGET[earliest]


def validate_planning_repair_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate Repair Report schema and local identity/status invariants."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(planning_repair_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    source_review = data.get("source_review", {})
    try:
        limits = PlanningLimits(**dict(data.get("planning_limits", {})))
        validate_planning_limits(limits)
    except (TypeError, ValueError, PlanningLimitError) as exc:
        errors.append(f"Planning Repair limits are invalid: {exc}")
        limits = PlanningLimits()
    request_hash = planning_repair_request_hash(
        str(data.get("project_id", "")),
        str(source_review.get("report_id", "")),
        tuple(str(item) for item in data.get("issue_ids", [])),
        str(data.get("reason", "")),
        limits,
        dict(data.get("planning_provider", {})),
    )
    if data.get("repair_id") != planning_repair_id(request_hash):
        errors.append("Planning Repair identity mismatch")
    action_ids = [str(item.get("action_id", "")) for item in data.get("actions", [])]
    if action_ids != [f"PRA-{index:03d}" for index in range(1, len(action_ids) + 1)]:
        errors.append("Planning Repair action IDs must be contiguous from PRA-001")
    status = data.get("status")
    actions = list(data.get("actions", []))
    if status == "applied" and (not actions or data.get("result_review") is None):
        errors.append("Applied Planning Repair requires actions and a result review")
    if status == "blocked" and not any(
        item.get("operation") == "route_manual" for item in actions
    ):
        errors.append("Blocked Planning Repair requires a route_manual action")
    if status == "noop" and actions:
        errors.append("Noop Planning Repair must not contain actions")
    if status in {"blocked", "noop"} and data.get("result_review") is not None:
        errors.append("Blocked/noop Planning Repair cannot claim a result review")
    invalidated = list(data.get("downstream_invalidated", []))
    if invalidated != list(dict.fromkeys(invalidated)):
        errors.append("Planning Repair downstream_invalidated contains duplicates")
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
            f"Planning Repair references unregistered artifact: {artifact_type}"
        )
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise PlanningReviewError(
            f"Planning Repair references unknown {artifact_type} version {version}"
        )
    if not path.is_file():
        raise PlanningReviewError(f"Planning Repair artifact version is missing: {path}")
    data = read_json(path)
    if f"sha256:{sha256_json(data)}" != reference.get("content_hash"):
        raise PlanningReviewError(
            f"Planning Repair artifact hash mismatch: {artifact_type} v{version}"
        )
    return data


def _review_for_ref(
    workspace: Path,
    reference: dict[str, Any],
    schema_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    raw_path = Path(str(reference.get("path", "")))
    if raw_path.is_absolute():
        raise PlanningReviewError("absolute Planning Review path is not allowed")
    path = ensure_within(workspace, workspace / raw_path)
    root = ensure_within(workspace, workspace / ".slidethus/planning/reviews")
    if path.parent != root:
        raise PlanningReviewError(
            "Planning Review must be stored directly under the admitted review directory"
        )
    if not path.is_file():
        raise PlanningReviewError(f"Planning Review is missing: {raw_path}")
    if sha256_file(path) != reference.get("sha256"):
        raise PlanningReviewError(f"Planning Review hash mismatch: {raw_path}")
    errors = planning_review_reference_errors(workspace, path, schema_dir)
    if errors:
        raise PlanningReviewError("Invalid Planning Review: " + "; ".join(errors))
    data = read_json(path)
    if data.get("report_id") != reference.get("report_id"):
        raise PlanningReviewError("Planning Review identity mismatch")
    return path, data


def planning_repair_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted Repair Report and all historical references."""

    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Planning Repair cannot be read: {exc}",)
    errors.extend(validate_planning_repair_data(report, schema_dir))
    if report_path.name != f"{planning_repair_file_key(report)}.json":
        errors.append("Planning Repair filename mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if report.get("project_id") != state.get("project_id"):
        errors.append("Planning Repair project_id mismatch")
        return tuple(errors)
    try:
        _source_path, source_review = _review_for_ref(
            workspace,
            report["source_review"],
            schema_dir,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        return tuple(errors)
    source_issue_map = {
        str(item["issue_id"]): item for item in source_review.get("issues", [])
    }
    selected_ids = [str(item) for item in report.get("issue_ids", [])]
    unknown = sorted(set(selected_ids) - set(source_issue_map))
    if unknown:
        errors.append("Planning Repair references unknown source issues: " + ", ".join(unknown))
    selected = [source_issue_map[item] for item in selected_ids if item in source_issue_map]
    if selected:
        expected_target = target_phase_for_selected_issues(selected)
        if report.get("target_phase") != expected_target:
            errors.append("Planning Repair target_phase disagrees with selected issues")
    result_review: dict[str, Any] | None = None
    if report.get("result_review") is not None:
        try:
            _result_path, result_review = _review_for_ref(
                workspace,
                report["result_review"],
                schema_dir,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    if result_review is not None:
        result_ids = {
            str(item["issue_id"]) for item in result_review.get("issues", [])
        }
        if not set(report.get("remaining_issue_ids", [])).issubset(result_ids):
            errors.append("Planning Repair remaining issues are absent from result review")
    for action in report.get("actions", []):
        for field in ("before_ref", "after_ref"):
            reference = action.get(field)
            if reference is None:
                continue
            try:
                artifact = _artifact_for_ref(workspace, state, reference)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                continue
            if (
                field == "after_ref"
                and reference.get("artifact_type") in {"slide_specs", "layout_plans"}
                and artifact.get("planning_lineage", {}).get("provider")
                != report.get("planning_provider")
            ):
                errors.append(
                    "Planning Repair provider disagrees with regenerated "
                    f"{reference.get('artifact_type')} lineage"
                )
        change_id = action.get("change_report_id")
        if change_id is not None:
            try:
                found = find_planning_change_report(
                    workspace,
                    str(change_id),
                    schema_dir=schema_dir,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
            else:
                if found is None:
                    errors.append(f"Planning Repair change report is missing: {change_id}")
    return tuple(errors)


def find_planning_repair_report(
    workspace: Path,
    repair_id: str,
    *,
    schema_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Return one verified Repair Report by stable ID."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/planning/repairs"
    if not root.exists():
        return None
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    for path in sorted(root.glob("*.json")):
        try:
            data = read_json(path)
        except Exception:
            continue
        if data.get("repair_id") != repair_id:
            continue
        errors = planning_repair_reference_errors(
            workspace,
            path,
            admitted_schema_dir,
        )
        if errors:
            raise PlanningReviewError(
                "Invalid Planning Repair Report: " + "; ".join(errors)
            )
        return path, copy.deepcopy(data)
    return None


def planning_repair_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for every persisted Planning Repair Report."""

    root = workspace / ".slidethus/planning/repairs"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Planning Repair directory"))
            continue
        for error in planning_repair_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
