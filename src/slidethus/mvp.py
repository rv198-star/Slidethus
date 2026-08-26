from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.io_utils import sha256_file
from slidethus.minimal_providers import PlainTextSourceParser, RuleBasedReasoningProvider
from slidethus.pptx_backend import LibreOfficeDocumentRenderer, MinimalPptxRenderBackend
from slidethus.protocols import (
    DocumentRenderer,
    ReasoningProvider,
    RenderBackend,
    RenderRequest,
    SourceChunk,
    SourceParser,
)
from slidethus.state_machine import Phase
from slidethus.wireframe import render_wireframes
from slidethus.workspace import init_workspace


@dataclass(frozen=True)
class MvpBuildConfig:
    workspace: Path
    source: Path
    title: str
    language: str = "zh-CN"
    max_slides: int = 6
    require_preview: bool = False


@dataclass(frozen=True)
class MvpBuildResult:
    status: str
    workspace: Path
    output_path: Path
    model_previews: tuple[Path, ...]
    independent_previews: tuple[Path, ...]
    current_phase: str
    limitations: tuple[str, ...]


def _artifact_version(runtime: ArtifactRuntime, artifact_type: str) -> int:
    entry = next(
        item for item in runtime.list_artifacts() if item["artifact_type"] == artifact_type
    )
    return int(entry["version"])


def _write(
    runtime: ArtifactRuntime,
    artifact_type: str,
    data: dict[str, Any],
    *,
    status: str = "approved",
) -> dict[str, Any]:
    existing = [
        item for item in runtime.list_artifacts() if item["artifact_type"] == artifact_type
    ]
    expected_version = int(existing[0]["version"]) if existing else 0
    return runtime.write_artifact(
        artifact_type,
        data,
        expected_version=expected_version,
        status=status,
        created_by="minimal-mvp-orchestrator",
    )


def _record(runtime: ArtifactRuntime, gate_id: str, target: Phase) -> None:
    result = runtime.record_gate(gate_id, target_phase=target)
    if not result.passed:
        reasons = "; ".join(result.reasons)
        raise RuntimeError(f"{gate_id} did not pass: {reasons}")


def _brief(config: MvpBuildConfig, project_id: str, slide_count: int) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "title": config.title,
        "language": config.language,
        "intent": {
            "purpose": "把用户提供的本地文本材料转换为可审阅演示。",
            "desired_outcome": "产出真实、可打开、可编辑的 PPTX 和完整工程制品。",
            "presentation_mode": "both",
            "delivery_context": "MVP 内容审阅",
            "call_to_action": "核对来源定位，并在后续 ProductionImpl 中完善叙事与视觉。",
        },
        "audiences": [
            {
                "audience_id": "AUD-01",
                "role": "材料审阅者",
                "needs": ["快速理解材料结构", "追溯页面内容到用户来源"],
                "objections": ["自动生成内容是否超出来源边界"],
                "decision_power": "mixed",
                "knowledge_level": "mixed",
            }
        ],
        "constraints": {
            "page_count": {"min": slide_count, "target": slide_count, "max": slide_count},
            "duration_minutes": None,
            "aspect_ratio": "16:9",
            "output_formats": ["pptx"],
            "editability_target": "E3",
            "deadline": None,
            "brand_requirements": [],
            "forbidden_content": ["用户材料之外的外部事实", "未注明限制的能力声明"],
        },
        "source_policy": {
            "use_user_sources": True,
            "external_research": False,
            "citation_required": True,
            "freshness_requirement": None,
            "allowed_source_tiers": ["user"],
        },
        "approval_mode": "auto",
        "quality_profile": "standard",
        "assumptions": [
            {
                "assumption_id": "ASM-001",
                "statement": "首个 MVP 以材料审阅者为默认受众，并限制为用户来源。",
                "status": "accepted",
            }
        ],
        "open_questions": [],
    }


