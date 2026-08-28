from __future__ import annotations

import codecs
import re
from html.parser import HTMLParser
from typing import Any

from slidethus.errors import SourceIngestionError
from slidethus.protocols import DetectedSourceFormat, SourceParseRequest, SourceParseResult

from .common import (
    RiskFinding,
    SourceBlock,
    append_source_block,
    build_parse_result,
    read_source_bytes,
)

_CHARSET = re.compile(
    br"<meta\b[^>]*charset\s*=\s*['\"]?\s*([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_BLOCK_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "blockquote",
    "pre",
    "dt",
    "dd",
    "figcaption",
    "caption",
}
_IGNORED_TAGS = {"script", "style", "template"}
_EXTERNAL_SCHEMES = ("http://", "https://", "//")


def _decode_html(payload: bytes) -> tuple[str, str]:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16"), "utf-16"
    match = _CHARSET.search(payload[:8192])
    if match:
        encoding = match.group(1).decode("ascii", errors="ignore")
        try:
            codecs.lookup(encoding)
            return payload.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError) as exc:
            raise SourceIngestionError(
                f"HTML declares an unsupported or invalid charset: {encoding}"
            ) from exc
    try:
        return payload.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError as exc:
        raise SourceIngestionError(
            "HTML is not UTF-8/UTF-16 and has no usable declared charset"
        ) from exc


