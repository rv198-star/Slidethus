from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import ReviewRepairError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json

_PHASE_ORDER = {phase: index for index, phase in enumerate(("P0", "P1", "P2", "P3", "P4", "P5A", "P5B", "P6", "P7"))}
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
}


def repair_plan_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("plan_id", None)
    return payload


def repair_plan_id(data: dict[str, Any]) -> str:
    return "RPL-" + sha256_json(repair_plan_identity_payload(data))[:16].upper()


def repair_action_id(action: dict[str, Any]) -> str:
    payload = copy.deepcopy(action)
    payload.pop("action_id", None)
    return "RPA-" + sha256_json(payload)[:16].upper()


def repair_report_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("repair_id", None)
    return payload


def repair_report_id(data: dict[str, Any]) -> str:
    return "RRR-" + sha256_json(repair_report_identity_payload(data))[:16].upper()


def repair_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def _schema(schema_dir: Path, name: str) -> dict[str, Any]:
    path = schema_dir / name
    if not path.is_file():
        raise ReviewRepairError(f"Missing M5 repair schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def target_phase_for_repair_issues(issues: list[dict[str, Any]]) -> str | None:
    if not issues:
        return None
    earliest = min(
        (str(item["earliest_phase"]) for item in issues),
        key=lambda phase: _PHASE_ORDER[phase],
    )
    return _PHASE_TARGETS[earliest]


def validate_repair_plan_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir, "review_repair_plan.schema.json")).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("plan_id") != repair_plan_id(data):
        errors.append("Review Repair Plan identity mismatch")
    inputs = [str(item.get("artifact_type", "")) for item in data.get("inputs", [])]
    if inputs != sorted(inputs) or len(inputs) != len(set(inputs)):
        errors.append("Review Repair Plan inputs must be unique and sorted")
    source_ids = [str(item.get("source_id", "")) for item in data.get("issues", [])]
    if len(source_ids) != len(set(source_ids)):
        errors.append("Review Repair Plan contains duplicate source issues")
    action_ids = [str(item.get("action_id", "")) for item in data.get("actions", [])]
    if len(action_ids) != len(set(action_ids)):
        errors.append("Review Repair Plan contains duplicate action IDs")
    for action in data.get("actions", []):
        if action.get("action_id") != repair_action_id(action):
            errors.append(f"Review Repair action identity mismatch: {action.get('action_id')}")
    expected_status = "not_required" if not data.get("issues") else "planned"
    if data.get("status") != expected_status:
        errors.append("Review Repair Plan status disagrees with selected issues")
    if data.get("target_phase") != target_phase_for_repair_issues(list(data.get("issues", []))):
        errors.append("Review Repair Plan target_phase mismatch")
    known = set(source_ids)
    for action in data.get("actions", []):
        if not set(str(item) for item in action.get("source_ids", [])).issubset(known):
            errors.append(f"Review Repair action references unknown source issue: {action.get('action_id')}")
    return tuple(errors)


def validate_repair_report_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir, "review_repair_report.schema.json")).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("repair_id") != repair_report_id(data):
        errors.append("Review Repair Report identity mismatch")
    before = [str(item.get("artifact_type", "")) for item in data.get("before_inputs", [])]
    after = [str(item.get("artifact_type", "")) for item in data.get("after_inputs", [])]
    if before != sorted(before) or len(before) != len(set(before)):
        errors.append("Review Repair before_inputs must be unique and sorted")
    if after != sorted(after) or len(after) != len(set(after)):
        errors.append("Review Repair after_inputs must be unique and sorted")
    if data.get("status") == "applied":
        result = data.get("result_deterministic")
        if not isinstance(result, dict) or result.get("status") != "pass":
            errors.append("Applied Review Repair must end with a passing deterministic review")
    if data.get("status") == "not_required" and data.get("actions"):
        errors.append("Not-required Review Repair cannot contain execution actions")
    return tuple(errors)


def _artifact_path(workspace: Path, state: dict[str, Any], ref: dict[str, Any]) -> Path:
    artifact_type = str(ref["artifact_type"])
    entry = next((item for item in state.get("artifacts", []) if item.get("artifact_type") == artifact_type), None)
    if entry is None:
        raise ReviewRepairError(f"Review Repair references unknown artifact: {artifact_type}")
    version = int(ref["version"])
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise ReviewRepairError(f"Review Repair references unknown {artifact_type} version {version}")
    return ensure_within(workspace, path)