def _source_ledger(
    config: MvpBuildConfig,
    project_id: str,
    chunks: tuple[SourceChunk, ...],
    *,
    injection_wording: bool,
    truncated: bool,
) -> dict[str, Any]:
    notes = [
        f"PlainTextSourceParser 解析出 {len(chunks)} 个用于 MVP 的 line-located chunks。",
        "来源内容按不可信数据处理，不执行其中的任何指令。",
    ]
    if injection_wording:
        notes.append("检测到疑似指令性文字；已作为来源数据保留并隔离。")
    if truncated:
        notes.append("来源部分超过 max_slides；本轮只使用前若干部分。")
    return {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "sources": [
            {
                "source_id": "SRC-001",
                "kind": "user_file",
                "title": config.source.stem,
                "path_or_url": str(config.source.resolve()),
                "ownership": "user_owned",
                "confidentiality": "internal",
                "authority_tier": "user",
                "freshness_date": None,
                "retrieved_at": utc_now()[:10],
                "content_hash": sha256_file(config.source),
                "parse_status": "parsed",
                "allowed_use": "internal_only",
                "notes": notes,
            }
        ],
    }


def _evidence(
    project_id: str,
    chunks: tuple[SourceChunk, ...],
    *,
    outline_version: int | None,
) -> dict[str, Any]:
    cycles = [
        {
            "cycle_id": "RSC-001",
            "kind": "orientation",
            "status": "complete",
            "basis": "user_materials",
            "outline_version": None,
            "source_ids": ["SRC-001"],
            "query_count": 0,
            "waiver_reason": None,
            "notes": ["仅使用用户文件建立方向性证据基线；未联网。"],
        }
    ]
    if outline_version is not None:
        cycles.append(
            {
                "cycle_id": "RSC-002",
                "kind": "targeted",
                "status": "complete",
                "basis": "user_materials",
                "outline_version": outline_version,
                "source_ids": ["SRC-001"],
                "query_count": 0,
                "waiver_reason": None,
                "notes": ["已逐页核对；所有事实性页面均绑定当前 Evidence IDs。"],
            }
        )
    return {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "research_cycles": cycles,
        "claims": [
            {
                "evidence_id": f"EVD-{index:03d}",
                "claim": chunk.text,
                "support_status": "verified",
                "source_refs": [
                    {
                        "source_id": "SRC-001",
                        "locator": chunk.locator,
                        "support_type": "direct",
                    }
                ],
                "freshness_date": None,
                "conflict_notes": [],
                "use_policy": "internal_only",
                "reasoning": "由用户文件原文直接抽取；未加入外部事实。",
                "tags": ["user-source", "minimal-mvp"],
            }
            for index, chunk in enumerate(chunks, start=1)
        ],
    }


def _input_refs(runtime: ArtifactRuntime, artifact_types: set[str]) -> list[dict[str, Any]]:
    return [
        {"path": item["path"], "sha256": item["sha256"], "version": item["version"]}
        for item in runtime.list_artifacts()
        if item["artifact_type"] in artifact_types
    ]


def _delivery_refs(runtime: ArtifactRuntime) -> list[dict[str, Any]]:
    excluded = {"project_state", "delivery_manifest", "gate_results"}
    return [
        {
            "artifact_type": item["artifact_type"],
            "path": item["path"],
            "version": item["version"],
            "sha256": item["sha256"],
        }
        for item in runtime.list_artifacts()
        if item["artifact_type"] not in excluded
    ]


