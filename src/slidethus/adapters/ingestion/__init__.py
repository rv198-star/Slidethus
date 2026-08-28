from __future__ import annotations

from slidethus.protocols import SourceParser

from .csv import CsvSourceParser
from .docx import DocxSourceParser
from .html import HtmlSourceParser
from .image import ImageMetadataSourceParser
from .pdf import PdfSourceParser
from .pptx import PptxSourceParser
from .xlsx import XlsxSourceParser


def default_source_adapters() -> tuple[SourceParser, ...]:
    """Return every admitted M2.2 source adapter in deterministic order."""

    return (
        HtmlSourceParser(),
        CsvSourceParser(),
        PdfSourceParser(),
        DocxSourceParser(),
        PptxSourceParser(),
        XlsxSourceParser(),
        ImageMetadataSourceParser(),
    )


__all__ = [
    "CsvSourceParser",
    "DocxSourceParser",
    "HtmlSourceParser",
    "ImageMetadataSourceParser",
    "PdfSourceParser",
    "PptxSourceParser",
    "XlsxSourceParser",
    "default_source_adapters",
]
