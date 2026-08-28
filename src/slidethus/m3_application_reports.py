from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import M3ApplicationReportError, PlanningLimitError, WorkspaceError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.m2_application_reports import m2_report_reference_errors
from slidethus.planning_changes import (
    OUTLINE_CHANGE_PROVIDER_NAME,
    OUTLINE_CHANGE_PROVIDER_VERSION,
    find_planning_change_report,
)
from slidethus.planning_limits import validate_planning_limits
from slidethus.planning_repairs import planning_repair_reference_errors
from slidethus.planning_reviews import planning_review_reference_errors
from slidethus.protocols import PlanningLimits
from slidethus.schema_registry import SchemaRegistry

_LEVEL_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "P0": ("project_state", "project_brief", "gate_results", "decision_log"),
    "P2": (
        "project_state",
        "project_brief",
        "source_ledger",
        "evidence_ledger",
        "gate_results",
        "decision_log",
    ),
    "P3": (
        "project_state",
        "project_brief",
        "source_ledger",
        "evidence_ledger",
        "narrative_blueprint",
        "gate_results",
        "decision_log",
    ),
    "P4": (
        "project_state",
        "project_brief",
        "source_ledger",
        "evidence_ledger",
        "narrative_blueprint",
        "deck_outline",
        "gate_results",
        "decision_log",
    ),
    "P5A": (
        "project_state",
        "project_brief",
        "source_ledger",
        "evidence_ledger",
        "narrative_blueprint",
        "deck_outline",
        "slide_specs",
        "gate_results",
        "decision_log",
    ),
    "P5B": (
        "project_state",
        "project_brief",
        "source_ledger",
        "evidence_ledger",
        "narrative_blueprint",
        "deck_outline",
        "slide_specs",
        "layout_plans",
        "gate_results",
        "decision_log",
    ),
}
_PHASE_LEVEL = {
    "CREATED": "P0",
    "BRIEF_READY": "P0",
    "SOURCES_READY": "P2",
    "EVIDENCE_READY": "P2",
    "NARRATIVE_READY": "P3",
    "OUTLINE_READY": "P4",
    "SLIDE_SPECS_READY": "P5A",
    "LAYOUT_READY": "P5B",
    "VISUAL_SYSTEM_READY": "P5B",
    "DRAFT_RENDERED": "P5B",
    "REVIEWED": "P5B",
    "DELIVERY_READY": "P5B",
    "COMPLETED": "P5B",
}
_LEVEL_GATES: dict[str, tuple[str, ...]] = {
    "P0": (),
    "P2": ("G0", "G2"),
    "P3": ("G0", "G2", "G3"),
    "P4": ("G0", "G2", "G3", "G4"),
    "P5A": ("G0", "G2", "G3", "G4", "G5A"),
    "P5B": ("G0", "G2", "G3", "G4", "G5A", "G5B"),
}


