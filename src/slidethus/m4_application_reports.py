from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import RenderManifestError, WorkspaceError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.render_manifest import validate_render_manifest_data
from slidethus.render_preflight import validate_render_preflight_data
from slidethus.schema_registry import SchemaRegistry


def m4_report_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def m4_report_id(data: dict[str, Any]) -> str:
    return "M4R-" + sha256_json(m4_report_identity_payload(data))[:16].upper()


def m4_report_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def m4_finding_id(kind: str, code: str, message: str) -> str:
    prefix = {"blocker": "M4B", "warning": "M4W"}.get(kind)
    if prefix is None:
        raise RenderManifestError(f"Unknown M4 finding kind: {kind}")
    return f"{prefix}-" + sha256_json({"code": code, "message": message})[:16].upper()


def _schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "m4_application_report.schema.json"
    if not path.is_file():
        raise RenderManifestError(f"Missing M4 Application Report schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_m4_report_data(
    data: dict[str, Any],
    schema_dir: Path | None = None,
) -> tuple[str, ...]:
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(admitted)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != m4_report_id(data):
        errors.append("M4 Application Report identity mismatch")
    if data.get("config_hash") != f"sha256:{sha256_json(data.get('config', {}))}":
        errors.append("M4 Application config hash mismatch")
    backends = list(data.get("config", {}).get("backends", []))
    if backends != sorted(backends):
        errors.append("M4 Application backends must be sorted")
    capabilities = [str(item.get("capability", "")) for item in data.get("capabilities", [])]
    if capabilities != sorted(capabilities) or len(capabilities) != len(set(capabilities)):
        errors.append("M4 Application capabilities must be sorted and unique")
    action_ids = [str(item.get("action_id", "")) for item in data.get("actions", [])]
    expected_actions = [f"M4A-{index:03d}" for index in range(1, len(action_ids) + 1)]
    if action_ids != expected_actions:
        errors.append("M4 action IDs must be contiguous from M4A-001")
    for kind, field in (("blocker", "blockers"), ("warning", "warnings")):
        ids = [str(item.get("finding_id", "")) for item in data.get(field, [])]
        if len(ids) != len(set(ids)):
            errors.append(f"M4 Application contains duplicate {kind} IDs")
        for item in data.get(field, []):
            expected = m4_finding_id(
                kind,
                str(item.get("code", "")),
                str(item.get("message", "")),
            )
            if item.get("finding_id") != expected:
                errors.append(f"M4 {kind} identity mismatch: {item.get('finding_id')}")
    output_paths = [str(item.get("path", "")) for item in data.get("outputs", [])]
    if len(output_paths) != len(set(output_paths)):
        errors.append("M4 Application contains duplicate output paths")

    status = data.get("status")
    blockers = data.get("blockers", [])
    if status == "ready":
        if blockers:
            errors.append("Ready M4 Application Report cannot contain blockers")
        if data.get("preflight") is None or data.get("preflight", {}).get("status") != "pass":
            errors.append("Ready M4 Application Report requires passing preflight")
        if data.get("render_manifest") is None:
            errors.append("Ready M4 Application Report requires a Render Manifest")
        if data.get("g7", {}).get("status") != "pass":
            errors.append("Ready M4 Application Report requires G7 pass")
        if data.get("final_phase") not in {
            "DRAFT_RENDERED",
            "REVIEWED",
            "DELIVERY_READY",
            "COMPLETED",
        }:
            errors.append("Ready M4 Application Report requires DRAFT_RENDERED or later")
    elif not blockers:
        errors.append("Blocked/failed M4 Application Report requires at least one blocker")
    return tuple(errors)


