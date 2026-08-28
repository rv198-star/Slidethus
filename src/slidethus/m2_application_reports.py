from __future__ import annotations

import copy
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.errors import M2ApplicationReportError, WorkspaceError
from slidethus.io_utils import (
    canonical_json_bytes,
    ensure_within,
    read_json,
    sha256_file,
    sha256_json,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.source_snapshots import load_source_snapshot

_M2_PHASE_REQUIRED_GATES = {
    "CREATED": (),
    "BRIEF_READY": ("G0",),
    "SOURCES_READY": ("G0", "G1"),
    "EVIDENCE_READY": ("G0", "G1", "G2"),
    "NARRATIVE_READY": ("G0", "G1", "G2", "G3"),
    "OUTLINE_READY": ("G0", "G1", "G2", "G3", "G4"),
    "SLIDE_SPECS_READY": ("G0", "G1", "G2", "G3", "G4", "G5A"),
    "LAYOUT_READY": ("G0", "G1", "G2", "G3", "G4", "G5A"),
    "VISUAL_SYSTEM_READY": ("G0", "G1", "G2", "G3", "G4", "G5A"),
    "DRAFT_RENDERED": ("G0", "G1", "G2", "G3", "G4", "G5A"),
    "REVIEWED": ("G0", "G1", "G2", "G3", "G4", "G5A"),
    "DELIVERY_READY": ("G0", "G1", "G2", "G3", "G4", "G5A"),
    "COMPLETED": ("G0", "G1", "G2", "G3", "G4", "G5A"),
}


def m2_report_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic payload used for one stable M2 report ID."""

    payload = copy.deepcopy(data)
    payload.pop("report_id", None)
    return payload


def m2_report_id(data: dict[str, Any]) -> str:
    """Return the stable ID for one complete M2 Application Report."""

    return "M2R-" + sha256_json(m2_report_identity_payload(data))[:16].upper()


def m2_report_file_key(data: dict[str, Any]) -> str:
    """Return the content-addressed filename key for one report."""

    return sha256_json(data)


def m2_finding_id(kind: str, code: str, message: str) -> str:
    """Return a stable blocker/warning ID."""

    prefix = {"blocker": "M2B", "warning": "M2W"}.get(kind)
    if prefix is None:
        raise M2ApplicationReportError(f"Unknown M2 finding kind: {kind}")
    return f"{prefix}-" + sha256_json({"code": code, "message": message})[:16].upper()


def m2_report_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "m2_application_report.schema.json"
    if not path.is_file():
        raise M2ApplicationReportError(f"Missing M2 Application Report schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_m2_report_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    """Validate report schema, identity, ordering and status invariants."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(m2_report_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("report_id") != m2_report_id(data):
        errors.append("report identity mismatch")
    try:
        datetime.fromisoformat(str(data.get("generated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("generated_at is not a valid ISO-8601 timestamp")

    action_ids = [str(item.get("action_id", "")) for item in data.get("actions", [])]
    expected_actions = [f"M2A-{index:03d}" for index in range(1, len(action_ids) + 1)]
    if action_ids != expected_actions:
        errors.append("action IDs must be contiguous from M2A-001")

    inputs = data.get("inputs", {})
    requested_paths = [
        str(item.get("path", ""))
        for item in inputs.get("requested_sources", [])
    ]
    if len(requested_paths) != len(set(requested_paths)):
        errors.append("duplicate requested Source path")
    config = dict(inputs.get("config", {}))
    if inputs.get("config_hash") != f"sha256:{sha256_json(config)}":
        errors.append("M2 application config hash mismatch")
    limits = dict(config.get("limits", {}))
    source_limits = dict(limits.get("source", {}))
    requested_sources = list(inputs.get("requested_sources", []))
    if data.get("status") in {"ready", "degraded"}:
        if len(requested_sources) > int(limits.get("max_sources", 0)):
            errors.append("ready/degraded report exceeds requested Source count budget")
        requested_total = sum(
            int(item.get("size_bytes", 0)) for item in requested_sources
        )
        if requested_total > int(limits.get("max_total_source_bytes", 0)):
            errors.append("ready/degraded report exceeds requested Source byte budget")
        if any(
            int(item.get("size_bytes", 0))
            > int(source_limits.get("max_source_bytes", 0))
            for item in requested_sources
        ):
            errors.append("ready/degraded report exceeds per-Source byte budget")

    capabilities = [str(item.get("capability", "")) for item in data.get("capabilities", [])]
    if len(capabilities) != len(set(capabilities)):
        errors.append("duplicate capability entry")
    capability_map = {
        str(item.get("capability", "")): item for item in data.get("capabilities", [])
    }
    provider = config.get("provider")
    provider_capability = capability_map.get("external_research_provider", {})
    expected_provider_status = "available" if provider is not None else "missing"
    if provider_capability.get("status") != expected_provider_status:
        errors.append("Research provider capability disagrees with persisted config")

    security = data.get("security", {})
    if security.get("external_disclosure_approved") != config.get(
        "approve_external_disclosure"
    ):
        errors.append("external disclosure security fact disagrees with config")
    if security.get("high_risk_source_evidence_allowed") != config.get(
        "allow_high_risk_source_evidence"
    ):
        errors.append("high-risk Evidence security fact disagrees with config")

    for kind, field in (("blocker", "blockers"), ("warning", "warnings")):
        ids = [str(item.get("finding_id", "")) for item in data.get(field, [])]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate {kind} ID")
        for item in data.get(field, []):
            expected = m2_finding_id(kind, str(item.get("code", "")), str(item.get("message", "")))
            if item.get("finding_id") != expected:
                errors.append(f"{kind} identity mismatch: {item.get('finding_id')}")

    mode = data.get("mode")
    level = data.get("delivery_level")
    status = data.get("status")
    blockers = data.get("blockers", [])
    actions = list(data.get("actions", []))
    if not actions or actions[-1].get("stage") != "report" or actions[-1].get(
        "status"
    ) != "complete":
        errors.append("M2 application action chain must end with a completed report stage")
    if mode == "full" and (
        config.get("provider") is None
        or config.get("approve_external_disclosure") is not True
    ):
        errors.append("full mode requires provider identity and disclosure approval")
    if status == "degraded" and config.get("allow_research_degraded") is not True:
        errors.append("degraded status requires explicit research degradation approval")
    if status == "ready":
        expected_level = "D0" if mode == "full" else "D3"
        if level != expected_level:
            errors.append(f"ready {mode} mode requires {expected_level}")
    elif status == "degraded":
        if mode not in {"user_materials", "offline_degraded"} or level != "D3":
            errors.append("degraded report requires research-limited D3 mode")
    elif status == "rework_required":
        if level != "D4":
            errors.append("rework_required report requires D4")
    elif status in {"blocked", "failed"} and level != "D5":
        errors.append("blocked/failed report requires D5")
    if status in {"blocked", "rework_required", "failed"} and not blockers:
        errors.append("non-ready report status requires at least one blocker")
    if status in {"ready", "degraded"} and blockers:
        errors.append("ready/degraded report cannot contain blockers")

    outputs = data.get("outputs", {})
    if outputs.get("research_run_ids") and not any(
        item.get("stage") in {"orientation_research", "targeted_research"}
        for item in actions
    ):
        errors.append("Research Run outputs require a Research action record")
    if outputs.get("gap_report_path") and not any(
        item.get("stage") == "gap_analysis" for item in actions
    ):
        errors.append("Gap Report output requires a gap_analysis action record")
    research_run_ids = [str(item) for item in outputs.get("research_run_ids", [])]
    research_run_refs = list(outputs.get("research_runs", []))
    referenced_run_ids = [str(item.get("run_id", "")) for item in research_run_refs]
    if len(referenced_run_ids) != len(set(referenced_run_ids)):
        errors.append("duplicate Research Run snapshot reference")
    if sorted(research_run_ids) != sorted(referenced_run_ids):
        errors.append("research_run_ids disagree with research_runs")
    snapshot_paths = [str(item.get("snapshot_path", "")) for item in research_run_refs]
    if len(snapshot_paths) != len(set(snapshot_paths)):
        errors.append("duplicate Research Run snapshot path")

    gap_path = outputs.get("gap_report_path")
    gap_hash = outputs.get("gap_report_sha256")
    if (gap_path is None) != (gap_hash is None):
        errors.append("gap report path/hash must be set together")

    refs = data.get("outputs", {}).get("artifact_refs", [])
    ref_keys = [(item.get("artifact_type"), item.get("version")) for item in refs]
    if len(ref_keys) != len(set(ref_keys)):
        errors.append("duplicate output artifact reference")
    artifact_types = [str(item.get("artifact_type", "")) for item in refs]
    if len(artifact_types) != len(set(artifact_types)):
        errors.append("M2 report must bind at most one version per artifact type")
    required_artifact_types = {
        "project_state",
        "project_brief",
        "source_ledger",
        "evidence_ledger",
        "gate_results",
    }
    if not required_artifact_types.issubset(set(artifact_types)):
        errors.append(
            "M2 report lacks required final artifact refs: "
            + ", ".join(sorted(required_artifact_types - set(artifact_types)))
        )

    gate_ids = [str(item.get("gate_id", "")) for item in outputs.get("gates", [])]
    if len(gate_ids) != len(set(gate_ids)):
        errors.append("duplicate Gate result in report")
    return tuple(errors)


def _artifact_data_for_ref(
    workspace: Path,
    state: dict[str, Any],
    artifact_ref: dict[str, Any],
) -> dict[str, Any]:
    artifact_type = str(artifact_ref["artifact_type"])
    version = int(artifact_ref["version"])
    if artifact_type == "project_state":
        current_revision = int(state.get("revision", 0))
        if version == current_revision:
            return copy.deepcopy(state)
        if 1 <= version < current_revision:
            history_path = (
                workspace / ".slidethus/history/project_state" / f"{version:06d}.json"
            )
            if not history_path.is_file():
                raise M2ApplicationReportError(
                    f"M2 report Project State revision is missing: {version}"
                )
            return read_json(history_path)
        raise M2ApplicationReportError(
            f"M2 report references unknown Project State revision: {version}"
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
        raise M2ApplicationReportError(
            f"M2 report references unregistered artifact: {artifact_type}"
        )
    current_version = int(entry["version"])
    if version == current_version:
        path = workspace / str(entry["path"])
    elif 1 <= version < current_version:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise M2ApplicationReportError(
            f"M2 report references unknown {artifact_type} version: {version}"
        )
    if not path.is_file():
        raise M2ApplicationReportError(f"M2 report artifact version is missing: {path}")
    return read_json(path)


def m2_report_reference_errors(
    workspace: Path,
    report_path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    """Validate one persisted M2 report and all workspace references."""

    errors: list[str] = []
    try:
        data = read_json(report_path)
    except Exception as exc:  # noqa: BLE001
        return (f"report JSON cannot be read: {exc}",)
    errors.extend(validate_m2_report_data(data, schema_dir))
    if report_path.name != f"{m2_report_file_key(data)}.json":
        errors.append("content-addressed M2 report filename mismatch")

    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return tuple([*errors, "project_state.json is missing"])
    state = read_json(state_path)
    if data.get("project_id") != state.get("project_id"):
        errors.append("M2 report project_id mismatch")

    input_brief: dict[str, Any] | None = None
    input_brief_ref = data.get("inputs", {}).get("project_brief")
    if input_brief_ref is not None:
        try:
            input_brief = _artifact_data_for_ref(workspace, state, input_brief_ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        else:
            if f"sha256:{sha256_json(input_brief)}" != input_brief_ref.get(
                "content_hash"
            ):
                errors.append(
                    "artifact content hash mismatch: "
                    f"project_brief v{input_brief_ref.get('version')}"
                )

    if input_brief is not None:
        external_required = bool(
            input_brief.get("source_policy", {}).get("external_research")
        )
        freshness_requirement = str(
            input_brief.get("source_policy", {}).get("freshness_requirement") or ""
        ).strip()
        mode = str(data.get("mode", ""))
        if external_required and mode not in {"full", "offline_degraded"}:
            errors.append("M2 report mode disagrees with external-research Brief policy")
        if not external_required and mode != "user_materials":
            errors.append("M2 report mode disagrees with user-material Brief policy")
        if data.get("status") == "degraded" and freshness_requirement:
            errors.append("freshness-constrained Brief cannot produce a degraded M2 report")
        config = data.get("inputs", {}).get("config", {})
        provider_present = config.get("provider") is not None
        disclosure_approved = config.get("approve_external_disclosure") is True
        disclosure_capability = next(
            (
                item
                for item in data.get("capabilities", [])
                if item.get("capability") == "external_disclosure"
            ),
            {},
        )
        expected_disclosure_status = (
            "available"
            if disclosure_approved or not external_required
            else ("missing" if provider_present else "degraded")
        )
        if disclosure_capability.get("status") != expected_disclosure_status:
            errors.append("external disclosure capability disagrees with Brief/config policy")

    outputs = data.get("outputs", {})
    final_artifact_data: dict[str, dict[str, Any]] = {}
    for raw_ref in outputs.get("artifact_refs", []):
        try:
            artifact_data = _artifact_data_for_ref(workspace, state, raw_ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        artifact_type = str(raw_ref.get("artifact_type", ""))
        final_artifact_data[artifact_type] = artifact_data
        if f"sha256:{sha256_json(artifact_data)}" != raw_ref.get("content_hash"):
            errors.append(
                f"artifact content hash mismatch: {artifact_type} v{raw_ref.get('version')}"
            )

    source_ledger = final_artifact_data.get("source_ledger")
    if source_ledger is not None:
        final_sources = list(source_ledger.get("sources", []))
        expected_source_ids = sorted(
            str(item["source_id"]) for item in final_sources
        )
        if outputs.get("source_ids") != expected_source_ids:
            errors.append("M2 report source_ids disagree with bound Source Ledger")
        if data.get("status") in {"ready", "degraded"}:
            config_limits = data.get("inputs", {}).get("config", {}).get(
                "limits", {}
            )
            source_limits = config_limits.get("source", {})
            if len(final_sources) > int(config_limits.get("max_sources", 0)):
                errors.append("ready/degraded report exceeds final Source count budget")
            final_source_bytes = sum(
                int(item.get("size_bytes") or 0) for item in final_sources
            )
            if final_source_bytes > int(
                config_limits.get("max_total_source_bytes", 0)
            ):
                errors.append("ready/degraded report exceeds final Source byte budget")
            if any(
                int(item.get("size_bytes") or 0)
                > int(source_limits.get("max_source_bytes", 0))
                for item in final_sources
            ):
                errors.append("ready/degraded report exceeds final per-Source budget")

        user_sources_by_path = {
            str(item.get("path_or_url")): item
            for item in final_sources
            if item.get("kind") == "user_file"
        }
        for requested in data.get("inputs", {}).get("requested_sources", []):
            source = user_sources_by_path.get(str(requested.get("path", "")))
            if source is None:
                if data.get("status") in {"ready", "degraded"}:
                    errors.append(
                        f"ready/degraded report requested Source is absent from bound Ledger: {requested.get('path')}"
                    )
                continue
            if str(source.get("content_hash", "")).removeprefix("sha256:") != requested.get(
                "sha256"
            ):
                errors.append(
                    f"requested Source hash disagrees with bound Ledger: {requested.get('path')}"
                )
            if int(source.get("size_bytes") or 0) != int(
                requested.get("size_bytes", -1)
            ):
                errors.append(
                    f"requested Source size disagrees with bound Ledger: {requested.get('path')}"
                )

        high_risk_counts: dict[str, int] = {}
        for source in final_sources:
            if not source.get("ingestion"):
                continue
            source_id = str(source["source_id"])
            try:
                snapshot = load_source_snapshot(
                    workspace,
                    str(data.get("project_id")),
                    source,
                    schema_dir,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    f"M2 report cannot validate Source risk lineage {source_id}: {exc}"
                )
                continue
            count = sum(
                1 for item in snapshot.get("risks", []) if item.get("severity") == "high"
            )
            if count:
                high_risk_counts[source_id] = count
        security = data.get("security", {})
        expected_excluded = (
            []
            if security.get("high_risk_source_evidence_allowed")
            else sorted(high_risk_counts)
        )
        if security.get("excluded_source_ids") != expected_excluded:
            errors.append("M2 report excluded_source_ids disagree with bound Source risks")
        if int(security.get("high_risk_finding_count", -1)) != sum(
            high_risk_counts.values()
        ):
            errors.append("M2 report high_risk_finding_count disagrees with bound Source risks")
    evidence_ledger = final_artifact_data.get("evidence_ledger")
    if evidence_ledger is not None:
        expected_evidence_ids = sorted(
            str(item["evidence_id"]) for item in evidence_ledger.get("claims", [])
        )
        if outputs.get("evidence_ids") != expected_evidence_ids:
            errors.append("M2 report evidence_ids disagree with bound Evidence Ledger")

    application_research_limits = data.get("inputs", {}).get("config", {}).get(
        "limits", {}
    ).get("research", {})
    archived_runs: list[dict[str, Any]] = []
    cache_schema_path = schema_dir / "research_cache_snapshot.schema.json"
    research_cache_schema = (
        read_json(cache_schema_path) if cache_schema_path.is_file() else None
    )
    if outputs.get("research_runs") and research_cache_schema is None:
        errors.append("research_cache_snapshot.schema.json is missing")

    for run_ref in outputs.get("research_runs", []):
        run_id = str(run_ref.get("run_id", ""))
        raw_snapshot_path = str(run_ref.get("snapshot_path", ""))
        try:
            relative = Path(raw_snapshot_path)
            if relative.is_absolute():
                raise WorkspaceError("absolute Research Run snapshot path is not allowed")
            snapshot_path = ensure_within(workspace, workspace / relative)
            admitted_snapshot_root = ensure_within(
                workspace,
                workspace / ".slidethus/m2/research-runs",
            )
            if snapshot_path.parent != admitted_snapshot_root:
                raise WorkspaceError(
                    "Research Run snapshot must be stored directly under .slidethus/m2/research-runs"
                )
        except (OSError, ValueError, WorkspaceError) as exc:
            errors.append(f"M2 report Research Run snapshot path is unsafe: {run_id}: {exc}")
            continue
        if not snapshot_path.is_file():
            errors.append(f"M2 report Research Run snapshot is missing: {run_id}")
            continue
        if sha256_file(snapshot_path) != run_ref.get("snapshot_sha256"):
            errors.append(f"M2 report Research Run snapshot hash mismatch: {run_id}")
        try:
            run = read_json(snapshot_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"M2 report Research Run snapshot cannot be read: {run_id}: {exc}")
            continue
        expected_name = f"{sha256_json(run)}.json"
        if snapshot_path.name != expected_name:
            errors.append(f"M2 report Research Run snapshot filename mismatch: {run_id}")
        archived_runs.append(run)
        if run.get("run_id") != run_id:
            errors.append(f"M2 report Research Run identity mismatch: {run_id}")
        if run.get("project_id") != data.get("project_id"):
            errors.append(f"M2 report Research Run project mismatch: {run_id}")
        if run.get("status") != run_ref.get("status"):
            errors.append(f"M2 report Research Run status mismatch: {run_id}")
        if run.get("cycle_id") != run_ref.get("cycle_id"):
            errors.append(f"M2 report Research Run cycle mismatch: {run_id}")
        run_limits = dict(run.get("limits", {}))
        wider_limits = sorted(
            name
            for name, admitted_value in application_research_limits.items()
            if int(run_limits.get(name, admitted_value)) > int(admitted_value)
        )
        if wider_limits:
            errors.append(
                f"M2 report Research Run exceeds application policy {run_id}: "
                + ", ".join(wider_limits)
            )
        tasks = list(run.get("tasks", []))
        if len(tasks) > int(application_research_limits.get("max_queries", 0)):
            errors.append(f"M2 report Research Run exceeds query budget: {run_id}")
        if any(
            len(str(task.get("query", "")))
            > int(application_research_limits.get("max_query_chars", 0))
            for task in tasks
        ):
            errors.append(f"M2 report Research Run exceeds query length budget: {run_id}")
        total_results = sum(int(task.get("result_count", 0)) for task in tasks)
        if total_results > int(
            application_research_limits.get("max_total_results", 0)
        ):
            errors.append(f"M2 report Research Run exceeds total result budget: {run_id}")
        if any(
            int(task.get("result_count", 0))
            > int(application_research_limits.get("max_results_per_query", 0))
            for task in tasks
        ):
            errors.append(f"M2 report Research Run exceeds per-query result budget: {run_id}")
        for task in tasks:
            raw_cache_path = task.get("cache_snapshot_path")
            raw_cache_hash = task.get("cache_snapshot_sha256")
            if raw_cache_path is None and raw_cache_hash is None:
                continue
            if raw_cache_path is None or raw_cache_hash is None:
                errors.append(
                    f"M2 report Research Run has incomplete cache reference: {run_id} {task.get('task_id')}"
                )
                continue
            try:
                cache_relative = Path(str(raw_cache_path))
                if cache_relative.is_absolute():
                    raise WorkspaceError("absolute Research cache path is not allowed")
                cache_path = ensure_within(workspace, workspace / cache_relative)
                admitted_cache_root = ensure_within(
                    workspace,
                    workspace / ".slidethus/cache/research",
                )
                if (
                    cache_path.parent.parent != admitted_cache_root
                    or cache_path.parent.name != str(task.get("input_key", ""))
                ):
                    raise WorkspaceError(
                        "Research cache snapshot must be stored under its input-key directory"
                    )
            except (OSError, ValueError, WorkspaceError) as exc:
                errors.append(
                    f"M2 report Research cache path is unsafe: {run_id} {task.get('task_id')}: {exc}"
                )
                continue
            if not cache_path.is_file():
                errors.append(
                    f"M2 report Research cache snapshot is missing: {run_id} {task.get('task_id')}"
                )
                continue
            if sha256_file(cache_path) != raw_cache_hash:
                errors.append(
                    f"M2 report Research cache hash mismatch: {run_id} {task.get('task_id')}"
                )
            try:
                cache = read_json(cache_path)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    f"M2 report Research cache cannot be read: {run_id} {task.get('task_id')}: {exc}"
                )
                continue
            if research_cache_schema is not None:
                for error in sorted(
                    Draft202012Validator(research_cache_schema).iter_errors(cache),
                    key=lambda item: list(item.absolute_path),
                ):
                    errors.append(
                        f"M2 report Research cache schema {run_id} {task.get('task_id')}:{error.json_path}:{error.message}"
                    )
            if cache_path.name != f"{sha256_json(cache)}.json":
                errors.append(
                    f"M2 report Research cache filename mismatch: {run_id} {task.get('task_id')}"
                )
            if cache.get("project_id") != data.get("project_id"):
                errors.append(
                    f"M2 report Research cache project mismatch: {run_id} {task.get('task_id')}"
                )
            if cache.get("input_key") != task.get("input_key"):
                errors.append(
                    f"M2 report Research cache input-key mismatch: {run_id} {task.get('task_id')}"
                )
            if cache.get("provider") != run.get("provider"):
                errors.append(
                    f"M2 report Research cache provider mismatch: {run_id} {task.get('task_id')}"
                )
            if cache.get("query", {}).get("query_id") != task.get("query_id"):
                errors.append(
                    f"M2 report Research cache query mismatch: {run_id} {task.get('task_id')}"
                )
            results = list(cache.get("results", []))
            result_ids = [str(item.get("result_id", "")) for item in results]
            if len(results) != int(task.get("result_count", 0)):
                errors.append(
                    f"M2 report Research cache result count mismatch: {run_id} {task.get('task_id')}"
                )
            if result_ids != list(task.get("result_ids", [])):
                errors.append(
                    f"M2 report Research cache result IDs mismatch: {run_id} {task.get('task_id')}"
                )
            if any(
                len(str(item.get("title", "")))
                > int(application_research_limits.get("max_title_chars", 0))
                for item in results
            ):
                errors.append(
                    f"M2 report Research cache exceeds title budget: {run_id} {task.get('task_id')}"
                )
            if any(
                len(str(item.get("summary", "")))
                > int(application_research_limits.get("max_summary_chars", 0))
                for item in results
            ):
                errors.append(
                    f"M2 report Research cache exceeds summary budget: {run_id} {task.get('task_id')}"
                )
            if any(
                len(canonical_json_bytes(item.get("metadata", {})))
                > int(application_research_limits.get("max_metadata_bytes", 0))
                for item in results
            ):
                errors.append(
                    f"M2 report Research cache exceeds metadata budget: {run_id} {task.get('task_id')}"
                )

    report_state: dict[str, Any] | None = None
    state_ref = next(
        (
            item
            for item in outputs.get("artifact_refs", [])
            if item.get("artifact_type") == "project_state"
        ),
        None,
    )
    if state_ref is None:
        errors.append("M2 report does not bind a Project State revision")
    else:
        try:
            report_state = _artifact_data_for_ref(workspace, state, state_ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        else:
            if report_state.get("current_phase") != outputs.get("final_phase"):
                errors.append("M2 report final_phase disagrees with bound Project State")
            summaries = {
                str(item.get("gate_id")): str(item.get("status"))
                for item in report_state.get("completed_gates", [])
            }
            reported_gates = {
                str(item.get("gate_id")): str(item.get("status"))
                for item in outputs.get("gates", [])
            }
            required_gates = _M2_PHASE_REQUIRED_GATES.get(
                str(report_state.get("current_phase")),
                (),
            )
            for gate_id in required_gates:
                if reported_gates.get(gate_id) != "pass":
                    errors.append(
                        f"M2 report omits a passing {gate_id} required by bound Project State"
                    )
                if summaries.get(gate_id) not in {"pass", "waived"}:
                    errors.append(
                        f"Bound Project State lacks accepted {gate_id} for its current phase"
                    )

    gap_data: dict[str, Any] | None = None
    raw_gap_path = outputs.get("gap_report_path")
    if raw_gap_path is not None:
        try:
            gap_relative = Path(str(raw_gap_path))
            if gap_relative.is_absolute():
                raise WorkspaceError("absolute Gap Report path is not allowed")
            gap_path = ensure_within(workspace, workspace / gap_relative)
            admitted_gap_root = ensure_within(
                workspace,
                workspace / ".slidethus/evidence/gaps",
            )
            if gap_path.parent != admitted_gap_root:
                raise WorkspaceError(
                    "Gap Report must be stored directly under .slidethus/evidence/gaps"
                )
        except (OSError, ValueError, WorkspaceError) as exc:
            errors.append(f"M2 report gap output path is unsafe: {exc}")
        else:
            if not gap_path.is_file():
                errors.append(f"M2 report gap output is missing: {raw_gap_path}")
            elif sha256_file(gap_path) != outputs.get("gap_report_sha256"):
                errors.append("M2 report gap output hash mismatch")
            else:
                try:
                    gap_data = read_json(gap_path)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"M2 report gap output cannot be read: {exc}")

    timestamps: list[str] = []
    if report_state is not None:
        artifact_entries = {
            str(item.get("artifact_type")): item
            for item in report_state.get("artifacts", [])
        }
        for reference in outputs.get("artifact_refs", []):
            artifact_type = str(reference.get("artifact_type", ""))
            if artifact_type == "project_state":
                continue
            entry = artifact_entries.get(artifact_type)
            if (
                entry is not None
                and int(entry.get("version", 0)) == int(reference.get("version", -1))
                and entry.get("updated_at")
            ):
                timestamps.append(str(entry["updated_at"]))
    timestamps.extend(
        str(run["updated_at"])
        for run in archived_runs
        if run.get("updated_at")
    )
    if gap_data is not None and gap_data.get("generated_at"):
        timestamps.append(str(gap_data["generated_at"]))
    expected_generated_at = max(timestamps) if timestamps else "1970-01-01T00:00:00Z"
    if data.get("generated_at") != expected_generated_at:
        errors.append("M2 report generated_at disagrees with bound runtime facts")
    return tuple(errors)


def inspect_m2_application_report(
    workspace: Path,
    report_id: str,
    *,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    """Locate, verify, and return one persisted M2 Application Report."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/m2/runs"
    if not root.exists():
        raise M2ApplicationReportError(f"No M2 Application Reports exist: {workspace}")
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    match: Path | None = None
    for path in sorted(root.glob("*.json")):
        try:
            data = read_json(path)
        except Exception:
            continue
        if data.get("report_id") == report_id or path.stem == report_id:
            match = path
            break
    if match is None:
        raise M2ApplicationReportError(f"Unknown M2 Application Report: {report_id}")
    errors = m2_report_reference_errors(workspace, match, admitted_schema_dir)
    if errors:
        raise M2ApplicationReportError("Invalid M2 Application Report: " + "; ".join(errors))
    return read_json(match)


def list_m2_application_reports(
    workspace: Path,
    *,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """List verified M2 Application Report summaries."""

    workspace = workspace.resolve()
    root = workspace / ".slidethus/m2/runs"
    if not root.exists():
        return ()
    admitted_schema_dir = (schema_dir or SchemaRegistry().schema_dir).resolve()
    summaries: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        errors = m2_report_reference_errors(workspace, path, admitted_schema_dir)
        if errors:
            raise M2ApplicationReportError(
                f"Invalid M2 Application Report {path.name}: " + "; ".join(errors)
            )
        data = read_json(path)
        summaries.append(
            {
                "report_id": data["report_id"],
                "status": data["status"],
                "delivery_level": data["delivery_level"],
                "mode": data["mode"],
                "generated_at": data["generated_at"],
                "final_phase": data["outputs"]["final_phase"],
                "path": path.relative_to(workspace).as_posix(),
            }
        )
    summaries.sort(key=lambda item: (str(item["generated_at"]), str(item["report_id"])))
    return tuple(summaries)


def m2_application_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    """Return validation errors for every persisted M2 Application Report."""

    report_root = workspace / ".slidethus/m2/runs"
    snapshot_root = workspace / ".slidethus/m2/research-runs"
    errors: list[tuple[str, str]] = []
    if report_root.exists():
        for entry in sorted(report_root.iterdir()):
            if not entry.is_file() or entry.suffix != ".json":
                errors.append(
                    (
                        entry.relative_to(workspace).as_posix(),
                        "unexpected entry in M2 Application Report directory",
                    )
                )
        for path in sorted(report_root.glob("*.json")):
            relative = path.relative_to(workspace).as_posix()
            for error in m2_report_reference_errors(workspace, path, schema_dir):
                errors.append((relative, error))

    if snapshot_root.exists():
        research_schema_path = schema_dir / "research_run.schema.json"
        research_schema = (
            read_json(research_schema_path) if research_schema_path.is_file() else None
        )
        state = read_json(workspace / "project_state.json")
        for entry in sorted(snapshot_root.iterdir()):
            relative = entry.relative_to(workspace).as_posix()
            if (
                not entry.is_file()
                or entry.suffix != ".json"
                or re.fullmatch(r"[a-f0-9]{64}\.json", entry.name) is None
            ):
                errors.append(
                    (relative, "unexpected entry in M2 Research Run snapshot directory")
                )
                continue
            try:
                run = read_json(entry)
            except Exception as exc:  # noqa: BLE001
                errors.append((relative, f"Research Run snapshot cannot be read: {exc}"))
                continue
            if entry.name != f"{sha256_json(run)}.json":
                errors.append((relative, "Research Run snapshot filename mismatch"))
            if run.get("project_id") != state.get("project_id"):
                errors.append((relative, "Research Run snapshot project_id mismatch"))
            if research_schema is None:
                errors.append((relative, "research_run.schema.json is missing"))
            else:
                for error in sorted(
                    Draft202012Validator(research_schema).iter_errors(run),
                    key=lambda item: list(item.absolute_path),
                ):
                    errors.append(
                        (
                            relative,
                            f"Research Run snapshot schema:{error.json_path}:{error.message}",
                        )
                    )
    return tuple(errors)
