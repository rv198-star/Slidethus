from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import ReviewSynthesisError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.stage_ai_reviews import (
    STAGES,
    stage_review_reference_errors,
)
from slidethus.workflow_application_reports import workflow_report_reference_errors

_STAGE_ORDER = {stage: index for index, stage in enumerate(STAGES)}
_SEVERITY_ORDER = {"suggestion": 0, "minor": 1, "major": 2, "critical": 3}
_OVERFIT_LOCATOR = re.compile(r"\b(?:S-[0-9]{3}|BLK-S[0-9]{3}-[0-9]{2}|REG-S[0-9]{3}-[0-9]{2})\b")


def synthesis_cluster_id(cluster: dict[str, Any]) -> str:
    payload = {
        "pattern_code": cluster.get("pattern_code"),
        "issue_ids": sorted(str(item) for item in cluster.get("issue_ids", [])),
        "root_phase": cluster.get("root_phase"),
        "classification": cluster.get("classification"),
    }
    return "SYS-" + sha256_json(payload)[:16].upper()


def synthesis_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def synthesis_report_id(data: dict[str, Any]) -> str:
    return "SYN-" + sha256_json(synthesis_identity_payload(data))[:16].upper()


def synthesis_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def synthesis_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "review_synthesis_report.schema.json"
    if not path.is_file():
        raise ReviewSynthesisError(f"Missing Review Synthesis schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def max_severity(issues: list[dict[str, Any]]) -> str:
    if not issues:
        raise ReviewSynthesisError("Synthesis cluster requires at least one issue")
    return max((str(item["severity"]) for item in issues), key=lambda value: _SEVERITY_ORDER[value])


def root_phase(issues: list[dict[str, Any]]) -> str:
    if not issues:
        raise ReviewSynthesisError("Synthesis cluster requires at least one issue")
    return min((str(item["earliest_phase"]) for item in issues), key=lambda value: _STAGE_ORDER[value])


def cluster_scope(issues: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "stages": sorted({str(item["observed_stage"]) for item in issues}, key=_STAGE_ORDER.__getitem__),
        "artifact_types": sorted(
            {str(item["artifact_type"]) for item in issues if item.get("artifact_type") is not None}
        ),
        "slide_ids": sorted(
            {str(item["slide_id"]) for item in issues if item.get("slide_id") is not None}
        ),
    }


def promotion_decision(
    classification: str,
    scenario_independent_statement: str,
    issues: list[dict[str, Any]],
) -> tuple[bool, str]:
    if classification != "systemic_candidate":
        return False, "Cluster is explicitly case-local after whole-attempt attribution."
    if _OVERFIT_LOCATOR.search(scenario_independent_statement):
        return False, "Systemic statement still contains case-local slide/block/region identifiers."
    severity = max_severity(issues)
    if severity in {"critical", "major"}:
        return True, f"{severity.title()} systemic capability/invariant failure is eligible for repair consideration."
    if severity == "suggestion":
        return False, "Suggestions are not promoted by default."
    scope = cluster_scope(issues)
    broad_scope = any(
        item.get("scope") in {"multi_slide", "cross_artifact", "cross_stage", "attempt_wide"}
        for item in issues
    )
    recurrent = (
        len(scope["slide_ids"]) >= 2
        or len(scope["artifact_types"]) >= 2
        or len(scope["stages"]) >= 2
        or (len(issues) >= 2 and broad_scope)
    )
    if recurrent:
        return True, "Minor issue recurs across a broader scope and is eligible for repair consideration."
    return False, "Minor issue lacks enough recurrence evidence for framework-level promotion."


def validate_synthesis_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(synthesis_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != synthesis_report_id(data):
        errors.append("Review Synthesis identity mismatch")
    review_keys = [
        (str(item.get("stage", "")), str(item.get("report_id", "")))
        for item in data.get("stage_reviews", [])
    ]
    expected_keys = sorted(review_keys, key=lambda item: (_STAGE_ORDER.get(item[0], 999), item[1]))
    if review_keys != expected_keys or len(review_keys) != len(set(review_keys)):
        errors.append("Review Synthesis stage_reviews must be unique and stage-sorted")
    cluster_ids = [str(item.get("cluster_id", "")) for item in data.get("clusters", [])]
    if len(cluster_ids) != len(set(cluster_ids)):
        errors.append("Review Synthesis contains duplicate cluster IDs")
    clustered: list[str] = []
    for cluster in data.get("clusters", []):
        if cluster.get("cluster_id") != synthesis_cluster_id(cluster):
            errors.append(f"Review Synthesis cluster identity mismatch: {cluster.get('cluster_id')}")
        issue_ids = list(cluster.get("issue_ids", []))
        if issue_ids != sorted(issue_ids):
            errors.append(f"Review Synthesis cluster issue_ids must be sorted: {cluster.get('cluster_id')}")
        clustered.extend(str(item) for item in issue_ids)
    if len(clustered) != len(set(clustered)):
        errors.append("Review Synthesis issue belongs to more than one cluster")
    unclustered = list(data.get("unclustered_issue_ids", []))
    if unclustered != sorted(unclustered):
        errors.append("Review Synthesis unclustered_issue_ids must be sorted")
    if set(clustered).intersection(unclustered):
        errors.append("Review Synthesis issue cannot be both clustered and unclustered")
    summary = data.get("summary", {})
    expected_summary = {
        "stage_review_count": len(data.get("stage_reviews", [])),
        "cluster_count": len(data.get("clusters", [])),
        "systemic_candidate_count": sum(
            item.get("classification") == "systemic_candidate" for item in data.get("clusters", [])
        ),
        "case_local_count": sum(
            item.get("classification") == "case_local" for item in data.get("clusters", [])
        ),
        "unclustered_count": len(unclustered),
    }
    for key, value in expected_summary.items():
        if int(summary.get(key, -1)) != value:
            errors.append(f"Review Synthesis {key} mismatch")
    capability = str(data.get("capability", {}).get("status", ""))
    expected_status = "blocked" if capability == "missing" else (
        "issues" if data.get("clusters") or unclustered else "pass"
    )
    if data.get("status") != expected_status:
        errors.append("Review Synthesis status disagrees with capability/findings")
    return tuple(errors)


def synthesis_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Review Synthesis is unreadable: {exc}",)
    errors.extend(validate_synthesis_data(report, schema_dir))
    if report_path.name != f"{synthesis_file_key(report)}.json":
        errors.append("Review Synthesis filename/content hash mismatch")
    issue_map: dict[str, dict[str, Any]] = {}
    workflow_id: str | None = None
    for ref in report.get("stage_reviews", []):
        try:
            relative = Path(str(ref.get("path", "")))
            if relative.is_absolute():
                raise ReviewSynthesisError("absolute Stage AI Review path is not allowed")
            path = ensure_within(workspace, workspace / relative)
            admitted = ensure_within(workspace, workspace / ".slidethus/review/stage-ai")
            if admitted != path and admitted not in path.parents:
                raise ReviewSynthesisError("Stage AI Review ref is outside admitted root")
            if sha256_file(path) != ref.get("sha256"):
                errors.append(f"Review Synthesis Stage AI Review hash mismatch: {relative.as_posix()}")
            stage_report = read_json(path)
            errors.extend(stage_review_reference_errors(workspace, path, schema_dir))
            if stage_report.get("report_id") != ref.get("report_id"):
                errors.append("Review Synthesis Stage AI Review identity mismatch")
            if stage_report.get("stage") != ref.get("stage") or stage_report.get("status") != ref.get("status"):
                errors.append("Review Synthesis Stage AI Review metadata mismatch")
            current_workflow_id = str(stage_report.get("workflow_report", {}).get("report_id", ""))
            workflow_id = workflow_id or current_workflow_id
            if current_workflow_id != workflow_id:
                errors.append("Review Synthesis mixes Stage AI Reviews from different attempts")
            for issue in stage_report.get("issues", []):
                issue_id = str(issue["issue_id"])
                if issue_id in issue_map:
                    errors.append(f"Review Synthesis duplicate Stage AI issue identity: {issue_id}")
                issue_map[issue_id] = issue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Review Synthesis Stage AI Review ref is invalid: {exc}")
    wref = report.get("workflow_report", {})
    try:
        relative = Path(str(wref.get("path", "")))
        if relative.is_absolute():
            raise ReviewSynthesisError("absolute workflow path is not allowed")
        workflow_path = ensure_within(workspace, workspace / relative)
        errors.extend(workflow_report_reference_errors(workspace, workflow_path, schema_dir))
        workflow = read_json(workflow_path)
        if sha256_file(workflow_path) != wref.get("sha256"):
            errors.append("Review Synthesis workflow hash mismatch")
        for key in ("report_id", "workflow", "status", "final_phase"):
            if workflow.get(key) != wref.get(key):
                errors.append(f"Review Synthesis workflow {key} mismatch")
        if workflow_id is not None and workflow.get("report_id") != workflow_id:
            errors.append("Review Synthesis workflow does not match Stage AI Reviews")
        if report.get("project_id") != workflow.get("project_id"):
            errors.append("Review Synthesis project_id mismatch")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Review Synthesis workflow ref is invalid: {exc}")
    known_ids = set(issue_map)
    clustered_ids = {
        str(issue_id)
        for cluster in report.get("clusters", [])
        for issue_id in cluster.get("issue_ids", [])
    }
    unclustered_ids = {str(item) for item in report.get("unclustered_issue_ids", [])}
    if clustered_ids | unclustered_ids != known_ids:
        errors.append("Review Synthesis does not cover every Stage AI issue exactly once")
    if int(report.get("summary", {}).get("issue_count", -1)) != len(known_ids):
        errors.append("Review Synthesis issue_count mismatch")
    for cluster in report.get("clusters", []):
        issues = [issue_map[str(item)] for item in cluster.get("issue_ids", []) if str(item) in issue_map]
        if len(issues) != len(cluster.get("issue_ids", [])):
            errors.append(f"Review Synthesis cluster references unknown issue: {cluster.get('cluster_id')}")
            continue
        expected_severity = max_severity(issues)
        earliest_admitted_root = root_phase(issues)
        expected_scope = cluster_scope(issues)
        expected_eligible, expected_reason = promotion_decision(
            str(cluster.get("classification", "")),
            str(cluster.get("scenario_independent_statement", "")),
            issues,
        )
        if cluster.get("max_severity") != expected_severity:
            errors.append(f"Review Synthesis cluster max_severity mismatch: {cluster.get('cluster_id')}")
        cluster_root = str(cluster.get("root_phase", ""))
        if (
            cluster_root not in _STAGE_ORDER
            or _STAGE_ORDER[cluster_root] > _STAGE_ORDER[earliest_admitted_root]
        ):
            errors.append(
                f"Review Synthesis cluster root_phase is later than admitted responsibility: {cluster.get('cluster_id')}"
            )
        if cluster.get("scope") != expected_scope:
            errors.append(f"Review Synthesis cluster scope mismatch: {cluster.get('cluster_id')}")
        if cluster.get("promotion_eligible") != expected_eligible:
            errors.append(f"Review Synthesis cluster promotion_eligible mismatch: {cluster.get('cluster_id')}")
        if cluster.get("promotion_reason") != expected_reason:
            errors.append(f"Review Synthesis cluster promotion_reason mismatch: {cluster.get('cluster_id')}")
    return tuple(errors)


def synthesis_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/review/synthesis"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Review Synthesis directory"))
            continue
        for message in synthesis_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, message))
    return tuple(errors)
