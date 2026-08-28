from __future__ import annotations

import importlib
import io
import re
import stat
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

from slidethus.errors import SourceCapabilityError, SourceIngestionError
from slidethus.ingestion import (
    build_source_risks,
    validate_source_parse_limits,
    verify_detected_source_format,
)
from slidethus.io_utils import sha256_bytes
from slidethus.protocols import (
    DetectedSourceFormat,
    SourceChunk,
    SourceParseRequest,
    SourceParseResult,
)

RiskFinding = tuple[str, str, str, str | None]


@dataclass(frozen=True)
class SourceBlock:
    """One format-native, independently locatable source block."""

    locator: str
    text: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArchiveInspection:
    """Safety findings produced before an OOXML library opens a package."""

    entry_count: int
    uncompressed_bytes: int
    warnings: tuple[str, ...] = ()
    risks: tuple[RiskFinding, ...] = ()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def require_dependency(module_name: str, *, extra: str = "ingestion") -> Any:
    """Import one optional adapter dependency with an actionable error."""

    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise SourceCapabilityError(
            f"Optional dependency '{module_name}' is required; install slidethus[{extra}]"
        ) from exc


def read_source_bytes(
    request: SourceParseRequest,
    detected_format: DetectedSourceFormat,
) -> bytes:
    """Read one bounded payload and verify it still matches parser selection."""

    validate_source_parse_limits(request.limits)
    path = request.path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    stat_size = path.stat().st_size
    if stat_size > request.limits.max_source_bytes:
        raise SourceIngestionError(
            f"Source exceeds max_source_bytes: {stat_size} > {request.limits.max_source_bytes}"
        )
    payload = path.read_bytes()
    if len(payload) > request.limits.max_source_bytes:
        raise SourceIngestionError(
            "Source exceeds max_source_bytes after read: "
            f"{len(payload)} > {request.limits.max_source_bytes}"
        )
    if not payload:
        raise SourceIngestionError(f"Source file is empty: {path}")
    verify_detected_source_format(path, payload, detected_format)
    return payload


def _normalize_block_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()


def append_source_block(
    blocks: list[SourceBlock],
    block: SourceBlock,
    *,
    max_blocks: int,
) -> None:
    """Append one non-empty block while bounding pre-Chunk adapter memory."""

    if not _normalize_block_text(block.text):
        return
    if len(blocks) >= max_blocks:
        raise SourceIngestionError(
            f"Source exceeds max_chunks before splitting: {len(blocks) + 1} > {max_blocks}"
        )
    blocks.append(block)


def build_chunks(
    source_id: str,
    blocks: list[SourceBlock],
    *,
    max_chunk_chars: int,
    max_chunks: int,
) -> tuple[SourceChunk, ...]:
    """Convert format-native blocks to stable, bounded Source Chunks."""

    chunks: list[SourceChunk] = []
    for block in blocks:
        text = _normalize_block_text(block.text)
        if not text:
            continue
        fragments = [
            text[offset : offset + max_chunk_chars]
            for offset in range(0, len(text), max_chunk_chars)
        ]
        for fragment_index, fragment in enumerate(fragments, start=1):
            ordinal = len(chunks) + 1
            digest = sha256_bytes(fragment.encode("utf-8"))
            locator = block.locator
            metadata = dict(block.metadata)
            if len(fragments) > 1:
                char_start = (fragment_index - 1) * max_chunk_chars + 1
                char_end = char_start + len(fragment) - 1
                locator = f"{block.locator}; chars {char_start}-{char_end}"
                metadata.update(
                    {
                        "char_start": char_start,
                        "char_end": char_end,
                        "fragment_index": fragment_index,
                        "fragment_count": len(fragments),
                    }
                )
            chunks.append(
                SourceChunk(
                    source_id=source_id,
                    locator=locator,
                    text=fragment,
                    chunk_id=f"CHK-{source_id}-{ordinal:04d}-{digest[:8].upper()}",
                    ordinal=ordinal,
                    content_hash=f"sha256:{digest}",
                    kind=block.kind,
                    metadata=metadata,
                )
            )
            if len(chunks) > max_chunks:
                raise SourceIngestionError(
                    f"Source exceeds max_chunks: {len(chunks)} > {max_chunks}"
                )
    if not chunks:
        raise SourceIngestionError("Source contains no usable text or metadata")
    return tuple(chunks)


