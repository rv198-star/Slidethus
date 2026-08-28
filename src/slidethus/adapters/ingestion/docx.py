from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from slidethus.errors import SourceIngestionError
from slidethus.protocols import DetectedSourceFormat, SourceParseRequest, SourceParseResult

from .common import (
    SourceBlock,
    append_source_block,
    build_parse_result,
    preflight_ooxml,
    read_source_bytes,
    require_archive_member,
    require_dependency,
)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _xml_supplemental_blocks(
    payload: bytes,
    *,
    max_blocks: int,
) -> tuple[list[SourceBlock], list[str]]:
    blocks: list[SourceBlock] = []
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            for index, textbox in enumerate(root.iter(f"{_W}txbxContent"), start=1):
                text = " ".join(
                    node.text.strip()
                    for node in textbox.iter(f"{_W}t")
                    if node.text and node.text.strip()
                )
                if text:
                    append_source_block(
                        blocks,
                        SourceBlock(
                            locator=f"textbox {index}",
                            text=text,
                            kind="docx_textbox",
                            metadata={"textbox": index},
                        ),
                        max_blocks=max_blocks,
                    )
            for index, drawing in enumerate(root.iter(f"{_WP}docPr"), start=1):
                alt = (drawing.attrib.get("descr") or drawing.attrib.get("title") or "").strip()
                if alt:
                    append_source_block(
                        blocks,
                        SourceBlock(
                            locator=f"image alt {index}",
                            text=alt,
                            kind="docx_image_alt",
                            metadata={"image_index": index},
                        ),
                        max_blocks=max_blocks,
                    )
            names = set(archive.namelist())
            if "word/footnotes.xml" in names:
                warnings.append("DOCX footnotes are present but are not extracted in M2.2")
            if "word/comments.xml" in names:
                warnings.append("DOCX comments are present but are not extracted in M2.2")
            if "word/endnotes.xml" in names:
                warnings.append("DOCX endnotes are present but are not extracted in M2.2")
            if next(root.iter(f"{_M}oMath"), None) is not None:
                warnings.append(
                    "DOCX equations are present but equation structure is not extracted in M2.2"
                )
            if next(root.iter(f"{_W}altChunk"), None) is not None:
                warnings.append(
                    "DOCX contains altChunk imported content that is not extracted in M2.2"
                )
            chart_count = sum(1 for name in names if name.startswith("word/charts/"))
            if chart_count:
                warnings.append(
                    f"DOCX contains {chart_count} chart part(s); chart data and presentation semantics are not extracted"
                )
            diagram_count = sum(1 for name in names if name.startswith("word/diagrams/"))
            if diagram_count:
                warnings.append(
                    f"DOCX contains {diagram_count} SmartArt/diagram part(s); diagram semantics are not extracted"
                )
            image_count = sum(1 for name in names if name.startswith("word/media/"))
            if image_count:
                warnings.append(
                    f"DOCX contains {image_count} image asset(s); image content and OCR were not interpreted"
                )
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise SourceIngestionError(f"DOCX XML cannot be inspected: {exc}") from exc
    return blocks, warnings


