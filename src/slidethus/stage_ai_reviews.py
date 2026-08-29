from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import StageReviewError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.workflow_application_reports import workflow_report_reference_errors

STAGES = ("P0", "P1", "P2", "P3", "P4", "P5A", "P5B", "P6", "P7")
_STAGE_ORDER = {stage: index for index, stage in enumerate(STAGES)}
STAGE_FOCUS_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "P0": ("project_brief",),
    "P1": ("source_ledger",),
    "P2": ("evidence_ledger",),
    "P3": ("narrative_blueprint",),
    "P4": ("deck_outline",),
    "P5A": ("slide_specs",),
    "P5B": ("layout_plans",),
    "P6": ("visual_system", "asset_manifest"),
    "P7": ("render_manifest",),
}
_APPLICATION_OUTPUT_KINDS = {
    "m3_application",
    "m4_application",
    "m5_application",
    "m5_audit",
    "m5_improve",
}


def stage_issue_id(issue: dict[str, Any]) -> str:
    payload = {
        "code": issue.get("code"),
        "observed_stage": issue.get("observed_stage"),
        "earliest_phase": issue.get("earliest_phase"),
        "artifact_type": issue.get("artifact_type"),
        "slide_id": issue.get("slide_id"),
        "block_id": issue.get("block_id"),
        "region_id": issue.get("region_id"),
        "scope": issue.get("scope"),
    }
    return "SAI-" + sha256_json(payload)[:16].upper()


def stage_review_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def stage_review_id(data: dict[str, Any]) -> str:
    return "SAR-" + sha256_json(stage_review_identity_payload(data))[:16].upper()


def stage_review_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def stage_review_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "stage_ai_review_report.schema.json"
    if not path.is_file():
        raise StageReviewError(f"Missing Stage AI Review schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def workflow_report_ref(workspace: Path, path: Path, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": str(report["report_id"]),
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "workflow": str(report["workflow"]),
        "status": str(report["status"]),
        "final_phase": str(report["final_phase"]),
    }