def build_parse_result(
    *,
    request: SourceParseRequest,
    detected_format: DetectedSourceFormat,
    parser_name: str,
    parser_version: str,
    payload: bytes,
    blocks: list[SourceBlock],
    warnings: list[str] | tuple[str, ...] = (),
    extra_risks: list[RiskFinding] | tuple[RiskFinding, ...] = (),
    parse_status: str = "parsed",
) -> SourceParseResult:
    """Build one validated adapter result from a single captured payload."""

    chunks = build_chunks(
        request.source_id,
        blocks,
        max_chunk_chars=request.limits.max_chunk_chars,
        max_chunks=request.limits.max_chunks,
    )
    if parse_status not in {"parsed", "partial"}:
        raise SourceIngestionError(f"Invalid successful parse status: {parse_status}")
    risks = build_source_risks(
        chunks,
        request.source_id,
        extra_risks,
        max_risks=request.limits.max_risks,
    )
    return SourceParseResult(
        source_id=request.source_id,
        parser_name=parser_name,
        parser_version=parser_version,
        detected_format=detected_format,
        source_sha256=sha256_bytes(payload),
        size_bytes=len(payload),
        parsed_at=utc_now(),
        chunks=chunks,
        parse_status=parse_status,
        warnings=tuple(dict.fromkeys(str(item) for item in warnings if str(item))),
        risks=risks,
    )


