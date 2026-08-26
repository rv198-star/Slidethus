from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import SourceIngestionError, WorkspaceError
from slidethus.io_utils import (
    ensure_within,
    read_json,
    sha256_bytes,
    sha256_file,
    sha256_json,
)
from slidethus.protocols import SourceChunk, SourceParseLimits, SourceParseResult


def build_source_snapshot(
    project_id: str,
    result: SourceParseResult,
    limits: SourceParseLimits,
) -> dict[str, Any]:
    """Build the immutable parse snapshot referenced by the Source Ledger."""

    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "source_id": result.source_id,
        "source_sha256": result.source_sha256,
        "size_bytes": result.size_bytes,
        "created_at": result.parsed_at,
        "detected_format": asdict(result.detected_format),
        "parser": {"name": result.parser_name, "version": result.parser_version},
        "limits": asdict(limits),
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "locator": chunk.locator,
                "text": chunk.text,
                "content_hash": chunk.content_hash,
                "kind": chunk.kind,
                "metadata": chunk.metadata,
            }
            for chunk in result.chunks
        ],
        "warnings": list(result.warnings),
        "risks": [asdict(risk) for risk in result.risks],
    }


def source_snapshot_key(result: SourceParseResult, limits: SourceParseLimits) -> str:
    """Return a stable cache key for source bytes, parser identity, format, and limits."""

    return sha256_json(
        {
            "source_id": result.source_id,
            "source_sha256": result.source_sha256,
            "parser_name": result.parser_name,
            "parser_version": result.parser_version,
            "detected_format": asdict(result.detected_format),
            "limits": asdict(limits),
        }
    )


def source_snapshot_key_from_data(data: dict[str, Any]) -> str:
    """Recompute the immutable cache key from a persisted snapshot."""

    parser = data.get("parser", {})
    return sha256_json(
        {
            "source_id": data.get("source_id"),
            "source_sha256": data.get("source_sha256"),
            "parser_name": parser.get("name"),
            "parser_version": parser.get("version"),
            "detected_format": data.get("detected_format"),
            "limits": data.get("limits"),
        }
    )