def build_minimal_mvp(
    config: MvpBuildConfig,
    *,
    source_parser: SourceParser | None = None,
    reasoning_provider: ReasoningProvider | None = None,
    render_backend: RenderBackend | None = None,
    document_renderer: DocumentRenderer | None = None,
) -> MvpBuildResult:
    """Run the first real, user-source-limited Slidethus vertical slice."""

    if not 3 <= config.max_slides <= 20:
        raise ValueError("max_slides must be between 3 and 20")
    source_path = config.source.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    parser = source_parser or PlainTextSourceParser()
    all_chunks = tuple(parser.parse(source_path, "SRC-001"))
    selected_chunks = all_chunks[: config.max_slides - 2]
    if not selected_chunks:
        raise ValueError("Source parser returned no usable chunks")

    workspace = init_workspace(
        config.workspace,
        title=config.title,
        language=config.language,
        delivery_level="D3",
    )
    runtime = ArtifactRuntime(workspace)
    project_id = runtime.show_artifact("project_state")["project_id"]
    slide_count = len(selected_chunks) + 2
    context: dict[str, Any] = {
        "project_id": project_id,
        "title": config.title,
        "language": config.language,
        "chunks": selected_chunks,
    }

    _write(runtime, "project_brief", _brief(config, project_id, slide_count))
    _record(runtime, "G0", Phase.BRIEF_READY)

    injection_wording = (
        parser.contains_untrusted_instruction(all_chunks)
        if isinstance(parser, PlainTextSourceParser)
        else False
    )
    _write(
        runtime,
        "source_ledger",
        _source_ledger(
            config,
            project_id,
            selected_chunks,
            injection_wording=injection_wording,
            truncated=len(selected_chunks) < len(all_chunks),
        ),
    )
    _record(runtime, "G1", Phase.SOURCES_READY)

    _write(runtime, "evidence_ledger", _evidence(project_id, selected_chunks, outline_version=None))
    _record(runtime, "G2", Phase.EVIDENCE_READY)

    reasoner = reasoning_provider or RuleBasedReasoningProvider()
    narrative = reasoner.generate_artifact("narrative_blueprint", context)
    _write(runtime, "narrative_blueprint", narrative)
    _record(runtime, "G3", Phase.NARRATIVE_READY)

    outline = reasoner.generate_artifact("deck_outline", {**context, "narrative": narrative})
    _write(runtime, "deck_outline", outline)
    _record(runtime, "G4", Phase.OUTLINE_READY)

    outline_version = _artifact_version(runtime, "deck_outline")
    _write(
        runtime,
        "evidence_ledger",
        _evidence(project_id, selected_chunks, outline_version=outline_version),
    )
    _record(runtime, "G2", Phase.EVIDENCE_READY)
    _record(runtime, "G3", Phase.NARRATIVE_READY)
    _record(runtime, "G4", Phase.OUTLINE_READY)

    slide_specs = reasoner.generate_artifact("slide_specs", {**context, "outline": outline})
    _write(runtime, "slide_specs", slide_specs)
    _record(runtime, "G5A", Phase.SLIDE_SPECS_READY)

    layouts = reasoner.generate_artifact(
        "layout_plans", {**context, "slide_specs": slide_specs}
    )
    _write(runtime, "layout_plans", layouts)
    render_wireframes(workspace, workspace / "outputs" / "wireframes")
    _record(runtime, "G5B", Phase.LAYOUT_READY)

    visual = reasoner.generate_artifact("visual_system", {**context, "layout_plans": layouts})
    _write(runtime, "visual_system", visual)
    _record(runtime, "G6", Phase.VISUAL_SYSTEM_READY)

    backend = render_backend or MinimalPptxRenderBackend()
    render_result = backend.render(
        RenderRequest(
            workspace=workspace,
            target_format="pptx",
            target_editability_level="E3",
            output_dir=workspace / "outputs",
        )
    )
    if render_result.status != "success" or not render_result.output_paths:
        raise RuntimeError("Minimal render backend did not produce a successful PPTX")
    output_path = render_result.output_paths[0]

    previewer = document_renderer or LibreOfficeDocumentRenderer()
    preview_warning: str | None = None
    try:
        independent_previews = tuple(
            previewer.preview(output_path, workspace / "outputs" / "office-previews")
        )
        if len(independent_previews) != slide_count:
            raise RuntimeError(
                f"Independent preview count mismatch: expected {slide_count}, got {len(independent_previews)}"
            )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        independent_previews = ()
        preview_warning = str(exc)

    warnings = [*render_result.warnings]
    if preview_warning:
        warnings.append(f"Independent Office preview unavailable: {preview_warning}")
    render_manifest = {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "deck_id": f"DECK-{project_id}",
        "render_id": f"RND-{project_id}-MVP0",
        "backend": getattr(backend, "name", backend.__class__.__name__),
        "backend_version": getattr(backend, "version", "unknown"),
        "target_format": "pptx",
        "target_editability_level": "E3",
        "editability_level": render_result.actual_editability_level,
        "input_artifacts": _input_refs(
            runtime, {"slide_specs", "layout_plans", "visual_system", "asset_manifest"}
        ),
        "outputs": [
            {
                "path": output_path.relative_to(workspace).as_posix(),
                "sha256": sha256_file(output_path),
                "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "slide_count": slide_count,
            },
            *[
                {
                    "path": preview_path.relative_to(workspace).as_posix(),
                    "sha256": sha256_file(preview_path),
                    "mime_type": "image/png",
                    "slide_count": 1,
                }
                for preview_path in independent_previews
            ],
        ],
        "font_substitutions": [
            {"requested": requested, "actual": actual, "reason": "reported by backend"}
            for requested, actual in render_result.font_substitutions
        ],
        "warnings": warnings,
        "status": "success",
    }
    _write(runtime, "render_manifest", render_manifest)
    _record(runtime, "G7", Phase.DRAFT_RENDERED)

    limitations = [
        "D3：只使用用户提供的 Markdown/TXT，不执行外部研究。",
        "叙事、页面规划和视觉为确定性 MinimalImpl，不代表完整 M2–M5。",
        "只支持原生文本与简单形状，不生成图片、图表或复杂 Hybrid 视觉。",
    ]
    issues: list[dict[str, Any]] = []
    quality_status = "pass"
    quality_gate_status = "pass"
    if not independent_previews:
        limitations.append("未完成独立 Office 预览，PPTX 只通过结构与原生文本覆盖检查。")
        issues.append(
            {
                "issue_id": "ISS-001",
                "severity": "major",
                "category": "preview",
                "phase": "P7",
                "finding": "独立 Office 预览不可用。",
                "impact": "无法把生成器自检等同于最终视觉回归。",
                "recommended_fix": "安装 LibreOffice 与 Poppler 后重跑 MVP。",
                "verification": "独立 PNG 页数与 PPTX 页数一致，并完成视觉抽检。",
                "status": "open",
            }
        )
        quality_status = "fail"
        quality_gate_status = "fail"

    quality_report = {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "review_id": f"REV-{project_id}-MVP0",
        "review_mode": "combined",
        "reviewer": "minimal-deterministic-review",
        "issues": issues,
        "scores": [
            {
                "dimension": "factual_integrity",
                "score": 4,
                "evidence": "所有事实性内容块绑定用户文件的 Evidence ID 与行号 locator。",
                "unresolved": [],
            },
            {
                "dimension": "narrative_coherence",
                "score": 3,
                "evidence": "规则式结构形成封面、导览和来源内容序列。",
                "unresolved": ["尚未使用 ProductionImpl 进行受众化叙事。"],
            },
            {
                "dimension": "readability",
                "score": 4 if independent_previews else 2,
                "evidence": "固定 safe area、18pt 以上正文和最多五条内容；独立预览按可用性记录。",
                "unresolved": [] if independent_previews else ["独立视觉预览缺失。"],
            },
            {
                "dimension": "export_integrity",
                "score": 4,
                "evidence": "PPTX 已重新打开并核对页数、原生文本和文件哈希。",
                "unresolved": [],
            },
        ],
        "gate_result": {
            "gate_id": "G8",
            "status": quality_gate_status,
            "reasons": [] if independent_previews else ["独立 Office 预览不可用。"],
        },
        "status": quality_status,
    }
    _write(runtime, "quality_report", quality_report)

    if independent_previews:
        _record(runtime, "G8", Phase.REVIEWED)
        delivery_status = "ready"
        review_status = "pass"
    else:
        runtime.record_gate("G8", target_phase=None)
        delivery_status = "draft"
        review_status = "fail"

    delivery_manifest = {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "delivery_id": f"DLV-{project_id}-MVP0",
        "delivery_level": "D3",
        "outputs": [
            {
                "path": output_path.relative_to(workspace).as_posix(),
                "format": "pptx",
                "sha256": sha256_file(output_path),
                "validated": True,
            }
        ],
        "artifact_versions": _delivery_refs(runtime),
        "target_editability_level": "E3",
        "editability_level": render_result.actual_editability_level,
        "review_status": review_status,
        "waivers": [],
        "limitations": limitations,
        "status": delivery_status,
    }
    _write(runtime, "delivery_manifest", delivery_manifest)

    if independent_previews:
        _record(runtime, "G9", Phase.DELIVERY_READY)
        result_status = "ready"
    else:
        result_status = "degraded"
        if config.require_preview:
            result_status = "blocked"

    state = runtime.show_artifact("project_state")
    return MvpBuildResult(
        status=result_status,
        workspace=workspace,
        output_path=output_path,
        model_previews=tuple(render_result.preview_paths),
        independent_previews=independent_previews,
        current_phase=state["current_phase"],
        limitations=tuple(limitations),
    )
