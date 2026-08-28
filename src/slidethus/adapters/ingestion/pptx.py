from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable
from typing import Any

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
    scalar_text,
)


def _iter_shapes(shapes: Iterable[Any], prefix: tuple[int, ...] = ()) -> Iterable[tuple[tuple[int, ...], Any]]:
    for index, shape in enumerate(shapes, start=1):
        path = (*prefix, index)
        yield path, shape
        nested = getattr(shape, "shapes", None)
        if nested is not None:
            yield from _iter_shapes(nested, path)


def _shape_path(path: tuple[int, ...]) -> str:
    return ".".join(str(index) for index in path)


def _chart_lines(chart: Any) -> list[str]:
    """Extract chart categories and series without opening its embedded workbook."""

    series_contracts: list[tuple[str, list[str]]] = []
    for series_number, series in enumerate(chart.series, start=1):
        name = str(getattr(series, "name", "") or f"series {series_number}")
        values = [scalar_text(value) for value in getattr(series, "values", ())]
        series_contracts.append((name, values))

    categories: list[str] = []
    try:
        plots = list(chart.plots)
        if plots:
            categories = [
                scalar_text(getattr(category, "label", category))
                for category in plots[0].categories
            ]
    except (AttributeError, TypeError, ValueError):
        categories = []

    if categories and series_contracts:
        lines = ["Category | " + " | ".join(name for name, _values in series_contracts)]
        row_count = max(
            len(categories),
            *(len(values) for _name, values in series_contracts),
        )
        for row_index in range(row_count):
            row = [categories[row_index] if row_index < len(categories) else ""]
            row.extend(
                values[row_index] if row_index < len(values) else ""
                for _name, values in series_contracts
            )
            lines.append(" | ".join(row))
        return lines
    return [f"{name}: {', '.join(values)}" for name, values in series_contracts]


