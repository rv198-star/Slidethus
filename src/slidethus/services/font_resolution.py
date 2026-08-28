from __future__ import annotations

import shutil
import subprocess
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


class FontResolutionService:
    """Resolve Visual System font families through Fontconfig without copying font files."""

    def __init__(
        self,
        *,
        font_match: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.font_match = font_match or shutil.which("fc-match")
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self.font_match)

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

    def resolve_family(
        self,
        requested: str,
        *,
        fallbacks: list[str] | tuple[str, ...] = (),
    ) -> FontResolution:
        """Resolve one requested family and admitted fallbacks conservatively."""

        requested = " ".join(str(requested).split()).strip()
        if not requested:
            raise FontResolutionError("Requested font family is empty")
        actual, file_path = self._match(requested)
        if _normalized_family(actual) == _normalized_family(requested):
            return FontResolution(
                requested=requested,
                actual=actual,
                status="available",
                file_path=file_path,
                reason="requested_font_available",
            )
        for fallback in fallbacks:
            normalized = " ".join(str(fallback).split()).strip()
            if not normalized:
                continue
            matched, fallback_file = self._match(normalized)
            if _normalized_family(matched) == _normalized_family(normalized):
                return FontResolution(
                    requested=requested,
                    actual=matched,
                    status="substituted",
                    file_path=fallback_file,
                    reason=f"fallback_selected:{normalized}",
                )
        return FontResolution(
            requested=requested,
            actual=actual,
            status="substituted",
            file_path=file_path,
            reason="fontconfig_best_match",
        )

    def resolve_visual_system(self, visual_system: dict[str, Any]) -> tuple[FontResolution, ...]:
        """Resolve every unique Visual System typography family in stable order."""

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
            )
            for family in requested
        )
