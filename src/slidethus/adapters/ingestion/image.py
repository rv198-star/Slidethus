from __future__ import annotations

import io
import warnings
from typing import Any

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

_SENSITIVE_EXIF_TAGS = {
    "Artist",
    "BodySerialNumber",
    "CameraOwnerName",
    "Copyright",
    "GPSInfo",
    "HostComputer",
    "ImageUniqueID",
    "LensSerialNumber",
}
_TEXT_EXIF_TAGS = {
    "ImageDescription",
    "XPTitle",
    "XPSubject",
    "XPKeywords",
    "XPComment",
    "UserComment",
}


def _text_value(value: Any) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-16-le", "utf-8"):
            try:
                return value.decode(encoding).rstrip("\x00").strip()
            except UnicodeDecodeError:
                continue
        return ""
    return str(value).strip()


class ImageMetadataSourceParser:
    name = "image-metadata-source-parser"
    version = "1.0.0"
    priority = 100

    def supports(self, detected_format: DetectedSourceFormat) -> bool:
        return detected_format.family == "image"

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult:
        payload = read_source_bytes(request, detected_format)
        Image = require_dependency("PIL.Image")
        ExifTags = require_dependency("PIL.ExifTags")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(payload)) as image:
                    width, height = image.size
                    frame_count = int(getattr(image, "n_frames", 1) or 1)
                    pixels_per_frame = int(width) * int(height)
                    total_pixels = pixels_per_frame * frame_count
                    if width < 1 or height < 1:
                        raise SourceIngestionError(
                            f"Image has invalid dimensions: {width}x{height}"
                        )
                    if total_pixels > request.limits.max_image_pixels:
                        raise SourceIngestionError(
                            "Image exceeds max_image_pixels across frames: "
                            f"{total_pixels} > {request.limits.max_image_pixels}"
                        )
                    image_format = str(image.format or "unknown").upper()
                    mode = str(image.mode or "unknown")
                    info_keys = sorted(str(key) for key in image.info)
                    dpi = image.info.get("dpi")
                    exif = image.getexif()
                    exif_items = list(exif.items()) if exif else []
                with Image.open(io.BytesIO(payload)) as verifier:
                    verifier.verify()
        except SourceIngestionError:
            raise
        except Exception as exc:
            raise SourceIngestionError(f"Image cannot be opened or verified: {exc}") from exc

        metadata_lines = [
            f"Format: {image_format}",
            f"Dimensions: {width} x {height}",
            f"Mode: {mode}",
            f"Frames: {frame_count}",
            "OCR performed: no",
        ]
        if dpi:
            metadata_lines.append(f"DPI: {dpi}")
        if info_keys:
            metadata_lines.append(f"Metadata fields: {', '.join(info_keys)}")
        blocks: list[SourceBlock] = []
        append_source_block(
            blocks,
            SourceBlock(
                locator="image metadata",
                text="\n".join(metadata_lines),
                kind="image_metadata",
                metadata={
                    "format": image_format,
                    "width": width,
                    "height": height,
                    "mode": mode,
                    "frame_count": frame_count,
                    "pixels_per_frame": pixels_per_frame,
                    "total_pixels": total_pixels,
                    "ocr_performed": False,
                },
            ),
            max_blocks=request.limits.max_chunks,
        )

        tag_names = getattr(ExifTags, "TAGS", {})
        sensitive_tags: list[str] = []
        for tag_id, raw_value in exif_items:
            tag_name = str(tag_names.get(tag_id, tag_id))
            if tag_name in _SENSITIVE_EXIF_TAGS:
                sensitive_tags.append(tag_name)
            if tag_name not in _TEXT_EXIF_TAGS:
                continue
            value = _text_value(raw_value)
            if value:
                append_source_block(
                    blocks,
                    SourceBlock(
                        locator=f"EXIF {tag_name}",
                        text=value,
                        kind="image_exif_text",
                        metadata={"exif_tag": tag_name},
                    ),
                    max_blocks=request.limits.max_chunks,
                )

        risks: list[RiskFinding] = []
        if sensitive_tags:
            risks.append(
                (
                    "sensitive_metadata",
                    "warning",
                    "Image contains potentially identifying EXIF fields: "
                    + ", ".join(sorted(set(sensitive_tags)))
                    + ". Values were not copied into the summary block.",
                    "image EXIF",
                )
            )
        adapter_warnings = [
            "Image content was not interpreted and OCR was not attempted in M2.2"
        ]
        return build_parse_result(
            request=request,
            detected_format=detected_format,
            parser_name=self.name,
            parser_version=self.version,
            payload=payload,
            blocks=blocks,
            warnings=adapter_warnings,
            extra_risks=risks,
            parse_status="partial",
        )