def snapshot_schema(schema_dir: Path) -> dict[str, Any]:
    path = schema_dir / "source_snapshot.schema.json"
    if not path.exists():
        raise SourceIngestionError(f"Missing source snapshot schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_snapshot_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    """Validate one parse snapshot schema and deterministic chunk invariants."""

    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(snapshot_schema(schema_dir)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)

    chunks = data.get("chunks", [])
    chunk_ids = [str(item.get("chunk_id", "")) for item in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        errors.append("duplicate chunk_id")
    ordinals = [item.get("ordinal") for item in chunks]
    if ordinals != list(range(1, len(chunks) + 1)):
        errors.append("chunk ordinals must be contiguous from 1")
    source_id = str(data.get("source_id", ""))
    for chunk in chunks:
        digest = sha256_bytes(str(chunk.get("text", "")).encode("utf-8"))
        expected_hash = f"sha256:{digest}"
        if chunk.get("content_hash") != expected_hash:
            errors.append(f"chunk hash mismatch: {chunk.get('chunk_id')}")
        expected_id = f"CHK-{source_id}-{int(chunk.get('ordinal', 0)):04d}-{digest[:8].upper()}"
        if chunk.get("chunk_id") != expected_id:
            errors.append(f"chunk identity mismatch: {chunk.get('chunk_id')}")

    risk_ids = [str(item.get("risk_id", "")) for item in data.get("risks", [])]
    if len(risk_ids) != len(set(risk_ids)):
        errors.append("duplicate risk_id")
    expected_risk_ids = [
        f"RSK-{source_id}-{index:03d}" for index in range(1, len(risk_ids) + 1)
    ]
    if risk_ids != expected_risk_ids:
        errors.append("risk IDs must be contiguous and source-scoped")
    return tuple(errors)


def source_snapshot_reference_errors(
    workspace: Path,
    project_id: str,
    source: dict[str, Any],
    schema_dir: Path,
) -> tuple[str, ...]:
    """Return all errors for a Source Ledger ingestion snapshot reference."""

    ingestion = source.get("ingestion")
    if not ingestion:
        return ()

    errors: list[str] = []
    raw_path = ingestion.get("snapshot_path", "")
    try:
        relative = Path(str(raw_path))
        if relative.is_absolute():
            raise WorkspaceError(f"Absolute snapshot path is not allowed: {relative}")
        snapshot_path = ensure_within(workspace, workspace / relative)
    except (OSError, ValueError, WorkspaceError) as exc:
        return (str(exc),)
    if not snapshot_path.exists():
        return (f"snapshot is missing: {raw_path}",)
    if not snapshot_path.is_file():
        return (f"snapshot is not a regular file: {raw_path}",)

    actual_file_hash = sha256_file(snapshot_path)
    if actual_file_hash != ingestion.get("snapshot_sha256"):
        errors.append("snapshot file hash mismatch")
    try:
        data = read_json(snapshot_path)
    except Exception as exc:  # noqa: BLE001
        return tuple([*errors, f"snapshot JSON cannot be read: {exc}"])
    errors.extend(validate_snapshot_data(data, schema_dir))
    if errors:
        return tuple(errors)

    expected_snapshot_name = f"{source_snapshot_key_from_data(data)}.json"
    if snapshot_path.name != expected_snapshot_name:
        errors.append("snapshot cache key mismatch")
    if data.get("project_id") != project_id:
        errors.append("snapshot project_id mismatch")
    if data.get("source_id") != source.get("source_id"):
        errors.append("snapshot source_id mismatch")
    if f"sha256:{data.get('source_sha256')}" != source.get("content_hash"):
        errors.append("snapshot source content hash mismatch")
    if data.get("size_bytes") != source.get("size_bytes"):
        errors.append("snapshot size mismatch")
    parser = data.get("parser", {})
    if parser.get("name") != ingestion.get("parser_name"):
        errors.append("snapshot parser name mismatch")
    if parser.get("version") != ingestion.get("parser_version"):
        errors.append("snapshot parser version mismatch")
    detected = data.get("detected_format", {})
    if detected.get("family") != ingestion.get("detected_family"):
        errors.append("snapshot detected family mismatch")
    if len(data.get("chunks", [])) != ingestion.get("chunk_count"):
        errors.append("snapshot chunk count mismatch")
    if len(data.get("warnings", [])) != ingestion.get("warning_count"):
        errors.append("snapshot warning count mismatch")
    if len(data.get("risks", [])) != ingestion.get("risk_count"):
        errors.append("snapshot risk count mismatch")
    if data.get("limits") != ingestion.get("limits"):
        errors.append("snapshot parse limits mismatch")
    return tuple(errors)


def load_source_snapshot(
    workspace: Path,
    project_id: str,
    source: dict[str, Any],
    schema_dir: Path,
) -> dict[str, Any]:
    errors = source_snapshot_reference_errors(workspace, project_id, source, schema_dir)
    if errors:
        raise SourceIngestionError("Invalid source snapshot: " + "; ".join(errors))
    ingestion = source.get("ingestion")
    if not ingestion:
        raise SourceIngestionError(f"Source has no ingestion snapshot: {source.get('source_id')}")
    return read_json(workspace / ingestion["snapshot_path"])


def snapshot_chunks(snapshot: dict[str, Any]) -> tuple[SourceChunk, ...]:
    return tuple(
        SourceChunk(
            source_id=str(snapshot["source_id"]),
            locator=str(item["locator"]),
            text=str(item["text"]),
            chunk_id=str(item["chunk_id"]),
            ordinal=int(item["ordinal"]),
            content_hash=str(item["content_hash"]),
            kind=str(item["kind"]),
            metadata=dict(item.get("metadata", {})),
        )
        for item in snapshot.get("chunks", [])
    )
