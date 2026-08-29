from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import SemanticReviewError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json

_PHASE_ORDER = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
    "P4": 4,
    "P5A": 5,
    "P5B": 6,
    "P8": 7,
}
_PHASE_TARGETS = {
    "P0": "CREATED",
    "P1": "BRIEF_READY",
    "P2": "SOURCES_READY",
    "P3": "EVIDENCE_READY",
    "P4": "NARRATIVE_READY",
    "P5A": "OUTLINE_READY",
    "P5B": "SLIDE_SPECS_READY",
    "P8": "DRAFT_RENDERED",
}
SEMANTIC_DIMENSIONS = (
    "purpose_fit",
    "audience_fit",
    "factual_integrity",
    "narrative_coherence",
    "slide_clarity",
    "evidence_sufficiency",
    "presentation_usability",
)


def semantic_issue_id(issue: dict[str, Any]) -> str:
    payload = {
        "code": issue.get("code"),
        "artifact_type": issue.get("artifact_type"),
        "slide_id": issue.get("slide_id"),
        "block_id": issue.get("block_id"),
        "region_id": issue.get("region_id"),
        "earliest_phase": issue.get("earliest_phase"),
    }
    return "SRI-" + sha256_json(payload)[:16].upper()


def semantic_review_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def semantic_review_id(data: dict[str, Any]) -> str:
    return "SVR-" + sha256_json(semantic_review_identity_payload(data))[:16].upper()


def semantic_scorecard_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def semantic_scorecard_id(data: dict[str, Any]) -> str:
    return "SCR-" + sha256_json(semantic_scorecard_identity_payload(data))[:16].upper()


def report_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def _schema(schema_dir: Path, name: str) -> dict[str, Any]:
    path = schema_dir / name
    if not path.is_file():
        raise SemanticReviewError(f"Missing M5 semantic review schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def target_phase_for_issues(issues: list[dict[str, Any]]) -> str | None:
    blocking = [
        item
        for item in issues
        if item.get("status") == "open" and item.get("severity") in {"critical", "major"}
    ]
    if not blocking:
        return None
    earliest = min(
        (str(item["earliest_phase"]) for item in blocking),
        key=lambda phase: _PHASE_ORDER[phase],
    )
    return _PHASE_TARGETS[earliest]


def validate_semantic_review_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir, "semantic_review_report.schema.json")).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != semantic_review_id(data):
        errors.append("Semantic Review identity mismatch")
    issue_ids = [str(item.get("issue_id", "")) for item in data.get("issues", [])]
    if len(issue_ids) != len(set(issue_ids)):
        errors.append("Semantic Review contains duplicate issue IDs")
    for issue in data.get("issues", []):
        if issue.get("issue_id") != semantic_issue_id(issue):
            errors.append(f"Semantic issue identity mismatch: {issue.get('issue_id')}")
    inputs = [str(item.get("artifact_type", "")) for item in data.get("inputs", [])]
    if inputs != sorted(inputs) or len(inputs) != len(set(inputs)):
        errors.append("Semantic Review inputs must be unique and sorted by artifact_type")
    open_issues = [item for item in data.get("issues", []) if item.get("status") == "open"]
    summary = data.get("summary", {})
    expected = {
        "critical_count": sum(item.get("severity") == "critical" for item in open_issues),
        "major_count": sum(item.get("severity") == "major" for item in open_issues),
        "minor_count": sum(item.get("severity") == "minor" for item in open_issues),
        "open_count": len(open_issues),
    }
    for key, value in expected.items():
        if int(summary.get(key, -1)) != value:
            errors.append(f"Semantic Review {key} mismatch")
    capability = data.get("capability", {}).get("status")
    expected_status = "blocked" if capability == "missing" else ("issues" if open_issues else "pass")
    if data.get("status") != expected_status:
        errors.append("Semantic Review status disagrees with capability/issues")
    expected_target = target_phase_for_issues(open_issues) if capability == "available" else None
    if data.get("target_phase") != expected_target:
        errors.append("Semantic Review target_phase mismatch")
    return tuple(errors)