def _artifact_version(
    workspace: Path,
    state: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    artifact_type = str(reference["artifact_type"])
    version = int(reference["version"])
    entry = next(
        (item for item in state.get("artifacts", []) if item.get("artifact_type") == artifact_type),
        None,
    )
    if entry is None:
        raise RenderManifestError(f"M4 report references unregistered artifact: {artifact_type}")
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise RenderManifestError(
            f"M4 report references unknown {artifact_type} version: {version}"
        )
    if not path.is_file():
        raise RenderManifestError(f"M4 report artifact version is missing: {path}")
    data = read_json(path)
    if f"sha256:{sha256_json(data)}" != reference.get("content_hash"):
        raise RenderManifestError(
            f"M4 report artifact content hash mismatch: {artifact_type} v{version}"
        )
    return data


def _state_revision(workspace: Path, current: dict[str, Any], revision: int) -> dict[str, Any]:
    current_revision = int(current.get("revision", 0))
    if revision == current_revision:
        return copy.deepcopy(current)
    if 1 <= revision < current_revision:
        path = workspace / ".slidethus/history/project_state" / f"{revision:06d}.json"
        if path.is_file():
            return read_json(path)
    raise RenderManifestError(f"M4 report Project State revision is missing: {revision}")


def _safe_runtime_file(workspace: Path, raw_path: str, root_name: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute():
        raise WorkspaceError(f"absolute runtime path is not allowed: {raw_path}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / root_name)
    if root not in path.parents:
        raise WorkspaceError(f"runtime path is outside {root_name}: {raw_path}")
    return path


def m4_report_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"M4 Application Report cannot be read: {exc}",)
    errors.extend(validate_m4_report_data(report, schema_dir))
    if report_path.name != f"{m4_report_file_key(report)}.json":
        errors.append("M4 Application Report filename mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    current_state = read_json(state_path)
    if report.get("project_id") != current_state.get("project_id"):
        errors.append("M4 Application Report project_id mismatch")
    try:
        bound_state = _state_revision(
            workspace,
            current_state,
            int(report.get("project_state", {}).get("revision", 0)),
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        bound_state = None
    if bound_state is not None:
        if f"sha256:{sha256_json(bound_state)}" != report.get("project_state", {}).get(
            "content_hash"
        ):
            errors.append("M4 Application Report Project State hash mismatch")
        if bound_state.get("current_phase") != report.get("final_phase"):
            errors.append("M4 Application Report final_phase disagrees with Project State")
        g7 = next(
            (
                item
                for item in bound_state.get("completed_gates", [])
                if item.get("gate_id") == "G7"
            ),
            None,
        )
        if report.get("g7", {}).get("status") == "pass" and (
            g7 is None or g7.get("status") not in {"pass", "waived"}
        ):
            errors.append("M4 Application Report G7 pass is absent from Project State")

    manifest_ref = report.get("render_manifest")
    manifest: dict[str, Any] | None = None
    if manifest_ref is not None:
        try:
            manifest = _artifact_version(workspace, current_state, manifest_ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        else:
            errors.extend(
                f"Render Manifest: {item}"
                for item in validate_render_manifest_data(manifest, schema_dir)
            )
            expected_outputs = [
                {
                    "path": str(item["path"]),
                    "sha256": str(item["sha256"]),
                    "role": str(item.get("role", "")),
                    "backend": item.get("backend"),
                }
                for item in manifest.get("outputs", [])
            ]
            if report.get("outputs") != expected_outputs:
                errors.append("M4 Application outputs disagree with bound Render Manifest")

    preflight_ref = report.get("preflight")
    if preflight_ref is not None:
        try:
            path = _safe_runtime_file(
                workspace,
                str(preflight_ref.get("path", "")),
                ".slidethus/render/preflight",
            )
        except (OSError, ValueError, WorkspaceError) as exc:
            errors.append(f"M4 preflight path is unsafe: {exc}")
        else:
            if not path.is_file():
                errors.append("M4 preflight is missing")
            elif sha256_file(path) != preflight_ref.get("sha256"):
                errors.append("M4 preflight hash mismatch")
            else:
                preflight = read_json(path)
                if preflight.get("preflight_id") != preflight_ref.get("preflight_id"):
                    errors.append("M4 preflight identity mismatch")
                errors.extend(
                    f"Render Preflight: {item}"
                    for item in validate_render_preflight_data(preflight, schema_dir)
                )
    for output in report.get("outputs", []):
        try:
            path = _safe_runtime_file(workspace, str(output.get("path", "")), "outputs")
        except (OSError, ValueError, WorkspaceError) as exc:
            errors.append(f"M4 output path is unsafe: {exc}")
            continue
        if not path.is_file():
            errors.append(f"M4 output is missing: {output.get('path')}")
        elif sha256_file(path) != output.get("sha256"):
            errors.append(f"M4 output hash mismatch: {output.get('path')}")
    return tuple(errors)


def list_m4_application_reports(
    workspace: Path,
    *,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    workspace = workspace.resolve()
    root = workspace / ".slidethus/m4/runs"
    if not root.exists():
        return ()
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    output: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        errors = m4_report_reference_errors(workspace, path, admitted)
        if errors:
            raise RenderManifestError(
                f"Invalid M4 Application Report {path.name}: " + "; ".join(errors)
            )
        report = read_json(path)
        output.append(
            {
                "report_id": report["report_id"],
                "status": report["status"],
                "generated_at": report["generated_at"],
                "final_phase": report["final_phase"],
                "path": path.relative_to(workspace).as_posix(),
            }
        )
    output.sort(key=lambda item: (item["generated_at"], item["report_id"]))
    return tuple(output)


def inspect_m4_application_report(
    workspace: Path,
    report_id: str,
    *,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    for path in sorted((workspace / ".slidethus/m4/runs").glob("*.json")):
        report = read_json(path)
        if report.get("report_id") != report_id and path.stem != report_id:
            continue
        errors = m4_report_reference_errors(workspace, path, admitted)
        if errors:
            raise RenderManifestError("Invalid M4 Application Report: " + "; ".join(errors))
        return report
    raise RenderManifestError(f"Unknown M4 Application Report: {report_id}")


def m4_application_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/m4/runs"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in M4 Application directory"))
            continue
        for error in m4_report_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
