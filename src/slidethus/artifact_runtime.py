from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from slidethus.constants import PROJECT_STATE_SCHEMA_VERSION, SCHEMA_VERSION
from slidethus.errors import (
    ArtifactConflictError,
    ArtifactError,
    GateError,
    MigrationError,
    RecoveryError,
)
from slidethus.gate_contracts import GATE_REQUIRED_PATHS
from slidethus.gates import GateResult, evaluate_gate
from slidethus.io_utils import (
    atomic_write_json,
    ensure_within,
    read_json,
    sha256_bytes,
    sha256_file,
    sha256_json,
)
from slidethus.migrations import DEFAULT_MIGRATIONS, MigrationRegistry
from slidethus.schema_registry import SchemaRegistry
from slidethus.state_machine import FORWARD_SEQUENCE, Phase, require_transition
from slidethus.validation import ValidationReport, validate_workspace

try:  # pragma: no cover - platform-specific import
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - platform-specific import
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]


FaultInjector = Callable[[str, Path, int], None]

ARTIFACT_PHASE: dict[str, tuple[Phase, str]] = {
    "project_brief": (Phase.CREATED, "G0"),
    "source_ledger": (Phase.BRIEF_READY, "G1"),
    "evidence_ledger": (Phase.SOURCES_READY, "G2"),
    "narrative_blueprint": (Phase.EVIDENCE_READY, "G3"),
    "deck_outline": (Phase.NARRATIVE_READY, "G4"),
    "slide_specs": (Phase.OUTLINE_READY, "G5A"),
    "layout_plans": (Phase.SLIDE_SPECS_READY, "G5B"),
    "visual_system": (Phase.LAYOUT_READY, "G6"),
    "render_manifest": (Phase.VISUAL_SYSTEM_READY, "G7"),
    "quality_report": (Phase.DRAFT_RENDERED, "G8"),
    "delivery_manifest": (Phase.REVIEWED, "G9"),
}

GATE_ORDER = ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7", "G8", "G9")
GATE_PREDECESSOR = {gate: phase for phase, gate in ARTIFACT_PHASE.values()}


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def artifact_id(project_id: str, artifact_type: str) -> str:
    """Return a stable artifact ID derived from project and type."""

    digest = hashlib.sha256(f"{project_id}:{artifact_type}".encode()).hexdigest()[:16].upper()
    return f"ART-{digest}"


def _json_file_hash(data: Any) -> str:
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return sha256_bytes(payload)