def validate_semantic_scorecard_data(
    data: dict[str, Any],
    schema_dir: Path,
    source_review: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir, "semantic_scorecard_report.schema.json")).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != semantic_scorecard_id(data):
        errors.append("Semantic Scorecard identity mismatch")
    dimensions = [str(item.get("dimension", "")) for item in data.get("dimensions", [])]
    if tuple(sorted(dimensions)) != tuple(sorted(SEMANTIC_DIMENSIONS)):
        errors.append("Semantic Scorecard must contain each required dimension exactly once")
    capability_available = data.get("capability", {}).get("status") == "available"
    if source_review is not None:
        known = {str(item["issue_id"]): item for item in source_review.get("issues", [])}
        for dimension in data.get("dimensions", []):
            refs = set(str(item) for item in dimension.get("issue_ids", []))
            if not refs.issubset(known):
                errors.append(f"Semantic Scorecard references unknown issue: {dimension.get('dimension')}")
            if capability_available and int(dimension.get("score", 0)) < 3 and not refs:
                errors.append(
                    f"Semantic Scorecard low score lacks an explicit Round A issue: {dimension.get('dimension')}"
                )
        blockers = [
            item for item in source_review.get("issues", [])
            if item.get("status") == "open" and item.get("severity") in {"critical", "major"}
        ]
        expected_blocking = len(blockers)
    else:
        expected_blocking = int(data.get("summary", {}).get("blocking_count", 0))
    scores = [int(item.get("score", 0)) for item in data.get("dimensions", [])]
    expected_overall = round(sum(scores) / len(scores), 2) if scores else 0.0
    expected_minimum = min(scores) if scores else 0
    summary = data.get("summary", {})
    if float(summary.get("overall_score", -1)) != expected_overall:
        errors.append("Semantic Scorecard overall_score mismatch")
    if int(summary.get("minimum_score", -1)) != expected_minimum:
        errors.append("Semantic Scorecard minimum_score mismatch")
    if int(summary.get("blocking_count", -1)) != expected_blocking:
        errors.append("Semantic Scorecard blocking_count mismatch")
    capability = data.get("capability", {}).get("status")
    expected_status = "blocked" if capability == "missing" else ("issues" if expected_blocking else "pass")
    if data.get("status") != expected_status:
        errors.append("Semantic Scorecard status disagrees with blocking issues/capability")
    return tuple(errors)


def _historical_artifact_path(workspace: Path, state: dict[str, Any], ref: dict[str, Any]) -> Path:
    artifact_type = str(ref["artifact_type"])
    entry = next(
        (item for item in state.get("artifacts", []) if item.get("artifact_type") == artifact_type),
        None,
    )
    if entry is None:
        raise SemanticReviewError(f"Semantic Review references unknown artifact: {artifact_type}")
    version = int(ref["version"])
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise SemanticReviewError(f"Semantic Review references unknown {artifact_type} version {version}")
    return ensure_within(workspace, path)


def semantic_review_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        data = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Semantic Review is unreadable: {exc}",)
    errors.extend(validate_semantic_review_data(data, schema_dir))
    state = read_json(workspace / "project_state.json")
    for ref in data.get("inputs", []):
        try:
            path = _historical_artifact_path(workspace, state, ref)
            observed = read_json(path)
            if f"sha256:{sha256_json(observed)}" != ref.get("content_hash"):
                errors.append(f"Semantic Review artifact hash mismatch: {ref.get('artifact_type')}")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    dref = data.get("deterministic_review", {})
    try:
        relative = Path(str(dref.get("path", "")))
        path = ensure_within(workspace, workspace / relative)
        admitted = ensure_within(workspace, workspace / ".slidethus/review/deterministic")
        if admitted != path and admitted not in path.parents:
            raise SemanticReviewError("Semantic Review deterministic input is outside admitted root")
        deterministic = read_json(path)
        if sha256_file(path) != dref.get("sha256"):
            errors.append("Semantic Review deterministic report hash mismatch")
        if deterministic.get("review_id") != dref.get("review_id"):
            errors.append("Semantic Review deterministic report identity mismatch")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Semantic Review deterministic input is invalid: {exc}")
    return tuple(errors)


def semantic_scorecard_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    try:
        data = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Semantic Scorecard is unreadable: {exc}",)
    source_ref = data.get("source_review", {})
    try:
        relative = Path(str(source_ref.get("path", "")))
        source_path = ensure_within(workspace, workspace / relative)
        admitted = ensure_within(workspace, workspace / ".slidethus/review/semantic/open-issue")
        if admitted != source_path and admitted not in source_path.parents:
            raise SemanticReviewError("Semantic Scorecard source review is outside admitted root")
        source = read_json(source_path)
        errors = list(validate_semantic_scorecard_data(data, schema_dir, source))
        if sha256_file(source_path) != source_ref.get("sha256"):
            errors.append("Semantic Scorecard source review hash mismatch")
        if source.get("report_id") != source_ref.get("report_id"):
            errors.append("Semantic Scorecard source review identity mismatch")
        return tuple(errors)
    except Exception as exc:  # noqa: BLE001
        return tuple([*validate_semantic_scorecard_data(data, schema_dir), f"Semantic Scorecard source review is invalid: {exc}"])


def semantic_review_workspace_errors(workspace: Path, schema_dir: Path) -> tuple[tuple[str, str], ...]:
    errors: list[tuple[str, str]] = []
    roots = (
        (workspace / ".slidethus/review/semantic/open-issue", semantic_review_reference_errors),
        (workspace / ".slidethus/review/semantic/scorecard", semantic_scorecard_reference_errors),
    )
    for root, validator in roots:
        if not root.exists():
            continue
        for entry in sorted(root.iterdir()):
            relative = entry.relative_to(workspace).as_posix()
            if not entry.is_file() or entry.suffix != ".json":
                errors.append((relative, "unexpected entry in Semantic Review directory"))
                continue
            for message in validator(workspace, entry, schema_dir):
                errors.append((relative, message))
    return tuple(errors)