def preflight_ooxml(payload: bytes, request: SourceParseRequest) -> ArchiveInspection:
    """Reject unsafe or ambiguous OOXML containers before a library opens them."""

    warnings: list[str] = []
    risks: list[RiskFinding] = []
    infos: list[zipfile.ZipInfo] = []
    total_uncompressed = 0
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) > request.limits.max_archive_entries:
                raise SourceIngestionError(
                    "Archive exceeds max_archive_entries: "
                    f"{len(infos)} > {request.limits.max_archive_entries}"
                )
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > request.limits.max_uncompressed_bytes:
                raise SourceIngestionError(
                    "Archive exceeds max_uncompressed_bytes: "
                    f"{total_uncompressed} > {request.limits.max_uncompressed_bytes}"
                )

            seen_members: set[str] = set()
            for info in infos:
                normalized_name = info.filename.replace("\\", "/")
                member = PurePosixPath(normalized_name)
                member_key = normalized_name.casefold()
                if member_key in seen_members:
                    raise SourceIngestionError(
                        f"Archive contains a duplicate member name: {info.filename}"
                    )
                seen_members.add(member_key)
                if (
                    member.is_absolute()
                    or ".." in member.parts
                    or (member.parts and ":" in member.parts[0])
                ):
                    raise SourceIngestionError(
                        f"Archive member escapes package root: {info.filename}"
                    )
                file_type = (info.external_attr >> 16) & 0o170000
                if file_type == stat.S_IFLNK:
                    raise SourceIngestionError(
                        f"Archive symlink member is not supported: {info.filename}"
                    )
                if info.file_size > request.limits.max_archive_member_bytes:
                    raise SourceIngestionError(
                        "Archive member exceeds max_archive_member_bytes: "
                        f"{info.filename} ({info.file_size} > "
                        f"{request.limits.max_archive_member_bytes})"
                    )
                if info.flag_bits & 0x1:
                    raise SourceIngestionError(
                        f"Encrypted archive member is not supported: {info.filename}"
                    )
                lowered = normalized_name.lower()
                if lowered.endswith("vbaproject.bin"):
                    raise SourceIngestionError("Macro-enabled OOXML content is not supported")
                if "/embeddings/" in lowered or "/activex/" in lowered:
                    is_standard_office_data = (
                        "/embeddings/" in lowered
                        and PurePosixPath(lowered).suffix
                        in {".xlsx", ".docx", ".pptx", ".csv"}
                    )
                    risks.append(
                        (
                            "embedded_object",
                            "warning" if is_standard_office_data else "high",
                            (
                                "OOXML package contains an embedded Office data file; cached visible content was used and the embedded file was not opened."
                                if is_standard_office_data
                                else "OOXML package contains embedded or ActiveX content; it was not executed or extracted."
                            ),
                            normalized_name,
                        )
                    )
                    if len(risks) > request.limits.max_risks:
                        raise SourceIngestionError(
                            "Source exceeds max_risks during OOXML preflight: "
                            f"{len(risks)} > {request.limits.max_risks}"
                        )

            content_types_info = next(
                (
                    info
                    for info in infos
                    if info.filename.replace("\\", "/").casefold()
                    == "[content_types].xml".casefold()
                ),
                None,
            )
            if content_types_info is not None:
                content_types = archive.read(content_types_info).lower()
                if b"macroenabled" in content_types or b"vbaproject" in content_types:
                    raise SourceIngestionError(
                        "Macro-enabled OOXML content type is not supported"
                    )

            for info in infos:
                normalized_name = info.filename.replace("\\", "/")
                lowered_name = normalized_name.lower()
                if not lowered_name.endswith((".xml", ".rels")) or info.file_size == 0:
                    continue
                try:
                    xml_bytes = archive.read(info)
                    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", xml_bytes, re.IGNORECASE):
                        raise SourceIngestionError(
                            f"OOXML part contains a prohibited DTD/entity: {normalized_name}"
                        )
                    if not lowered_name.endswith(".rels"):
                        continue
                    root = ElementTree.fromstring(xml_bytes)
                except SourceIngestionError:
                    raise
                except (ElementTree.ParseError, RuntimeError, zipfile.BadZipFile):
                    warnings.append(
                        f"Relationship file could not be inspected: {normalized_name}"
                    )
                    continue
                for relationship in root:
                    if relationship.attrib.get("TargetMode") != "External":
                        continue
                    target = relationship.attrib.get("Target", "").strip()
                    displayed_target = target[:500] + ("…" if len(target) > 500 else "")
                    risks.append(
                        (
                            "external_relationship",
                            "warning",
                            "OOXML external target was preserved but never opened: "
                            + (displayed_target or "<empty target>"),
                            normalized_name,
                        )
                    )
                    if len(risks) > request.limits.max_risks:
                        raise SourceIngestionError(
                            "Source exceeds max_risks during OOXML preflight: "
                            f"{len(risks)} > {request.limits.max_risks}"
                        )
    except zipfile.BadZipFile as exc:
        raise SourceIngestionError("Source is not a valid OOXML ZIP package") from exc
    return ArchiveInspection(
        entry_count=len(infos),
        uncompressed_bytes=total_uncompressed,
        warnings=tuple(warnings),
        risks=tuple(risks),
    )


def require_archive_member(payload: bytes, member: str) -> None:
    """Require the defining OOXML part for a claimed package family."""

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if member not in archive.namelist():
                raise SourceIngestionError(
                    f"OOXML package is missing required part: {member}"
                )
    except zipfile.BadZipFile as exc:
        raise SourceIngestionError("Source is not a valid OOXML ZIP package") from exc


def is_formula_like_text(value: str) -> bool:
    """Return whether text may execute as a spreadsheet formula on import."""

    normalized = value.lstrip()
    if not normalized or normalized[0] not in {"=", "+", "-", "@"}:
        return False
    if normalized[0] in {"=", "@"}:
        return True
    numeric = normalized[:-1] if normalized.endswith("%") else normalized
    try:
        Decimal(numeric)
    except InvalidOperation:
        return True
    return False


def scalar_text(value: Any) -> str:
    """Serialize spreadsheet values deterministically without evaluating formulas."""

    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)
