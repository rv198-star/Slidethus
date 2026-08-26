from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from slidethus.io_utils import atomic_write_bytes, ensure_within, read_json
from slidethus.protocols import RenderRequest, RenderResult

LOGICAL_WIDTH = 1280
LOGICAL_HEIGHT = 720
SLIDE_WIDTH_INCHES = 13.333333
SLIDE_HEIGHT_INCHES = 7.5


def _hex_color(value: str) -> RGBColor:
    normalized = value.lstrip("#")
    if len(normalized) != 6:
        raise ValueError(f"Expected six-digit color, got {value!r}")
    return RGBColor.from_string(normalized.upper())


def _inches(value: float, logical_total: int, physical_total: float) -> Inches:
    return Inches(value / logical_total * physical_total)


def _block_text(content: Any) -> list[str]:
    if isinstance(content, list):
        return [str(item) for item in content]
    if isinstance(content, dict):
        return [f"{key}: {value}" for key, value in content.items()]
    return [str(content)]


def _xml_escape(value: str) -> str:
    return html.escape(value, quote=True)


def _set_run_font(run: Any, style: dict[str, Any]) -> None:
    """Set Latin and East Asian typefaces for cross-renderer CJK fidelity."""

    run.font.name = style["font_family"]
    run.font.size = Pt(style["font_size"])
    run.font.bold = style["font_weight"] >= 600
    run.font.color.rgb = _hex_color(style["color"])
    properties = run._r.get_or_add_rPr()  # python-pptx has no public East Asian API
    east_asian = properties.find("{http://schemas.openxmlformats.org/drawingml/2006/main}ea")
    if east_asian is None:
        east_asian = OxmlElement("a:ea")
        properties.append(east_asian)
    east_asian.set("typeface", style["font_family"])