class _SemanticHTMLParser(HTMLParser):
    def __init__(
        self,
        *,
        max_blocks: int,
        max_risks: int,
        max_rows: int,
        max_cells: int,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.max_blocks = max_blocks
        self.max_risks = max_risks
        self.max_rows = max_rows
        self.max_cells = max_cells
        self.blocks: list[SourceBlock] = []
        self.risks: list[RiskFinding] = []
        self.warnings: list[str] = []
        self._tag_counts: dict[str, int] = {}
        self._active_tag: str | None = None
        self._active_locator = ""
        self._active_kind = "html_block"
        self._active_metadata: dict[str, Any] = {}
        self._parts: list[str] = []
        self._ignored_depth = 0
        self._title_depth = 0
        self.title = ""
        self.table_rows = 0
        self.table_cells = 0
        self._in_table_row = False
        self._table_cell_parts: list[str] = []
        self._table_cells_in_row: list[str] = []
        self._anchor_targets: list[str] = []

    def _next_locator(self, tag: str) -> str:
        self._tag_counts[tag] = self._tag_counts.get(tag, 0) + 1
        return f"html {tag}[{self._tag_counts[tag]}]"

    def _append_block(self, block: SourceBlock) -> None:
        append_source_block(self.blocks, block, max_blocks=self.max_blocks)

    def _append_risk(self, finding: RiskFinding) -> None:
        if len(self.risks) >= self.max_risks:
            raise SourceIngestionError(
                f"Source exceeds max_risks: {len(self.risks) + 1} > {self.max_risks}"
            )
        self.risks.append(finding)

    def _append_text(self, value: str) -> None:
        if self._in_table_row:
            self._table_cell_parts.append(value)
        elif self._active_tag is not None:
            self._parts.append(value)

    def _start_block(self, tag: str, *, kind: str | None = None) -> None:
        self._finish_block()
        self._active_tag = tag
        self._active_locator = self._next_locator(tag)
        self._active_kind = kind or f"html_{tag}"
        self._active_metadata = {"html_tag": tag}
        self._parts = []

    def _finish_block(self) -> None:
        if self._active_tag is None:
            return
        text = " ".join(part.strip() for part in self._parts if part.strip()).strip()
        if text:
            self._append_block(
                SourceBlock(
                    locator=self._active_locator,
                    text=text,
                    kind=self._active_kind,
                    metadata=dict(self._active_metadata),
                )
            )
        self._active_tag = None
        self._active_locator = ""
        self._active_metadata = {}
        self._parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        attributes = {name.lower(): value or "" for name, value in attrs}
        if normalized in _IGNORED_TAGS:
            self._ignored_depth += 1
            self._append_risk(
                (
                    "active_content",
                    "high" if normalized == "script" else "warning",
                    f"HTML contains <{normalized}> content; it was ignored and never executed.",
                    self._next_locator(normalized),
                )
            )
            return
        if self._ignored_depth:
            return
        if normalized == "title":
            self._title_depth += 1
        if normalized == "tr":
            self._finish_block()
            self._in_table_row = True
            self._table_cells_in_row = []
            self.table_rows += 1
            if self.table_rows > self.max_rows:
                raise SourceIngestionError(
                    f"HTML exceeds max_rows: {self.table_rows} > {self.max_rows}"
                )
        elif normalized in {"td", "th"} and self._in_table_row:
            self._table_cell_parts = []
            self.table_cells += 1
            if self.table_cells > self.max_cells:
                raise SourceIngestionError(
                    f"HTML exceeds max_cells: {self.table_cells} > {self.max_cells}"
                )
        elif normalized in _BLOCK_TAGS:
            self._start_block(normalized)
        elif normalized == "img":
            alt = attributes.get("alt", "").strip()
            if alt:
                metadata: dict[str, Any] = {"html_tag": "img", "attribute": "alt"}
                source_target = attributes.get("src", "").strip()
                if source_target:
                    metadata["source_target"] = source_target
                self._append_block(
                    SourceBlock(
                        locator=self._next_locator("img-alt"),
                        text=alt,
                        kind="html_image_alt",
                        metadata=metadata,
                    )
                )
        elif normalized == "br" and self._active_tag is not None:
            self._parts.append("\n")

        if normalized == "a":
            self._anchor_targets.append(attributes.get("href", "").strip())

        for attribute in ("href", "src", "action", "formaction"):
            value = attributes.get(attribute, "").strip()
            if value.lower().startswith(_EXTERNAL_SCHEMES):
                displayed_target = value[:500] + ("…" if len(value) > 500 else "")
                self._append_risk(
                    (
                        "external_relationship",
                        "warning",
                        f"HTML {normalized}.{attribute} target was preserved but never opened: {displayed_target}",
                        self._next_locator(f"{normalized}-{attribute}"),
                    )
                )
        if any(name.startswith("on") and value for name, value in attributes.items()):
            self._append_risk(
                (
                    "active_content",
                    "high",
                    f"HTML <{normalized}> contains an inline event handler; it was not executed.",
                    self._next_locator(f"{normalized}-event"),
                )
            )

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in _IGNORED_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if normalized == "title" and self._title_depth:
            self._title_depth -= 1
        if normalized == "a" and self._anchor_targets:
            target = self._anchor_targets.pop()
            if target:
                self._append_text(f" ({target})")
        if normalized in {"td", "th"} and self._in_table_row:
            cell = " ".join(
                part.strip() for part in self._table_cell_parts if part.strip()
            ).strip()
            self._table_cells_in_row.append(cell)
            self._table_cell_parts = []
        elif normalized == "tr" and self._in_table_row:
            text = " | ".join(self._table_cells_in_row).strip(" |")
            if text:
                self._append_block(
                    SourceBlock(
                        locator=self._next_locator("table-row"),
                        text=text,
                        kind="html_table_row",
                        metadata={
                            "html_tag": "tr",
                            "cell_count": len(self._table_cells_in_row),
                        },
                    )
                )
            self._in_table_row = False
            self._table_cells_in_row = []
        elif normalized == self._active_tag:
            self._finish_block()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._title_depth:
            self.title += data
        self._append_text(data)

    def close(self) -> None:
        super().close()
        self._finish_block()
        if self._in_table_row:
            text = " | ".join(self._table_cells_in_row).strip(" |")
            if text:
                self._append_block(
                    SourceBlock(
                        locator=self._next_locator("table-row"),
                        text=text,
                        kind="html_table_row",
                    )
                )
            self._in_table_row = False


class HtmlSourceParser:
    name = "html-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        return detected_format.family == "html"

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        payload = read_source_bytes(request, detected_format)
        text, encoding = _decode_html(payload)
        parser = _SemanticHTMLParser(
            max_blocks=request.limits.max_chunks,
            max_risks=request.limits.max_risks,
            max_rows=request.limits.max_rows,
            max_cells=request.limits.max_cells,
        )
        try:
            parser.feed(text)
            parser.close()
        except SourceIngestionError:
            raise
        except Exception as exc:
            raise SourceIngestionError(f"HTML parsing failed: {exc}") from exc
        warnings = list(parser.warnings)
        if encoding.lower().replace("_", "-") not in {"utf-8", "utf8"}:
            warnings.append(f"HTML decoded as {encoding}; normalized to Unicode text")
        document_title = parser.title.strip()
        if document_title:
            if len(parser.blocks) >= request.limits.max_chunks:
                raise SourceIngestionError(
                    "HTML title would exceed max_chunks: "
                    f"{len(parser.blocks) + 1} > {request.limits.max_chunks}"
                )
            parser.blocks.insert(
                0,
                SourceBlock(
                    locator="html title[1]",
                    text=document_title,
                    kind="html_title",
                    metadata={"html_tag": "title", "document_title": document_title},
                ),
            )
        return build_parse_result(
            request=request,
            detected_format=detected_format,
            parser_name=self.name,
            parser_version=self.version,
            payload=payload,
            blocks=parser.blocks,
            warnings=warnings,
            extra_risks=parser.risks,
        )
