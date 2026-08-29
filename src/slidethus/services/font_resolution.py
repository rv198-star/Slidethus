from __future__ import annotations

import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.errors import FontResolutionError, RenderCapabilityError


@dataclass(frozen=True)
class FontResolution:
    requested: str
    actual: str
    status: str
    file_path: str | None
    reason: str

    def as_manifest_value(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "actual": self.actual,
            "status": self.status,
            "file_path": self.file_path,
            "reason": self.reason,
        }


def _normalized_family(value: str) -> str:
    return " ".join(value.casefold().replace(",", " ").split())


def _required_codepoints(value: str) -> frozenset[int]:
    return frozenset(
        ord(char)
        for char in value
        if not char.isspace() and not unicodedata.category(char).startswith("C")
    )


def _parse_fontconfig_charset(value: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for token in value.split():
        try:
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                start = int(start_text, 16)
                end = int(end_text, 16)
                if end < start or end > 0x10FFFF:
                    raise ValueError
                ranges.append((start, end))
            else:
                codepoint = int(token, 16)
                if codepoint > 0x10FFFF:
                    raise ValueError
                ranges.append((codepoint, codepoint))
        except ValueError as exc:
            raise FontResolutionError(
                f"fc-query returned an invalid charset token: {token}"
            ) from exc
    if not ranges:
        raise FontResolutionError("fc-query returned no Unicode charset coverage")
    return tuple(ranges)


def _codepoint_label(codepoint: int) -> str:
    width = 4 if codepoint <= 0xFFFF else 6
    return f"U+{codepoint:0{width}X}"


class FontResolutionService:
    """Resolve Visual System font families through Fontconfig without copying font files."""

    def __init__(
        self,
        *,
        font_match: str | None = None,
        font_query: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.font_match = font_match or shutil.which("fc-match")
        sibling_query = (
            Path(font_match).with_name("fc-query")
            if font_match is not None
            else None
        )
        self.font_query = (
            font_query
            or (str(sibling_query) if sibling_query and sibling_query.is_file() else None)
            or shutil.which("fc-query")
        )
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self.font_match and self.font_query)

    def _match(self, family: str) -> tuple[str, str | None]:
        if not self.font_match:
            raise RenderCapabilityError("Font resolution requires the Fontconfig `fc-match` tool")
        process = subprocess.run(
            [self.font_match, "-f", "%{family[0]}\n%{file}\n", family],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        if process.returncode != 0:
            raise FontResolutionError(
                f"fc-match failed for {family}: {(process.stderr or process.stdout).strip()}"
            )
        lines = [item.strip() for item in process.stdout.splitlines() if item.strip()]
        if not lines:
            raise FontResolutionError(f"fc-match returned no result for {family}")
        actual = lines[0]
        file_path = lines[1] if len(lines) > 1 and Path(lines[1]).is_file() else None
        return actual, file_path

    def _missing_codepoints(
        self,
        file_path: str | None,
        required: frozenset[int],
    ) -> frozenset[int]:
        if not required:
            return frozenset()
        if not self.font_query:
            raise RenderCapabilityError(
                "Font glyph coverage requires the Fontconfig `fc-query` tool"
            )
        if not file_path or not Path(file_path).is_file():
            raise FontResolutionError(
                "Fontconfig did not resolve a readable font file for glyph coverage"
            )
        process = subprocess.run(
            [self.font_query, "-f", "%{charset}\n", file_path],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        if process.returncode != 0:
            raise FontResolutionError(
                "fc-query failed for "
                f"{file_path}: {(process.stderr or process.stdout).strip()}"
            )
        covered = _parse_fontconfig_charset(process.stdout)
        return frozenset(
            codepoint
            for codepoint in required
            if not any(start <= codepoint <= end for start, end in covered)
        )

    def _coverage_failure(
        self,
        *,
        family: str,
        file_path: str | None,
        required: frozenset[int],
    ) -> str | None:
        try:
            missing = self._missing_codepoints(file_path, required)
        except (FontResolutionError, RenderCapabilityError) as exc:
            return f"{family}: {exc}"
        if not missing:
            return None
        examples = ", ".join(_codepoint_label(item) for item in sorted(missing)[:12])
        suffix = "" if len(missing) <= 12 else f", +{len(missing) - 12} more"
        return f"{family}: missing {len(missing)} required glyph(s): {examples}{suffix}"

    def resolve_family(
        self,
        requested: str,
        *,
        fallbacks: list[str] | tuple[str, ...] = (),
        required_characters: str = "",
    ) -> FontResolution:
        """Resolve one requested family and admitted fallbacks conservatively."""

        requested = " ".join(str(requested).split()).strip()
        if not requested:
            raise FontResolutionError("Requested font family is empty")
        required = _required_codepoints(required_characters)
        failures: list[str] = []
        actual, file_path = self._match(requested)
        requested_failure = self._coverage_failure(
            family=actual,
            file_path=file_path,
            required=required,
        )
        if (
            _normalized_family(actual) == _normalized_family(requested)
            and requested_failure is None
        ):
            return FontResolution(
                requested=requested,
                actual=actual,
                status="available",
                file_path=file_path,
                reason="requested_font_available:glyph_coverage_verified",
            )
        if requested_failure:
            failures.append(requested_failure)
        for fallback in fallbacks:
            normalized = " ".join(str(fallback).split()).strip()
            if not normalized:
                continue
            matched, fallback_file = self._match(normalized)
            failure = self._coverage_failure(
                family=matched,
                file_path=fallback_file,
                required=required,
            )
            if (
                _normalized_family(matched) == _normalized_family(normalized)
                and failure is None
            ):
                return FontResolution(
                    requested=requested,
                    actual=matched,
                    status="substituted",
                    file_path=fallback_file,
                    reason=f"fallback_selected:{normalized}:glyph_coverage_verified",
                )
            if failure:
                failures.append(failure)
        if (
            _normalized_family(actual) != _normalized_family(requested)
            and requested_failure is None
        ):
            return FontResolution(
                requested=requested,
                actual=actual,
                status="substituted",
                file_path=file_path,
                reason="fontconfig_best_match:glyph_coverage_verified",
            )
        detail = "; ".join(dict.fromkeys(failures))
        raise FontResolutionError(
            f"No compatible font covers the required deck glyphs for {requested}"
            + (f": {detail}" if detail else "")
        )

    def resolve_visual_system(
        self,
        visual_system: dict[str, Any],
        *,
        required_characters_by_family: dict[str, str] | None = None,
    ) -> tuple[FontResolution, ...]:
        """Resolve every unique Visual System typography family in stable order."""

        requirements = required_characters_by_family or {}
        fallbacks_by_family = {
            str(key): tuple(str(item) for item in value)
            for key, value in visual_system.get("font_fallbacks", {}).items()
        }
        requested = sorted(
            {
                str(style.get("font_family", "")).strip()
                for style in visual_system.get("typography", {}).values()
                if str(style.get("font_family", "")).strip()
            }
        )
        return tuple(
            self.resolve_family(
                family,
                fallbacks=fallbacks_by_family.get(family, ()),
                required_characters=requirements.get(family, ""),
            )
            for family in requested
        )