class MinimalPptxRenderBackend:
    """Render schema-backed layouts as native editable PPTX text and shapes."""

    name = "python-pptx-minimal"
    version = "0.1.0"

    def render(self, request: RenderRequest) -> RenderResult:
        if request.target_format != "pptx":
            raise ValueError("MinimalPptxRenderBackend only supports pptx")
        workspace = request.workspace.resolve()
        output_dir = ensure_within(workspace, request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        specs = read_json(workspace / "slides/slide_specs.json")
        layouts = read_json(workspace / "layout/layout_plans.json")
        visual = read_json(workspace / "design/visual_system.json")
        outline = read_json(workspace / "outline/deck_outline.json")
        project_id = specs["project_id"]
        output_path = output_dir / f"{project_id.lower()}.pptx"

        presentation = Presentation()
        presentation.slide_width = Inches(SLIDE_WIDTH_INCHES)
        presentation.slide_height = Inches(SLIDE_HEIGHT_INCHES)
        blank_layout = presentation.slide_layouts[6]
        specs_by_id = {slide["slide_id"]: slide for slide in specs["slides"]}

        for plan in layouts["plans"]:
            slide_spec = specs_by_id[plan["slide_id"]]
            slide = presentation.slides.add_slide(blank_layout)
            background = slide.background.fill
            background.solid()
            background.fore_color.rgb = _hex_color(visual["colors"]["background"])
            self._add_accent(slide, visual)
            blocks = {item["block_id"]: item for item in slide_spec["content_blocks"]}
            for region in sorted(plan["regions"], key=lambda item: item["z"]):
                self._add_region(slide, region, blocks[region["block_id"]], visual)

        buffer = BytesIO()
        presentation.save(buffer)
        atomic_write_bytes(output_path, buffer.getvalue())
        self.validate_output(output_path, outline, specs)
        model_previews = self._render_model_previews(
            output_dir / "model-previews", specs, layouts, visual
        )
        return RenderResult(
            status="success",
            output_paths=(output_path,),
            preview_paths=tuple(model_previews),
            actual_editability_level="E3",
            warnings=(
                "Model SVG previews share the layout model with the generator; use an independent Office preview for G8.",
                "Minimal renderer supports native text and simple shapes only.",
            ),
        )

    @staticmethod
    def _add_accent(slide: Any, visual: dict[str, Any]) -> None:
        accent = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0),
            Inches(0),
            Inches(0.12),
            Inches(SLIDE_HEIGHT_INCHES),
        )
        accent.fill.solid()
        accent.fill.fore_color.rgb = _hex_color(visual["colors"]["accent"])
        accent.line.fill.background()

    @staticmethod
    def _add_region(
        slide: Any,
        region: dict[str, Any],
        block: dict[str, Any],
        visual: dict[str, Any],
    ) -> None:
        x = _inches(region["x"], LOGICAL_WIDTH, SLIDE_WIDTH_INCHES)
        y = _inches(region["y"], LOGICAL_HEIGHT, SLIDE_HEIGHT_INCHES)
        width = _inches(region["w"], LOGICAL_WIDTH, SLIDE_WIDTH_INCHES)
        height = _inches(region["h"], LOGICAL_HEIGHT, SLIDE_HEIGHT_INCHES)
        is_surface = block["semantic_role"] in {"body", "evidence", "diagram", "table"}
        if is_surface:
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = _hex_color(visual["colors"]["surface"])
            shape.line.color.rgb = _hex_color("#D8D2C6")
        else:
            shape = slide.shapes.add_textbox(x, y, width, height)
        text_frame = shape.text_frame
        text_frame.clear()
        text_frame.word_wrap = True
        text_frame.margin_left = Inches(0.16)
        text_frame.margin_right = Inches(0.16)
        text_frame.margin_top = Inches(0.08)
        text_frame.margin_bottom = Inches(0.08)
        text_frame.vertical_anchor = {
            "top": MSO_ANCHOR.TOP,
            "middle": MSO_ANCHOR.MIDDLE,
            "bottom": MSO_ANCHOR.BOTTOM,
        }[region["valign"]]
        alignment = {
            "left": PP_ALIGN.LEFT,
            "center": PP_ALIGN.CENTER,
            "right": PP_ALIGN.RIGHT,
        }[region["align"]]

        style_name = {
            "headline": "display" if block["block_id"].startswith("BLK-S001-") else "title"
        }.get(
            block["semantic_role"],
            "caption" if block["semantic_role"] == "caption" else "body",
        )
        style = visual["typography"][style_name]
        values = _block_text(block["content"])
        for index, value in enumerate(values):
            paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
            paragraph.text = value
            paragraph.alignment = alignment
            paragraph.level = 0
            paragraph.space_after = Pt(8 if len(values) > 1 else 0)
            if len(values) > 1 and block["content_type"] == "list":
                paragraph.text = f"• {value}"
            for run in paragraph.runs:
                _set_run_font(run, style)

    @staticmethod
    def validate_output(
        output_path: Path,
        outline: dict[str, Any],
        specs: dict[str, Any],
    ) -> None:
        """Reopen the generated file and verify native slide/text coverage."""

        presentation = Presentation(output_path)
        expected_slides = len(outline["slides"])
        if len(presentation.slides) != expected_slides:
            raise ValueError(
                f"PPTX slide count mismatch: expected {expected_slides}, got {len(presentation.slides)}"
            )
        for index, (slide, spec) in enumerate(
            zip(presentation.slides, specs["slides"], strict=True), start=1
        ):
            rendered_text = "\n".join(
                shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False)
            )
            for block in spec["content_blocks"]:
                for value in _block_text(block["content"]):
                    if value not in rendered_text:
                        raise ValueError(
                            f"PPTX slide {index} is missing native text from {block['block_id']}"
                        )

    @staticmethod
    def _render_model_previews(
        output_dir: Path,
        specs: dict[str, Any],
        layouts: dict[str, Any],
        visual: dict[str, Any],
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        specs_by_id = {slide["slide_id"]: slide for slide in specs["slides"]}
        outputs: list[Path] = []
        for plan in layouts["plans"]:
            blocks = {
                block["block_id"]: block
                for block in specs_by_id[plan["slide_id"]]["content_blocks"]
            }
            svg = [
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">',
                f'<rect width="1280" height="720" fill="{_xml_escape(visual["colors"]["background"])}"/>',
                f'<rect width="12" height="720" fill="{_xml_escape(visual["colors"]["accent"])}"/>',
            ]
            for region in plan["regions"]:
                block = blocks[region["block_id"]]
                if block["semantic_role"] in {"body", "evidence", "diagram", "table"}:
                    svg.append(
                        f'<rect x="{region["x"]}" y="{region["y"]}" width="{region["w"]}" height="{region["h"]}" rx="10" fill="{_xml_escape(visual["colors"]["surface"])}" stroke="#D8D2C6"/>'
                    )
                style_name = "title" if block["semantic_role"] == "headline" else (
                    "caption" if block["semantic_role"] == "caption" else "body"
                )
                style = visual["typography"][style_name]
                y = region["y"] + style["font_size"] + 12
                for line in _block_text(block["content"]):
                    svg.append(
                        f'<text x="{region["x"] + 16}" y="{y}" font-family="Arial,sans-serif" font-size="{style["font_size"]}" fill="{_xml_escape(style["color"])}">{_xml_escape(line[:110])}</text>'
                    )
                    y += style["font_size"] * 1.35
            svg.append("</svg>")
            path = output_dir / f"{plan['slide_id']}.svg"
            path.write_text("\n".join(svg) + "\n", encoding="utf-8")
            outputs.append(path)
        return outputs


class LibreOfficeDocumentRenderer:
    """Render PPTX through LibreOffice and Poppler for independent PNG previews."""

    def __init__(
        self,
        *,
        soffice: str | None = None,
        pdftoppm: str | None = None,
        font_match: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.soffice = soffice or shutil.which("soffice")
        self.pdftoppm = pdftoppm or shutil.which("pdftoppm")
        self.font_match = font_match or shutil.which("fc-match")
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self.soffice and self.pdftoppm)

    def preview(self, document_path: Path, output_dir: Path) -> Sequence[Path]:
        if not self.available:
            raise RuntimeError("LibreOffice preview requires soffice and pdftoppm")
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="slidethus-preview-") as temporary_name:
            temporary_dir = Path(temporary_name)
            profile_dir = temporary_dir / "libreoffice-profile"
            profile_dir.mkdir()
            cache_dir = temporary_dir / "font-cache"
            cache_dir.mkdir()
            system_font_paths = [
                path
                for path in (
                    "/System/Library/Fonts",
                    "/System/Library/Fonts/Supplemental",
                    "/Library/Fonts",
                    "/usr/share/fonts",
                    "/usr/local/share/fonts",
                )
                if Path(path).exists()
            ]
            process_environment = {
                **os.environ,
                "XDG_CACHE_HOME": str(cache_dir),
                "SAL_FONTPATH": os.pathsep.join(system_font_paths),
            }
            staged_fonts = self._stage_document_fonts(
                document_path,
                profile_dir,
                process_environment,
            )
            if self._contains_cjk(document_path) and staged_fonts == 0:
                raise RuntimeError(
                    "CJK preview requires a discoverable local font; no document font was staged"
                )
            convert = subprocess.run(
                [
                    str(self.soffice),
                    f"-env:UserInstallation={profile_dir.as_uri()}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(temporary_dir),
                    str(document_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=process_environment,
            )
            pdf_path = temporary_dir / f"{document_path.stem}.pdf"
            if convert.returncode != 0 or not pdf_path.exists():
                detail = (convert.stderr or convert.stdout).strip()
                raise RuntimeError(f"LibreOffice preview failed: {detail or convert.returncode}")
            prefix = output_dir / "slide"
            raster = subprocess.run(
                [str(self.pdftoppm), "-png", "-r", "144", str(pdf_path), str(prefix)],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=process_environment,
            )
            if raster.returncode != 0:
                detail = (raster.stderr or raster.stdout).strip()
                raise RuntimeError(f"PDF preview rasterization failed: {detail or raster.returncode}")
        paths = sorted(output_dir.glob("slide-*.png"))
        if not paths:
            raise RuntimeError("Independent preview produced no PNG pages")
        for path in paths:
            if path.stat().st_size == 0:
                raise RuntimeError(f"Independent preview is empty: {path}")
        return tuple(paths)

    def _stage_document_fonts(
        self,
        document_path: Path,
        profile_dir: Path,
        environment: dict[str, str],
    ) -> int:
        if not self.font_match:
            return 0
        families: set[str] = set()
        presentation = Presentation(document_path)
        for slide in presentation.slides:
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        if run.font.name:
                            families.add(run.font.name)
        font_dir = profile_dir / "user" / "fonts"
        font_dir.mkdir(parents=True, exist_ok=True)
        staged: set[Path] = set()
        for family in sorted(families):
            match = subprocess.run(
                [self.font_match, "-f", "%{file}\n", family],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=environment,
            )
            if match.returncode != 0:
                continue
            first_line = match.stdout.splitlines()[0].strip() if match.stdout else ""
            source = Path(first_line)
            if not source.is_file() or source.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                continue
            destination = font_dir / source.name
            if destination not in staged:
                shutil.copyfile(source, destination)
                staged.add(destination)
        return len(staged)

    @staticmethod
    def _contains_cjk(document_path: Path) -> bool:
        presentation = Presentation(document_path)
        for slide in presentation.slides:
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and re.search(
                    r"[\u3400-\u9fff]", shape.text
                ):
                    return True
        return False
