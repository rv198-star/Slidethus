from __future__ import annotations

import copy
import time
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from jsonschema import Draft202012Validator

from slidethus.errors import WorkflowApplicationError
from slidethus.io_utils import (
    atomic_create_json,
    ensure_within,
    read_json,
    sha256_file,
    sha256_json,
)

try:  # pragma: no cover - platform boundary
    import fcntl
except ImportError:  # pragma: no cover - platform boundary
    fcntl = None  # type: ignore[assignment]


@dataclass(frozen=True)
class WorkflowOperationalLimits:
    max_input_bytes: int = 100 * 1024 * 1024
    max_slide_updates: int = 64
    max_wall_seconds: int = 900
    max_cache_age_seconds: int = 24 * 60 * 60
    max_provider_cost_usd: float | None = None

    def validate(self) -> None:
        if not 1 <= self.max_input_bytes <= 10 * 1024 * 1024 * 1024:
            raise WorkflowApplicationError("max_input_bytes must be between 1 byte and 10 GiB")
        if not 1 <= self.max_slide_updates <= 999:
            raise WorkflowApplicationError("max_slide_updates must be between 1 and 999")
        if not 1 <= self.max_wall_seconds <= 24 * 60 * 60:
            raise WorkflowApplicationError("max_wall_seconds must be between 1 second and 24 hours")
        if not 0 <= self.max_cache_age_seconds <= 30 * 24 * 60 * 60:
            raise WorkflowApplicationError("max_cache_age_seconds must be between 0 and 30 days")
        if self.max_provider_cost_usd is not None and not 0 <= self.max_provider_cost_usd <= 1_000_000:
            raise WorkflowApplicationError("max_provider_cost_usd must be between 0 and 1000000")


