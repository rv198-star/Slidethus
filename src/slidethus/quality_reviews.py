from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from slidethus.deterministic_reviews import deterministic_review_reference_errors
from slidethus.io_utils import ensure_within, read_json, sha256_file
from slidethus.review_regressions import regression_reference_errors
from slidethus.review_repairs import repair_report_reference_errors
from slidethus.semantic_reviews import (
    semantic_review_reference_errors,
    semantic_scorecard_reference_errors,
)
from slidethus.visual_reviews import visual_review_reference_errors


def _runtime_path(workspace: Path, raw: Any, admitted_root: str) -> Path:
    relative = Path(str(raw))
    if relative.is_absolute():
        raise ValueError(f"Production Quality Report path is absolute: {raw}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / admitted_root)
    if root != path and root not in path.parents:
        raise ValueError(f"Production Quality Report path is outside {admitted_root}: {raw}")
    return path


def _load_ref(
    workspace: Path,
    ref: dict[str, Any],
    root: str,
    validator: Callable[[Path, Path, Path], tuple[str, ...]],
    schema_dir: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        path = _runtime_path(workspace, ref.get("path", ""), root)
        if not path.is_file():
            return None, [f"Production Quality Report input is missing: {ref.get('path')}"]
        if sha256_file(path) != ref.get("sha256"):
            errors.append(f"Production Quality Report input hash mismatch: {ref.get('path')}")
        data = read_json(path)
        expected_id = data.get("review_id") if root.endswith("deterministic") else data.get("report_id")
        if root.endswith("reports"):
            expected_id = data.get("repair_id")
        if root.endswith("regression"):
            expected_id = data.get("regression_id")
        if str(expected_id) != str(ref.get("report_id")):
            errors.append(f"Production Quality Report input identity mismatch: {ref.get('path')}")
        errors.extend(validator(workspace, path, schema_dir))
        return data, errors
    except Exception as exc:  # noqa: BLE001
        return None, [f"Production Quality Report input is invalid: {exc}"]


def _report_artifacts_are_current(workspace: Path, report: dict[str, Any]) -> bool:
    state = read_json(workspace / "project_state.json")
    entries = {str(item.get("artifact_type")): item for item in state.get("artifacts", [])}
    for ref in report.get("inputs", []):
        entry = entries.get(str(ref.get("artifact_type")))
        if entry is None:
            return False
        if int(entry.get("version", 0)) != int(ref.get("version", -1)):
            return False
        expected = ref.get("content_hash")
        if expected is not None and str(entry.get("content_hash")) != str(expected):
            return False
        observed = ref.get("observed_content_hash")
        if observed is not None and str(entry.get("content_hash")) != str(observed):
            return False
    return True


def production_quality_reference_errors(
    workspace: Path,
    data: dict[str, Any],
    schema_dir: Path,
    *,
    require_current: bool = True,
) -> tuple[str, ...]:
    """Validate immutable Quality lineage and, when active, current G8 readiness."""

    production = data.get("production_review")
    if not isinstance(production, dict):
        return ()
    errors: list[str] = []
    d, d_errors = _load_ref(
        workspace,
        production.get("deterministic_review", {}),
        ".slidethus/review/deterministic",
        deterministic_review_reference_errors,
        schema_dir,
    )
    s, s_errors = _load_ref(
        workspace,
        production.get("semantic_review", {}),
        ".slidethus/review/semantic/open-issue",
        semantic_review_reference_errors,
        schema_dir,
    )
    c, c_errors = _load_ref(
        workspace,
        production.get("semantic_scorecard", {}),
        ".slidethus/review/semantic/scorecard",
        semantic_scorecard_reference_errors,
        schema_dir,
    )
    v, v_errors = _load_ref(
        workspace,
        production.get("visual_review", {}),
        ".slidethus/review/visual",
        visual_review_reference_errors,
        schema_dir,
    )
    r, r_errors = _load_ref(
        workspace,
        production.get("regression_report", {}),
        ".slidethus/review/regression",
        regression_reference_errors,
        schema_dir,
    )
    errors.extend([*d_errors, *s_errors, *c_errors, *v_errors, *r_errors])
    repair_ref = production.get("repair_report")
    repair = None
    if isinstance(repair_ref, dict):
        repair, repair_errors = _load_ref(
            workspace,
            repair_ref,
            ".slidethus/review/repairs/reports",
            repair_report_reference_errors,
            schema_dir,
        )
        errors.extend(repair_errors)

    if require_current:
        if d is not None:
            if d.get("status") != "pass":
                errors.append("Production G8 requires a passing deterministic review")
            if not _report_artifacts_are_current(workspace, d):
                errors.append("Production deterministic review is stale")
        if s is not None:
            if s.get("status") == "blocked" or s.get("capability", {}).get("status") != "available":
                errors.append("Production G8 requires semantic review capability")
            if not _report_artifacts_are_current(workspace, s):
                errors.append("Production semantic review is stale")
        if c is not None and (c.get("status") == "blocked" or c.get("capability", {}).get("status") != "available"):
            errors.append("Production G8 requires semantic scorecard capability")
        if v is not None and (v.get("status") == "blocked" or v.get("capability", {}).get("status") != "available"):
            errors.append("Production G8 requires full-page visual review capability")
        if r is not None and r.get("status") != "pass":
            errors.append("Production G8 requires passing cross-deck regression")
        if repair is not None and repair.get("status") in {"blocked", "failed"}:
            errors.append("Production G8 cannot use a blocked/failed repair result")

    source_issues: dict[str, tuple[str, dict[str, Any]]] = {}
    if s is not None:
        source_issues.update(
            {str(item["issue_id"]): ("semantic", item) for item in s.get("issues", [])}
        )
    if v is not None:
        source_issues.update(
            {str(item["issue_id"]): ("visual", item) for item in v.get("issues", [])}
        )
    quality_issues = {str(item["issue_id"]): item for item in data.get("issues", [])}
    mappings = production.get("issue_sources", [])
    mapped_quality = {str(item.get("quality_issue_id")) for item in mappings}
    if mapped_quality != set(quality_issues):
        errors.append("Production Quality Report issue_sources do not cover Quality issues exactly")
    mapped_sources: set[str] = set()
    for mapping in mappings:
        quality_id = str(mapping.get("quality_issue_id"))
        source_id = str(mapping.get("source_issue_id"))
        source_type = str(mapping.get("source_type"))
        if source_id not in source_issues:
            errors.append(f"Production Quality Report maps unknown source issue: {source_id}")
            continue
        expected_type, source_issue = source_issues[source_id]
        if source_type != expected_type:
            errors.append(f"Production Quality Report source type mismatch: {source_id}")
        quality = quality_issues.get(quality_id)
        if quality is not None:
            if quality.get("severity") != source_issue.get("severity"):
                errors.append(f"Production Quality issue severity drift: {quality_id}")
            if quality.get("phase") != source_issue.get("earliest_phase"):
                errors.append(f"Production Quality issue phase drift: {quality_id}")
        mapped_sources.add(source_id)
    expected_sources = {
        source_id
        for source_id, (_kind, item) in source_issues.items()
        if item.get("status") == "open"
    }
    if mapped_sources != expected_sources:
        errors.append("Production Quality Report does not aggregate every current open source issue")
    return tuple(dict.fromkeys(errors))


def production_quality_gate_reasons(
    workspace: Path,
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    if not isinstance(data.get("production_review"), dict):
        return ("Production Render Manifest requires M5 production_review lineage for G8",)
    return production_quality_reference_errors(
        workspace,
        data,
        schema_dir,
        require_current=True,
    )


def quality_review_workspace_errors(workspace: Path, schema_dir: Path) -> tuple[tuple[str, str], ...]:
    path = workspace / "review/quality_report.json"
    if not path.is_file():
        return ()
    try:
        data = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return (("review/quality_report.json", f"Quality Report is unreadable: {exc}"),)
    state = read_json(workspace / "project_state.json")
    entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == "quality_report"
        ),
        None,
    )
    active = bool(entry) and str(entry.get("status")) != "draft" and str(
        state.get("current_phase")
    ) in {"REVIEWED", "DELIVERY_READY", "COMPLETED"}
    return tuple(
        ("review/quality_report.json", message)
        for message in production_quality_reference_errors(
            workspace,
            data,
            schema_dir,
            require_current=active,
        )
    )
