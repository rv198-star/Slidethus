from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import RenderAssetError, RenderCapabilityError
from slidethus.io_utils import ensure_within, sha256_file

_SVG_BLOCKED_ELEMENTS = {"script", "foreignobject", "iframe", "object", "embed"}
_EXTERNAL_REF = re.compile(r"^(?:https?:|//|file:|javascript:)", re.IGNORECASE)
_CSS_EXTERNAL = re.compile(r"url\(\s*['\"]?(?:https?:|//|file:|javascript:)", re.IGNORECASE)
_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
}


@dataclass(frozen=True)
class ResolvedRenderAsset:
    asset_id: str
    kind: str
    path: Path
    media_type: str
    content_hash: str
    width: int | None
    height: int | None
    fit: str
    editable_as: str
    attribution: str | None

    def as_sidecar_value(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "media_type": self.media_type,
            "content_hash": self.content_hash,
            "width": self.width,
            "height": self.height,
            "fit": self.fit,
            "editable_as": self.editable_as,
            "attribution": self.attribution,
        }


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].lower()


def validate_safe_svg(path: Path, *, max_bytes: int = 10 * 1024 * 1024) -> None:
    """Reject active content and external references in one local SVG asset."""

    if path.stat().st_size > max_bytes:
        raise RenderAssetError(f"SVG asset exceeds {max_bytes} bytes: {path}")
    payload = path.read_bytes()
    lowered = payload.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise RenderAssetError(f"SVG DTD/entity declarations are not allowed: {path}")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RenderAssetError(f"SVG asset is invalid XML: {path}: {exc}") from exc
    if _local_name(root.tag) != "svg":
        raise RenderAssetError(f"SVG asset root is not <svg>: {path}")
    for element in root.iter():
        if _local_name(element.tag) in _SVG_BLOCKED_ELEMENTS:
            raise RenderAssetError(
                f"SVG active/foreign element is not allowed: {_local_name(element.tag)}"
            )
        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            value = str(raw_value).strip()
            if name.startswith("on"):
                raise RenderAssetError(f"SVG event handler is not allowed: {name}")
            if name in {"href", "src"} and value and not value.startswith("#"):
                if _EXTERNAL_REF.match(value) or not value.startswith("data:image/"):
                    raise RenderAssetError(f"SVG external reference is not allowed: {value}")
            if name == "style" and _CSS_EXTERNAL.search(value):
                raise RenderAssetError("SVG external CSS url() is not allowed")
        if element.text and _CSS_EXTERNAL.search(element.text):
            raise RenderAssetError("SVG external CSS url() is not allowed")


