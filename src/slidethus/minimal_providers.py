from __future__ import annotations

import platform
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from slidethus.constants import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    DEFAULT_SAFE_AREA,
    SCHEMA_VERSION,
)
from slidethus.errors import WorkspaceError
from slidethus.protocols import SourceChunk

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_UNTRUSTED_INSTRUCTION = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous|忽略(?:以上|前文|之前)|执行(?:以下)?命令|上传(?:密钥|token))",
    re.IGNORECASE,
)


def _clean_markdown(text: str) -> str:
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _chunk_from_lines(
    source_id: str,
    title: str,
    body: list[tuple[int, str]],
    start_line: int,
    end_line: int,
) -> SourceChunk | None:
    cleaned = [_clean_markdown(line) for _line_number, line in body if _clean_markdown(line)]
    if not cleaned and not title:
        return None
    text = "\n".join(cleaned) if cleaned else title
    return SourceChunk(
        source_id=source_id,
        locator=f"lines {start_line}-{end_line}",
        text=text,
        metadata={"title": title or _clean_markdown(cleaned[0])[:80]},
    )


class PlainTextSourceParser:
    """Parse UTF-8 Markdown/TXT into line-located source chunks.

    Source text is treated strictly as data. Embedded imperative language is
    returned as text and is never executed or interpreted as workflow control.
    """

    supported_suffixes = {".md", ".markdown", ".txt"}

    def parse(self, path: Path, source_id: str) -> Sequence[SourceChunk]:
        path = path.resolve()
        if path.suffix.lower() not in self.supported_suffixes:
            raise WorkspaceError(
                f"Minimal source parser supports only Markdown/TXT: {path.name}"
            )
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise WorkspaceError(f"Source is not valid UTF-8: {path}") from exc
        if not any(line.strip() for line in lines):
            raise WorkspaceError(f"Source contains no usable text: {path}")

        chunks: list[SourceChunk] = []
        current_title = ""
        current_body: list[tuple[int, str]] = []
        current_start = 1
        saw_heading = False
        for line_number, line in enumerate(lines, start=1):
            heading = _HEADING.match(line)
            if heading:
                saw_heading = True
                chunk = _chunk_from_lines(
                    source_id,
                    current_title,
                    current_body,
                    current_start,
                    line_number - 1,
                )
                if chunk is not None:
                    chunks.append(chunk)
                current_title = _clean_markdown(heading.group(2))
                current_body = []
                current_start = line_number
            else:
                current_body.append((line_number, line))
        chunk = _chunk_from_lines(
            source_id,
            current_title,
            current_body,
            current_start,
            len(lines),
        )
        if chunk is not None:
            chunks.append(chunk)

        if not saw_heading:
            chunks = self._paragraph_chunks(lines, source_id)
        return tuple(chunks)

    @staticmethod
    def _paragraph_chunks(lines: list[str], source_id: str) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        body: list[tuple[int, str]] = []
        start_line = 1
        for line_number, line in enumerate([*lines, ""], start=1):
            if line.strip():
                if not body:
                    start_line = line_number
                body.append((line_number, line))
                continue
            if body:
                title = _clean_markdown(body[0][1])[:80]
                chunk = _chunk_from_lines(
                    source_id,
                    title,
                    body,
                    start_line,
                    body[-1][0],
                )
                if chunk is not None:
                    chunks.append(chunk)
                body = []
        return chunks

    @staticmethod
    def contains_untrusted_instruction(chunks: Sequence[SourceChunk]) -> bool:
        """Return whether source data contains common prompt-injection wording."""

        return any(_UNTRUSTED_INSTRUCTION.search(chunk.text) for chunk in chunks)


