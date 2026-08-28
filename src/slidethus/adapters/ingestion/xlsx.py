from __future__ import annotations

import io
import zipfile

from slidethus.errors import SourceIngestionError
from slidethus.protocols import DetectedSourceFormat, SourceParseRequest, SourceParseResult

from .common import (
    RiskFinding,
    SourceBlock,
    append_source_block,
    build_parse_result,
    is_formula_like_text,
    preflight_ooxml,
    read_source_bytes,
    require_archive_member,
    require_dependency,
    scalar_text,
)


class XlsxSourceParser:
    name = "xlsx-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        return detected_format.family == "xlsx"

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        payload = read_source_bytes(request, detected_format)
        inspection = preflight_ooxml(payload, request)
        require_archive_member(payload, "xl/workbook.xml")
        openpyxl = require_dependency("openpyxl")
        try:
            workbook = openpyxl.load_workbook(
                io.BytesIO(payload),
                read_only=True,
                data_only=False,
                keep_links=False,
            )
        except Exception as exc:
            raise SourceIngestionError(f"XLSX cannot be opened: {exc}") from exc

        blocks: list[SourceBlock] = []
        warnings = list(inspection.warnings)
        risks: list[RiskFinding] = list(inspection.risks)
        partial_content = any(
            risk[0] == "embedded_object" for risk in inspection.risks
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
        comment_parts = [
            name
            for name in names
            if name.startswith(("xl/comments", "xl/threadedComments/"))
        ]
        if comment_parts:
            partial_content = True
            warnings.append(
                f"XLSX contains {len(comment_parts)} comment part(s); comments are not extracted in M2.2"
            )
        media_count = sum(1 for name in names if name.startswith("xl/media/"))
        if media_count:
            partial_content = True
            warnings.append(
                f"XLSX contains {media_count} image/media asset(s); visual content and OCR were not interpreted"
            )
        chart_count = sum(1 for name in names if name.startswith("xl/charts/"))
        if chart_count:
            partial_content = True
            warnings.append(
                f"XLSX contains {chart_count} chart part(s); chart presentation semantics were not extracted"
            )
        total_rows = 0
        total_cells = 0
        try:
            worksheets = list(workbook.worksheets)
            if len(worksheets) > request.limits.max_sheets:
                raise SourceIngestionError(
                    f"XLSX exceeds max_sheets: {len(worksheets)} > {request.limits.max_sheets}"
                )
            if not worksheets:
                raise SourceIngestionError("XLSX contains no worksheets")

            for sheet_number, worksheet in enumerate(worksheets, start=1):
                estimated_rows = int(worksheet.max_row or 0)
                estimated_columns = int(worksheet.max_column or 0)
                if estimated_rows > request.limits.max_rows - total_rows:
                    raise SourceIngestionError(
                        "XLSX declared dimensions exceed max_rows: "
                        f"{total_rows + estimated_rows} > {request.limits.max_rows}"
                    )
                estimated_cells = estimated_rows * estimated_columns
                if estimated_cells > request.limits.max_cells - total_cells:
                    raise SourceIngestionError(
                        "XLSX declared dimensions exceed max_cells: "
                        f"{total_cells + estimated_cells} > {request.limits.max_cells}"
                    )

                sheet_had_content = False
                for row_number, row in enumerate(worksheet.iter_rows(), start=1):
                    total_rows += 1
                    total_cells += len(row)
                    if total_rows > request.limits.max_rows:
                        raise SourceIngestionError(
                            f"XLSX exceeds max_rows: {total_rows} > {request.limits.max_rows}"
                        )
                    if total_cells > request.limits.max_cells:
                        raise SourceIngestionError(
                            f"XLSX exceeds max_cells: {total_cells} > {request.limits.max_cells}"
                        )

                    values: list[str] = []
                    for cell in row:
                        value = scalar_text(cell.value)
                        if not value:
                            continue
                        coordinate = str(cell.coordinate)
                        number_format = str(getattr(cell, "number_format", "") or "General")
                        displayed = f"{coordinate}: {value}"
                        if number_format != "General":
                            displayed += f" [number_format: {number_format}]"
                        values.append(displayed)
                        is_formula = str(getattr(cell, "data_type", "")) == "f"
                        formula_like = (
                            not is_formula
                            and isinstance(cell.value, str)
                            and is_formula_like_text(cell.value)
                        )
                        if is_formula or formula_like:
                            if len(risks) >= request.limits.max_risks:
                                raise SourceIngestionError(
                                    "XLSX exceeds max_risks: "
                                    f"{len(risks) + 1} > {request.limits.max_risks}"
                                )
                            risks.append(
                                (
                                    "formula_injection",
                                    "warning",
                                    "Spreadsheet formula or formula-like text was preserved verbatim and never evaluated.",
                                    f"sheet {worksheet.title!r} cell {coordinate}",
                                )
                            )
                    if not values:
                        continue
                    sheet_had_content = True
                    append_source_block(
                        blocks,
                        SourceBlock(
                            locator=f"sheet {worksheet.title!r} row {row_number}",
                            text=" | ".join(values),
                            kind="xlsx_row",
                            metadata={
                                "sheet": worksheet.title,
                                "sheet_number": sheet_number,
                                "sheet_state": worksheet.sheet_state,
                                "row": row_number,
                                "visited_cell_count": len(row),
                            },
                        ),
                        max_blocks=request.limits.max_chunks,
                    )
                if not sheet_had_content:
                    warnings.append(f"Worksheet {worksheet.title!r} contains no usable values")

            title = str(workbook.properties.title or "").strip()
            if title and blocks:
                first = blocks[0]
                blocks[0] = SourceBlock(
                    locator=first.locator,
                    text=first.text,
                    kind=first.kind,
                    metadata={**first.metadata, "document_title": title},
                )
        finally:
            workbook.close()

        return build_parse_result(
            request=request,
            detected_format=detected_format,
            parser_name=self.name,
            parser_version=self.version,
            payload=payload,
            blocks=blocks,
            warnings=warnings,
            extra_risks=risks,
            parse_status="partial" if partial_content else "parsed",
        )
