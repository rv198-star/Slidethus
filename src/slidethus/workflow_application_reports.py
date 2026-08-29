from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import WorkflowApplicationError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json

_WORKFLOW_POLICY = {
    "create": "create_workspace",
    "rebuild": "rebuild_workspace",
    "improve": "admitted_repair",
    "audit": "review_only",
    "revise": "target_scoped_change",
    "extract_style": "style_candidate",
}


def workflow_report_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def workflow_report_id(data: dict[str, Any]) -> str:
    return "WFR-" + sha256_json(workflow_report_identity_payload(data))[:16].upper()


def workflow_report_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def workflow_request_hash(payload: dict[str, Any]) -> str:
    return f"sha256:{sha256_json(payload)}"


def _schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "workflow_application_report.schema.json"
    if not path.is_file():
        raise WorkflowApplicationError(f"Missing Workflow Application schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def _artifact_map(values: list[dict[str, Any]]) -> dict[str, tuple[int, str]]:
    return {
        str(item["artifact_type"]): (int(item["version"]), str(item["content_hash"]))
        for item in values
    }


def validate_workflow_report_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != workflow_report_id(data):
        errors.append("Workflow Application Report identity mismatch")
    workflow = str(data.get("workflow", ""))
    if data.get("mutation_policy") != _WORKFLOW_POLICY.get(workflow):
        errors.append("Workflow mutation policy does not match workflow type")
    action_ids = [str(item.get("action_id", "")) for item in data.get("actions", [])]
    if action_ids != [f"WFA-{index:03d}" for index in range(1, len(action_ids) + 1)]:
        errors.append("Workflow action IDs must be contiguous")
    capabilities = [str(item.get("capability", "")) for item in data.get("capabilities", [])]
    if capabilities != sorted(capabilities) or len(capabilities) != len(set(capabilities)):
        errors.append("Workflow capabilities must be sorted and unique")
    for field in ("artifacts_before", "artifacts_after"):
        types = [str(item.get("artifact_type", "")) for item in data.get(field, [])]
        if types != sorted(types) or len(types) != len(set(types)):
            errors.append(f"Workflow {field} must be sorted and unique by artifact_type")
    before = _artifact_map(list(data.get("artifacts_before", [])))
    after = _artifact_map(list(data.get("artifacts_after", [])))
    expected_changed = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )
    if list(data.get("changed_artifacts", [])) != expected_changed:
        errors.append("Workflow changed_artifacts does not match before/after refs")
    if data.get("status") == "ready" and data.get("blockers"):
        errors.append("Ready Workflow Application Report cannot contain blockers")
    if data.get("status") in {"blocked", "failed"} and not data.get("blockers"):
        errors.append("Blocked/failed Workflow Application Report requires blockers")
    if workflow == "audit" and expected_changed:
        errors.append("Audit workflow cannot change frozen semantic/render artifact refs")
    return tuple(errors)


def _artifact_reference_errors(
    workspace: Path,
    state: dict[str, Any],
    reference: dict[str, Any],
) -> tuple[str, ...]:
    artifact_type = str(reference.get("artifact_type", ""))
    entry = next(
        (item for item in state.get("artifacts", []) if item.get("artifact_type") == artifact_type),
        None,
    )
    if entry is None:
        return (f"Workflow report references unregistered artifact: {artifact_type}",)
    version = int(reference.get("version", 0))
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        return (f"Workflow report references unknown {artifact_type} version {version}",)
    if not path.is_file():
        return (f"Workflow report artifact version is missing: {artifact_type} v{version}",)
    observed = f"sha256:{sha256_json(read_json(path))}"
    if observed != reference.get("content_hash"):
        return (f"Workflow report artifact hash mismatch: {artifact_type} v{version}",)
    return ()


def workflow_report_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Workflow Application Report cannot be read: {exc}",)
    errors.extend(validate_workflow_report_data(report, schema_dir))
    if report_path.name != f"{workflow_report_file_key(report)}.json":
        errors.append("Workflow Application Report filename/content hash mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if report.get("project_id") != state.get("project_id"):
        errors.append("Workflow Application project_id mismatch")
    for reference in [*report.get("artifacts_before", []), *report.get("artifacts_after", [])]:
        errors.extend(_artifact_reference_errors(workspace, state, reference))
    for output in report.get("outputs", []):
        try:
            relative = Path(str(output.get("path", "")))
            if relative.is_absolute():
                raise WorkflowApplicationError("absolute output ref is not allowed")
            path = ensure_within(workspace, workspace / relative)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Workflow output ref is unsafe: {exc}")
            continue
        if not path.is_file():
            errors.append(f"Workflow output ref is missing: {relative.as_posix()}")
        elif sha256_file(path) != output.get("sha256"):
            errors.append(f"Workflow output ref hash mismatch: {relative.as_posix()}")
    return tuple(errors)


def list_workflow_application_reports(
    workspace: Path,
    *,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    workspace = workspace.resolve()
    root = workspace / ".slidethus/workflows/runs"
    if not root.exists():
        return ()
    admitted = (schema_dir or Path(__file__).resolve().parent / "_schemas").resolve()
    output: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        errors = workflow_report_reference_errors(workspace, path, admitted)
        if errors:
            raise WorkflowApplicationError(
                f"Invalid Workflow Application Report {path.name}: " + "; ".join(errors)
            )
        report = read_json(path)
        output.append(
            {
                "report_id": str(report["report_id"]),
                "workflow": str(report["workflow"]),
                "status": str(report["status"]),
                "final_phase": str(report["final_phase"]),
                "path": path.relative_to(workspace).as_posix(),
            }
        )
    return tuple(output)


def inspect_workflow_application_report(
    workspace: Path,
    report_id: str,
    *,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    root = workspace / ".slidethus/workflows/runs"
    admitted = (schema_dir or Path(__file__).resolve().parent / "_schemas").resolve()
    for path in sorted(root.glob("*.json")):
        report = read_json(path)
        if report.get("report_id") != report_id and path.stem != report_id:
            continue
        errors = workflow_report_reference_errors(workspace, path, admitted)
        if errors:
            raise WorkflowApplicationError(
                "Invalid Workflow Application Report: " + "; ".join(errors)
            )
        return report
    raise WorkflowApplicationError(f"Unknown Workflow Application Report: {report_id}")


def workflow_application_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/workflows/runs"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Workflow Application run directory"))
            continue
        for message in workflow_report_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, message))
    return tuple(errors)
