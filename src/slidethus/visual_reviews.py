from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.deterministic_reviews import deterministic_review_reference_errors
from slidethus.errors import VisualReviewError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.semantic_reviews import (
    semantic_review_reference_errors,
    semantic_scorecard_reference_errors,
)

_PHASE_ORDER = {phase: index for index, phase in enumerate(("P5A", "P5B", "P6", "P7"))}
_PHASE_TARGETS = {
    "P5A": "OUTLINE_READY",
    "P5B": "SLIDE_SPECS_READY",
    "P6": "LAYOUT_READY",
    "P7": "VISUAL_SYSTEM_READY",
}


def visual_issue_id(issue: dict[str, Any]) -> str:
    payload = {
        "code": issue.get("code"),
        "slide_id": issue.get("slide_id"),
        "related_slide_ids": sorted(str(item) for item in issue.get("related_slide_ids", [])),
        "region_id": issue.get("region_id"),
        "earliest_phase": issue.get("earliest_phase"),
    }
    return "VRI-" + sha256_json(payload)[:16].upper()


def visual_review_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def visual_review_id(data: dict[str, Any]) -> str:
    return "VVR-" + sha256_json(visual_review_identity_payload(data))[:16].upper()


def visual_review_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def visual_review_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "visual_review_report.schema.json"
    if not path.is_file():
        raise VisualReviewError(f"Missing Visual Review schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def target_phase_for_visual_issues(issues: list[dict[str, Any]]) -> str | None:
    blocking = [
        item for item in issues
        if item.get("status") == "open" and item.get("severity") in {"critical", "major"}
    ]
    if not blocking:
        return None
    earliest = min(
        (str(item["earliest_phase"]) for item in blocking),
        key=lambda phase: _PHASE_ORDER[phase],
    )
    return _PHASE_TARGETS[earliest]


def validate_visual_review_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(visual_review_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != visual_review_id(data):
        errors.append("Visual Review identity mismatch")
    issue_ids = [str(item.get("issue_id", "")) for item in data.get("issues", [])]
    if len(issue_ids) != len(set(issue_ids)):
        errors.append("Visual Review contains duplicate issue IDs")
    for issue in data.get("issues", []):
        if issue.get("issue_id") != visual_issue_id(issue):
            errors.append(f"Visual issue identity mismatch: {issue.get('issue_id')}")
        related = set(str(item) for item in issue.get("related_slide_ids", []))
        slide_id = issue.get("slide_id")
        if slide_id is None and not related:
            errors.append(f"Visual issue has no slide scope: {issue.get('issue_id')}")
        if slide_id is not None and related and str(slide_id) not in related:
            errors.append(f"Visual issue primary slide is absent from related scope: {issue.get('issue_id')}")
    image_keys = [(str(item.get("slide_id")), str(item.get("kind"))) for item in data.get("image_set", [])]
    if len(image_keys) != len(set(image_keys)):
        errors.append("Visual Review contains duplicate slide/kind image evidence")
    final_pages = [item for item in data.get("image_set", []) if item.get("kind") == "final_svg_png"]
    office_pages = [item for item in data.get("image_set", []) if item.get("kind") == "office_preview"]
    summary = data.get("summary", {})
    if int(summary.get("page_count", -1)) != len(final_pages):
        errors.append("Visual Review page_count mismatch")
    if int(summary.get("office_page_count", -1)) != len(office_pages):
        errors.append("Visual Review office_page_count mismatch")
    issues = [item for item in data.get("issues", []) if item.get("status") == "open"]
    expected = {
        "critical_count": sum(item.get("severity") == "critical" for item in issues),
        "major_count": sum(item.get("severity") == "major" for item in issues),
        "minor_count": sum(item.get("severity") == "minor" for item in issues),
        "open_count": len(issues),
    }
    for key, value in expected.items():
        if int(summary.get(key, -1)) != value:
            errors.append(f"Visual Review {key} mismatch")
    capability = data.get("capability", {}).get("status")
    expected_status = "blocked" if capability == "missing" else ("issues" if issues else "pass")
    if data.get("status") != expected_status:
        errors.append("Visual Review status disagrees with capability/issues")
    expected_target = target_phase_for_visual_issues(issues) if capability == "available" else None
    if data.get("target_phase") != expected_target:
        errors.append("Visual Review target_phase mismatch")
    return tuple(errors)


def _runtime_path(workspace: Path, raw: Any, admitted_root: str) -> Path:
    relative = Path(str(raw))
    if relative.is_absolute():
        raise VisualReviewError(f"Visual Review path is absolute: {raw}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / admitted_root)
    if root != path and root not in path.parents:
        raise VisualReviewError(f"Visual Review path is outside {admitted_root}: {raw}")
    return path


def visual_review_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    try:
        data = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"Visual Review is unreadable: {exc}",)
    errors = list(validate_visual_review_data(data, schema_dir))
    refs = (
        (data.get("deterministic_review", {}), ".slidethus/review/deterministic", deterministic_review_reference_errors),
        (data.get("semantic_review", {}), ".slidethus/review/semantic/open-issue", semantic_review_reference_errors),
        (data.get("semantic_scorecard", {}), ".slidethus/review/semantic/scorecard", semantic_scorecard_reference_errors),
    )
    for ref, root, validator in refs:
        try:
            path = _runtime_path(workspace, ref.get("path", ""), root)
            if sha256_file(path) != ref.get("sha256"):
                errors.append(f"Visual Review upstream report hash mismatch: {ref.get('path')}")
            errors.extend(validator(workspace, path, schema_dir))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Visual Review upstream report is invalid: {exc}")
    for image in data.get("image_set", []):
        try:
            path = _runtime_path(workspace, image.get("path", ""), "outputs")
            if not path.is_file() or sha256_file(path) != image.get("sha256"):
                errors.append(f"Visual Review image evidence mismatch: {image.get('path')}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Visual Review image evidence is invalid: {exc}")
    return tuple(errors)


def visual_review_workspace_errors(workspace: Path, schema_dir: Path) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/review/visual"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Visual Review directory"))
            continue
        for message in visual_review_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, message))
    return tuple(errors)
