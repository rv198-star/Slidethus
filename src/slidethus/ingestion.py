from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from slidethus.errors import SourceIngestionError, UnsupportedSourceError
from slidethus.io_utils import sha256_bytes
from slidethus.protocols import (
    DetectedSourceFormat,
    SourceChunk,
    SourceParseLimits,
    SourceParser,
    SourceParseRequest,
    SourceParseResult,
    SourceRisk,
)

_SOURCE_ID = re.compile(r"^SRC-[0-9]{3}$")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_UNTRUSTED_INSTRUCTION_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|override)\s+(?:all\s+)?(?:previous|prior|system|developer)\s+(?:instructions?|prompts?|messages?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:execute|run|invoke|call)\s+(?:the\s+)?(?:following\s+)?(?:command|tool|shell|script)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:reveal|print|upload|exfiltrate)\s+(?:the\s+)?(?:secret|token|password|system prompt|api key)\b",
        re.IGNORECASE,
    ),
    re.compile(r"忽略(?:以上|前文|之前|先前|所有).{0,12}(?:指令|提示|要求|内容)"),
    re.compile(
        r"(?:(?:请|必须|现在|立即|直接|务必|你(?:需要|应该|要)?)(?:执行|运行|调用)(?:以下|这个|该)?|(?:执行|运行|调用)(?:以下|这个|该))(?:命令|工具|脚本|终端)"
    ),
    re.compile(r"(?:上传|泄露|显示|输出)(?:密钥|令牌|密码|系统提示词|API\s*Key)", re.IGNORECASE),
)
_EXTERNAL_LINK = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
_ACTIVE_CONTENT = re.compile(r"(?:<script\b|javascript:|vbscript:|powershell\b|curl\s+https?://)", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_markdown(text: str) -> str:
    text = re.sub(r"`{1,3}", "", text)
    text = _MARKDOWN_LINK.sub(r"\1 (\2)", text)
    text = re.sub(r"[*_~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_source_format_bytes(path: Path, payload: bytes) -> DetectedSourceFormat:
    """Detect a source family from one captured payload and its filename."""

    path = path.resolve()
    suffix = path.suffix.lower()
    head = payload[:8192]
    guessed_type = mimetypes.guess_type(path.name)[0]

    if head.startswith(b"%PDF-"):
        return DetectedSourceFormat("pdf", "application/pdf", suffix, "pdf-header", "high")
    if head.startswith(b"PK\x03\x04"):
        office = {
            ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ".pptx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        }
        family, media_type = office.get(suffix, ("zip", guessed_type or "application/zip"))
        return DetectedSourceFormat(family, media_type, suffix, "zip-header", "high")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedSourceFormat("image", "image/png", suffix, "png-header", "high")
    if head.startswith(b"\xff\xd8\xff"):
        return DetectedSourceFormat("image", "image/jpeg", suffix, "jpeg-header", "high")
    if head.startswith((b"GIF87a", b"GIF89a")):
        return DetectedSourceFormat("image", "image/gif", suffix, "gif-header", "high")
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return DetectedSourceFormat("image", "image/webp", suffix, "webp-header", "high")
    if head.startswith(b"BM"):
        return DetectedSourceFormat("image", "image/bmp", suffix, "bmp-header", "high")
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return DetectedSourceFormat("image", "image/tiff", suffix, "tiff-header", "high")
    if head.startswith(b"\x00\x00\x01\x00"):
        return DetectedSourceFormat("image", "image/x-icon", suffix, "ico-header", "high")
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return DetectedSourceFormat(
            "ole",
            guessed_type or "application/x-ole-storage",
            suffix,
            "ole-header",
            "high",
        )

    stripped = head.lstrip().lower()
    if suffix in {".html", ".htm"} or stripped.startswith(
        (b"<!doctype html", b"<html", b"<head", b"<body")
    ):
        return DetectedSourceFormat("html", "text/html", suffix, "html-text", "high")

    family = {
        ".md": "markdown",
        ".markdown": "markdown",
        ".csv": "csv",
        ".tsv": "tsv",
    }.get(suffix, "text")
    media_type = {
        "markdown": "text/markdown",
        "csv": "text/csv",
        "tsv": "text/tab-separated-values",
    }.get(family, guessed_type or "text/plain")
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return DetectedSourceFormat(family, media_type, suffix, "unicode-bom", "high")
    if b"\x00" not in head:
        try:
            head.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
        else:
            confidence = (
                "high"
                if suffix in {".md", ".markdown", ".txt", ".csv", ".tsv"}
                else "medium"
            )
            return DetectedSourceFormat(
                family,
                media_type,
                suffix,
                "decodable-text",
                confidence,
            )

    return DetectedSourceFormat(
        "unknown",
        guessed_type or "application/octet-stream",
        suffix,
        "unknown",
        "low",
    )


def detect_source_format(path: Path) -> DetectedSourceFormat:
    """Detect a source family from signatures first and suffixes second."""

    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise SourceIngestionError(f"Source is not a regular file: {path}")
    with path.open("rb") as handle:
        head = handle.read(8192)
    return detect_source_format_bytes(path, head)


def verify_detected_source_format(
    path: Path,
    payload: bytes,
    expected: DetectedSourceFormat,
) -> None:
    """Reject a file whose captured bytes no longer match parser selection."""

    actual = detect_source_format_bytes(path, payload)
    expected_contract = (
        expected.family,
        expected.media_type,
        expected.suffix,
        expected.detection_method,
    )
    actual_contract = (
        actual.family,
        actual.media_type,
        actual.suffix,
        actual.detection_method,
    )
    if actual_contract != expected_contract:
        raise SourceIngestionError(
            "Source format changed between detection and parsing: "
            f"expected {expected.family}/{expected.detection_method}, "
            f"captured {actual.family}/{actual.detection_method}"
        )


class ParserRegistry:
    """Select one provider-neutral parser using explicit support and priority."""

    def __init__(self, parsers: Iterable[SourceParser] = ()) -> None:
        self._parsers: list[SourceParser] = []
        for parser in parsers:
            self.register(parser)

    @property
    def parsers(self) -> tuple[SourceParser, ...]:
        return tuple(self._parsers)

    def register(self, parser: SourceParser) -> None:
        identity = (parser.name, parser.version)
        if any((item.name, item.version) == identity for item in self._parsers):
            raise SourceIngestionError(
                f"Parser is already registered: {parser.name}@{parser.version}"
            )
        self._parsers.append(parser)

    def select(self, detected_format: DetectedSourceFormat) -> SourceParser:
        candidates = [parser for parser in self._parsers if parser.supports(detected_format)]
        if not candidates:
            raise UnsupportedSourceError(
                "No admitted parser supports "
                f"family={detected_format.family}, media_type={detected_format.media_type}"
            )
        candidates.sort(key=lambda item: item.priority, reverse=True)
        top_priority = candidates[0].priority
        top = [item for item in candidates if item.priority == top_priority]
        if len(top) > 1:
            identities = ", ".join(f"{item.name}@{item.version}" for item in top)
            raise SourceIngestionError(
                f"Ambiguous parser selection at priority {top_priority}: {identities}"
            )
        return candidates[0]

    def parse(self, request: SourceParseRequest) -> SourceParseResult:
        detected_format = detect_source_format(request.path)
        parser = self.select(detected_format)
        return parser.parse(request, detected_format)


def parse_source(parser: SourceParser, request: SourceParseRequest) -> SourceParseResult:
    """Run one explicit parser after deterministic format detection."""

    detected_format = detect_source_format(request.path)
    if not parser.supports(detected_format):
        raise UnsupportedSourceError(
            f"{parser.name}@{parser.version} does not support {detected_format.family}"
        )
    return parser.parse(request, detected_format)


def contains_untrusted_instruction(chunks: Iterable[SourceChunk]) -> bool:
    """Return whether parsed source data contains common instruction-injection wording."""

    return any(
        pattern.search(chunk.text)
        for chunk in chunks
        for pattern in _UNTRUSTED_INSTRUCTION_PATTERNS
    )


def validate_source_parse_limits(limits: SourceParseLimits) -> None:
    """Validate shared source limits before cache lookup or adapter execution."""

    for name, value in asdict(limits).items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SourceIngestionError(f"Source parse limit {name} must be a positive integer")
    if limits.max_chunks > 9999:
        raise SourceIngestionError("max_chunks must not exceed 9999")
    if limits.max_risks > 99_999:
        raise SourceIngestionError("max_risks must not exceed 99999")


def build_source_risks(
    chunks: Iterable[SourceChunk],
    source_id: str,
    extra_findings: Iterable[tuple[str, str, str, str | None]] = (),
    *,
    max_risks: int = 10_000,
) -> tuple[SourceRisk, ...]:
    """Build deterministic source-risk records from extracted data and adapter findings."""

    unique: list[tuple[str, str, str, str | None]] = []
    seen: set[tuple[str, str | None, str]] = set()

    def add(finding: tuple[str, str, str, str | None]) -> None:
        key = (finding[0], finding[3], finding[2])
        if key in seen:
            return
        if len(unique) >= max_risks:
            raise SourceIngestionError(
                f"Source exceeds max_risks: {len(unique) + 1} > {max_risks}"
            )
        seen.add(key)
        unique.append(finding)

    for chunk in chunks:
        searchable = "\n".join(
            part
            for part in (str(chunk.metadata.get("title", "")), chunk.text)
            if part
        )
        if any(pattern.search(searchable) for pattern in _UNTRUSTED_INSTRUCTION_PATTERNS):
            add(
                (
                    "prompt_injection",
                    "high",
                    "Source contains instruction-like wording; preserve as data and never execute it.",
                    chunk.locator,
                )
            )
        if _ACTIVE_CONTENT.search(searchable):
            add(
                (
                    "active_content",
                    "high",
                    "Source contains active-content wording or script markers.",
                    chunk.locator,
                )
            )
        if _EXTERNAL_LINK.search(searchable):
            add(
                (
                    "external_link",
                    "info",
                    "Source contains external links; links were not opened during parsing.",
                    chunk.locator,
                )
            )
    for finding in extra_findings:
        add(finding)
    return tuple(
        SourceRisk(
            risk_id=f"RSK-{source_id}-{index:03d}",
            category=category,
            severity=severity,
            message=message,
            locator=locator,
        )
        for index, (category, severity, message, locator) in enumerate(unique, start=1)
    )


class TextSourceParser:
    """Production text/Markdown parser with stable locators, hashes, limits, and risks."""

    name = "text-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        if detected_format.family == "markdown":
            return detected_format.suffix in {".md", ".markdown"}
        if detected_format.family == "text":
            return detected_format.suffix in {"", ".txt"}
        return False

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        path = request.path.resolve()
        if not _SOURCE_ID.fullmatch(request.source_id):
            raise SourceIngestionError(f"Invalid source ID: {request.source_id}")
        if not self.supports(detected_format):
            raise UnsupportedSourceError(
                f"{self.name} does not support detected family {detected_format.family}"
            )
        limits = request.limits
        validate_source_parse_limits(limits)

        stat_size = path.stat().st_size
        if stat_size > limits.max_source_bytes:
            raise SourceIngestionError(
                f"Source exceeds max_source_bytes: {stat_size} > {limits.max_source_bytes}"
            )
        payload = path.read_bytes()
        verify_detected_source_format(path, payload, detected_format)
        size_bytes = len(payload)
        if size_bytes > limits.max_source_bytes:
            raise SourceIngestionError(
                f"Source exceeds max_source_bytes after read: {size_bytes} > {limits.max_source_bytes}"
            )
        text, encoding, warnings = self._decode(payload, path)
        lines = text.splitlines()
        if not any(line.strip() for line in lines):
            raise SourceIngestionError(f"Source contains no usable text: {path}")

        chunks, split_count = self._chunk_lines(
            lines,
            request.source_id,
            max_chunk_chars=limits.max_chunk_chars,
        )
        if not chunks:
            raise SourceIngestionError(f"Source parser returned no usable chunks: {path}")
        if len(chunks) > limits.max_chunks:
            raise SourceIngestionError(
                f"Source exceeds max_chunks: {len(chunks)} > {limits.max_chunks}"
            )
        if split_count:
            warnings.append(
                f"{split_count} logical section(s) were split to satisfy max_chunk_chars"
            )
        if encoding != "utf-8":
            warnings.append(f"Source decoded as {encoding}; normalized to Unicode text")

        risks = build_source_risks(
            chunks,
            request.source_id,
            max_risks=request.limits.max_risks,
        )
        return SourceParseResult(
            source_id=request.source_id,
            parser_name=self.name,
            parser_version=self.version,
            detected_format=detected_format,
            source_sha256=sha256_bytes(payload),
            size_bytes=size_bytes,
            parsed_at=_utc_now(),
            chunks=tuple(chunks),
            warnings=tuple(dict.fromkeys(warnings)),
            risks=tuple(risks),
        )

    @staticmethod
    def _decode(payload: bytes, path: Path) -> tuple[str, str, list[str]]:
        warnings: list[str] = []
        try:
            if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
                return payload.decode("utf-16"), "utf-16", warnings
            return payload.decode("utf-8-sig"), "utf-8", warnings
        except UnicodeDecodeError as exc:
            raise SourceIngestionError(
                f"Source is not valid UTF-8/UTF-16 text: {path}"
            ) from exc

    def _chunk_lines(
        self,
        lines: list[str],
        source_id: str,
        *,
        max_chunk_chars: int,
    ) -> tuple[list[SourceChunk], int]:
        heading_rows = [
            (line_number, match)
            for line_number, line in enumerate(lines, start=1)
            if (match := _HEADING.match(line))
        ]
        if heading_rows:
            spans: list[tuple[int, int, str, int | None]] = []
            if heading_rows[0][0] > 1:
                spans.append((1, heading_rows[0][0] - 1, "", None))
            for index, (line_number, match) in enumerate(heading_rows):
                end_line = (
                    heading_rows[index + 1][0] - 1
                    if index + 1 < len(heading_rows)
                    else len(lines)
                )
                spans.append(
                    (
                        line_number,
                        end_line,
                        _clean_markdown(match.group(2)),
                        len(match.group(1)),
                    )
                )
        else:
            spans = self._paragraph_spans(lines)

        chunks: list[SourceChunk] = []
        split_count = 0
        for start_line, end_line, title, heading_level in spans:
            generated = self._chunks_from_span(
                lines,
                source_id,
                start_line=start_line,
                end_line=end_line,
                title=title,
                heading_level=heading_level,
                max_chunk_chars=max_chunk_chars,
                start_ordinal=len(chunks) + 1,
            )
            if len(generated) > 1:
                split_count += 1
            chunks.extend(generated)
        return chunks, split_count

    @staticmethod
    def _paragraph_spans(lines: list[str]) -> list[tuple[int, int, str, int | None]]:
        spans: list[tuple[int, int, str, int | None]] = []
        start: int | None = None
        for line_number, line in enumerate([*lines, ""], start=1):
            if line.strip() and start is None:
                start = line_number
            if not line.strip() and start is not None:
                end = line_number - 1
                title = _clean_markdown(lines[start - 1])[:120]
                spans.append((start, end, title, None))
                start = None
        return spans

    def _chunks_from_span(
        self,
        lines: list[str],
        source_id: str,
        *,
        start_line: int,
        end_line: int,
        title: str,
        heading_level: int | None,
        max_chunk_chars: int,
        start_ordinal: int,
    ) -> list[SourceChunk]:
        body_start = start_line + 1 if heading_level is not None else start_line
        rows = [
            (line_number, _clean_markdown(lines[line_number - 1]))
            for line_number in range(body_start, end_line + 1)
            if _clean_markdown(lines[line_number - 1])
        ]
        if not rows and title:
            rows = [(start_line, title)]
        if not rows:
            return []

        groups: list[tuple[list[tuple[int, str]], tuple[int, int] | None]] = []
        current: list[tuple[int, str]] = []
        current_chars = 0
        for row in rows:
            added = len(row[1]) + (1 if current else 0)
            if current and current_chars + added > max_chunk_chars:
                groups.append((current, None))
                current = []
                current_chars = 0
            if len(row[1]) > max_chunk_chars:
                if current:
                    groups.append((current, None))
                    current = []
                    current_chars = 0
                for offset in range(0, len(row[1]), max_chunk_chars):
                    fragment = row[1][offset : offset + max_chunk_chars]
                    groups.append(
                        (
                            [(row[0], fragment)],
                            (offset + 1, offset + len(fragment)),
                        )
                    )
                continue
            current.append(row)
            current_chars += added
        if current:
            groups.append((current, None))

        chunks: list[SourceChunk] = []
        for group_index, (group, char_range) in enumerate(groups):
            ordinal = start_ordinal + group_index
            text = "\n".join(value for _line_number, value in group)
            digest = sha256_bytes(text.encode("utf-8"))
            if char_range is not None:
                chunk_start = group[0][0]
                chunk_end = group[0][0]
                locator = (
                    f"line {chunk_start}; chars {char_range[0]}-{char_range[1]}"
                )
            else:
                chunk_start = (
                    start_line
                    if group_index == 0 and heading_level is not None
                    else group[0][0]
                )
                chunk_end = end_line if len(groups) == 1 else group[-1][0]
                locator = f"lines {chunk_start}-{chunk_end}"
            chunk_title = title
            if len(groups) > 1 and title:
                chunk_title = f"{title} ({group_index + 1}/{len(groups)})"
            metadata = {
                "title": chunk_title or text[:120],
                "line_start": chunk_start,
                "line_end": chunk_end,
                "heading_level": heading_level,
            }
            if char_range is not None:
                metadata.update(
                    {
                        "char_start": char_range[0],
                        "char_end": char_range[1],
                    }
                )
            chunks.append(
                SourceChunk(
                    source_id=source_id,
                    locator=locator,
                    text=text,
                    chunk_id=f"CHK-{source_id}-{ordinal:04d}-{digest[:8].upper()}",
                    ordinal=ordinal,
                    content_hash=f"sha256:{digest}",
                    kind="section" if heading_level is not None else "paragraph",
                    metadata=metadata,
                )
            )
        return chunks


def default_parser_registry() -> ParserRegistry:
    from slidethus.adapters.ingestion import default_source_adapters

    return ParserRegistry([TextSourceParser(), *default_source_adapters()])