def build_artifact_entry(
    *,
    project_id: str,
    artifact_type: str,
    path: str,
    schema: str,
    schema_version: str,
    version: int,
    status: str,
    data: dict[str, Any],
    created_by: str,
    created_at: str,
    updated_at: str | None = None,
    supersedes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical registry metadata for one artifact version."""

    return {
        "artifact_id": artifact_id(project_id, artifact_type),
        "artifact_type": artifact_type,
        "project_id": project_id,
        "path": path,
        "schema": schema,
        "schema_version": schema_version,
        "version": version,
        "status": status,
        "sha256": _json_file_hash(data),
        "content_hash": f"sha256:{sha256_json(data)}",
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "created_by": created_by,
        "supersedes": supersedes,
    }


class _WorkspaceLock(AbstractContextManager["_WorkspaceLock"]):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def __enter__(self) -> _WorkspaceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                self._handle.write("\0")
                self._handle.flush()
            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._handle is not None:
            if fcntl is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            self._handle.close()


class ArtifactRuntime:
    """Versioned, optimistic-locking artifact registry with crash recovery."""

    def __init__(
        self,
        workspace: Path,
        *,
        registry: SchemaRegistry | None = None,
        migrations: MigrationRegistry | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.registry = registry or SchemaRegistry()
        self.migrations = migrations or DEFAULT_MIGRATIONS
        self.fault_injector = fault_injector
        self.runtime_dir = self.workspace / ".slidethus"
        self.transactions_dir = self.runtime_dir / "transactions"
        self.history_dir = self.runtime_dir / "history"
        self.lock_path = self.runtime_dir / "runtime.lock"
        if not (self.workspace / "project_state.json").exists():
            raise ArtifactError(f"Missing project_state.json: {self.workspace}")

    def _lock(self) -> _WorkspaceLock:
        return _WorkspaceLock(self.lock_path)

    def _pending_journals(self) -> list[Path]:
        if not self.transactions_dir.exists():
            return []
        return sorted(path for path in self.transactions_dir.glob("*.json") if path.is_file())

    def _restore_journal(self, journal: dict[str, Any]) -> None:
        for item in reversed(journal.get("files", [])):
            target = ensure_within(self.workspace, self.workspace / item["path"])
            if item["before_exists"]:
                atomic_write_json(target, item["before"])
            elif target.exists():
                target.unlink()

    def _archive_journal(self, path: Path, status: str) -> None:
        archive_dir = self.transactions_dir / status
        archive_dir.mkdir(parents=True, exist_ok=True)
        journal = read_json(path)
        summary = {
            "transaction_id": journal.get("transaction_id", path.stem),
            "status": status,
            "created_at": journal.get("created_at"),
            "paths": [item.get("path") for item in journal.get("files", [])],
        }
        archive_path = archive_dir / path.name
        os.replace(path, archive_path)
        atomic_write_json(archive_path, summary)

    def _recover_unlocked(self) -> tuple[str, ...]:
        recovered: list[str] = []
        for journal_path in self._pending_journals():
            try:
                journal = read_json(journal_path)
                all_after = all(
                    (self.workspace / item["path"]).exists()
                    and read_json(self.workspace / item["path"]) == item["after"]
                    for item in journal.get("files", [])
                )
                transaction_id = str(journal.get("transaction_id", journal_path.stem))
                if all_after:
                    report = validate_workspace(self.workspace, self.registry, check_hashes=True)
                    if report.ok:
                        self._archive_journal(journal_path, "committed")
                        recovered.append(f"{transaction_id}:commit-confirmed")
                    else:
                        self._restore_journal(journal)
                        self._archive_journal(journal_path, "rolled-back")
                        recovered.append(f"{transaction_id}:rolled-back")
                else:
                    self._restore_journal(journal)
                    self._archive_journal(journal_path, "rolled-back")
                    recovered.append(f"{transaction_id}:rolled-back")
            except Exception as exc:  # noqa: BLE001
                raise RecoveryError(f"Cannot recover {journal_path}: {exc}") from exc
        return tuple(recovered)

    def recover(self) -> tuple[str, ...]:
        """Resolve every interrupted journal before new work."""

        with self._lock():
            return self._recover_unlocked()

    def _commit(
        self,
        files: dict[Path, dict[str, Any]],
        *,
        validate_after_write: bool = True,
    ) -> None:
        transaction_id = uuid.uuid4().hex
        journal_path = self.transactions_dir / f"{transaction_id}.json"
        journal_files = []
        for target, after in files.items():
            target = ensure_within(self.workspace, target)
            journal_files.append(
                {
                    "path": target.relative_to(self.workspace).as_posix(),
                    "before_exists": target.exists(),
                    "before": read_json(target) if target.exists() else None,
                    "after": after,
                }
            )
        journal = {
            "transaction_id": transaction_id,
            "status": "prepared",
            "created_at": utc_now(),
            "files": journal_files,
        }
        atomic_write_json(journal_path, journal)
        try:
            for index, item in enumerate(journal_files, start=1):
                target = self.workspace / item["path"]
                atomic_write_json(target, item["after"])
                if self.fault_injector is not None:
                    self.fault_injector("after_write", target, index)
            if validate_after_write:
                report = validate_workspace(self.workspace, self.registry, check_hashes=True)
                if not report.ok:
                    codes = ", ".join(issue.code for issue in report.issues if issue.severity == "error")
                    raise ArtifactError(f"Transaction would leave an invalid workspace: {codes}")
        except Exception:
            self._restore_journal(journal)
            self._archive_journal(journal_path, "rolled-back")
            raise
        self._archive_journal(journal_path, "committed")

    def _state(self) -> dict[str, Any]:
        return read_json(self.workspace / "project_state.json")

    @staticmethod
    def _entry(state: dict[str, Any], artifact_type: str) -> dict[str, Any] | None:
        return next(
            (item for item in state.get("artifacts", []) if item.get("artifact_type") == artifact_type),
            None,
        )

    def list_artifacts(self) -> tuple[dict[str, Any], ...]:
        """List registry metadata without reading artifact bodies."""

        with self._lock():
            self._recover_unlocked()
            state = self._state()
            return self._list_artifacts_unlocked(state)

    def _list_artifacts_unlocked(self, state: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        state_entry = {
            "artifact_id": artifact_id(state["project_id"], "project_state"),
            "artifact_type": "project_state",
            "project_id": state["project_id"],
            "path": "project_state.json",
            "schema": "project_state.schema.json",
            "schema_version": state["schema_version"],
            "version": state["revision"],
            "status": "approved",
            "sha256": sha256_file(self.workspace / "project_state.json"),
            "content_hash": f"sha256:{sha256_json(state)}",
        }
        return tuple(sorted([*state.get("artifacts", []), state_entry], key=lambda item: item["artifact_type"]))

    def show_artifact(self, artifact_type: str, *, version: int | None = None) -> dict[str, Any]:
        """Read the current or an immutable prior artifact version."""

        with self._lock():
            self._recover_unlocked()
            return self._show_artifact_unlocked(artifact_type, version=version)

    def read_artifact_snapshot(self, artifact_type: str) -> tuple[dict[str, Any], int]:
        """Atomically read the current artifact body together with its optimistic-lock version."""

        with self._lock():
            self._recover_unlocked()
            state = self._state()
            if artifact_type == "project_state":
                return state, int(state["revision"])
            entry = self._entry(state, artifact_type)
            if entry is None:
                raise ArtifactError(f"Artifact is not registered: {artifact_type}")
            return read_json(self.workspace / entry["path"]), int(entry["version"])

    def read_artifact_graph_snapshot(
        self,
        artifact_types: tuple[str, ...],
        *,
        optional_artifact_types: tuple[str, ...] = (),
    ) -> dict[str, dict[str, Any]]:
        """Read several current artifacts and registry facts under one workspace lock."""

        if len(artifact_types) != len(set(artifact_types)):
            raise ArtifactError("Artifact graph snapshot contains duplicate artifact types")
        optional = set(optional_artifact_types)
        if not optional.issubset(set(artifact_types)):
            raise ArtifactError("Optional artifact types must be included in the graph request")
        with self._lock():
            self._recover_unlocked()
            state = self._state()
            snapshots: dict[str, dict[str, Any]] = {}
            for artifact_type in artifact_types:
                if artifact_type == "project_state":
                    snapshots[artifact_type] = {
                        "data": copy.deepcopy(state),
                        "version": int(state["revision"]),
                        "content_hash": f"sha256:{sha256_json(state)}",
                        "updated_at": None,
                        "status": "approved",
                    }
                    continue
                entry = self._entry(state, artifact_type)
                if entry is None:
                    if artifact_type in optional:
                        continue
                    raise ArtifactError(f"Artifact is not registered: {artifact_type}")
                snapshots[artifact_type] = {
                    "data": read_json(self.workspace / entry["path"]),
                    "version": int(entry["version"]),
                    "content_hash": str(entry["content_hash"]),
                    "updated_at": str(entry["updated_at"]),
                    "status": str(entry["status"]),
                }
            return snapshots

    def _show_artifact_unlocked(
        self, artifact_type: str, *, version: int | None = None
    ) -> dict[str, Any]:
        state = self._state()
        if artifact_type == "project_state":
            current_revision = int(state["revision"])
            if version is None or version == current_revision:
                return state
            history_path = self.history_dir / "project_state" / f"{version:06d}.json"
            if not history_path.exists():
                raise ArtifactError(f"Missing project_state revision: {version}")
            return read_json(history_path)
        entry = self._entry(state, artifact_type)
        if entry is None:
            raise ArtifactError(f"Artifact is not registered: {artifact_type}")
        current_version = int(entry["version"])
        if version is None or version == current_version:
            return read_json(self.workspace / entry["path"])
        if version < 1 or version > current_version:
            raise ArtifactError(f"Unknown {artifact_type} version: {version}")
        history_path = self.history_dir / artifact_type / f"{version:06d}.json"
        if not history_path.exists():
            raise ArtifactError(f"Missing history snapshot: {artifact_type} v{version}")
        return read_json(history_path)

    def validate(self, artifact_type: str | None = None) -> ValidationReport:
        """Validate one artifact schema or the complete workspace graph."""

        with self._lock():
            self._recover_unlocked()
            if artifact_type is None:
                return validate_workspace(self.workspace, self.registry, check_hashes=True)
            entry = self.registry.entry(artifact_type)
            path = self.workspace / entry.default_path
            report = ValidationReport()
            if not path.exists():
                report.add("missing_artifact", f"Artifact does not exist: {artifact_type}", entry.default_path.as_posix())
                return report
            data = read_json(path)
            for error in self.registry.validator(artifact_type).iter_errors(data):
                report.add("schema_error", error.message, entry.default_path.as_posix())
            if artifact_type == "project_state":
                return report
            state_entry = self._entry(self._state(), artifact_type)
            if state_entry is None:
                report.add("unregistered_artifact", f"Artifact is not registered: {artifact_type}", "project_state.json")
            elif state_entry.get("sha256") != sha256_file(path):
                report.add("artifact_hash_mismatch", f"Hash mismatch for {artifact_type}", "project_state.json")
            return report

    def _prepare_artifact_update(
        self,
        state: dict[str, Any],
        artifact_type: str,
        data: dict[str, Any],
        *,
        expected_version: int,
        status: str,
        created_by: str,
    ) -> tuple[dict[Path, dict[str, Any]], dict[str, Any], dict[str, Any]]:
        if artifact_type == "project_state":
            raise ArtifactError("project_state is managed by runtime transactions, not artifact writes")
        catalog_entry = self.registry.entry(artifact_type)
        errors = list(self.registry.validator(artifact_type).iter_errors(data))
        if errors:
            raise ArtifactError(f"Schema validation failed for {artifact_type}: {errors[0].message}")
        if data.get("project_id") != state.get("project_id"):
            raise ArtifactError(f"Project ID mismatch for {artifact_type}")
        current = self._entry(state, artifact_type)
        path = self.workspace / catalog_entry.default_path
        files: dict[Path, dict[str, Any]] = {}
        now = utc_now()
        if current is None:
            if expected_version != 0:
                raise ArtifactConflictError(f"Expected absent {artifact_type}, got expected_version={expected_version}")
            version = 1
            created_at = now
            supersedes = None
        else:
            current_version = int(current["version"])
            if current_version != expected_version:
                raise ArtifactConflictError(
                    f"Version conflict for {artifact_type}: expected {expected_version}, current {current_version}"
                )
            if not path.exists() or current.get("sha256") != sha256_file(path):
                raise ArtifactConflictError(f"Registered hash conflict for {artifact_type}; migrate or reconcile manual edits")
            version = current_version + 1
            created_at = str(current["created_at"])
            supersedes = {"artifact_id": current["artifact_id"], "version": current_version}
            history_path = self.history_dir / artifact_type / f"{current_version:06d}.json"
            if history_path.exists() and read_json(history_path) != read_json(path):
                raise ArtifactConflictError(f"History snapshot conflict for {artifact_type} v{current_version}")
            if not history_path.exists():
                files[history_path] = read_json(path)
        new_entry = build_artifact_entry(
            project_id=state["project_id"],
            artifact_type=artifact_type,
            path=catalog_entry.default_path.as_posix(),
            schema=catalog_entry.schema_path.name,
            schema_version=str(data["schema_version"]),
            version=version,
            status=status,
            data=data,
            created_by=created_by,
            created_at=created_at,
            updated_at=now,
            supersedes=supersedes,
        )
        candidate_state = copy.deepcopy(state)
        candidate_state["revision"] = int(candidate_state.get("revision", 0)) + 1
        state_history = self.history_dir / "project_state" / f"{int(state.get('revision', 1)):06d}.json"
        if not state_history.exists():
            files[state_history] = state
        if current is None:
            candidate_state["artifacts"].append(new_entry)
        else:
            candidate_state["artifacts"] = [
                new_entry if item.get("artifact_type") == artifact_type else item
                for item in candidate_state["artifacts"]
            ]
        files[path] = data
        return files, candidate_state, new_entry

    @staticmethod
    def _invalidate_downstream(state: dict[str, Any], artifact_type: str) -> None:
        contract = ARTIFACT_PHASE.get(artifact_type)
        if contract is None:
            return
        predecessor, produced_gate = contract
        invalid_gate_index = GATE_ORDER.index(produced_gate)
        state["completed_gates"] = [
            item
            for item in state.get("completed_gates", [])
            if GATE_ORDER.index(item["gate_id"]) < invalid_gate_index
        ]
        current = Phase(state["current_phase"])
        if FORWARD_SEQUENCE.index(current) > FORWARD_SEQUENCE.index(predecessor):
            state["current_phase"] = predecessor.value
            state["status"] = "blocked" if any(
                item.get("status") == "open" for item in state.get("blockers", [])
            ) else "active"
        changed_stage = invalid_gate_index
        stage_by_type = {
            name: GATE_ORDER.index(gate) for name, (_phase, gate) in ARTIFACT_PHASE.items()
        }
        for entry in state.get("artifacts", []):
            entry_stage = stage_by_type.get(entry.get("artifact_type"))
            if (
                entry.get("artifact_type") != artifact_type
                and entry_stage is not None
                and entry_stage > changed_stage
            ):
                entry["status"] = "draft"

    @staticmethod
    def _rollback_for_failed_gate(state: dict[str, Any], gate_id: str) -> None:
        failed_index = GATE_ORDER.index(gate_id)
        state["completed_gates"] = [
            item
            for item in state.get("completed_gates", [])
            if GATE_ORDER.index(item["gate_id"]) <= failed_index
        ]
        predecessor = GATE_PREDECESSOR[gate_id]
        current = Phase(state["current_phase"])
        if FORWARD_SEQUENCE.index(current) > FORWARD_SEQUENCE.index(predecessor):
            state["current_phase"] = predecessor.value
        state["status"] = "blocked" if any(
            item.get("status") == "open" for item in state.get("blockers", [])
        ) else "active"

    def write_artifact(
        self,
        artifact_type: str,
        data: dict[str, Any],
        *,
        expected_version: int,
        status: str = "draft",
        created_by: str = "agent",
    ) -> dict[str, Any]:
        """Publish one artifact version and its registry update as one transaction."""

        with self._lock():
            self._recover_unlocked()
            state = self._state()
            if state.get("schema_version") != PROJECT_STATE_SCHEMA_VERSION:
                raise MigrationError("Workspace must be migrated before artifact writes")
            files, candidate_state, new_entry = self._prepare_artifact_update(
                state,
                artifact_type,
                data,
                expected_version=expected_version,
                status=status,
                created_by=created_by,
            )
            self._invalidate_downstream(candidate_state, artifact_type)
            files[self.workspace / "project_state.json"] = candidate_state
            self._commit(files)
            return new_entry

    def write_artifact_with_runtime_fact(
        self,
        artifact_type: str,
        data: dict[str, Any],
        *,
        expected_version: int,
        fact_path: Path,
        fact_data: dict[str, Any],
        status: str = "draft",
        created_by: str = "agent",
    ) -> tuple[dict[str, Any], bool]:
        """Atomically publish one semantic artifact version and one immutable runtime fact."""

        with self._lock():
            self._recover_unlocked()
            state = self._state()
            if state.get("schema_version") != PROJECT_STATE_SCHEMA_VERSION:
                raise MigrationError("Workspace must be migrated before artifact writes")
            admitted_fact_path = ensure_within(self.workspace, fact_path)
            if admitted_fact_path.exists():
                if read_json(admitted_fact_path) != fact_data:
                    raise ArtifactConflictError(
                        f"Immutable runtime fact path contains different content: {admitted_fact_path}"
                    )
                fact_created = False
            else:
                fact_created = True
            files, candidate_state, new_entry = self._prepare_artifact_update(
                state,
                artifact_type,
                data,
                expected_version=expected_version,
                status=status,
                created_by=created_by,
            )
            self._invalidate_downstream(candidate_state, artifact_type)
            if fact_created:
                files[admitted_fact_path] = fact_data
            files[self.workspace / "project_state.json"] = candidate_state
            self._commit(files)
            return new_entry, fact_created

    def route_rework(
        self,
        target_phase: Phase,
        *,
        reason: str,
        expected_artifact_versions: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Persist one explicit backward workflow transition and invalidate later Gates/artifacts."""

        normalized_reason = " ".join(reason.split()).strip()
        if not normalized_reason:
            raise ArtifactError("Rework routing requires a reason")
        with self._lock():
            self._recover_unlocked()
            state = self._state()
            for artifact_type, expected_version in (
                expected_artifact_versions or {}
            ).items():
                entry = self._entry(state, artifact_type)
                current_version = int(entry["version"]) if entry is not None else 0
                if current_version != int(expected_version):
                    raise ArtifactConflictError(
                        f"Rework input changed for {artifact_type}: expected "
                        f"{expected_version}, current {current_version}"
                    )
            current = Phase(state["current_phase"])
            if current is target_phase:
                return copy.deepcopy(state)
            require_transition(current, target_phase)
            if FORWARD_SEQUENCE.index(target_phase) >= FORWARD_SEQUENCE.index(current):
                raise ArtifactError(
                    f"Rework target must be earlier than current phase: {current} -> {target_phase}"
                )

            decision_entry = self._entry(state, "decision_log")
            if decision_entry is None:
                raise ArtifactError("decision_log artifact is not registered")
            decision_data = read_json(self.workspace / decision_entry["path"])
            decision_id = self._next_log_id(
                decision_data.get("decisions", []),
                "decision_id",
                "DEC",
            )
            decision = {
                "decision_id": decision_id,
                "statement": f"Route workflow rework from {current.value} to {target_phase.value}",
                "rationale": normalized_reason,
                "status": "active",
                "created_at": utc_now(),
                "created_by": "artifact-runtime-rework",
                "supersedes": None,
            }
            candidate_decision_data = copy.deepcopy(decision_data)
            candidate_decision_data["decisions"].append(decision)
            files, candidate_state, _decision_artifact_entry = self._prepare_artifact_update(
                state,
                "decision_log",
                candidate_decision_data,
                expected_version=int(decision_entry["version"]),
                status="approved",
                created_by="artifact-runtime-rework",
            )
            candidate_state["current_phase"] = target_phase.value
            candidate_state["status"] = "blocked" if any(
                item.get("status") == "open"
                for item in candidate_state.get("blockers", [])
            ) else "active"

            admitted_gate_count = min(
                FORWARD_SEQUENCE.index(target_phase),
                len(GATE_ORDER),
            )
            candidate_state["completed_gates"] = [
                item
                for item in candidate_state.get("completed_gates", [])
                if GATE_ORDER.index(item["gate_id"]) < admitted_gate_count
            ]
            artifact_stage = {
                artifact_type: GATE_ORDER.index(gate_id)
                for artifact_type, (_phase, gate_id) in ARTIFACT_PHASE.items()
            }
            for entry in candidate_state.get("artifacts", []):
                stage = artifact_stage.get(str(entry.get("artifact_type")))
                if stage is not None and stage >= admitted_gate_count:
                    entry["status"] = "draft"

            candidate_state["decisions"] = [
                item
                for item in candidate_state.get("decisions", [])
                if item.get("decision_id") != decision_id
            ] + [
                {
                    "decision_id": decision_id,
                    "statement": decision["statement"],
                    "status": "active",
                }
            ]
            files[self.workspace / "project_state.json"] = candidate_state
            self._commit(files)
            return copy.deepcopy(candidate_state)

    def _next_log_id(self, items: list[dict[str, Any]], key: str, prefix: str) -> str:
        numbers = [int(str(item[key]).split("-")[-1]) for item in items if key in item]
        return f"{prefix}-{(max(numbers, default=0) + 1):03d}"

    def record_decision(
        self,
        statement: str,
        *,
        rationale: str = "",
        created_by: str = "agent",
        expected_version: int,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        """Append a versioned decision-log entry."""

        data = self.show_artifact("decision_log")
        decision = {
            "decision_id": self._next_log_id(data["decisions"], "decision_id", "DEC"),
            "statement": statement,
            "rationale": rationale,
            "status": "active",
            "created_at": utc_now(),
            "created_by": created_by,
            "supersedes": supersedes,
        }
        data["decisions"].append(decision)
        self.write_artifact("decision_log", data, expected_version=expected_version, created_by=created_by)
        return decision

    def record_assumption(
        self,
        statement: str,
        *,
        basis: str = "",
        risk: str = "medium",
        created_by: str = "agent",
        expected_version: int,
    ) -> dict[str, Any]:
        """Append a versioned assumption-log entry."""

        data = self.show_artifact("assumption_log")
        assumption = {
            "assumption_id": self._next_log_id(data["assumptions"], "assumption_id", "ASM"),
            "statement": statement,
            "basis": basis,
            "risk": risk,
            "status": "active",
            "created_at": utc_now(),
            "created_by": created_by,
            "resolved_by": None,
        }
        data["assumptions"].append(assumption)
        self.write_artifact("assumption_log", data, expected_version=expected_version, created_by=created_by)
        return assumption

    def _artifact_refs_for_gate(self, state: dict[str, Any], gate_id: str) -> list[dict[str, Any]]:
        required = set(GATE_REQUIRED_PATHS[gate_id])
        return [
            {
                "artifact_type": item["artifact_type"],
                "path": item["path"],
                "version": item["version"],
                "sha256": item["sha256"],
            }
            for item in state.get("artifacts", [])
            if item.get("path") in required
        ]

    def record_gate(
        self,
        gate_id: str,
        *,
        approved_by: str | None = "deterministic-runtime",
        waive: bool = False,
        waiver_reason: str | None = None,
        issue_refs: tuple[str, ...] = (),
        target_phase: Phase | None = None,
    ) -> GateResult:
        """Persist a Gate evaluation and optionally advance the project phase."""

        gate_id = gate_id.upper()
        if gate_id not in GATE_REQUIRED_PATHS:
            raise GateError(f"Unknown gate: {gate_id}")
        with self._lock():
            self._recover_unlocked()
            result = evaluate_gate(self.workspace, gate_id)
            state = self._state()
            gate_entry = self._entry(state, "gate_results")
            if gate_entry is None:
                raise GateError("gate_results artifact is not registered")
            gate_data = read_json(self.workspace / gate_entry["path"])
            issue_severities: dict[str, str] = {}
            issue_statuses: dict[str, str] = {}
            quality_path = self.workspace / "review/quality_report.json"
            if quality_path.exists():
                quality = read_json(quality_path)
                issue_severities = {
                    item["issue_id"]: item["severity"] for item in quality.get("issues", [])
                }
                issue_statuses = {
                    item["issue_id"]: item["status"] for item in quality.get("issues", [])
                }
            status = result.status
            reason_severities = {
                reason: self._gate_reason_severity(reason) for reason in result.reasons
            }
            if waive and not result.passed:
                if not approved_by or not waiver_reason or not issue_refs:
                    raise GateError("A waiver requires approver, reason, and explicit issue references")
                missing = [issue for issue in issue_refs if issue not in issue_severities]
                if missing:
                    raise GateError(f"Waiver references unknown issues: {', '.join(missing)}")
                if any(issue_severities[issue] == "critical" for issue in issue_refs):
                    raise GateError("Critical issues cannot be waived")
                if any(
                    severity == "critical" and issue_statuses.get(issue_id) == "open"
                    for issue_id, severity in issue_severities.items()
                ):
                    raise GateError("Open Critical issues prevent every waiver")
                if any(issue_severities[issue] != "major" for issue in issue_refs):
                    raise GateError("Only Major blocking issues use the explicit waiver path")
                if any(issue_statuses[issue] != "open" for issue in issue_refs):
                    raise GateError("Only open Major issues can be waived")
                if any(severity == "critical" for severity in reason_severities.values()):
                    raise GateError("Deterministic integrity failures cannot be waived")
                status = "waived"
            check_results = []
            if result.reasons:
                for index, reason in enumerate(result.reasons, start=1):
                    check_results.append(
                        {
                            "check_id": f"{gate_id}-CHK-{index:03d}",
                            "status": "fail" if status != "blocked" else "blocked",
                            "severity": reason_severities[reason],
                            "message": reason,
                        }
                    )
            else:
                check_results.append(
                    {"check_id": f"{gate_id}-CHK-001", "status": "pass", "severity": "info", "message": "Deterministic gate checks passed"}
                )
            for issue_ref in issue_refs:
                check_results.append(
                    {
                        "check_id": f"{gate_id}-ISSUE-{issue_ref}",
                        "status": "fail",
                        "severity": issue_severities[issue_ref],
                        "message": f"Waived issue {issue_ref}",
                        "issue_ref": issue_ref,
                    }
                )
            record_number = max(
                [int(item["gate_record_id"].split("-")[-1]) for item in gate_data["records"]],
                default=0,
            ) + 1
            now = utc_now()
            artifact_versions = self._artifact_refs_for_gate(state, gate_id)
            record = {
                "gate_record_id": f"GTR-{record_number:04d}",
                "gate_id": gate_id,
                "status": status,
                "artifact_versions": artifact_versions,
                "check_results": check_results,
                "issue_refs": list(issue_refs),
                "approved_by": approved_by,
                "evaluated_at": now,
                "waiver_reason": waiver_reason if status == "waived" else None,
                "notes": [],
            }
            candidate_gate_data = copy.deepcopy(gate_data)
            candidate_gate_data["records"].append(record)
            files, candidate_state, _new_entry = self._prepare_artifact_update(
                state,
                "gate_results",
                candidate_gate_data,
                expected_version=int(gate_entry["version"]),
                status="approved",
                created_by=approved_by or "runtime",
            )
            summary = {
                "gate_id": gate_id,
                "gate_record_id": record["gate_record_id"],
                "status": status,
                "artifact_hashes": [item["sha256"] for item in artifact_versions],
                "artifact_versions": artifact_versions,
                "evaluated_at": now,
                "approved_by": approved_by,
                "waiver_reason": record["waiver_reason"],
                "notes": [],
            }
            candidate_state["completed_gates"] = [
                item for item in candidate_state.get("completed_gates", []) if item.get("gate_id") != gate_id
            ] + [summary]
            if gate_id == "G0" and status in {"pass", "waived"}:
                candidate_state["blockers"] = [
                    {
                        **item,
                        "status": "resolved",
                    }
                    if item.get("blocker_id") == "BKR-001"
                    else item
                    for item in candidate_state.get("blockers", [])
                ]
            if status not in {"pass", "waived"}:
                self._rollback_for_failed_gate(candidate_state, gate_id)
            elif target_phase is not None:
                current = Phase(candidate_state["current_phase"])
                require_transition(current, target_phase)
                candidate_state["current_phase"] = target_phase.value
                candidate_state["status"] = "completed" if target_phase is Phase.COMPLETED else "active"
            files[self.workspace / "project_state.json"] = candidate_state
            self._commit(files)
        return GateResult(gate_id, status, result.reasons)

    @staticmethod
    def _gate_reason_severity(reason: str) -> str:
        non_waivable_markers = (
            "validation:",
            "required artifact is missing",
            "unknown gate",
            "render gate has not passed",
            "render did not complete successfully",
            "successful render must record",
            "delivery has no outputs",
        )
        return "critical" if reason.startswith(non_waivable_markers) else "major"

    def migrate_workspace(self, *, dry_run: bool = False, created_by: str = "migration-runtime") -> dict[str, Any]:
        """Migrate a legacy workspace to the current runtime contract."""

        with self._lock():
            self._recover_unlocked()
            state = self._state()
            current_version = str(state.get("schema_version", ""))
            if current_version == PROJECT_STATE_SCHEMA_VERSION:
                return {"status": "current", "from": current_version, "to": current_version, "steps": []}
            migrated, steps = self.migrations.migrate(
                "project_state", state, PROJECT_STATE_SCHEMA_VERSION
            )
            if dry_run:
                return {
                    "status": "planned",
                    "from": current_version,
                    "to": PROJECT_STATE_SCHEMA_VERSION,
                    "steps": [f"{step.from_version}->{step.to_version}" for step in steps],
                }
            now = utc_now()
            project_id = migrated["project_id"]
            upgraded_entries = []
            for old in state.get("artifacts", []):
                artifact_type = old["artifact_type"]
                catalog = self.registry.entry(artifact_type)
                path = self.workspace / catalog.default_path
                data = read_json(path)
                upgraded_entries.append(
                    build_artifact_entry(
                        project_id=project_id,
                        artifact_type=artifact_type,
                        path=catalog.default_path.as_posix(),
                        schema=catalog.schema_path.name,
                        schema_version=str(data.get("schema_version", catalog.schema_version)),
                        version=int(old.get("version", 1)),
                        status=str(old.get("status", "draft")),
                        data=data,
                        created_by=created_by,
                        created_at=now,
                    )
                )
            gate_records = []
            summaries = []
            for index, old_gate in enumerate(state.get("completed_gates", []), start=1):
                required_paths = set(GATE_REQUIRED_PATHS.get(old_gate["gate_id"], ()))
                refs = [
                    {"artifact_type": item["artifact_type"], "path": item["path"], "version": item["version"], "sha256": item["sha256"]}
                    for item in upgraded_entries
                    if item["path"] in required_paths
                ]
                status = old_gate["status"]
                waiver_reason = "Imported legacy waiver" if status == "waived" else None
                record_id = f"GTR-{index:04d}"
                gate_records.append(
                    {
                        "gate_record_id": record_id,
                        "gate_id": old_gate["gate_id"],
                        "status": status,
                        "artifact_versions": refs,
                        "check_results": [{"check_id": f"{old_gate['gate_id']}-LEGACY-001", "status": "pass" if status in {"pass", "waived"} else status, "severity": "info", "message": "Imported from M0 project_state"}],
                        "issue_refs": [],
                        "approved_by": created_by,
                        "evaluated_at": now,
                        "waiver_reason": waiver_reason,
                        "notes": old_gate.get("notes", []),
                    }
                )
                summaries.append(
                    {
                        "gate_id": old_gate["gate_id"],
                        "gate_record_id": record_id,
                        "status": status,
                        "artifact_hashes": [item["sha256"] for item in refs],
                        "artifact_versions": refs,
                        "evaluated_at": now,
                        "approved_by": created_by,
                        "waiver_reason": waiver_reason,
                        "notes": old_gate.get("notes", []),
                    }
                )
            system_data = {
                "gate_results": {"schema_version": SCHEMA_VERSION, "project_id": project_id, "records": gate_records},
                "decision_log": {
                    "schema_version": SCHEMA_VERSION,
                    "project_id": project_id,
                    "decisions": [
                        {
                            "decision_id": item["decision_id"],
                            "statement": item["statement"],
                            "rationale": "Imported from M0 project_state",
                            "status": item["status"],
                            "created_at": now,
                            "created_by": created_by,
                            "supersedes": None,
                        }
                        for item in state.get("decisions", [])
                    ],
                },
                "assumption_log": {"schema_version": SCHEMA_VERSION, "project_id": project_id, "assumptions": []},
            }
            files: dict[Path, dict[str, Any]] = {
                self.history_dir / "project_state" / f"{int(state.get('revision', 1)):06d}.json": state
            }
            for artifact_type, data in system_data.items():
                catalog = self.registry.entry(artifact_type)
                self.registry.validator(artifact_type).validate(data)
                files[self.workspace / catalog.default_path] = data
                upgraded_entries.append(
                    build_artifact_entry(
                        project_id=project_id,
                        artifact_type=artifact_type,
                        path=catalog.default_path.as_posix(),
                        schema=catalog.schema_path.name,
                        schema_version=SCHEMA_VERSION,
                        version=1,
                        status="approved",
                        data=data,
                        created_by=created_by,
                        created_at=now,
                    )
                )
            migrated["artifacts"] = upgraded_entries
            migrated["completed_gates"] = summaries
            migrated["revision"] = int(state.get("revision", 1)) + 1
            files[self.workspace / "project_state.json"] = migrated
            self._commit(files)
            return {
                "status": "migrated",
                "from": current_version,
                "to": PROJECT_STATE_SCHEMA_VERSION,
                "steps": [f"{step.from_version}->{step.to_version}" for step in steps],
            }