def _validate_artifact_refs(workspace: Path, refs: list[dict[str, Any]]) -> list[str]:
    state = read_json(workspace / "project_state.json")
    errors: list[str] = []
    for ref in refs:
        try:
            path = _artifact_path(workspace, state, ref)
            if f"sha256:{sha256_json(read_json(path))}" != ref.get("content_hash"):
                errors.append(f"Review Repair artifact hash mismatch: {ref.get('artifact_type')}")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    return errors


def repair_plan_reference_errors(workspace: Path, path: Path, schema_dir: Path) -> tuple[str, ...]:
    try:
        data = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return (f"Review Repair Plan is unreadable: {exc}",)
    errors = list(validate_repair_plan_data(data, schema_dir))
    errors.extend(_validate_artifact_refs(workspace, list(data.get("inputs", []))))
    roots = {
        "deterministic": ".slidethus/review/deterministic",
        "semantic": ".slidethus/review/semantic/open-issue",
        "visual": ".slidethus/review/visual",
    }
    for ref in data.get("source_reports", []):
        try:
            relative = Path(str(ref.get("path", "")))
            report_path = ensure_within(workspace, workspace / relative)
            root = ensure_within(workspace, workspace / roots[str(ref["source_type"])])
            if root != report_path and root not in report_path.parents:
                raise ReviewRepairError("Repair source report is outside admitted review root")
            if not report_path.is_file() or sha256_file(report_path) != ref.get("sha256"):
                errors.append(f"Repair source report hash mismatch: {ref.get('path')}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Repair source report is invalid: {exc}")
    return tuple(errors)


def repair_report_reference_errors(workspace: Path, path: Path, schema_dir: Path) -> tuple[str, ...]:
    try:
        data = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return (f"Review Repair Report is unreadable: {exc}",)
    errors = list(validate_repair_report_data(data, schema_dir))
    errors.extend(_validate_artifact_refs(workspace, list(data.get("before_inputs", []))))
    errors.extend(_validate_artifact_refs(workspace, list(data.get("after_inputs", []))))
    plan = data.get("plan", {})
    try:
        plan_path = ensure_within(workspace, workspace / Path(str(plan.get("path", ""))))
        root = ensure_within(workspace, workspace / ".slidethus/review/repairs/plans")
        if root != plan_path and root not in plan_path.parents:
            raise ReviewRepairError("Repair Report plan is outside admitted root")
        if sha256_file(plan_path) != plan.get("sha256"):
            errors.append("Repair Report plan hash mismatch")
        errors.extend(repair_plan_reference_errors(workspace, plan_path, schema_dir))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Repair Report plan is invalid: {exc}")
    result = data.get("result_deterministic")
    if isinstance(result, dict):
        try:
            review_path = ensure_within(workspace, workspace / Path(str(result.get("path", ""))))
            root = ensure_within(workspace, workspace / ".slidethus/review/deterministic")
            if root != review_path and root not in review_path.parents:
                raise ReviewRepairError("Repair result deterministic review is outside admitted root")
            if sha256_file(review_path) != result.get("sha256"):
                errors.append("Repair result deterministic review hash mismatch")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Repair result deterministic review is invalid: {exc}")
    return tuple(errors)


def review_repair_workspace_errors(workspace: Path, schema_dir: Path) -> tuple[tuple[str, str], ...]:
    errors: list[tuple[str, str]] = []
    for root, validator in (
        (workspace / ".slidethus/review/repairs/plans", repair_plan_reference_errors),
        (workspace / ".slidethus/review/repairs/reports", repair_report_reference_errors),
    ):
        if not root.exists():
            continue
        for entry in sorted(root.iterdir()):
            relative = entry.relative_to(workspace).as_posix()
            if not entry.is_file() or entry.suffix != ".json":
                errors.append((relative, "unexpected entry in Review Repair directory"))
                continue
            for message in validator(workspace, entry, schema_dir):
                errors.append((relative, message))
    return tuple(errors)
