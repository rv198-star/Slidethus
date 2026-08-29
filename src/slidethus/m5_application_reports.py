from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import M5ApplicationError, WorkspaceError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.quality_reviews import production_quality_reference_errors
from slidethus.schema_registry import SchemaRegistry


def m5_report_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def m5_report_id(data: dict[str, Any]) -> str:
    return "M5R-" + sha256_json(m5_report_identity_payload(data))[:16].upper()


def m5_report_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def _schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "m5_application_report.schema.json"
    if not path.is_file():
        raise M5ApplicationError(f"Missing M5 Application schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_m5_report_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != m5_report_id(data):
        errors.append("M5 Application Report identity mismatch")
    if data.get("config_hash") != f"sha256:{sha256_json(data.get('config', {}))}":
        errors.append("M5 Application config hash mismatch")
    action_ids = [str(item.get("action_id", "")) for item in data.get("actions", [])]
    expected = [f"M5A-{index:03d}" for index in range(1, len(action_ids) + 1)]
    if action_ids != expected:
        errors.append("M5 Application action IDs must be contiguous")
    capabilities = [str(item.get("capability", "")) for item in data.get("capabilities", [])]
    if capabilities != sorted(capabilities) or len(capabilities) != len(set(capabilities)):
        errors.append("M5 Application capabilities must be sorted and unique")
    if data.get("status") == "ready":
        if data.get("blockers"):
            errors.append("Ready M5 Application Report cannot contain blockers")
        if data.get("g8", {}).get("status") != "pass":
            errors.append("Ready M5 Application Report requires G8 pass")
        if data.get("final_phase") not in {"REVIEWED", "DELIVERY_READY", "COMPLETED"}:
            errors.append("Ready M5 Application Report requires REVIEWED or later")
        for key in ("deterministic", "semantic", "scorecard", "visual", "regression", "quality"):
            if data.get("reviews", {}).get(key) is None:
                errors.append(f"Ready M5 Application Report requires {key} review ref")
    elif not data.get("blockers"):
        errors.append("Blocked/failed M5 Application Report requires at least one blocker")
    return tuple(errors)


def _safe_runtime_file(workspace: Path, raw: str, admitted_root: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute():
        raise WorkspaceError(f"absolute runtime path is not allowed: {raw}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / admitted_root)
    if root != path and root not in path.parents:
        raise WorkspaceError(f"runtime path is outside {admitted_root}: {raw}")
    return path


def m5_report_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"M5 Application Report cannot be read: {exc}",)
    errors = list(validate_m5_report_data(report, schema_dir))
    if report_path.name != f"{m5_report_file_key(report)}.json":
        errors.append("M5 Application Report filename mismatch")
    state = read_json(workspace / "project_state.json")
    if report.get("project_id") != state.get("project_id"):
        errors.append("M5 Application project_id mismatch")
    revision = int(report.get("project_state", {}).get("revision", 0))
    current_revision = int(state.get("revision", 0))
    if revision == current_revision:
        bound_state = state
    else:
        path = workspace / ".slidethus/history/project_state" / f"{revision:06d}.json"
        bound_state = read_json(path) if path.is_file() else None
    if bound_state is None:
        errors.append(f"M5 Application Project State revision is missing: {revision}")
    else:
        if f"sha256:{sha256_json(bound_state)}" != report.get("project_state", {}).get("content_hash"):
            errors.append("M5 Application Project State hash mismatch")
        if bound_state.get("current_phase") != report.get("final_phase"):
            errors.append("M5 Application final_phase disagrees with bound Project State")

    roots = {
        "deterministic": ".slidethus/review/deterministic",
        "semantic": ".slidethus/review/semantic/open-issue",
        "scorecard": ".slidethus/review/semantic/scorecard",
        "visual": ".slidethus/review/visual",
        "repair_plan": ".slidethus/review/repairs/plans",
        "repair_report": ".slidethus/review/repairs/reports",
        "regression": ".slidethus/review/regression",
        "quality": ".slidethus/m5/quality",
    }
    for key, ref in report.get("reviews", {}).items():
        if ref is None:
            continue
        try:
            path = _safe_runtime_file(workspace, str(ref.get("path", "")), roots[key])
            if not path.is_file() or sha256_file(path) != ref.get("sha256"):
                errors.append(f"M5 Application review ref hash mismatch: {key}")
            elif key == "quality":
                quality = read_json(path)
                errors.extend(
                    f"Quality snapshot: {message}"
                    for message in production_quality_reference_errors(
                        workspace,
                        quality,
                        schema_dir,
                        require_current=(revision == current_revision),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"M5 Application review ref is invalid ({key}): {exc}")
    return tuple(errors)


def list_m5_application_reports(
    workspace: Path,
    *,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    root = workspace.resolve() / ".slidethus/m5/runs"
    if not root.exists():
        return ()
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    output: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        errors = m5_report_reference_errors(workspace.resolve(), path, admitted)
        if errors:
            raise M5ApplicationError(f"Invalid M5 Application Report {path.name}: " + "; ".join(errors))
        report = read_json(path)
        output.append(
            {
                "report_id": str(report["report_id"]),
                "status": str(report["status"]),
                "final_phase": str(report["final_phase"]),
                "path": path.relative_to(workspace).as_posix(),
            }
        )
    return tuple(output)


def inspect_m5_application_report(
    workspace: Path,
    report_id: str,
    *,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    root = workspace.resolve() / ".slidethus/m5/runs"
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    for path in sorted(root.glob("*.json")):
        report = read_json(path)
        if report.get("report_id") != report_id and path.stem != report_id:
            continue
        errors = m5_report_reference_errors(workspace.resolve(), path, admitted)
        if errors:
            raise M5ApplicationError("Invalid M5 Application Report: " + "; ".join(errors))
        return report
    raise M5ApplicationError(f"Unknown M5 Application Report: {report_id}")


def m5_application_workspace_errors(workspace: Path, schema_dir: Path) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/m5/runs"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in M5 Application directory"))
            continue
        for message in m5_report_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, message))
    return tuple(errors)