class WorkflowLease(AbstractContextManager["WorkflowLease"]):
    """Non-blocking workspace-level exclusive lease for one product workflow."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.path = self.workspace.parent / f".{self.workspace.name}.slidethus-workflow.lock"
        self._handle: BinaryIO | None = None

    def __enter__(self) -> WorkflowLease:
        if fcntl is None:
            raise WorkflowApplicationError(
                "Workflow exclusive lease is unavailable on this platform"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise WorkflowApplicationError(
                "Another product workflow already holds the workspace lease"
            ) from exc
        self._handle = handle
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


_TERMINAL_EVENT_TYPES = {"recovered", "cache_hit", "blocked", "completed", "failed"}


def workflow_attempt_id(
    project_id: str,
    workflow: str,
    request_hash: str,
    execution_signature: str,
    started_at: str,
) -> str:
    payload = {
        "project_id": project_id,
        "workflow": workflow,
        "request_hash": request_hash,
        "execution_signature": execution_signature,
        "started_at": started_at,
    }
    return "WAT-" + sha256_json(payload)[:16].upper()


def workflow_event_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("event_id", None)
    return payload


def workflow_event_id(data: dict[str, Any]) -> str:
    return "WEV-" + sha256_json(workflow_event_identity_payload(data))[:16].upper()


def workflow_event_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def _event_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "workflow_event.schema.json"
    if not path.is_file():
        raise WorkflowApplicationError(f"Missing Workflow Event schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_workflow_event_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_event_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("event_id") != workflow_event_id(data):
        errors.append("Workflow Event identity mismatch")
    if data.get("event_type") == "started" and int(data.get("sequence", 0)) != 1:
        errors.append("Workflow started event must use sequence=1")
    if data.get("event_type") == "started" and data.get("operation_id") is not None:
        errors.append("Workflow started event cannot reference an operation")
    return tuple(errors)


def persist_workflow_event(
    workspace: Path,
    *,
    schema_dir: Path,
    project_id: str,
    attempt_id: str,
    workflow: str,
    request_hash: str,
    execution_signature: str,
    event_type: str,
    sequence: int,
    detail: str,
    operation_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    event: dict[str, Any] = {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "event_id": "",
        "attempt_id": attempt_id,
        "workflow": workflow,
        "request_hash": request_hash,
        "execution_signature": execution_signature,
        "event_type": event_type,
        "occurred_at": utc_now(),
        "sequence": sequence,
        "detail": " ".join(str(detail).split()).strip(),
        "operation_id": operation_id,
    }
    event["event_id"] = workflow_event_id(event)
    errors = validate_workflow_event_data(event, schema_dir)
    if errors:
        raise WorkflowApplicationError("Invalid Workflow Event: " + "; ".join(errors))
    root = workspace / ".slidethus/workflows/events"
    path = root / f"{workflow_event_file_key(event)}.json"
    created = atomic_create_json(path, event)
    if not created and read_json(path) != event:
        raise WorkflowApplicationError(f"Immutable Workflow Event conflict: {path}")
    return path, event


def workflow_operation_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("operation_id", None)
    return payload


def workflow_operation_id(data: dict[str, Any]) -> str:
    return "WOP-" + sha256_json(workflow_operation_identity_payload(data))[:16].upper()


def workflow_operation_file_key(data: dict[str, Any]) -> str:
    return sha256_json(data)


def _schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "workflow_operation_report.schema.json"
    if not path.is_file():
        raise WorkflowApplicationError(f"Missing Workflow Operation schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_workflow_operation_data(
    data: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("operation_id") != workflow_operation_id(data):
        errors.append("Workflow Operation identity mismatch")
    limits = data.get("limits", {})
    metrics = data.get("metrics", {})
    if int(metrics.get("input_bytes", 0)) > int(limits.get("max_input_bytes", 0)):
        if not any(item.get("code") == "workflow_input_budget_exceeded" for item in data.get("blockers", [])):
            errors.append("Input budget overflow requires an explicit blocker")
    if int(metrics.get("slide_updates", 0)) > int(limits.get("max_slide_updates", 0)):
        if not any(item.get("code") == "workflow_slide_update_budget_exceeded" for item in data.get("blockers", [])):
            errors.append("Slide-update budget overflow requires an explicit blocker")
    if data.get("status") == "ready" and data.get("blockers"):
        errors.append("Ready Workflow Operation cannot contain blockers")
    if data.get("status") in {"ready", "blocked"} and data.get("workflow_report") is None:
        errors.append("Ready/blocked Workflow Operation requires a Workflow Application Report")
    provider_cost = metrics.get("provider_cost_usd")
    cost_limit = limits.get("max_provider_cost_usd")
    if (
        provider_cost is not None
        and cost_limit is not None
        and float(provider_cost) > float(cost_limit)
        and not any(
            item.get("code") == "workflow_provider_cost_budget_exceeded"
            for item in data.get("blockers", [])
        )
    ):
        errors.append("Provider cost overflow requires an explicit blocker")
    if (
        int(data.get("duration_ms", 0)) > int(limits.get("max_wall_seconds", 0)) * 1000
        and data.get("status") == "ready"
    ):
        errors.append("Ready Workflow Operation exceeds the admitted wall-time budget")
    return tuple(errors)


def persist_workflow_operation(
    workspace: Path,
    *,
    schema_dir: Path,
    project_id: str,
    attempt_id: str,
    workflow: str,
    request_hash: str,
    execution_signature: str,
    status: str,
    cache_status: str,
    started_at: str,
    started_monotonic_ns: int,
    limits: WorkflowOperationalLimits,
    input_bytes: int,
    slide_updates: int,
    workflow_result: Any | None,
    blockers: list[dict[str, str]],
    provider_cost_usd: float | None,
    provider_cost_status: str,
) -> Path:
    finished = utc_now()
    duration_ms = max(0, int((time.monotonic_ns() - started_monotonic_ns) / 1_000_000))
    report_ref = None
    actions = outputs = changed = 0
    if workflow_result is not None:
        actions = len(workflow_result.report.get("actions", []))
        outputs = len(workflow_result.report.get("outputs", []))
        changed = len(workflow_result.report.get("changed_artifacts", []))
        report_ref = {
            "report_id": str(workflow_result.report["report_id"]),
            "path": workflow_result.path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(workflow_result.path),
        }
    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "operation_id": "",
        "attempt_id": attempt_id,
        "workflow": workflow,
        "request_hash": request_hash,
        "execution_signature": execution_signature,
        "status": status,
        "cache_status": cache_status,
        "started_at": started_at,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "limits": asdict(limits),
        "metrics": {
            "input_bytes": input_bytes,
            "slide_updates": slide_updates,
            "actions": actions,
            "outputs": outputs,
            "changed_artifacts": changed,
            "provider_cost_usd": provider_cost_usd,
            "provider_cost_status": provider_cost_status,
        },
        "lease": {"mode": "exclusive", "status": "acquired"},
        "workflow_report": report_ref,
        "blockers": blockers,
    }
    report["operation_id"] = workflow_operation_id(report)
    errors = validate_workflow_operation_data(report, schema_dir)
    if errors:
        raise WorkflowApplicationError(
            "Invalid Workflow Operation Report: " + "; ".join(errors)
        )
    root = workspace / ".slidethus/workflows/operations"
    path = root / f"{workflow_operation_file_key(report)}.json"
    created = atomic_create_json(path, report)
    if not created and read_json(path) != report:
        raise WorkflowApplicationError(f"Immutable Workflow Operation conflict: {path}")
    return path


def workflow_operation_reference_errors(
    workspace: Path,
    path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    try:
        report = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return (f"Workflow Operation cannot be read: {exc}",)
    errors = list(validate_workflow_operation_data(report, schema_dir))
    if path.name != f"{workflow_operation_file_key(report)}.json":
        errors.append("Workflow Operation filename/content hash mismatch")
    if report.get("project_id") != read_json(workspace / "project_state.json").get("project_id"):
        errors.append("Workflow Operation project_id mismatch")
    ref = report.get("workflow_report")
    if isinstance(ref, dict):
        try:
            relative = Path(str(ref.get("path", "")))
            if relative.is_absolute():
                raise WorkflowApplicationError("absolute workflow report path")
            target = ensure_within(workspace, workspace / relative)
            root = ensure_within(workspace, workspace / ".slidethus/workflows/runs")
            if root not in target.parents:
                raise WorkflowApplicationError("workflow report ref is outside runs root")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Workflow Operation report ref is unsafe: {exc}")
        else:
            if not target.is_file():
                errors.append("Workflow Operation report ref is missing")
            elif sha256_file(target) != ref.get("sha256"):
                errors.append("Workflow Operation report ref hash mismatch")
            else:
                data = read_json(target)
                if str(data.get("report_id")) != str(ref.get("report_id")):
                    errors.append("Workflow Operation report ref identity mismatch")
                if data.get("workflow") != report.get("workflow"):
                    errors.append("Workflow Operation workflow disagrees with Workflow Report")
                if data.get("request_hash") != report.get("request_hash"):
                    errors.append("Workflow Operation request hash disagrees with Workflow Report")
                if data.get("status") != report.get("status"):
                    errors.append("Workflow Operation status disagrees with Workflow Report")
                metrics = report.get("metrics", {})
                expected_metrics = {
                    "actions": len(data.get("actions", [])),
                    "outputs": len(data.get("outputs", [])),
                    "changed_artifacts": len(data.get("changed_artifacts", [])),
                }
                for field, expected in expected_metrics.items():
                    if int(metrics.get(field, -1)) != expected:
                        errors.append(f"Workflow Operation metric disagrees with Workflow Report: {field}")
    attempt_id = str(report.get("attempt_id", ""))
    event_root = workspace / ".slidethus/workflows/events"
    bound_events: list[dict[str, Any]] = []
    if event_root.exists():
        for candidate in event_root.glob("*.json"):
            try:
                event = read_json(candidate)
            except Exception:  # noqa: BLE001
                continue
            if event.get("attempt_id") == attempt_id:
                bound_events.append(event)
    starts = [event for event in bound_events if event.get("event_type") == "started"]
    terminals = [
        event for event in bound_events if event.get("event_type") in _TERMINAL_EVENT_TYPES
    ]
    if len(starts) != 1:
        errors.append("Workflow Operation attempt must bind exactly one started event")
    if len(terminals) != 1:
        errors.append("Workflow Operation attempt must bind exactly one terminal event")
    else:
        terminal = terminals[0]
        if terminal.get("operation_id") != report.get("operation_id"):
            errors.append("Workflow Operation terminal event identity mismatch")
        expected_terminal = {
            ("ready", "hit"): "cache_hit",
            ("ready", "miss"): "completed",
            ("blocked", "miss"): "blocked",
            ("failed", "miss"): "failed",
        }.get((str(report.get("status")), str(report.get("cache_status"))))
        if expected_terminal is not None and terminal.get("event_type") != expected_terminal:
            errors.append("Workflow Operation terminal event type disagrees with operation status")
    return tuple(errors)


def workflow_operation_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/workflows/operations"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Workflow Operation directory"))
            continue
        for message in workflow_operation_reference_errors(workspace, entry, schema_dir):
            errors.append((relative, message))
    return tuple(errors)


def workflow_event_reference_errors(
    workspace: Path,
    path: Path,
    schema_dir: Path,
) -> tuple[str, ...]:
    try:
        event = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return (f"Workflow Event cannot be read: {exc}",)
    errors = list(validate_workflow_event_data(event, schema_dir))
    if path.name != f"{workflow_event_file_key(event)}.json":
        errors.append("Workflow Event filename/content hash mismatch")
    state = read_json(workspace / "project_state.json")
    if event.get("project_id") != state.get("project_id"):
        errors.append("Workflow Event project_id mismatch")
    operation_id = event.get("operation_id")
    if operation_id is not None:
        operation = None
        for candidate in (workspace / ".slidethus/workflows/operations").glob("*.json"):
            try:
                candidate_data = read_json(candidate)
            except Exception:  # noqa: BLE001
                continue
            if candidate_data.get("operation_id") == operation_id:
                operation = candidate_data
                break
        if operation is None:
            errors.append("Workflow Event references unknown operation")
        elif operation.get("attempt_id") != event.get("attempt_id"):
            errors.append("Workflow Event and Operation bind different attempts")
    return tuple(errors)


def workflow_event_workspace_errors(
    workspace: Path,
    schema_dir: Path,
) -> tuple[tuple[str, str], ...]:
    root = workspace / ".slidethus/workflows/events"
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    by_attempt: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for entry in sorted(root.iterdir()):
        relative = entry.relative_to(workspace).as_posix()
        if not entry.is_file() or entry.suffix != ".json":
            errors.append((relative, "unexpected entry in Workflow Event directory"))
            continue
        messages = workflow_event_reference_errors(workspace, entry, schema_dir)
        errors.extend((relative, message) for message in messages)
        if messages:
            continue
        event = read_json(entry)
        by_attempt.setdefault(str(event["attempt_id"]), []).append((entry, event))
    for attempt_id, rows in by_attempt.items():
        events = [event for _path, event in rows]
        starts = [event for event in events if event.get("event_type") == "started"]
        terminals = [
            event for event in events if event.get("event_type") in _TERMINAL_EVENT_TYPES
        ]
        sequences = [int(event.get("sequence", 0)) for event in events]
        relative = rows[0][0].relative_to(workspace).as_posix()
        if len(starts) != 1:
            errors.append((relative, f"Workflow attempt {attempt_id} must have exactly one started event"))
        if len(terminals) > 1:
            errors.append((relative, f"Workflow attempt {attempt_id} cannot have multiple terminal events"))
        if len(sequences) != len(set(sequences)) or sorted(sequences) != list(
            range(1, len(sequences) + 1)
        ):
            errors.append((relative, f"Workflow attempt {attempt_id} event sequences are not contiguous"))
    return tuple(errors)


def recover_incomplete_workflow_attempts(
    workspace: Path,
    *,
    schema_dir: Path,
) -> tuple[dict[str, str], ...]:
    """Close orphaned attempts after the caller has acquired the workspace lease."""

    root = workspace / ".slidethus/workflows/events"
    if not root.exists():
        return ()
    events: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        messages = workflow_event_reference_errors(workspace, path, schema_dir)
        if messages:
            raise WorkflowApplicationError(
                f"Cannot recover invalid Workflow Event {path.name}: " + "; ".join(messages)
            )
        events.append(read_json(path))
    by_attempt: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_attempt.setdefault(str(event["attempt_id"]), []).append(event)
    operation_root = workspace / ".slidethus/workflows/operations"
    operations = [
        read_json(path) for path in sorted(operation_root.glob("*.json"))
    ] if operation_root.exists() else []
    recovered: list[dict[str, str]] = []
    for attempt_id, rows in sorted(by_attempt.items()):
        if not any(item.get("event_type") == "started" for item in rows):
            continue
        if any(item.get("event_type") in _TERMINAL_EVENT_TYPES for item in rows):
            continue
        started = next(item for item in rows if item.get("event_type") == "started")
        operation = next(
            (item for item in operations if item.get("attempt_id") == attempt_id),
            None,
        )
        if operation is None:
            event_type = "recovered"
            operation_id = None
            detail = (
                "Recovered an interrupted workflow attempt after reacquiring the exclusive lease; "
                "no terminal Workflow Operation had been persisted."
            )
        else:
            status = str(operation.get("status"))
            event_type = {
                "ready": "cache_hit" if operation.get("cache_status") == "hit" else "completed",
                "blocked": "blocked",
                "failed": "failed",
            }.get(status, "recovered")
            operation_id = str(operation.get("operation_id"))
            detail = f"Recovered missing terminal event from persisted operation {operation_id}."
        persist_workflow_event(
            workspace,
            schema_dir=schema_dir,
            project_id=str(started["project_id"]),
            attempt_id=attempt_id,
            workflow=str(started["workflow"]),
            request_hash=str(started["request_hash"]),
            execution_signature=str(started["execution_signature"]),
            event_type=event_type,
            sequence=max(int(item.get("sequence", 0)) for item in rows) + 1,
            detail=detail,
            operation_id=operation_id,
        )
        recovered.append(
            {
                "attempt_id": attempt_id,
                "workflow": str(started["workflow"]),
                "request_hash": str(started["request_hash"]),
                "execution_signature": str(started["execution_signature"]),
            }
        )
    return tuple(recovered)


def current_workflow_report_matches(
    workspace: Path,
    report: dict[str, Any],
) -> bool:
    state_path = workspace / "project_state.json"
    if not state_path.is_file():
        return False
    state = read_json(state_path)
    entries = {str(item.get("artifact_type")): item for item in state.get("artifacts", [])}
    for ref in report.get("artifacts_after", []):
        entry = entries.get(str(ref.get("artifact_type")))
        if entry is None:
            return False
        if int(entry.get("version", 0)) != int(ref.get("version", -1)):
            return False
        if str(entry.get("content_hash")) != str(ref.get("content_hash")):
            return False
    return True


def find_cached_workflow_result(
    workspace: Path,
    *,
    schema_dir: Path,
    request_hash: str,
    execution_signature: str,
    max_age_seconds: int,
) -> tuple[Path, dict[str, Any]] | None:
    if max_age_seconds <= 0:
        return None
    operation_root = workspace / ".slidethus/workflows/operations"
    if not operation_root.exists():
        return None
    now = datetime.now(UTC)
    candidates: list[tuple[str, dict[str, Any]]] = []
    for path in operation_root.glob("*.json"):
        if workflow_operation_reference_errors(workspace, path, schema_dir):
            continue
        try:
            operation = read_json(path)
            finished = datetime.fromisoformat(
                str(operation.get("finished_at", "")).replace("Z", "+00:00")
            )
            if finished.tzinfo is None:
                continue
            age_seconds = (now - finished).total_seconds()
        except (TypeError, ValueError):
            continue
        if (
            0 <= age_seconds <= max_age_seconds
            and operation.get("status") == "ready"
            and operation.get("request_hash") == request_hash
            and operation.get("execution_signature") == execution_signature
            and isinstance(operation.get("workflow_report"), dict)
        ):
            candidates.append((str(operation.get("finished_at", "")), operation))
    for _finished, operation in sorted(candidates, reverse=True):
        ref = operation["workflow_report"]
        relative = Path(str(ref["path"]))
        if relative.is_absolute():
            continue
        report_path = workspace / relative
        if not report_path.is_file() or sha256_file(report_path) != ref.get("sha256"):
            continue
        report = read_json(report_path)
        if current_workflow_report_matches(workspace, report):
            return report_path, report
    return None
