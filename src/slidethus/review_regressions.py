from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.deterministic_reviews import deterministic_review_reference_errors
from slidethus.errors import ReviewRegressionError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.review_repairs import repair_report_reference_errors
from slidethus.semantic_reviews import (
    semantic_review_reference_errors,
    semantic_scorecard_reference_errors,
)
from slidethus.visual_reviews import visual_review_reference_errors


def regression_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("regression_id", None)
    return payload


def regression_id(data: dict[str, Any]) -> str:
    return "REG-" + sha256_json(regression_identity_payload(data))[:16].upper()


def regression_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def regression_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "review_regression_report.schema.json"
    if not path.is_file():
        raise ReviewRegressionError(f"Missing Review Regression schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_regression_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(regression_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("regression_id") != regression_id(data):
        errors.append("Review Regression identity mismatch")
    review_types = [str(item.get("review_type", "")) for item in data.get("review_inputs", [])]
    if sorted(review_types) != ["deterministic", "scorecard", "semantic", "visual"]:
        errors.append("Review Regression must bind deterministic, semantic, scorecard and visual reports exactly once")
    gate_ids = [str(item.get("gate_id", "")) for item in data.get("gate_results", [])]
    expected_gates = ["G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7"]
    if gate_ids != expected_gates:
        errors.append("Review Regression gate_results must be ordered G0 through G7")
    gate_failures = sum(item.get("status") != "pass" for item in data.get("gate_results", []))
    unexpected = sum(bool(item.get("changed")) and not bool(item.get("allowed")) for item in data.get("artifact_changes", []))
    slide_failures = sum(item.get("status") == "fail" for item in data.get("slide_results", []))
    changed_slides = sum(bool(item.get("expected_change")) for item in data.get("slide_results", []))
    unchanged_slides = len(data.get("slide_results", [])) - changed_slides
    summary = data.get("summary", {})
    expected = {
        "gate_failures": gate_failures,
        "unexpected_artifact_changes": unexpected,
        "slide_failures": slide_failures,
        "changed_slide_count": changed_slides,
        "unchanged_slide_count": unchanged_slides,
    }
    for key, value in expected.items():
        if int(summary.get(key, -1)) != value:
            errors.append(f"Review Regression {key} mismatch")
    blocked = any(item.get("status") == "blocked" for item in data.get("review_inputs", []))
    repair = data.get("repair")
    if isinstance(repair, dict) and repair.get("status") in {"blocked", "failed"}:
        blocked = True
    expected_status = "blocked" if blocked else ("issues" if gate_failures or unexpected or slide_failures else "pass")
    if data.get("status") != expected_status:
        errors.append("Review Regression status disagrees with inputs/regression failures")
    return tuple(errors)


def _runtime_path(workspace: Path, raw: Any, admitted_root: str) -> Path:
    relative = Path(str(raw))
    if relative.is_absolute():
        raise ReviewRegressionError(f"Regression input path is absolute: {raw}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / admitted_root)
    if root != path and root not in path.parents:
        raise ReviewRegressionError(f"Regression input is outside {admitted_root}: {raw}")
    return path


def regression_reference_errors(workspace: Path, path: Path, schema_dir: Path) -> tuple[str, ...]:
    try:
        data = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return (f"Review Regression is unreadable: {exc}",)
    errors = list(validate_regression_data(data, schema_dir))
    validators = {
        "deterministic": (".slidethus/review/deterministic", deterministic_review_reference_errors),
        "semantic": (".slidethus/review/semantic/open-issue", semantic_review_reference_errors),
        "scorecard": (".slidethus/review/semantic/scorecard", semantic_scorecard_reference_errors),
        "visual": (".slidethus/review/visual", visual_review_reference_errors),
    }
    for ref in data.get("review_inputs", []):
        try:
            root, validator = validators[str(ref["review_type"])]
            report_path = _runtime_path(workspace, ref.get("path", ""), root)
            if sha256_file(report_path) != ref.get("sha256"):
                errors.append(f"Regression review input hash mismatch: {ref.get('path')}")
            errors.extend(validator(workspace, report_path, schema_dir))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Regression review input is invalid: {exc}")
    repair = data.get("repair")
    if isinstance(repair, dict):
        try:
            repair_path = _runtime_path(workspace, repair.get("path", ""), ".slidethus/review/repairs/reports")
            if sha256_file(repair_path) != repair.get("sha256"):
                errors.append("Regression repair report hash mismatch")
            errors.extend(repair_report_reference_errors(workspace, repair_path, schema_dir))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Regression repair report is invalid: {exc}")
    return tuple(errors)


def review_regression_workspace_errors(workspace: Path, schema_dir: Path) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/review/regression"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Review Regression directory"))
            continue
        for message in regression_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, message))
    return tuple(errors)
