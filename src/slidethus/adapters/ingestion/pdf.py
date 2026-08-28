from __future__ import annotations

import io
import re

from slidethus.errors import SourceIngestionError
from slidethus.protocols import DetectedSourceFormat, SourceParseRequest, SourceParseResult

from .common import (
    RiskFinding,
    SourceBlock,
    append_source_block,
    build_parse_result,
    read_source_bytes,
    require_dependency,
)


class PdfSourceParser:
    name = "pdf-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        return detected_format.family == "pdf"

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        payload = read_source_bytes(request, detected_format)
        pypdf = require_dependency("pypdf")
        try:
            reader = pypdf.PdfReader(io.BytesIO(payload), strict=False)
        except Exception as exc:
            raise SourceIngestionError(f"PDF cannot be opened: {exc}") from exc
        if reader.is_encrypted:
            raise SourceIngestionError("Encrypted PDF is not supported")
        page_count = len(reader.pages)
        if page_count > request.limits.max_pages:
            raise SourceIngestionError(
                f"PDF exceeds max_pages: {page_count} > {request.limits.max_pages}"
            )
        if page_count == 0:
            raise SourceIngestionError("PDF contains no pages")

        warnings: list[str] = []
        blocks: list[SourceBlock] = []
        extracted_bytes = 0
        estimated_chunks = 0
        metadata = reader.metadata or {}
        document_title = str(metadata.get("/Title") or "").strip()
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise SourceIngestionError(
                    f"PDF text extraction failed on page {page_number}: {exc}"
                ) from exc
            text = text.strip()
            if not text:
                warnings.append(
                    f"Page {page_number} has no extractable text; OCR was not attempted"
                )
                continue
            extracted_bytes += len(text.encode("utf-8"))
            if extracted_bytes > request.limits.max_uncompressed_bytes:
                raise SourceIngestionError(
                    "PDF extracted text exceeds max_uncompressed_bytes: "
                    f"{extracted_bytes} > {request.limits.max_uncompressed_bytes}"
                )
            estimated_chunks += max(
                1,
                (len(text) + request.limits.max_chunk_chars - 1)
                // request.limits.max_chunk_chars,
            )
            if estimated_chunks > request.limits.max_chunks:
                raise SourceIngestionError(
                    "PDF extracted text exceeds max_chunks after splitting: "
                    f"{estimated_chunks} > {request.limits.max_chunks}"
                )
            block_metadata = {"page": page_number}
            if document_title:
                block_metadata["document_title"] = document_title
            append_source_block(
                blocks,
                SourceBlock(
                    locator=f"page {page_number}",
                    text=text,
                    kind="pdf_page",
                    metadata=block_metadata,
                ),
                max_blocks=request.limits.max_chunks,
            )

        if not blocks:
            raise SourceIngestionError(
                "PDF contains no extractable text; OCR was not attempted"
            )

        risks: list[RiskFinding] = []
        if re.search(br"/(?:JavaScript|OpenAction|AA)\b", payload, re.IGNORECASE):
            risks.append(
                (
                    "active_content",
                    "high",
                    "PDF contains JavaScript or automatic-action markers; they were not executed.",
                    "pdf catalog",
                )
            )
        if re.search(br"/(?:EmbeddedFiles|Filespec)\b", payload, re.IGNORECASE):
            risks.append(
                (
                    "embedded_object",
                    "high",
                    "PDF contains embedded-file markers; attachments were not extracted or executed.",
                    "pdf catalog",
                )
            )
        if re.search(br"/(?:Annots|AcroForm|RichMedia)\b", payload, re.IGNORECASE):
            warnings.append(
                "PDF annotations, forms, or rich-media markers are present but are not extracted"
            )
        return build_parse_result(
            request=request,
            detected_format=detected_format,
            parser_name=self.name,
            parser_version=self.version,
            payload=payload,
            blocks=blocks,
            warnings=warnings,
            extra_risks=risks,
            parse_status="partial" if warnings or risks else "parsed",
        )