class PptxSourceParser:
    name = "pptx-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        return detected_format.family == "pptx"

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        payload = read_source_bytes(request, detected_format)
        inspection = preflight_ooxml(payload, request)
        require_archive_member(payload, "ppt/presentation.xml")
        pptx = require_dependency("pptx")
        try:
            presentation = pptx.Presentation(io.BytesIO(payload))
        except Exception as exc:
            raise SourceIngestionError(f"PPTX cannot be opened: {exc}") from exc
        slide_count = len(presentation.slides)
        if slide_count > request.limits.max_slides:
            raise SourceIngestionError(
                f"PPTX exceeds max_slides: {slide_count} > {request.limits.max_slides}"
            )
        if slide_count == 0:
            raise SourceIngestionError("PPTX contains no slides")

        blocks: list[SourceBlock] = []
        warnings = list(inspection.warnings)
        table_rows = 0
        table_cells = 0
        partial_content = any(
            risk[0] == "embedded_object" for risk in inspection.risks
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
        comment_count = sum(1 for name in names if name.startswith("ppt/comments/"))
        if comment_count:
            partial_content = True
            warnings.append(
                f"PPTX contains {comment_count} comment part(s); comments are not extracted in M2.2"
            )
        diagram_count = sum(1 for name in names if name.startswith("ppt/diagrams/"))
        if diagram_count:
            partial_content = True
            warnings.append(
                f"PPTX contains {diagram_count} SmartArt/diagram part(s); diagram semantics are not extracted"
            )
        audiovisual_extensions = {
            ".aac",
            ".avi",
            ".m4a",
            ".m4v",
            ".mov",
            ".mp3",
            ".mp4",
            ".mpeg",
            ".wav",
            ".wmv",
        }
        audiovisual_count = sum(
            1
            for name in names
            if name.startswith("ppt/media/")
            and any(name.lower().endswith(suffix) for suffix in audiovisual_extensions)
        )
        if audiovisual_count:
            partial_content = True
            warnings.append(
                f"PPTX contains {audiovisual_count} audio/video asset(s); media content was not interpreted"
            )
        for slide_number, slide in enumerate(presentation.slides, start=1):
            slide_had_text = False
            for shape_path, shape in _iter_shapes(slide.shapes):
                locator_base = f"slide {slide_number} shape {_shape_path(shape_path)}"
                if getattr(shape, "has_text_frame", False):
                    text = str(shape.text or "").strip()
                    if text:
                        slide_had_text = True
                        append_source_block(
                            blocks,
                            SourceBlock(
                                locator=locator_base,
                                text=text,
                                kind="pptx_shape_text",
                                metadata={
                                    "slide": slide_number,
                                    "shape_path": list(shape_path),
                                    "shape_name": str(getattr(shape, "name", "")),
                                },
                            ),
                            max_blocks=request.limits.max_chunks,
                        )
                if getattr(shape, "has_table", False):
                    table = shape.table
                    for row_number, row in enumerate(table.rows, start=1):
                        table_rows += 1
                        table_cells += len(row.cells)
                        if table_rows > request.limits.max_rows:
                            raise SourceIngestionError(
                                f"PPTX exceeds max_rows: {table_rows} > {request.limits.max_rows}"
                            )
                        if table_cells > request.limits.max_cells:
                            raise SourceIngestionError(
                                f"PPTX exceeds max_cells: {table_cells} > {request.limits.max_cells}"
                            )
                        values = [cell.text.strip() for cell in row.cells]
                        if any(values):
                            slide_had_text = True
                            append_source_block(
                                blocks,
                                SourceBlock(
                                    locator=f"{locator_base} table row {row_number}",
                                    text=" | ".join(values),
                                    kind="pptx_table_row",
                                    metadata={
                                        "slide": slide_number,
                                        "shape_path": list(shape_path),
                                        "row": row_number,
                                        "cell_count": len(values),
                                    },
                                ),
                                max_blocks=request.limits.max_chunks,
                            )
                if getattr(shape, "has_chart", False):
                    chart_lines: list[str] = []
                    try:
                        chart_lines = _chart_lines(shape.chart)
                    except Exception as exc:
                        partial_content = True
                        warnings.append(
                            f"Chart data could not be extracted at {locator_base}: {exc}"
                        )
                    if chart_lines:
                        slide_had_text = True
                        append_source_block(
                            blocks,
                            SourceBlock(
                                locator=f"{locator_base} chart",
                                text="\n".join(chart_lines),
                                kind="pptx_chart_data",
                                metadata={
                                    "slide": slide_number,
                                    "shape_path": list(shape_path),
                                },
                            ),
                            max_blocks=request.limits.max_chunks,
                        )
                try:
                    image = shape.image
                except (AttributeError, TypeError, ValueError):
                    image = None
                if image is not None:
                    partial_content = True
                    filename = str(getattr(image, "filename", "image"))
                    append_source_block(
                        blocks,
                        SourceBlock(
                            locator=f"{locator_base} image metadata",
                            text=(
                                f"Image: {filename}; content type: "
                                f"{getattr(image, 'content_type', 'unknown')}; OCR performed: no"
                            ),
                            kind="pptx_image_metadata",
                            metadata={
                                "slide": slide_number,
                                "shape_path": list(shape_path),
                                "filename": filename,
                                "ocr_performed": False,
                            },
                        ),
                        max_blocks=request.limits.max_chunks,
                    )

            if getattr(slide, "has_notes_slide", False):
                try:
                    notes_text = slide.notes_slide.notes_text_frame.text.strip()
                except (AttributeError, ValueError):
                    notes_text = ""
                if notes_text:
                    slide_had_text = True
                    append_source_block(
                        blocks,
                        SourceBlock(
                            locator=f"slide {slide_number} notes",
                            text=notes_text,
                            kind="pptx_notes",
                            metadata={"slide": slide_number},
                        ),
                        max_blocks=request.limits.max_chunks,
                    )
            if not slide_had_text:
                partial_content = True
                warnings.append(
                    f"Slide {slide_number} has no extractable text; image OCR was not attempted"
                )

        if not blocks:
            raise SourceIngestionError(
                "PPTX contains no extractable text, notes, table/chart data, or image metadata"
            )

        title = str(presentation.core_properties.title or "").strip()
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
            warnings=warnings,
            extra_risks=list(inspection.risks),
            parse_status="partial" if partial_content else "parsed",
        )