def application_output_refs(workspace: Path, workflow_report: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for output in workflow_report.get("outputs", []):
        kind = str(output.get("kind", ""))
        if kind not in _APPLICATION_OUTPUT_KINDS:
            continue
        relative = Path(str(output.get("path", "")))
        if relative.is_absolute():
            raise StageReviewError(f"Application output path is absolute: {relative}")
        path = ensure_within(workspace, workspace / relative)
        if not path.is_file():
            raise StageReviewError(f"Application output is missing: {relative.as_posix()}")
        if sha256_file(path) != output.get("sha256"):
            raise StageReviewError(f"Application output hash mismatch: {relative.as_posix()}")
        data = read_json(path)
        refs.append(
            {
                "kind": kind,
                "ref_id": str(output["ref_id"]),
                "path": relative.as_posix(),
                "sha256": str(output["sha256"]),
                "status": str(data.get("status", "unknown")),
            }
        )
    return sorted(refs, key=lambda item: (item["kind"], item["ref_id"], item["path"]))


def derive_failure_facts(workspace: Path, workflow_report: dict[str, Any]) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    for blocker in workflow_report.get("blockers", []):
        facts.append(
            {
                "source": "workflow",
                "code": str(blocker.get("code", "workflow_blocker")),
                "message": " ".join(str(blocker.get("message", "")).split()),
            }
        )
    for ref in application_output_refs(workspace, workflow_report):
        data = read_json(workspace / ref["path"])
        for blocker in data.get("blockers", []):
            code = str(blocker.get("code") or blocker.get("finding_id") or "application_blocker")
            code = "".join(char if char.isalnum() or char == "_" else "_" for char in code.lower())
            message = " ".join(str(blocker.get("message", "")).split())
            if message:
                facts.append({"source": str(ref["kind"]), "code": code, "message": message})
    unique = {(item["source"], item["code"], item["message"]): item for item in facts}
    return sorted(unique.values(), key=lambda item: (item["source"], item["code"], item["message"]))


def stage_is_applicable(stage: str, workflow_report: dict[str, Any]) -> bool:
    if stage not in STAGE_FOCUS_ARTIFACTS:
        raise StageReviewError(f"Unsupported Stage AI Review stage: {stage}")
    present = {str(item.get("artifact_type", "")) for item in workflow_report.get("artifacts_after", [])}
    if stage == "P6":
        return "visual_system" in present or any(
            str(item.get("kind", "")) == "m4_application"
            for item in workflow_report.get("outputs", [])
        )
    if stage == "P7":
        return "render_manifest" in present or any(
            str(item.get("kind", "")) == "m4_application"
            for item in workflow_report.get("outputs", [])
        )
    return bool(present.intersection(STAGE_FOCUS_ARTIFACTS[stage]))


def validate_stage_review_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(stage_review_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != stage_review_id(data):
        errors.append("Stage AI Review identity mismatch")
    stage = str(data.get("stage", ""))
    inputs = [str(item.get("artifact_type", "")) for item in data.get("inputs", [])]
    if inputs != sorted(inputs) or len(inputs) != len(set(inputs)):
        errors.append("Stage AI Review inputs must be unique and sorted by artifact_type")
    runtime_keys = [
        (str(item.get("kind", "")), str(item.get("ref_id", "")), str(item.get("path", "")))
        for item in data.get("application_outputs", [])
    ]
    if runtime_keys != sorted(runtime_keys) or len(runtime_keys) != len(set(runtime_keys)):
        errors.append("Stage AI Review application_outputs must be unique and sorted")
    issue_ids = [str(item.get("issue_id", "")) for item in data.get("issues", [])]
    if len(issue_ids) != len(set(issue_ids)):
        errors.append("Stage AI Review contains duplicate issue IDs")
    known_artifacts = set(inputs)
    for issue in data.get("issues", []):
        if issue.get("issue_id") != stage_issue_id(issue):
            errors.append(f"Stage AI issue identity mismatch: {issue.get('issue_id')}")
        if issue.get("observed_stage") != stage:
            errors.append(f"Stage AI issue observed_stage mismatch: {issue.get('issue_id')}")
        earliest = str(issue.get("earliest_phase", ""))
        if earliest in _STAGE_ORDER and stage in _STAGE_ORDER and _STAGE_ORDER[earliest] > _STAGE_ORDER[stage]:
            errors.append(f"Stage AI issue routes later than observed stage: {issue.get('issue_id')}")
        artifact_type = issue.get("artifact_type")
        if artifact_type is not None and str(artifact_type) not in known_artifacts:
            errors.append(f"Stage AI issue references unbound artifact: {artifact_type}")
    issues = [item for item in data.get("issues", []) if item.get("status") == "open"]
    summary = data.get("summary", {})
    expected = {
        "critical_count": sum(item.get("severity") == "critical" for item in issues),
        "major_count": sum(item.get("severity") == "major" for item in issues),
        "minor_count": sum(item.get("severity") == "minor" for item in issues),
        "suggestion_count": sum(item.get("severity") == "suggestion" for item in issues),
        "open_count": len(issues),
    }
    for key, value in expected.items():
        if int(summary.get(key, -1)) != value:
            errors.append(f"Stage AI Review {key} mismatch")
    capability = str(data.get("capability", {}).get("status", ""))
    expected_status = {
        "missing": "blocked",
        "not_applicable": "not_applicable",
        "available": "issues" if issues else "pass",
    }.get(capability)
    if data.get("status") != expected_status:
        errors.append("Stage AI Review status disagrees with capability/issues")
    if capability != "available" and issues:
        errors.append("Unavailable Stage AI Review cannot contain issues")
    return tuple(errors)


def _find_workflow_path(workspace: Path, report_id: str) -> Path:
    root = workspace / ".slidethus/workflows/runs"
    for path in sorted(root.glob("*.json")):
        try:
            report = read_json(path)
        except Exception:
            continue
        if report.get("report_id") == report_id:
            return path
    raise StageReviewError(f"Unknown Workflow Application Report: {report_id}")


def stage_review_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Stage AI Review is unreadable: {exc}",)
    errors.extend(validate_stage_review_data(report, schema_dir))
    if report_path.name != f"{stage_review_file_key(report)}.json":
        errors.append("Stage AI Review filename/content hash mismatch")
    try:
        wref = report.get("workflow_report", {})
        workflow_path = _find_workflow_path(workspace, str(wref.get("report_id", "")))
        relative = workflow_path.relative_to(workspace).as_posix()
        if relative != wref.get("path"):
            errors.append("Stage AI Review workflow path mismatch")
        if sha256_file(workflow_path) != wref.get("sha256"):
            errors.append("Stage AI Review workflow hash mismatch")
        workflow = read_json(workflow_path)
        errors.extend(workflow_report_reference_errors(workspace, workflow_path, schema_dir))
        for key in ("report_id", "workflow", "status", "final_phase"):
            if workflow.get(key) != wref.get(key):
                errors.append(f"Stage AI Review workflow {key} mismatch")
        if report.get("project_id") != workflow.get("project_id"):
            errors.append("Stage AI Review project_id mismatch")
        after = {str(item["artifact_type"]): item for item in workflow.get("artifacts_after", [])}
        for ref in report.get("inputs", []):
            expected = after.get(str(ref.get("artifact_type", "")))
            if expected != ref:
                errors.append(f"Stage AI Review input does not match attempt snapshot: {ref.get('artifact_type')}")
        expected_outputs = application_output_refs(workspace, workflow)
        if report.get("application_outputs") != expected_outputs:
            errors.append("Stage AI Review application_outputs mismatch")
        expected_failures = derive_failure_facts(workspace, workflow)
        if report.get("failure_facts") != expected_failures:
            errors.append("Stage AI Review failure_facts mismatch")
        applicable = stage_is_applicable(str(report.get("stage", "")), workflow)
        capability = str(report.get("capability", {}).get("status", ""))
        if not applicable and capability != "not_applicable":
            errors.append("Stage AI Review applicability mismatch")
        if applicable and capability == "not_applicable":
            errors.append("Applicable Stage AI Review cannot be marked not_applicable")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Stage AI Review workflow reference is invalid: {exc}")
    return tuple(errors)


def stage_review_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/review/stage-ai"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.rglob("*")):
        if entry.is_dir():
            continue
        relative = entry.relative_to(workspace).as_posix()
        if entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Stage AI Review directory"))
            continue
        for message in stage_review_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, message))
    return tuple(errors)
