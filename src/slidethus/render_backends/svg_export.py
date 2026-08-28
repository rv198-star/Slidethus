from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from slidethus.errors import RenderBackendError, RenderCapabilityError
from slidethus.io_utils import (
    atomic_create_bytes,
    atomic_create_json,
    ensure_within,
    read_json,
    sha256_bytes,
    sha256_file,
)
from slidethus.render_backends.node_toolchain import node_executable, validate_sidecar
from slidethus.render_backends.node_toolchain import renderer_root as resolve_renderer_root


@dataclass(frozen=True)
class SvgExportResult:
    png_paths: tuple[Path, ...]
    pdf_path: Path
    report_path: Path
    changed: bool


def _validate_png(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional adapter boundary
        raise RenderCapabilityError(
            "PNG export verification requires Pillow; install slidethus[rendering]"
        ) from exc
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001
        raise RenderBackendError(f"Exported PNG is invalid: {path}: {exc}") from exc
    return int(width), int(height)


def _validate_pdf(path: Path, expected_pages: int) -> None:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - optional adapter boundary
        raise RenderCapabilityError(
            "PDF export verification requires pypdf; install slidethus[rendering]"
        ) from exc
    try:
        reader = PdfReader(path)
    except Exception as exc:  # noqa: BLE001
        raise RenderBackendError(f"Exported PDF is invalid: {path}: {exc}") from exc
    if len(reader.pages) != expected_pages:
        raise RenderBackendError(
            f"Exported PDF page count mismatch: {len(reader.pages)} != {expected_pages}"
        )


class SvgPreviewExportService:
    """Rasterize Final SVG pages with resvg and compile a multi-page PDF with pdf-lib."""

    def __init__(
        self,
        workspace: Path,
        *,
        renderer_root: Path | None = None,
        node: str | None = None,
        timeout_seconds: int = 180,
    ) -> None:
        self.workspace = workspace.resolve()
        self.renderer_root = resolve_renderer_root(renderer_root)
        self.node = node
        self.timeout_seconds = timeout_seconds

    def export(
        self,
        svg_paths: tuple[Path, ...] | list[Path],
        *,
        generated_at: str,
        output_dir: Path,
    ) -> SvgExportResult:
        """Produce independently rasterized PNG pages and one valid PDF."""

        admitted: list[Path] = []
        for raw_path in svg_paths:
            path = ensure_within(self.workspace, raw_path.resolve())
            if not path.is_file() or path.suffix.lower() != ".svg":
                raise RenderBackendError(f"Preview input is not a Final SVG page: {path}")
            admitted.append(path)
        if not admitted:
            raise RenderBackendError("SVG preview export requires at least one page")
        root = ensure_within(self.workspace, output_dir.resolve())
        root.mkdir(parents=True, exist_ok=True)
        executable = node_executable(self.node)
        script = validate_sidecar(
            self.renderer_root,
            script_name="preview.mjs",
            dependencies={"@resvg/resvg-js": "2.6.2", "pdf-lib": "1.17.1"},
        )
        with tempfile.TemporaryDirectory(prefix="slidethus-svg-export-", dir=root) as name:
            temporary = Path(name)
            input_path = temporary / "inputs.json"
            raw_png_dir = temporary / "png"
            raw_pdf = temporary / "preview.pdf"
            raw_report = temporary / "report.json"
            inputs = [
                {"slide_id": path.name.split("-", 2)[0] + "-" + path.name.split("-", 2)[1], "path": str(path)}
                for path in admitted
            ]
            input_path.write_text(
                json.dumps(inputs, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    executable,
                    str(script),
                    "--inputs",
                    str(input_path),
                    "--png-dir",
                    str(raw_png_dir),
                    "--pdf",
                    str(raw_pdf),
                    "--report",
                    str(raw_report),
                    "--generated-at",
                    generated_at,
                ],
                cwd=self.renderer_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if process.returncode != 0 or not raw_pdf.is_file() or not raw_report.is_file():
                detail = (process.stderr or process.stdout).strip()
                raise RenderBackendError(
                    f"SVG preview/export sidecar failed: {detail or process.returncode}"
                )
            sidecar_report = read_json(raw_report)
            raw_pngs = sorted(raw_png_dir.glob("*.png"))
            if len(raw_pngs) != len(admitted):
                raise RenderBackendError(
                    f"PNG preview count mismatch: {len(raw_pngs)} != {len(admitted)}"
                )
            png_payloads = [(path.name, path.read_bytes()) for path in raw_pngs]
            pdf_payload = raw_pdf.read_bytes()

        png_dir = root / "png"
        png_outputs: list[Path] = []
        changed = False
        dimensions: list[dict[str, int | str]] = []
        for name, payload in png_payloads:
            digest = sha256_bytes(payload)
            slide_id = name.removesuffix(".png")
            path = png_dir / f"{slide_id}-{digest[:16]}.png"
            created = atomic_create_bytes(path, payload)
            changed = changed or created
            if not created and path.read_bytes() != payload:
                raise RenderBackendError(f"Immutable PNG output contains different content: {path}")
            width, height = _validate_png(path)
            dimensions.append(
                {"slide_id": slide_id, "width": width, "height": height}
            )
            png_outputs.append(path)
        pdf_digest = sha256_bytes(pdf_payload)
        pdf_path = root / f"preview-{pdf_digest[:16]}.pdf"
        pdf_created = atomic_create_bytes(pdf_path, pdf_payload)
        changed = changed or pdf_created
        if not pdf_created and pdf_path.read_bytes() != pdf_payload:
            raise RenderBackendError(f"Immutable PDF output contains different content: {pdf_path}")
        _validate_pdf(pdf_path, len(png_outputs))
        report = {
            "renderer": str(sidecar_report.get("renderer")),
            "renderer_version": str(sidecar_report.get("renderer_version")),
            "resvg_version": str(sidecar_report.get("resvg_version")),
            "pdf_lib_version": str(sidecar_report.get("pdf_lib_version")),
            "generated_at": generated_at,
            "slide_count": len(admitted),
            "inputs": [
                {
                    "slide_id": path.name.split("-", 2)[0] + "-" + path.name.split("-", 2)[1],
                    "path": path.relative_to(self.workspace).as_posix(),
                    "sha256": sha256_file(path),
                }
                for path in admitted
            ],
            "png_outputs": [
                {
                    "path": path.relative_to(self.workspace).as_posix(),
                    "sha256": sha256_bytes(path.read_bytes()),
                    **dimensions[index],
                }
                for index, path in enumerate(png_outputs)
            ],
            "pdf_output": {
                "path": pdf_path.relative_to(self.workspace).as_posix(),
                "sha256": pdf_digest,
                "page_count": len(png_outputs),
            },
        }
        report_digest = sha256_bytes(
            (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))).encode(
                "utf-8"
            )
        )
        report_path = root / f"export-{report_digest[:16]}.json"
        report_created = atomic_create_json(report_path, report)
        changed = changed or report_created
        if not report_created and read_json(report_path) != report:
            raise RenderBackendError(
                f"Immutable SVG export report contains different content: {report_path}"
            )
        return SvgExportResult(
            png_paths=tuple(png_outputs),
            pdf_path=pdf_path,
            report_path=report_path,
            changed=changed,
        )