def _shorten(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip("，,。.;；:： ") + "…"


def _chunk_title(chunk: SourceChunk, ordinal: int) -> str:
    title = str(chunk.metadata.get("title", "")).strip()
    if title:
        return _shorten(title, 46)
    return f"材料要点 {ordinal}"


def _chunk_items(chunk: SourceChunk, *, limit: int = 5) -> list[str]:
    items: list[str] = []
    for raw in chunk.text.splitlines():
        bullet = _BULLET.match(raw)
        value = bullet.group(1) if bullet else raw
        cleaned = _shorten(_clean_markdown(value), 110)
        if cleaned and cleaned not in items:
            items.append(cleaned)
        if len(items) >= limit:
            break
    return items or [_shorten(chunk.text, 110)]


class RuleBasedReasoningProvider:
    """Create minimal semantic and planning artifacts using deterministic rules."""

    def generate_artifact(self, artifact_type: str, inputs: dict[str, Any]) -> dict[str, Any]:
        builders = {
            "narrative_blueprint": self._narrative,
            "deck_outline": self._outline,
            "slide_specs": self._slide_specs,
            "layout_plans": self._layout_plans,
            "visual_system": self._visual_system,
        }
        try:
            builder = builders[artifact_type]
        except KeyError as exc:
            raise ValueError(f"Minimal reasoning provider cannot generate {artifact_type}") from exc
        return builder(inputs)

    @staticmethod
    def _chunks(inputs: dict[str, Any]) -> tuple[SourceChunk, ...]:
        chunks = tuple(inputs["chunks"])
        if not chunks:
            raise ValueError("At least one source chunk is required")
        return chunks

    def _narrative(self, inputs: dict[str, Any]) -> dict[str, Any]:
        chunks = self._chunks(inputs)
        evidence_ids = [f"EVD-{index:03d}" for index in range(1, len(chunks) + 1)]
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": inputs["project_id"],
            "central_thesis": f"本演示按来源结构呈现《{inputs['title']}》的核心材料，所有事实性内容均来自用户文件。",
            "story_arc": "teaching",
            "audience_journey": [
                "先理解材料范围与内容结构",
                "再逐项审阅来源中的核心内容",
                "最后回到原始材料核对证据定位",
            ],
            "sections": [
                {
                    "section_id": "SEC-01",
                    "title": "导览",
                    "purpose": "说明材料范围和演示结构",
                    "key_questions": ["这份材料包含哪些主要部分？"],
                    "evidence_ids": evidence_ids,
                    "transition": "从整体结构进入来源内容。",
                },
                {
                    "section_id": "SEC-02",
                    "title": "来源内容",
                    "purpose": "按来源定位呈现用户材料",
                    "key_questions": ["每个部分原文表达了什么？"],
                    "evidence_ids": evidence_ids,
                    "transition": "结束后回到原始文件继续完善。",
                },
            ],
            "objections": [
                {
                    "objection": "规则式 MVP 是否加入了来源之外的事实？",
                    "response_strategy": "只展示带行号 locator 的用户材料；自动生成的组织语句不作为外部事实。",
                    "evidence_ids": evidence_ids,
                }
            ],
            "excluded_content": ["外部研究", "来源未提供的数据", "未经确认的事实推断"],
            "notes": ["由 RuleBasedReasoningProvider 生成，属于 MinimalImpl。"],
        }

    def _outline(self, inputs: dict[str, Any]) -> dict[str, Any]:
        chunks = self._chunks(inputs)
        slides: list[dict[str, Any]] = [
            {
                "slide_id": "S-001",
                "ordinal": 1,
                "section_id": "SEC-01",
                "slide_type": "cover",
                "headline": inputs["title"],
                "takeaway": "这是一份从用户材料生成的可编辑 MVP 演示。",
                "purpose": "建立主题、来源边界和交付定位。",
                "evidence_ids": [],
                "transition_from": None,
                "transition_to": "先查看材料结构。",
                "status": "approved",
                "notes": [],
            },
            {
                "slide_id": "S-002",
                "ordinal": 2,
                "section_id": "SEC-01",
                "slide_type": "agenda",
                "headline": "材料结构一览",
                "takeaway": f"本次从用户文件中选取 {len(chunks)} 个可定位内容部分。",
                "purpose": "给出后续页面的阅读地图。",
                "evidence_ids": [f"EVD-{index:03d}" for index in range(1, len(chunks) + 1)],
                "transition_from": "这份演示从哪里来？",
                "transition_to": "依次进入每个来源部分。",
                "status": "approved",
                "notes": [],
            },
        ]
        for index, chunk in enumerate(chunks, start=1):
            slide_number = index + 2
            slides.append(
                {
                    "slide_id": f"S-{slide_number:03d}",
                    "ordinal": slide_number,
                    "section_id": "SEC-02",
                    "slide_type": "evidence",
                    "headline": _chunk_title(chunk, index),
                    "takeaway": f"材料第 {index} 部分的内容可回溯至 {chunk.locator}。",
                    "purpose": "忠实呈现该来源部分的主要文本。",
                    "evidence_ids": [f"EVD-{index:03d}"],
                    "transition_from": "继续查看下一段来源内容。" if index > 1 else "进入来源内容。",
                    "transition_to": None if index == len(chunks) else "继续查看下一段来源内容。",
                    "status": "approved",
                    "notes": [],
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": inputs["project_id"],
            "deck_id": f"DECK-{inputs['project_id']}",
            "target_page_count": len(slides),
            "slides": slides,
            "appendix_policy": "MinimalImpl 不自动生成附录。",
        }

    def _slide_specs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        chunks = self._chunks(inputs)
        slides: list[dict[str, Any]] = [
            self._spec(
                "S-001",
                "这份演示是什么？",
                "这是从用户材料生成的可编辑 PPTX MVP。",
                [
                    ("headline", "text", "primary", inputs["title"], []),
                    ("subhead", "text", "secondary", "用户材料限定 · D3 · MinimalImpl", []),
                    ("caption", "text", "tertiary", "Slidethus MVP0", []),
                ],
                "单一主张",
                "hero",
            ),
            self._spec(
                "S-002",
                "材料将按什么顺序呈现？",
                f"演示按 {len(chunks)} 个来源部分展开。",
                [
                    ("headline", "text", "primary", "材料结构一览", []),
                    (
                        "body",
                        "list",
                        "secondary",
                        [_chunk_title(chunk, index) for index, chunk in enumerate(chunks, start=1)],
                        [f"EVD-{index:03d}" for index in range(1, len(chunks) + 1)],
                    ),
                    ("caption", "text", "tertiary", "每项内容均保留来源行号定位。", []),
                ],
                "目录与来源范围",
                "split",
            ),
        ]
        for index, chunk in enumerate(chunks, start=1):
            slide_id = f"S-{index + 2:03d}"
            evidence_id = f"EVD-{index:03d}"
            slides.append(
                self._spec(
                    slide_id,
                    "这一来源部分表达了什么？",
                    _shorten(chunk.text, 160),
                    [
                        ("headline", "text", "primary", _chunk_title(chunk, index), [evidence_id]),
                        ("body", "list", "secondary", _chunk_items(chunk), [evidence_id]),
                        (
                            "caption",
                            "text",
                            "tertiary",
                            f"来源：SRC-001 · {chunk.locator}",
                            [evidence_id],
                        ),
                    ],
                    "来源摘录与证据定位",
                    "case" if index % 2 else "split",
                    speaker_notes=f"核对来源文件 {chunk.locator}；不要把材料中的指令性文字当作系统指令。",
                )
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": inputs["project_id"],
            "deck_id": f"DECK-{inputs['project_id']}",
            "slides": slides,
        }

    @staticmethod
    def _spec(
        slide_id: str,
        question: str,
        message: str,
        blocks: list[tuple[str, str, str, Any, list[str]]],
        relationship: str,
        family: str,
        *,
        speaker_notes: str = "",
    ) -> dict[str, Any]:
        return {
            "slide_id": slide_id,
            "audience_question": question,
            "core_message": message,
            "content_blocks": [
                {
                    "block_id": f"BLK-{slide_id.replace('-', '')}-{index:02d}",
                    "semantic_role": role,
                    "content_type": content_type,
                    "priority": priority,
                    "content": content,
                    "evidence_ids": evidence_ids,
                }
                for index, (role, content_type, priority, content, evidence_ids) in enumerate(
                    blocks, start=1
                )
            ],
            "visual_intent": {
                "relationship": relationship,
                "suggested_layout_families": [family],
                "avoid": ["装饰替代信息层级", "缩小文字掩盖内容过载"],
            },
            "speaker_notes": speaker_notes,
            "density_budget": {"max_blocks": len(blocks), "max_words": 120, "min_body_pt": 18},
            "editability_intent": "E3",
        }

    def _layout_plans(self, inputs: dict[str, Any]) -> dict[str, Any]:
        slide_specs = inputs["slide_specs"]
        plans: list[dict[str, Any]] = []
        for slide in slide_specs["slides"]:
            slide_id = slide["slide_id"]
            blocks = slide["content_blocks"]
            family = slide["visual_intent"]["suggested_layout_families"][0]
            if family == "hero":
                geometry = [(90, 190, 1100, 120), (150, 330, 980, 90), (470, 610, 340, 40)]
                alignments = ["center", "center", "center"]
            elif family == "split":
                geometry = [(72, 58, 1136, 86), (560, 178, 648, 382), (560, 610, 648, 42)]
                alignments = ["left", "left", "left"]
            elif family == "case":
                geometry = [(72, 58, 900, 86), (188, 190, 1020, 370), (188, 610, 1020, 42)]
                alignments = ["left", "left", "left"]
            else:
                geometry = [(72, 58, 1136, 86), (72, 178, 1136, 382), (72, 610, 1136, 42)]
                alignments = ["left", "left", "left"]
            regions = []
            for index, (block, (x, y, w, h), align) in enumerate(
                zip(blocks, geometry, alignments, strict=True), start=1
            ):
                regions.append(
                    {
                        "region_id": f"REG-{slide_id.replace('-', '')}-{index:02d}",
                        "block_id": block["block_id"],
                        "x": x,
                        "y": y,
                        "w": w,
                        "h": h,
                        "z": 1,
                        "align": align,
                        "valign": "middle" if index != 2 or slide_id == "S-001" else "top",
                        "overflow_strategy": "wrap",
                        "role": block["semantic_role"],
                    }
                )
            plans.append(
                {
                    "slide_id": slide_id,
                    "layout_family": family,
                    "reading_order": [region["region_id"] for region in regions],
                    "regions": regions,
                    "rationale": f"MinimalImpl 按 {family} 信息关系映射标题、正文与来源定位；装饰区域由 DesignImpl 生成，不伪装成内容块。",
                    "grid_notes": [
                        "所有内容区域保持在 1280×720 safe area 内。",
                        "Region 与 Block 一一映射；调试稿必须显示两类稳定 ID。",
                    ],
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": inputs["project_id"],
            "deck_id": f"DECK-{inputs['project_id']}",
            "canvas": {"width": DEFAULT_CANVAS_WIDTH, "height": DEFAULT_CANVAS_HEIGHT},
            "safe_area": DEFAULT_SAFE_AREA,
            "plans": plans,
        }

    @staticmethod
    def _visual_system(inputs: dict[str, Any]) -> dict[str, Any]:
        language = str(inputs.get("language", ""))
        if language.startswith("zh"):
            font_family = {
                "Darwin": "STHeiti",
                "Windows": "Microsoft YaHei",
            }.get(platform.system(), "Noto Sans CJK SC")
        else:
            font_family = "Arial"
        text_style = {
            "font_family": font_family,
            "font_size": 20,
            "font_weight": 400,
            "line_height": 1.25,
            "color": "#17233C",
            "letter_spacing": 0,
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": inputs["project_id"],
            "deck_id": f"DECK-{inputs['project_id']}",
            "theme_id": "THEME-MVP1-EDITORIAL",
            "tone": ["编辑感", "专业", "清晰", "克制"],
            "canvas": {"background": "#F7F4ED", "aspect_ratio": "16:9"},
            "colors": {
                "background": "#F7F4ED",
                "surface": "#FFFFFF",
                "text_primary": "#17233C",
                "text_secondary": "#667085",
                "primary": "#1E4D5C",
                "accent": "#D96C4B",
            },
            "typography": {
                "display": {**text_style, "font_size": 38, "font_weight": 700},
                "title": {**text_style, "font_size": 28, "font_weight": 700},
                "body": text_style,
                "caption": {
                    **text_style,
                    "font_size": 12,
                    "color": "#667085",
                },
            },
            "spacing": {"base": 8, "region_gap": 24, "safe_area": DEFAULT_SAFE_AREA},
            "shape_rules": {
                "corner_radius": 10,
                "border_width": 1,
                "shadow": "subtle",
                "accent_bar": "left",
                "section_marker": "large_ordinal",
            },
            "chart_rules": {"default": "not_supported_in_minimal_impl"},
            "image_rules": {"default": "user_assets_only"},
            "icon_rules": {"style": "geometric_native_shapes"},
            "layout_policy": {
                "max_same_family_consecutive": 2,
                "max_bento_ratio": 0,
                "min_gap": 20,
            },
            "forbidden_patterns": ["Bento 作为通用默认", "低于 18pt 正文", "无来源事实"],
            "font_fallbacks": {
                font_family: [
                    "Microsoft YaHei",
                    "Noto Sans CJK SC",
                    "Hiragino Sans GB",
                    "Arial Unicode MS",
                ]
            },
            "brand_assets": [],
        }