def m3_report_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic M3 report payload without its self-derived ID."""

    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def m3_report_id(data: dict[str, Any]) -> str:
    """Return one stable M3 Application Report ID."""

    return "M3R-" + sha256_json(m3_report_identity_payload(data))[:16].upper()


def m3_report_file_key(data: dict[str, Any]) -> str:
    """Return the content-addressed filename key for one M3 report."""

    return sha256_json(data)


def m3_finding_id(kind: str, code: str, message: str) -> str:
    """Return a stable blocker/warning ID."""

    prefix = {"blocker": "M3B", "warning": "M3W"}.get(kind)
    if prefix is None:
        raise M3ApplicationReportError(f"Unknown M3 finding kind: {kind}")
    return prefix + "-" + sha256_json({"code": code, "message": message})[:16].upper()


def m3_report_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "m3_application_report.schema.json"
    if not path.is_file():
        raise M3ApplicationReportError(f"Missing M3 Application Report schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_m3_report_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate report Schema, identity, status, action and Gate invariants."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(m3_report_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != m3_report_id(data):
        errors.append("M3 Application Report identity mismatch")
    try:
        datetime.fromisoformat(str(data.get("generated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("generated_at is not a valid ISO-8601 timestamp")

    inputs = data.get("inputs", {})
    config = dict(inputs.get("config", {}))
    if inputs.get("config_hash") != f"sha256:{sha256_json(config)}":
        errors.append("M3 application config hash mismatch")
    requested_paths = [
        str(item.get("path", "")) for item in inputs.get("requested_sources", [])
    ]
    if len(requested_paths) != len(set(requested_paths)):
        errors.append("duplicate requested Source path")
    try:
        validate_planning_limits(PlanningLimits(**dict(config.get("planning_limits", {}))))
    except (PlanningLimitError, TypeError, ValueError) as exc:
        errors.append(f"invalid persisted Planning limits: {exc}")
    m2_limits = dict(config.get("m2_limits", {}))
    source_limits = dict(m2_limits.get("source", {}))
    requested_sources = list(inputs.get("requested_sources", []))
    if data.get("status") in {"ready", "rework_required"}:
        if len(requested_sources) > int(m2_limits.get("max_sources", 0)):
            errors.append("M3 report exceeds requested Source count budget")
        if sum(int(item.get("size_bytes", 0)) for item in requested_sources) > int(
            m2_limits.get("max_total_source_bytes", 0)
        ):
            errors.append("M3 report exceeds requested Source byte budget")
        if any(
            int(item.get("size_bytes", 0))
            > int(source_limits.get("max_source_bytes", 0))
            for item in requested_sources
        ):
            errors.append("M3 report exceeds requested per-Source byte budget")
    if config.get("planning_provider") is None:
        errors.append("M3 application config requires a PlanningProvider identity")

    capabilities = [
        str(item.get("capability", "")) for item in data.get("capabilities", [])
    ]
    if len(capabilities) != len(set(capabilities)):
        errors.append("duplicate capability entry")
    capability_map = {
        str(item.get("capability", "")): item for item in data.get("capabilities", [])
    }
    required_capabilities = {
        "brief_completion",
        "planning_provider",
        "research_provider",
        "planning_review_and_repair",
        "wireframe_generation",
    }
    missing_capabilities = sorted(required_capabilities - set(capability_map))
    if missing_capabilities:
        errors.append(
            "M3 report lacks required capability facts: "
            + ", ".join(missing_capabilities)
        )
    if capability_map.get("planning_provider", {}).get("status") != "available":
        errors.append("PlanningProvider capability must be available")
    expected_research_status = (
        "available" if config.get("research_provider") is not None else "missing"
    )
    if capability_map.get("research_provider", {}).get("status") != expected_research_status:
        errors.append("ResearchProvider capability disagrees with persisted config")

    actions = list(data.get("actions", []))
    action_ids = [str(item.get("action_id", "")) for item in actions]
    if action_ids != [f"M3A-{index:03d}" for index in range(1, len(actions) + 1)]:
        errors.append("M3 action IDs must be contiguous from M3A-001")
    if not actions or actions[-1].get("stage") != "report" or actions[-1].get(
        "status"
    ) != "complete":
        errors.append("M3 action chain must end with a completed report stage")

    for kind, field in (("blocker", "blockers"), ("warning", "warnings")):
        ids = [str(item.get("finding_id", "")) for item in data.get(field, [])]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate {kind} ID")
        for item in data.get(field, []):
            expected = m3_finding_id(
                kind,
                str(item.get("code", "")),
                str(item.get("message", "")),
            )
            if item.get("finding_id") != expected:
                errors.append(f"{kind} identity mismatch: {item.get('finding_id')}")

    status = str(data.get("status", ""))
    level = str(data.get("planning_level", ""))
    blockers = list(data.get("blockers", []))
    outputs = data.get("outputs", {})
    if status == "ready":
        if level != "P5B":
            errors.append("ready M3 report requires P5B")
        if blockers:
            errors.append("ready M3 report cannot contain blockers")
        review = outputs.get("planning_review")
        if review is None:
            errors.append("ready M3 report requires a Planning Review")
        elif int(review.get("critical_count", -1)) or int(review.get("major_count", -1)):
            errors.append("ready M3 report cannot contain Critical/Major planning issues")
    elif status == "needs_input":
        if level != "P0":
            errors.append("needs_input M3 report requires P0")
        if not blockers:
            errors.append("needs_input M3 report requires a blocker")
    elif status in {"rework_required", "blocked", "failed"} and not blockers:
        errors.append(f"{status} M3 report requires a blocker")

    refs = list(outputs.get("artifact_refs", []))
    ref_types = [str(item.get("artifact_type", "")) for item in refs]
    if len(ref_types) != len(set(ref_types)):
        errors.append("M3 report must bind at most one version per artifact type")
    required_types = set(_LEVEL_ARTIFACTS.get(level, ()))
    missing_types = sorted(required_types - set(ref_types))
    unexpected_types = sorted(set(ref_types) - required_types)
    if missing_types:
        errors.append("M3 report lacks required artifact refs: " + ", ".join(missing_types))
    if unexpected_types:
        errors.append(
            "M3 report binds artifacts outside its planning level: "
            + ", ".join(unexpected_types)
        )

    gate_rows = list(outputs.get("gates", []))
    gate_ids = [str(item.get("gate_id", "")) for item in gate_rows]
    if len(gate_ids) != len(set(gate_ids)):
        errors.append("duplicate Gate result in M3 report")
    expected_gate_ids = {"G0", "G2", "G3", "G4", "G5A", "G5B"}
    if set(gate_ids) != expected_gate_ids:
        errors.append("M3 report must include exactly G0/G2/G3/G4/G5A/G5B")
    gate_map = {str(item.get("gate_id")): str(item.get("status")) for item in gate_rows}
    if status == "ready":
        for gate_id in _LEVEL_GATES["P5B"]:
            if gate_map.get(gate_id) != "pass":
                errors.append(f"ready M3 report requires passing {gate_id}")

    m2_ids = [str(item.get("report_id", "")) for item in outputs.get("m2_reports", [])]
    if len(m2_ids) != len(set(m2_ids)):
        errors.append("duplicate M2 report reference")
    if level != "P0" and not m2_ids:
        errors.append("M3 planning beyond P0 requires at least one M2 report reference")
    if status == "ready" and any(
        item.get("status") not in {"ready", "degraded"}
        for item in outputs.get("m2_reports", [])
    ):
        errors.append("ready M3 report cannot depend on a blocked/failed M2 report")
    action_stages = {str(item.get("stage")) for item in actions}
    if level != "P0" and "m2_orientation" not in action_stages:
        errors.append("M3 planning beyond P0 requires an m2_orientation action")
    if level == "P5B" and "m2_targeted" not in action_stages:
        errors.append("P5B M3 report requires an m2_targeted action")
    if outputs.get("planning_review") is not None and "planning_review" not in action_stages:
        errors.append("Planning Review output requires a planning_review action")
    if outputs.get("planning_repairs") and "planning_repair" not in action_stages:
        errors.append("Planning Repair outputs require a planning_repair action")
    repair_rows = list(outputs.get("planning_repairs", []))
    repair_ids = [str(item.get("repair_id", "")) for item in repair_rows]
    if len(repair_ids) != len(set(repair_ids)):
        errors.append("duplicate Planning Repair reference")
    if repair_rows and config.get("auto_repair") is not True:
        errors.append("Planning Repair outputs require auto_repair=true")
    if len(repair_rows) > int(config.get("max_repair_passes", -1)):
        errors.append("Planning Repair outputs exceed max_repair_passes")
    if status == "ready" and any(
        item.get("status") != "applied" for item in repair_rows
    ):
        errors.append("ready M3 report cannot depend on blocked/noop Planning Repair")
    wireframe_ids = [
        str(item.get("slide_id", "")) for item in outputs.get("wireframes", [])
    ]
    if len(wireframe_ids) != len(set(wireframe_ids)):
        errors.append("duplicate M3 wireframe slide reference")
    if level == "P5B" and not wireframe_ids:
        errors.append("P5B M3 report requires wireframe references")
    return tuple(errors)


def _artifact_for_ref(
    workspace: Path,
    state: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    artifact_type = str(reference["artifact_type"])
    version = int(reference["version"])
    if artifact_type == "project_state":
        current_revision = int(state.get("revision", 0))
        if version == current_revision:
            return copy.deepcopy(state)
        if 1 <= version < current_revision:
            path = workspace / ".slidethus/history/project_state" / f"{version:06d}.json"
            if not path.is_file():
                raise M3ApplicationReportError(
                    f"M3 report Project State revision is missing: {version}"
                )
            return read_json(path)
        raise M3ApplicationReportError(
            f"M3 report references unknown Project State revision: {version}"
        )
    entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == artifact_type
        ),
        None,
    )
    if entry is None:
        raise M3ApplicationReportError(
            f"M3 report references unregistered artifact: {artifact_type}"
        )
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise M3ApplicationReportError(
            f"M3 report references unknown {artifact_type} version: {version}"
        )
    if not path.is_file():
        raise M3ApplicationReportError(f"M3 report artifact version is missing: {path}")
    return read_json(path)


def _safe_runtime_path(
    workspace: Path,
    raw_path: str,
    admitted_root: str,
) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute():
        raise WorkspaceError(f"absolute runtime path is not allowed: {relative}")
    path = ensure_within(workspace, workspace / relative)
    root = ensure_within(workspace, workspace / admitted_root)
    if path.parent != root:
        raise WorkspaceError(
            f"runtime fact must be stored directly under {admitted_root}: {relative}"
        )
    return path


def m3_report_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted M3 report and its historical/runtime references."""

    errors: list[str] = []
    try:
        report = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"M3 Application Report cannot be read: {exc}",)
    errors.extend(validate_m3_report_data(report, schema_dir))
    if report_path.name != f"{m3_report_file_key(report)}.json":
        errors.append("M3 Application Report filename mismatch")
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if report.get("project_id") != state.get("project_id"):
        errors.append("M3 Application Report project_id mismatch")

    inputs = report.get("inputs", {})
    brief_ref = inputs.get("project_brief")
    if brief_ref is not None:
        try:
            brief = _artifact_for_ref(workspace, state, brief_ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        else:
            if f"sha256:{sha256_json(brief)}" != brief_ref.get("content_hash"):
                errors.append("M3 input Project Brief hash mismatch")

    outputs = report.get("outputs", {})
    artifact_data: dict[str, dict[str, Any]] = {}
    for reference in outputs.get("artifact_refs", []):
        try:
            data = _artifact_for_ref(workspace, state, reference)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        artifact_type = str(reference.get("artifact_type", ""))
        artifact_data[artifact_type] = data
        if f"sha256:{sha256_json(data)}" != reference.get("content_hash"):
            errors.append(
                f"M3 artifact hash mismatch: {artifact_type} v{reference.get('version')}"
            )

    config = dict(inputs.get("config", {}))
    planning_provider = config.get("planning_provider")
    for artifact_type in (
        "narrative_blueprint",
        "deck_outline",
        "slide_specs",
        "layout_plans",
    ):
        artifact = artifact_data.get(artifact_type)
        if artifact is None:
            continue
        lineage = artifact.get("planning_lineage", {})
        lineage_provider = lineage.get("provider")
        if lineage_provider == planning_provider:
            continue
        if artifact_type == "deck_outline" and lineage_provider == {
            "name": OUTLINE_CHANGE_PROVIDER_NAME,
            "version": OUTLINE_CHANGE_PROVIDER_VERSION,
        }:
            operations = list(artifact.get("operations_applied", []))
            if not operations:
                errors.append(
                    "Deck Outline uses local-operation lineage without operations_applied"
                )
                continue
            for change_id in operations:
                try:
                    found = find_planning_change_report(
                        workspace,
                        str(change_id),
                        schema_dir=schema_dir,
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        f"Deck Outline local-operation lineage has invalid Change Report {change_id}: {exc}"
                    )
                    continue
                if found is None:
                    errors.append(
                        f"Deck Outline local-operation lineage lacks Change Report {change_id}"
                    )
            continue
        errors.append(
            f"M3 PlanningProvider config disagrees with {artifact_type} lineage"
        )

    source_ledger = artifact_data.get("source_ledger")
    if source_ledger is not None:
        source_by_path = {
            str(item.get("path_or_url")): item
            for item in source_ledger.get("sources", [])
            if item.get("kind") == "user_file" and item.get("path_or_url")
        }
        for requested in inputs.get("requested_sources", []):
            source = source_by_path.get(str(requested.get("path")))
            if source is None:
                errors.append(
                    f"M3 requested Source is absent from bound Source Ledger: {requested.get('path')}"
                )
                continue
            if str(source.get("content_hash", "")).removeprefix("sha256:") != requested.get(
                "sha256"
            ):
                errors.append(
                    f"M3 requested Source hash disagrees with bound Source Ledger: {requested.get('path')}"
                )
            if int(source.get("size_bytes") or 0) != int(requested.get("size_bytes") or 0):
                errors.append(
                    f"M3 requested Source size disagrees with bound Source Ledger: {requested.get('path')}"
                )

    report_state = artifact_data.get("project_state")
    if report_state is not None:
        bound_phase = str(report_state.get("current_phase", ""))
        if bound_phase != outputs.get("final_phase"):
            errors.append("M3 final_phase disagrees with bound Project State")
        expected_level = _PHASE_LEVEL.get(bound_phase)
        if expected_level != report.get("planning_level"):
            errors.append(
                "M3 planning_level disagrees with the bound Project State phase"
            )
        accepted = {
            str(item.get("gate_id")): str(item.get("status"))
            for item in report_state.get("completed_gates", [])
        }
        for gate in outputs.get("gates", []):
            if gate.get("status") == "pass" and accepted.get(str(gate.get("gate_id"))) not in {
                "pass",
                "waived",
            }:
                errors.append(
                    f"M3 report Gate {gate.get('gate_id')} pass is absent from bound Project State"
                )

    m2_report_data: list[dict[str, Any]] = []
    for reference in outputs.get("m2_reports", []):
        try:
            path = _safe_runtime_path(
                workspace,
                str(reference.get("path", "")),
                ".slidethus/m2/runs",
            )
        except (WorkspaceError, OSError, ValueError) as exc:
            errors.append(f"M2 report path is unsafe: {exc}")
            continue
        if not path.is_file():
            errors.append(f"M2 report is missing: {reference.get('report_id')}")
            continue
        if sha256_file(path) != reference.get("sha256"):
            errors.append(f"M2 report hash mismatch: {reference.get('report_id')}")
        try:
            data = read_json(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"M2 report cannot be read: {exc}")
            continue
        if data.get("report_id") != reference.get("report_id"):
            errors.append("M2 report identity mismatch")
        if data.get("status") != reference.get("status"):
            errors.append("M2 report status mismatch")
        m2_report_data.append(data)
        errors.extend(m2_report_reference_errors(workspace, path, schema_dir))

    if m2_report_data:
        m2_requested_by_path = {
            str(item.get("path")): item
            for m2_report in m2_report_data
            for item in m2_report.get("inputs", {}).get("requested_sources", [])
        }
        m3_requested_by_path = {
            str(item.get("path")): item for item in inputs.get("requested_sources", [])
        }
        if m2_requested_by_path != m3_requested_by_path:
            errors.append("M3 requested Sources disagree with referenced M2 reports")
        expected_research_provider = config.get("research_provider")
        for m2_report in m2_report_data:
            actual_provider = (
                m2_report.get("inputs", {}).get("config", {}).get("provider")
            )
            if actual_provider != expected_research_provider:
                errors.append(
                    "M3 ResearchProvider config disagrees with referenced M2 report"
                )
        output_m2_ids = {
            str(item.get("report_id")) for item in outputs.get("m2_reports", [])
        }
        action_m2_ids = {
            str(ref)
            for action in report.get("actions", [])
            if action.get("stage") in {"m2_orientation", "m2_targeted"}
            for ref in action.get("refs", [])
            if str(ref).startswith("M2R-")
        }
        if output_m2_ids != action_m2_ids:
            errors.append("M3 M2 report outputs disagree with M2 action references")

    review_ref = outputs.get("planning_review")
    if review_ref is not None:
        try:
            path = _safe_runtime_path(
                workspace,
                str(review_ref.get("path", "")),
                ".slidethus/planning/reviews",
            )
        except (WorkspaceError, OSError, ValueError) as exc:
            errors.append(f"Planning Review path is unsafe: {exc}")
        else:
            if not path.is_file():
                errors.append("Planning Review is missing")
            else:
                if sha256_file(path) != review_ref.get("sha256"):
                    errors.append("Planning Review hash mismatch")
                review = read_json(path)
                if review.get("report_id") != review_ref.get("report_id"):
                    errors.append("Planning Review identity mismatch")
                summary = review.get("summary", {})
                for field in ("critical_count", "major_count", "minor_count"):
                    if int(summary.get(field, -1)) != int(review_ref.get(field, -2)):
                        errors.append(f"Planning Review {field} mismatch")
                if report.get("status") == "ready":
                    if review.get("status") != "pass":
                        errors.append("ready M3 report requires a passing Planning Review")
                    review_inputs = {
                        str(item.get("artifact_type")): {
                            "version": int(item.get("version", 0)),
                            "content_hash": str(item.get("content_hash", "")),
                        }
                        for item in review.get("inputs", [])
                    }
                    bound_review_inputs = {
                        artifact_type: {
                            "version": int(reference.get("version", 0)),
                            "content_hash": str(reference.get("content_hash", "")),
                        }
                        for reference in outputs.get("artifact_refs", [])
                        if (artifact_type := str(reference.get("artifact_type", "")))
                        in {
                            "project_brief",
                            "evidence_ledger",
                            "narrative_blueprint",
                            "deck_outline",
                            "slide_specs",
                            "layout_plans",
                        }
                    }
                    if review_inputs != bound_review_inputs:
                        errors.append(
                            "ready M3 report Planning Review does not bind the final planning artifacts"
                        )
                errors.extend(planning_review_reference_errors(workspace, path, schema_dir))

    for reference in outputs.get("planning_repairs", []):
        try:
            path = _safe_runtime_path(
                workspace,
                str(reference.get("path", "")),
                ".slidethus/planning/repairs",
            )
        except (WorkspaceError, OSError, ValueError) as exc:
            errors.append(f"Planning Repair path is unsafe: {exc}")
            continue
        if not path.is_file():
            errors.append(f"Planning Repair is missing: {reference.get('repair_id')}")
            continue
        if sha256_file(path) != reference.get("sha256"):
            errors.append(f"Planning Repair hash mismatch: {reference.get('repair_id')}")
        repair = read_json(path)
        if repair.get("repair_id") != reference.get("repair_id"):
            errors.append("Planning Repair identity mismatch")
        if repair.get("status") != reference.get("status"):
            errors.append("Planning Repair status mismatch")
        if repair.get("planning_limits") != config.get("planning_limits"):
            errors.append("Planning Repair limits disagree with M3 application config")
        if repair.get("planning_provider") != config.get("planning_provider"):
            errors.append("Planning Repair provider disagrees with M3 application config")
        errors.extend(planning_repair_reference_errors(workspace, path, schema_dir))

    layout = artifact_data.get("layout_plans", {})
    layout_wireframes = {
        str(item.get("slide_id")): item for item in layout.get("wireframes", [])
    }
    for reference in outputs.get("wireframes", []):
        slide_id = str(reference.get("slide_id", ""))
        try:
            path = _safe_runtime_path(
                workspace,
                str(reference.get("path", "")),
                ".slidethus/planning/wireframes",
            )
        except (WorkspaceError, OSError, ValueError) as exc:
            errors.append(f"Wireframe path is unsafe: {slide_id}: {exc}")
            continue
        if not path.is_file():
            errors.append(f"Wireframe is missing: {slide_id}")
            continue
        if sha256_file(path) != reference.get("sha256"):
            errors.append(f"Wireframe hash mismatch: {slide_id}")
        layout_ref = layout_wireframes.get(slide_id)
        if layout_ref is None:
            errors.append(f"Wireframe is absent from bound Layout Plans: {slide_id}")
        elif (
            layout_ref.get("path") != reference.get("path")
            or layout_ref.get("sha256") != reference.get("sha256")
        ):
            errors.append(f"Wireframe disagrees with bound Layout Plans: {slide_id}")
    if layout_wireframes and set(layout_wireframes) != {
        str(item.get("slide_id")) for item in outputs.get("wireframes", [])
    }:
        errors.append("M3 wireframe references do not cover bound Layout Plans")
    return tuple(errors)


def find_m3_application_report(
    workspace: Path,
    report_id: str,
    *,
    schema_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Return one verified M3 Application Report by stable ID."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/m3/runs"
    if not root.exists():
        return None
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    for path in sorted(root.glob("*.json")):
        try:
            data = read_json(path)
        except Exception:
            continue
        if data.get("report_id") != report_id:
            continue
        errors = m3_report_reference_errors(workspace, path, admitted_schema_dir)
        if errors:
            raise M3ApplicationReportError(
                "Invalid M3 Application Report: " + "; ".join(errors)
            )
        return path, copy.deepcopy(data)
    return None


def inspect_m3_application_report(
    workspace: Path,
    report_id: str,
    *,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    """Inspect one verified M3 report."""

    found = find_m3_application_report(
        workspace,
        report_id,
        schema_dir=schema_dir,
    )
    if found is None:
        raise M3ApplicationReportError(f"Unknown M3 Application Report: {report_id}")
    return found[1]


def list_m3_application_reports(
    workspace: Path,
    *,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """List verified M3 Application Report summaries."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/m3/runs"
    if not root.exists():
        return ()
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    summaries: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        errors = m3_report_reference_errors(workspace, path, admitted_schema_dir)
        if errors:
            raise M3ApplicationReportError(
                f"Invalid M3 Application Report {path.name}: " + "; ".join(errors)
            )
        data = read_json(path)
        summaries.append(
            {
                "report_id": data["report_id"],
                "status": data["status"],
                "planning_level": data["planning_level"],
                "generated_at": data["generated_at"],
                "final_phase": data["outputs"]["final_phase"],
                "path": path.relative_to(workspace).as_posix(),
            }
        )
    summaries.sort(key=lambda item: (str(item["generated_at"]), str(item["report_id"])))
    return tuple(summaries)


def m3_application_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for every persisted M3 Application Report."""

    root = workspace / ".slidethus/m3/runs"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in M3 Application Report directory"))
            continue
        for error in m3_report_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, error))
    return tuple(errors)
