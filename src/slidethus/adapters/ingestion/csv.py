from __future__ import annotations

import csv
import io

from slidethus.errors import SourceIngestionError
from slidethus.protocols import DetectedSourceFormat, SourceParseRequest, SourceParseResult

from .common import (
    RiskFinding,
    SourceBlock,
    append_source_block,
    build_parse_result,
    is_formula_like_text,
    read_source_bytes,
)


def _decode_delimited(payload: bytes) -> tuple[str, str]:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16"), "utf-16"
    try:
        return payload.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError as exc:
        raise SourceIngestionError("CSV/TSV source is not valid UTF-8 or UTF-16") from exc


def _dialect_contract(
    text: str,
    detected_format: DetectedSourceFormat,
) -> tuple[str, bool]:
    sample = text[:8192]
    sniffer = csv.Sniffer()
    if detected_format.family == "tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = sniffer.sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    try:
        has_header = sniffer.has_header(sample)
    except csv.Error:
        has_header = False
    return delimiter, has_header


class CsvSourceParser:
    name = "csv-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        return detected_format.family in {"csv", "tsv"}

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        payload = read_source_bytes(request, detected_format)
        text, encoding = _decode_delimited(payload)
        delimiter, has_header = _dialect_contract(text, detected_format)
        reader = csv.reader(
            io.StringIO(text, newline=""),
            delimiter=delimiter,
            strict=True,
        )
        blocks: list[SourceBlock] = []
        risks: list[RiskFinding] = []
        header: list[str] | None = None
        first_nonempty_seen = False
        row_count = 0
        cell_count = 0
        previous_physical_line = 0
        try:
            for row_number, raw_row in enumerate(reader, start=1):
                row_count += 1
                physical_line_end = reader.line_num
                physical_line_start = previous_physical_line + 1
                previous_physical_line = physical_line_end
                cell_count += len(raw_row)
                if row_count > request.limits.max_rows:
                    raise SourceIngestionError(
                        f"CSV exceeds max_rows: {row_count} > {request.limits.max_rows}"
                    )
                if cell_count > request.limits.max_cells:
                    raise SourceIngestionError(
                        f"CSV exceeds max_cells: {cell_count} > {request.limits.max_cells}"
                    )
                row = [cell.strip() for cell in raw_row]
                if not any(row):
                    continue
                locator = f"row {row_number}"
                if physical_line_start != physical_line_end:
                    locator += f"; lines {physical_line_start}-{physical_line_end}"
                for column_number, cell in enumerate(row, start=1):
                    if is_formula_like_text(cell):
                        if len(risks) >= request.limits.max_risks:
                            raise SourceIngestionError(
                                f"CSV exceeds max_risks: {len(risks) + 1} > {request.limits.max_risks}"
                            )
                        risks.append(
                            (
                                "formula_injection",
                                "warning",
                                "Delimited-text cell may execute as a spreadsheet formula; it was preserved as text and never evaluated.",
                                f"{locator} column {column_number}",
                            )
                        )
                if not first_nonempty_seen:
                    first_nonempty_seen = True
                    if has_header:
                        header = row
                        append_source_block(
                            blocks,
                            SourceBlock(
                                locator=locator,
                                text=" | ".join(row),
                                kind="csv_header",
                                metadata={
                                    "row": row_number,
                                    "physical_line_start": physical_line_start,
                                    "physical_line_end": physical_line_end,
                                    "column_count": len(row),
                                    "delimiter": delimiter,
                                    "header_inferred": True,
                                },
                            ),
                            max_blocks=request.limits.max_chunks,
                        )
                        continue
                values = []
                for index, cell in enumerate(row):
                    if not cell:
                        continue
                    label = header[index] if index < len(header) and header[index] else f"column {index + 1}"
                    values.append(f"{label}: {cell}")
                append_source_block(
                    blocks,
                    SourceBlock(
                        locator=locator,
                        text=" | ".join(values) if values else " | ".join(row),
                        kind="csv_row",
                        metadata={
                            "row": row_number,
                            "physical_line_start": physical_line_start,
                            "physical_line_end": physical_line_end,
                            "column_count": len(row),
                            "delimiter": delimiter,
                            "header_inferred": bool(header),
                        },
                    ),
                    max_blocks=request.limits.max_chunks,
                )
        except csv.Error as exc:
            raise SourceIngestionError(f"CSV parsing failed near row {row_count + 1}: {exc}") from exc

        warnings: list[str] = []
        if has_header:
            warnings.append("CSV header row was inferred heuristically")
        if encoding != "utf-8":
            warnings.append(f"Delimited source decoded as {encoding}; normalized to Unicode text")
        return build_parse_result(
            request=request,
            detected_format=detected_format,
            parser_name=self.name,
            parser_version=self.version,
            payload=payload,
            blocks=blocks,
            warnings=warnings,
            extra_risks=risks,
        )
