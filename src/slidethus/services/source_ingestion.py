from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import SourceIngestionError
from slidethus.ingestion import (
    ParserRegistry,
    default_parser_registry,
    detect_source_format,
    validate_source_parse_limits,
)
from slidethus.io_utils import atomic_create_json, sha256_bytes, sha256_file
from slidethus.protocols import (
    SourceChunk,
    SourceParseLimits,
    SourceParseRequest,
    SourceParseResult,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.source_snapshots import (
    build_source_snapshot,
    load_source_snapshot,
    snapshot_chunks,
    source_snapshot_key,
    source_snapshot_reference_errors,
    validate_snapshot_data,
)

_SOURCE_ID = re.compile(r"^SRC-[0-9]{3}$")
_OWNERSHIP = {"user_owned", "licensed", "public_reference", "unknown"}
_CONFIDENTIALITY = {"public", "internal", "confidential", "restricted"}
_AUTHORITY = {"user", "primary", "secondary", "community", "unknown"}
_ALLOWED_USE = {"full", "internal_only", "citation_only", "metadata_only", "do_not_use"}


@dataclass(frozen=True)
class SourceIngestionResult:
    source_id: str
    changed: bool
    source_record: dict[str, Any]
    snapshot_path: Path
    chunks: tuple[SourceChunk, ...]
    warnings: tuple[str, ...]
    risks: tuple[dict[str, Any], ...]


def fingerprint_source(path: Path) -> dict[str, str | int]:
    """Return deterministic source metadata without parsing content."""

    path = path.resolve()
    payload = path.read_bytes()
    return {
        "path": str(path),
        "sha256": sha256_bytes(payload),
        "size_bytes": len(payload),
    }


def _source_sort_key(source: dict[str, Any]) -> int:
    return int(str(source["source_id"]).split("-")[-1])


class SourceIngestionService:
    """Parse one local source and publish a recoverable Source Ledger reference."""

    def __init__(
        self,
        workspace: Path,
        *,
        parser_registry: ParserRegistry | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.parsers = parser_registry or default_parser_registry()
        self.schemas = schema_registry or SchemaRegistry()

    def ingest(
        self,
        path: Path,
        *,
        source_id: str | None = None,
        title: str | None = None,
        ownership: str | None = None,
        confidentiality: str | None = None,
        authority_tier: str | None = None,
        allowed_use: str | None = None,
        limits: SourceParseLimits | None = None,
    ) -> SourceIngestionResult:
        """Ingest a file idempotently; immutable cache writes precede ledger commit."""

        self.runtime.recover()
        source_path = path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        parse_limits = limits or SourceParseLimits()
        validate_source_parse_limits(parse_limits)
        ledger, ledger_version = self.runtime.read_artifact_snapshot("source_ledger")
        project_id = str(self.runtime.show_artifact("project_state")["project_id"])
        sources = list(ledger.get("sources", []))
        resolved_source_id = self._resolve_source_id(sources, source_path, source_id)
        existing = next(
            (item for item in sources if item.get("source_id") == resolved_source_id),
            None,
        )
        metadata = self._resolve_metadata(
            existing,
            source_path,
            title=title,
            ownership=ownership,
            confidentiality=confidentiality,
            authority_tier=authority_tier,
            allowed_use=allowed_use,
        )
        self._validate_policy(
            metadata["ownership"],
            metadata["confidentiality"],
            metadata["authority_tier"],
            metadata["allowed_use"],
        )

        detected = detect_source_format(source_path)
        parser = self.parsers.select(detected)
        if source_path.stat().st_size > parse_limits.max_source_bytes:
            raise SourceIngestionError(
                "Source exceeds max_source_bytes: "
                f"{source_path.stat().st_size} > {parse_limits.max_source_bytes}"
            )
        fingerprint = fingerprint_source(source_path)
        if int(fingerprint["size_bytes"]) > parse_limits.max_source_bytes:
            raise SourceIngestionError(
                "Source exceeds max_source_bytes after read: "
                f"{fingerprint['size_bytes']} > {parse_limits.max_source_bytes}"
            )

        snapshot = self._load_reusable_snapshot(
            existing,
            project_id=project_id,
            source_sha256=str(fingerprint["sha256"]),
            parser_name=parser.name,
            parser_version=parser.version,
            detected_family=detected.family,
            limits=parse_limits,
        )
        if snapshot is not None and fingerprint_source(source_path) == fingerprint:
            source_record = self._update_inventory_metadata(
                existing,
                source_path=source_path,
                metadata=metadata,
            )
            changed = source_record != existing
            if changed:
                self._commit_source_record(
                    ledger,
                    sources,
                    existing,
                    source_record,
                    expected_version=ledger_version,
                )
            return SourceIngestionResult(
                source_id=resolved_source_id,
                changed=changed,
                source_record=copy.deepcopy(source_record),
                snapshot_path=self.workspace / source_record["ingestion"]["snapshot_path"],
                chunks=snapshot_chunks(snapshot),
                warnings=tuple(snapshot.get("warnings", [])),
                risks=tuple(dict(item) for item in snapshot.get("risks", [])),
            )

        request = SourceParseRequest(
            path=source_path,
            source_id=resolved_source_id,
            limits=parse_limits,
        )
        result = parser.parse(request, detected)
        post_parse_fingerprint = fingerprint_source(source_path)
        if (
            post_parse_fingerprint["sha256"] != result.source_sha256
            or post_parse_fingerprint["size_bytes"] != result.size_bytes
        ):
            raise SourceIngestionError(
                "Source changed during parsing; no snapshot or Source Ledger version was published"
            )
        snapshot = build_source_snapshot(project_id, result, parse_limits)
        snapshot_errors = validate_snapshot_data(snapshot, self.schemas.schema_dir)
        if snapshot_errors:
            raise SourceIngestionError(
                "Parser produced an invalid source snapshot: " + "; ".join(snapshot_errors)
            )

        snapshot_key = source_snapshot_key(result, parse_limits)
        relative_snapshot_path = Path(".slidethus/cache/ingestion") / f"{snapshot_key}.json"
        snapshot_path = self.workspace / relative_snapshot_path
        created = atomic_create_json(snapshot_path, snapshot)
        if not created:
            snapshot = load_source_snapshot(
                self.workspace,
                project_id,
                self._record_for_snapshot_validation(
                    resolved_source_id,
                    result,
                    parse_limits,
                    relative_snapshot_path,
                    sha256_file(snapshot_path),
                    snapshot,
                ),
                self.schemas.schema_dir,
            )
        snapshot_sha256 = sha256_file(snapshot_path)

        source_record = self._build_source_record(
            existing,
            source_path=source_path,
            result=result,
            snapshot=snapshot,
            snapshot_path=relative_snapshot_path,
            snapshot_sha256=snapshot_sha256,
            limits=parse_limits,
            metadata=metadata,
        )
        self._commit_source_record(
            ledger,
            sources,
            existing,
            source_record,
            expected_version=ledger_version,
        )
        return SourceIngestionResult(
            source_id=resolved_source_id,
            changed=True,
            source_record=copy.deepcopy(source_record),
            snapshot_path=snapshot_path,
            chunks=snapshot_chunks(snapshot),
            warnings=tuple(snapshot["warnings"]),
            risks=tuple(dict(item) for item in snapshot["risks"]),
        )

    def load(self, source_id: str) -> SourceIngestionResult:
        """Load and verify a previously ingested source without reparsing it."""

        ledger = self.runtime.show_artifact("source_ledger")
        source = next(
            (item for item in ledger.get("sources", []) if item.get("source_id") == source_id),
            None,
        )
        if source is None:
            raise SourceIngestionError(f"Unknown source ID: {source_id}")
        project_id = str(self.runtime.show_artifact("project_state")["project_id"])
        snapshot = load_source_snapshot(
            self.workspace,
            project_id,
            source,
            self.schemas.schema_dir,
        )
        return SourceIngestionResult(
            source_id=source_id,
            changed=False,
            source_record=copy.deepcopy(source),
            snapshot_path=self.workspace / source["ingestion"]["snapshot_path"],
            chunks=snapshot_chunks(snapshot),
            warnings=tuple(snapshot.get("warnings", [])),
            risks=tuple(dict(item) for item in snapshot.get("risks", [])),
        )

    def _load_reusable_snapshot(
        self,
        source: dict[str, Any] | None,
        *,
        project_id: str,
        source_sha256: str,
        parser_name: str,
        parser_version: str,
        detected_family: str,
        limits: SourceParseLimits,
    ) -> dict[str, Any] | None:
        if source is None:
            return None
        ingestion = source.get("ingestion", {})
        if source.get("content_hash") != f"sha256:{source_sha256}":
            return None
        if ingestion.get("parser_name") != parser_name:
            return None
        if ingestion.get("parser_version") != parser_version:
            return None
        if ingestion.get("detected_family") != detected_family:
            return None
        if ingestion.get("limits") != asdict(limits):
            return None
        if source_snapshot_reference_errors(
            self.workspace,
            project_id,
            source,
            self.schemas.schema_dir,
        ):
            return None
        return load_source_snapshot(
            self.workspace,
            project_id,
            source,
            self.schemas.schema_dir,
        )

    @staticmethod
    def _resolve_metadata(
        existing: dict[str, Any] | None,
        source_path: Path,
        *,
        title: str | None,
        ownership: str | None,
        confidentiality: str | None,
        authority_tier: str | None,
        allowed_use: str | None,
    ) -> dict[str, str]:
        current = existing or {}
        resolved = {
            "title": str(title if title is not None else current.get("title", source_path.stem)).strip(),
            "ownership": str(ownership if ownership is not None else current.get("ownership", "user_owned")),
            "confidentiality": str(
                confidentiality
                if confidentiality is not None
                else current.get("confidentiality", "internal")
            ),
            "authority_tier": str(
                authority_tier
                if authority_tier is not None
                else current.get("authority_tier", "user")
            ),
            "allowed_use": str(
                allowed_use
                if allowed_use is not None
                else current.get("allowed_use", "internal_only")
            ),
        }
        if not resolved["title"]:
            raise SourceIngestionError("Source title must not be blank")
        return resolved

    @staticmethod
    def _update_inventory_metadata(
        existing: dict[str, Any] | None,
        *,
        source_path: Path,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        if existing is None or not existing.get("ingestion"):
            raise SourceIngestionError("Cannot reuse a source without an ingestion snapshot")
        source_record = copy.deepcopy(existing)
        source_record.update(
            {
                "kind": "user_file",
                "title": metadata["title"],
                "path_or_url": str(source_path),
                "ownership": metadata["ownership"],
                "confidentiality": metadata["confidentiality"],
                "authority_tier": metadata["authority_tier"],
                "allowed_use": metadata["allowed_use"],
            }
        )
        return source_record

    def _build_source_record(
        self,
        existing: dict[str, Any] | None,
        *,
        source_path: Path,
        result: SourceParseResult,
        snapshot: dict[str, Any],
        snapshot_path: Path,
        snapshot_sha256: str,
        limits: SourceParseLimits,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "source_id": result.source_id,
            "kind": "user_file",
            "title": metadata["title"],
            "path_or_url": str(source_path),
            "ownership": metadata["ownership"],
            "confidentiality": metadata["confidentiality"],
            "authority_tier": metadata["authority_tier"],
            "freshness_date": existing.get("freshness_date") if existing else None,
            "retrieved_at": result.parsed_at,
            "content_hash": f"sha256:{result.source_sha256}",
            "media_type": result.detected_format.media_type,
            "size_bytes": result.size_bytes,
            "ingestion": {
                "parser_name": result.parser_name,
                "parser_version": result.parser_version,
                "detected_family": result.detected_format.family,
                "snapshot_path": snapshot_path.as_posix(),
                "snapshot_sha256": snapshot_sha256,
                "chunk_count": len(snapshot["chunks"]),
                "warning_count": len(snapshot["warnings"]),
                "risk_count": len(snapshot["risks"]),
                "limits": asdict(limits),
                "ingested_at": snapshot["created_at"],
            },
            "parse_status": result.parse_status,
            "allowed_use": metadata["allowed_use"],
            "notes": self._merge_notes(existing, snapshot),
        }

    def _commit_source_record(
        self,
        ledger: dict[str, Any],
        sources: list[dict[str, Any]],
        existing: dict[str, Any] | None,
        source_record: dict[str, Any],
        *,
        expected_version: int,
    ) -> None:
        candidate = copy.deepcopy(ledger)
        candidate["sources"] = [
            source_record
            if item.get("source_id") == source_record["source_id"]
            else item
            for item in sources
        ]
        if existing is None:
            candidate["sources"].append(source_record)
        candidate["sources"] = sorted(candidate["sources"], key=_source_sort_key)
        self.runtime.write_artifact(
            "source_ledger",
            candidate,
            expected_version=expected_version,
            status="approved",
            created_by="source-ingestion-service",
        )

    def _same_user_file_path(self, source: dict[str, Any], source_path: Path) -> bool:
        if source.get("kind") != "user_file":
            return False
        try:
            candidate = Path(str(source.get("path_or_url", ""))).expanduser()
            if not candidate.is_absolute():
                candidate = self.workspace / candidate
            return candidate.resolve() == source_path
        except (OSError, RuntimeError, ValueError):
            return False

    def _resolve_source_id(
        self,
        sources: list[dict[str, Any]],
        source_path: Path,
        requested: str | None,
    ) -> str:
        id_match = next(
            (item for item in sources if item.get("source_id") == requested),
            None,
        ) if requested is not None else None
        path_match = next(
            (item for item in sources if self._same_user_file_path(item, source_path)),
            None,
        )
        if requested is not None:
            if not _SOURCE_ID.fullmatch(requested):
                raise SourceIngestionError(f"Invalid source ID: {requested}")
            if id_match is not None and not self._same_user_file_path(id_match, source_path):
                raise SourceIngestionError(
                    f"Source ID {requested} is already assigned to another source"
                )
            if path_match is not None and path_match.get("source_id") != requested:
                raise SourceIngestionError(
                    f"Source path is already assigned to {path_match.get('source_id')}"
                )
            return requested
        if path_match is not None:
            return str(path_match["source_id"])
        next_number = max(
            (int(str(item["source_id"]).split("-")[-1]) for item in sources),
            default=0,
        ) + 1
        if next_number > 999:
            raise SourceIngestionError("Source ID space is exhausted")
        return f"SRC-{next_number:03d}"

    @staticmethod
    def _validate_policy(
        ownership: str,
        confidentiality: str,
        authority_tier: str,
        allowed_use: str,
    ) -> None:
        values = {
            "ownership": (ownership, _OWNERSHIP),
            "confidentiality": (confidentiality, _CONFIDENTIALITY),
            "authority_tier": (authority_tier, _AUTHORITY),
            "allowed_use": (allowed_use, _ALLOWED_USE),
        }
        for name, (value, admitted) in values.items():
            if value not in admitted:
                raise SourceIngestionError(f"Invalid {name}: {value}")

    @staticmethod
    def _notes(snapshot: dict[str, Any]) -> list[str]:
        notes = [
            "Parsed by the M2 ProductionImpl ingestion path.",
            "Source content was treated as untrusted data; embedded instructions were not executed.",
        ]
        if snapshot.get("parse_status") == "partial":
            notes.append(
                "Parser completed with partial coverage; downstream evidence must honor the recorded warnings."
            )
        if snapshot["warnings"]:
            notes.append(f"Parser recorded {len(snapshot['warnings'])} warning(s).")
        high_risks = [item for item in snapshot["risks"] if item.get("severity") == "high"]
        if high_risks:
            notes.append(
                f"Parser recorded {len(high_risks)} high source-risk finding(s); review before downstream use."
            )
        return notes

    @classmethod
    def _merge_notes(
        cls,
        existing: dict[str, Any] | None,
        snapshot: dict[str, Any],
    ) -> list[str]:
        notes = cls._notes(snapshot)
        generated_prefixes = (
            "Parsed by the M2 ProductionImpl ingestion path.",
            "Source content was treated as untrusted data;",
            "Parser recorded ",
        )
        for note in (existing or {}).get("notes", []):
            value = str(note)
            if not value.startswith(generated_prefixes) and value not in notes:
                notes.append(value)
        return notes

    @staticmethod
    def _record_for_snapshot_validation(
        source_id: str,
        result: SourceParseResult,
        limits: SourceParseLimits,
        relative_path: Path,
        snapshot_sha256: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "content_hash": f"sha256:{result.source_sha256}",
            "parse_status": result.parse_status,
            "size_bytes": result.size_bytes,
            "ingestion": {
                "parser_name": result.parser_name,
                "parser_version": result.parser_version,
                "detected_family": result.detected_format.family,
                "snapshot_path": relative_path.as_posix(),
                "snapshot_sha256": snapshot_sha256,
                "chunk_count": len(snapshot["chunks"]),
                "warning_count": len(snapshot["warnings"]),
                "risk_count": len(snapshot["risks"]),
                "limits": asdict(limits),
                "ingested_at": snapshot["created_at"],
            },
        }