class DocxSourceParser:
    name = "docx-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        return detected_format.family == "docx"

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        payload = read_source_bytes(request, detected_format)
        inspection = preflight_ooxml(payload, request)
        require_archive_member(payload, "word/document.xml")
        docx = require_dependency("docx")
        paragraph_module = require_dependency("docx.text.paragraph")
        table_module = require_dependency("docx.table")
        namespace_module = require_dependency("docx.oxml.ns")
        try:
            document = docx.Document(io.BytesIO(payload))
        except Exception as exc:
            raise SourceIngestionError(f"DOCX cannot be opened: {exc}") from exc

        Paragraph = paragraph_module.Paragraph
        Table = table_module.Table
        qn = namespace_module.qn
        blocks: list[SourceBlock] = []
        paragraph_number = 0
        table_number = 0
        table_rows = 0
        table_cells = 0
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                paragraph_number += 1
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if text:
                    style_name = (
                        paragraph.style.name
                        if paragraph.style is not None and paragraph.style.name
                        else ""
                    )
                    append_source_block(
                        blocks,
                        SourceBlock(
                            locator=f"paragraph {paragraph_number}",
                            text=text,
                            kind="docx_paragraph",
                            metadata={
                                "paragraph": paragraph_number,
                                "style": style_name,
                            },
                        ),
                        max_blocks=request.limits.max_chunks,
                    )
            elif child.tag == qn("w:tbl"):
                table_number += 1
                table = Table(child, document)
                for row_number, row in enumerate(table.rows, start=1):
                    table_rows += 1
                    table_cells += len(row.cells)
                    if table_rows > request.limits.max_rows:
                        raise SourceIngestionError(
                            f"DOCX exceeds max_rows: {table_rows} > {request.limits.max_rows}"
                        )
                    if table_cells > request.limits.max_cells:
                        raise SourceIngestionError(
                            f"DOCX exceeds max_cells: {table_cells} > {request.limits.max_cells}"
                        )
                    values = [cell.text.strip() for cell in row.cells]
                    if any(values):
                        append_source_block(
                            blocks,
                            SourceBlock(
                                locator=f"table {table_number} row {row_number}",
                                text=" | ".join(values),
                                kind="docx_table_row",
                                metadata={
                                    "table": table_number,
                                    "row": row_number,
                                    "cell_count": len(values),
                                },
                            ),
                            max_blocks=request.limits.max_chunks,
                        )

        seen_story_parts: set[str] = set()
        for section_number, section in enumerate(document.sections, start=1):
            for label, story in (("header", section.header), ("footer", section.footer)):
                partname = str(story.part.partname)
                if partname in seen_story_parts:
                    continue
                seen_story_parts.add(partname)
                for paragraph_index, paragraph in enumerate(story.paragraphs, start=1):
                    text = paragraph.text.strip()
                    if text:
                        append_source_block(
                            blocks,
                            SourceBlock(
                                locator=(
                                    f"section {section_number} {label} paragraph {paragraph_index}"
                                ),
                                text=text,
                                kind=f"docx_{label}",
                                metadata={
                                    "section": section_number,
                                    "story": label,
                                    "paragraph": paragraph_index,
                                },
                            ),
                            max_blocks=request.limits.max_chunks,
                        )
                for story_table_number, story_table in enumerate(story.tables, start=1):
                    for row_number, row in enumerate(story_table.rows, start=1):
                        table_rows += 1
                        table_cells += len(row.cells)
                        if table_rows > request.limits.max_rows:
                            raise SourceIngestionError(
                                f"DOCX exceeds max_rows: {table_rows} > {request.limits.max_rows}"
                            )
                        if table_cells > request.limits.max_cells:
                            raise SourceIngestionError(
                                f"DOCX exceeds max_cells: {table_cells} > {request.limits.max_cells}"
                            )
                        values = [cell.text.strip() for cell in row.cells]
                        if any(values):
                            append_source_block(
                                blocks,
                                SourceBlock(
                                    locator=(
                                        f"section {section_number} {label} table "
                                        f"{story_table_number} row {row_number}"
                                    ),
                                    text=" | ".join(values),
                                    kind=f"docx_{label}_table_row",
                                    metadata={
                                        "section": section_number,
                                        "story": label,
                                        "table": story_table_number,
                                        "row": row_number,
                                        "cell_count": len(values),
                                    },
                                ),
                                max_blocks=request.limits.max_chunks,
                            )

        supplemental, supplemental_warnings = _xml_supplemental_blocks(
            payload,
            max_blocks=request.limits.max_chunks,
        )
        for block in supplemental:
            append_source_block(
                blocks,
                block,
                max_blocks=request.limits.max_chunks,
            )
        title = str(document.core_properties.title or "").strip()
        if title and blocks:
            first = blocks[0]
            blocks[0] = SourceBlock(
                locator=first.locator,
                text=first.text,
                kind=first.kind,
                metadata={**first.metadata, "document_title": title},
            )
        return build_parse_result(
            request=request,
            detected_format=detected_format,
            parser_name=self.name,
            parser_version=self.version,
            payload=payload,
            blocks=blocks,
            warnings=[*inspection.warnings, *supplemental_warnings],
            extra_risks=list(inspection.risks),
            parse_status=(
                "partial"
                if supplemental_warnings
                or any(risk[0] == "embedded_object" for risk in inspection.risks)
                else "parsed"
            ),
        )