def _raster_dimensions(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional adapter boundary
        raise RenderCapabilityError(
            "Raster asset verification requires Pillow; install slidethus[ingestion]"
        ) from exc
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001
        raise RenderAssetError(f"Raster asset cannot be verified: {path}: {exc}") from exc
    if width < 1 or height < 1:
        raise RenderAssetError(f"Raster asset has invalid dimensions: {path}")
    return int(width), int(height)


class RenderAssetService:
    """Resolve renderer assets from the versioned Asset Manifest without network access."""

    def __init__(
        self,
        workspace: Path,
        *,
        runtime: ArtifactRuntime | None = None,
        max_asset_bytes: int = 64 * 1024 * 1024,
        max_data_rows: int = 100_000,
        max_data_cells: int = 1_000_000,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.max_asset_bytes = max_asset_bytes
        self.max_data_rows = max_data_rows
        self.max_data_cells = max_data_cells

    def resolve(self, asset_ids: list[str] | tuple[str, ...]) -> dict[str, ResolvedRenderAsset]:
        manifest = self.runtime.show_artifact("asset_manifest")
        by_id = {str(item["asset_id"]): item for item in manifest.get("assets", [])}
        output: dict[str, ResolvedRenderAsset] = {}
        for asset_id in sorted(set(str(item) for item in asset_ids)):
            item = by_id.get(asset_id)
            if item is None:
                raise RenderAssetError(f"Unknown Asset ID: {asset_id}")
            if item.get("status") != "available":
                raise RenderAssetError(f"Asset is not available: {asset_id}")
            if item.get("allowed_use") in {"reference_only", "do_not_use"}:
                raise RenderAssetError(f"Asset is not admitted for rendering: {asset_id}")
            raw_path = str(item.get("path_or_url", "")).strip()
            if raw_path.startswith(("http://", "https://", "//", "data:", "file:")):
                raise RenderAssetError(
                    f"Renderer assets must be local workspace paths; network/data URI rejected: {asset_id}"
                )
            relative = Path(raw_path)
            if relative.is_absolute():
                raise RenderAssetError(f"Asset path must be workspace-relative: {asset_id}")
            path = ensure_within(self.workspace, self.workspace / relative)
            if not path.is_file():
                raise RenderAssetError(f"Asset file is missing: {asset_id}: {relative}")
            if path.stat().st_size > self.max_asset_bytes:
                raise RenderAssetError(
                    f"Asset exceeds max_asset_bytes={self.max_asset_bytes}: {asset_id}"
                )
            digest = sha256_file(path)
            expected = str(item.get("content_hash") or "").removeprefix("sha256:")
            if expected and expected != digest:
                raise RenderAssetError(f"Asset content hash mismatch: {asset_id}")
            suffix = path.suffix.lower()
            media_type = str(item.get("media_type") or _MEDIA_TYPES.get(suffix, "application/octet-stream"))
            width = item.get("width")
            height = item.get("height")
            kind = str(item.get("kind"))
            if suffix == ".svg" or kind == "svg":
                validate_safe_svg(path, max_bytes=self.max_asset_bytes)
            elif suffix in _RASTER_SUFFIXES or kind in {"image", "logo", "icon"}:
                measured_width, measured_height = _raster_dimensions(path)
                if width is not None and int(width) != measured_width:
                    raise RenderAssetError(f"Asset width metadata mismatch: {asset_id}")
                if height is not None and int(height) != measured_height:
                    raise RenderAssetError(f"Asset height metadata mismatch: {asset_id}")
                width, height = measured_width, measured_height
            output[asset_id] = ResolvedRenderAsset(
                asset_id=asset_id,
                kind=kind,
                path=path,
                media_type=media_type,
                content_hash=digest,
                width=int(width) if width is not None else None,
                height=int(height) if height is not None else None,
                fit=str(item.get("fit") or "contain"),
                editable_as=str(item.get("editable_as") or "not_editable"),
                attribution=(str(item["attribution"]) if item.get("attribution") else None),
            )
        return output

    def load_data(self, asset_id: str) -> Any:
        """Load bounded JSON/CSV/TSV chart or table data without formula evaluation."""

        resolved = self.resolve((asset_id,))[asset_id]
        if resolved.kind not in {"chart_data", "table_data"}:
            raise RenderAssetError(f"Asset is not declared as chart/table data: {asset_id}")
        suffix = resolved.path.suffix.lower()
        if suffix == ".json":
            try:
                value = json.loads(resolved.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RenderAssetError(f"Invalid JSON data asset: {asset_id}: {exc}") from exc
            return value
        if suffix not in {".csv", ".tsv"}:
            raise RenderAssetError(f"Unsupported data asset format: {asset_id}: {suffix}")
        delimiter = "\t" if suffix == ".tsv" else ","
        rows: list[list[str]] = []
        cells = 0
        try:
            with resolved.path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.reader(handle, delimiter=delimiter):
                    rows.append([str(cell) for cell in row])
                    cells += len(row)
                    if len(rows) > self.max_data_rows or cells > self.max_data_cells:
                        raise RenderAssetError(
                            f"Data asset exceeds row/cell limits: {asset_id}"
                        )
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise RenderAssetError(f"Invalid delimited data asset: {asset_id}: {exc}") from exc
        return rows
