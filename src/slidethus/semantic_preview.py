"""Content-addressed semantic planning previews for reviewed/critical decks."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.errors import VisualQualityError
from slidethus.io_utils import atomic_create_bytes, sha256_bytes, sha256_json
from slidethus.protocols import VisualReviewProvider
from slidethus.render_backends.artifact_tool_contract import artifact_tool_host_contract
from slidethus.visual_quality import (
    current_semantic_preview_receipt,
    current_visual_admission_policy,
    derive_visual_quality_decision,
    persist_semantic_preview_receipt,
    persist_visual_quality_review,
    planning_admission_dependency_key,
)


@dataclass(frozen=True)
class SemanticPlanningAdmissionResult:
    review_path: Path
    decision_path: Path
    review: dict[str, Any]
    decision: dict[str, Any]


def _text(value: Any, limit: int = 120) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _region_box(region: dict[str, Any]) -> tuple[float, float, float, float]:
    return tuple(float(region[key]) for key in ("x", "y", "w", "h"))  # type: ignore[return-value]


def _svg_text(
    output: list[str], text: str, *, x: float, y: float, size: float, fill: str = "#172033"
) -> None:
    output.append(
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:.2f}" '
        f'font-family="Arial,Noto Sans CJK SC,sans-serif" fill="{fill}">{html.escape(text)}</text>'
    )


def _chart(output: list[str], semantics: dict[str, Any], region: dict[str, Any]) -> None:
    x, y, w, h = _region_box(region)
    categories = list(semantics["categories"])
    series = list(semantics["series"])
    values = [float(value) for item in series for value in item["values"]]
    maximum = max(values) if values else 1.0
    maximum = maximum if maximum > 0 else 1.0
    chart_top = y + 46
    chart_height = max(40.0, h - 86)
    group_width = w / max(1, len(categories))
    bar_width = max(4.0, group_width / (len(series) + 1))
    colors = ("#3659B8", "#E17242", "#2A8C82", "#9B61B4")
    for category_index, category in enumerate(categories):
        for series_index, item in enumerate(series):
            value = float(item["values"][category_index])
            bar_h = max(2.0, chart_height * max(0.0, value) / maximum)
            bar_x = x + category_index * group_width + 10 + series_index * bar_width
            output.append(
                f'<rect x="{bar_x:.2f}" y="{chart_top + chart_height - bar_h:.2f}" '
                f'width="{bar_width - 3:.2f}" height="{bar_h:.2f}" rx="3" '
                f'fill="{colors[series_index % len(colors)]}"/>'
            )
        _svg_text(
            output,
            _text(category, 14),
            x=x + category_index * group_width + group_width / 2 - 12,
            y=y + h - 14,
            size=12,
            fill="#546078",
        )


def _table(output: list[str], content: Any, region: dict[str, Any], view: dict[str, Any]) -> None:
    x, y, w, h = _region_box(region)
    if isinstance(content, dict):
        rows = [content.get("headers", []), *content.get("rows", [])]
        rows = [row for row in rows if row]
    else:
        rows = list(content) if isinstance(content, list) else []
    if not rows or not isinstance(rows[0], list):
        raise VisualQualityError("Semantic table preview requires rectangular rows")
    columns = len(rows[0])
    row_h = h / len(rows)
    column_w = w / columns
    emphasized = view.get("emphasized_column")
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            fill = "#DCE6FF" if row_index < int(view["header_rows"]) else "#FFFFFF"
            if emphasized == column_index and row_index >= int(view["header_rows"]):
                fill = "#FFF0D8"
            cell_x = x + column_index * column_w
            cell_y = y + row_index * row_h
            output.append(
                f'<rect x="{cell_x:.2f}" y="{cell_y:.2f}" width="{column_w:.2f}" '
                f'height="{row_h:.2f}" fill="{fill}" stroke="#AAB4C7"/>'
            )
            _svg_text(
                output,
                _text(value, 24),
                x=cell_x + 8,
                y=cell_y + min(row_h - 6, 22),
                size=min(14, max(9, row_h / 3)),
            )


def _diagram(
    output: list[str], semantics: dict[str, Any], region: dict[str, Any], view: dict[str, Any]
) -> None:
    x, y, w, h = _region_box(region)
    geometry = {str(item["node_id"]): item for item in view["node_geometry"]}
    nodes = {str(item["id"]): item for item in semantics["nodes"]}
    for edge in semantics["edges"]:
        source = geometry[str(edge["from"])]
        target = geometry[str(edge["to"])]
        x1 = x + (float(source["x"]) + float(source["w"]) / 2) * w
        y1 = y + (float(source["y"]) + float(source["h"]) / 2) * h
        x2 = x + (float(target["x"]) + float(target["w"]) / 2) * w
        y2 = y + (float(target["y"]) + float(target["h"]) / 2) * h
        output.append(
            f'<path d="M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}" stroke="#50607A" '
            'stroke-width="3" fill="none" marker-end="url(#arrow)"/>'
        )
    for node_id, node in nodes.items():
        item = geometry[node_id]
        nx = x + float(item["x"]) * w
        ny = y + float(item["y"]) * h
        nw = float(item["w"]) * w
        nh = float(item["h"]) * h
        output.append(
            f'<rect x="{nx:.2f}" y="{ny:.2f}" width="{nw:.2f}" height="{nh:.2f}" '
            'rx="14" fill="#E8EEFF" stroke="#3659B8" stroke-width="2"/>'
        )
        _svg_text(
            output,
            _text(node["label"], 22),
            x=nx + 12,
            y=ny + min(nh / 2 + 5, nh - 8),
            size=min(16, max(10, nh / 4)),
        )


def _image(
    output: list[str], semantics: dict[str, Any], region: dict[str, Any], view: dict[str, Any]
) -> None:
    x, y, w, h = _region_box(region)
    output.append(
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
        'rx="16" fill="#D8E4E6" stroke="#6E8589" stroke-width="2"/>'
    )
    output.append(
        f'<path d="M{x:.2f},{y+h:.2f} L{x+w*.38:.2f},{y+h*.45:.2f} '
        f'L{x+w*.62:.2f},{y+h*.70:.2f} L{x+w:.2f},{y+h*.25:.2f}" '
        'fill="none" stroke="#6E8589" stroke-width="3"/>'
    )
    focal = view["focal_point"]
    fx = x + float(focal["x"]) * w
    fy = y + float(focal["y"]) * h
    output.append(
        f'<circle cx="{fx:.2f}" cy="{fy:.2f}" r="16" fill="none" '
        'stroke="#E17242" stroke-width="4"/>'
    )
    _svg_text(output, _text(semantics["subject"], 48), x=x + 18, y=y + 30, size=16)
    _svg_text(
        output,
        f"{view['fit']} · {_text(semantics['narrative_role'], 20)}",
        x=x + 18,
        y=y + h - 18,
        size=12,
        fill="#546078",
    )


def build_semantic_preview_svg(
    slide: dict[str, Any], plan: dict[str, Any], *, width: int, height: int
) -> str:
    """Render carrier semantics and view geometry, not raw JSON or equal placeholders."""

    representation = slide["representation"]
    kind = str(representation["kind"])
    regions = {str(item["region_id"]): item for item in plan["regions"]}
    blocks = {str(item["block_id"]): item for item in slide["content_blocks"]}
    primary = regions[str(plan["view"]["primary_region_id"])]
    primary_block = blocks[str(primary["block_id"])]
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#50607A"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#F7F9FC"/>',
    ]
    headline = next(
        (item for item in slide["content_blocks"] if item["semantic_role"] == "headline"),
        None,
    )
    if headline is not None:
        _svg_text(output, _text(headline["content"], 70), x=72, y=62, size=28)
    if kind == "chart":
        _chart(output, representation["semantics"], primary)
    elif kind == "table":
        _table(output, primary_block["content"], primary, plan["view"]["details"])
    elif kind == "diagram":
        _diagram(output, representation["semantics"], primary, plan["view"]["details"])
    elif kind == "image":
        _image(output, representation["semantics"], primary, plan["view"]["details"])
    else:
        x, y, w, h = _region_box(primary)
        size = min(56.0, max(24.0, math.sqrt(w * h) / 10))
        _svg_text(output, _text(slide["core_message"], 90), x=x + 10, y=y + h / 2, size=size)
        output.append(
            f'<line x1="{x:.2f}" y1="{y+h*.72:.2f}" x2="{x+w*.55:.2f}" '
            f'y2="{y+h*.72:.2f}" stroke="#E17242" stroke-width="8"/>'
        )
    _svg_text(
        output,
        f"{slide['slide_id']} · {kind} · {plan['layout_family']} · semantic planning preview",
        x=72,
        y=height - 24,
        size=12,
        fill="#68738A",
    )
    output.append("</svg>")
    return "\n".join(output) + "\n"


def render_semantic_previews(
    workspace: Path,
    *,
    runtime: ArtifactRuntime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Render and receipt exact current Seed/Specs/Layout semantic previews."""

    workspace = workspace.resolve()
    admitted_runtime = runtime or ArtifactRuntime(workspace)
    graph = admitted_runtime.read_artifact_graph_snapshot(
        ("project_brief", "deck_outline", "slide_specs", "layout_plans")
    )
    specs = graph["slide_specs"]["data"]
    layouts = graph["layout_plans"]["data"]
    if str(specs.get("schema_version", "")).split(".")[1] != "2" or str(
        layouts.get("schema_version", "")
    ).split(".")[1] != "2":
        raise VisualQualityError("Semantic previews require Specs/Layout 0.2")
    seed_ref = specs.get("art_direction_seed")
    if not isinstance(seed_ref, dict):
        raise VisualQualityError("Semantic previews require frozen ArtDirectionSeed")
    slides = {str(item["slide_id"]): item for item in specs["slides"]}
    preview_root = workspace / ".slidethus/visual-quality/planning/previews"
    pages: list[dict[str, Any]] = []
    for plan in layouts["plans"]:
        slide_id = str(plan["slide_id"])
        svg = build_semantic_preview_svg(
            slides[slide_id],
            plan,
            width=int(layouts["canvas"]["width"]),
            height=int(layouts["canvas"]["height"]),
        ).encode("utf-8")
        digest = sha256_bytes(svg)
        path = preview_root / f"{digest}.svg"
        created = atomic_create_bytes(path, svg)
        if not created and path.read_bytes() != svg:
            raise VisualQualityError(f"Immutable semantic preview differs: {path}")
        pages.append(
            {
                "slide_id": slide_id,
                "representation_id": str(plan["representation_ref"]["representation_id"]),
                "path": path.relative_to(workspace).as_posix(),
                "sha256": digest,
                "mime_type": "image/svg+xml",
            }
        )
    contract = artifact_tool_host_contract()
    generated = max(
        (str(item.get("updated_at") or "") for item in graph.values()),
        default=utc_now(),
    )
    receipt = {
        "schema_version": "0.1.0",
        "project_id": str(specs["project_id"]),
        "receipt_id": "",
        "generated_at": generated or utc_now(),
        "producer": {"name": "semantic-planning-preview", "version": "1.0.0"},
        "inputs": [
            {
                "artifact_type": artifact_type,
                "version": int(snapshot["version"]),
                "content_hash": str(snapshot["content_hash"]),
            }
            for artifact_type, snapshot in sorted(graph.items())
        ],
        "seed_ref": {
            key: seed_ref[key] for key in ("seed_id", "path", "content_hash")
        },
        "target_capability": {
            "backend": "artifact-tool",
            "contract_version": "2.0.0",
            "contract_hash": "sha256:" + sha256_json(contract),
        },
        "pages": pages,
    }
    return persist_semantic_preview_receipt(workspace, receipt)


def review_semantic_previews(
    workspace: Path,
    *,
    provider: VisualReviewProvider,
    author_identities: tuple[str, ...] = (),
) -> SemanticPlanningAdmissionResult:
    """Obtain immutable qualitative evidence over exact current semantic previews."""

    workspace = workspace.resolve()
    policy = current_visual_admission_policy(workspace, create=False)
    receipt = current_semantic_preview_receipt(workspace)
    if policy is None or receipt is None:
        raise VisualQualityError(
            "Qualitative planning review requires current policy and semantic previews"
        )
    runtime = ArtifactRuntime(workspace)
    outline = runtime.show_artifact("deck_outline")
    specs = runtime.show_artifact("slide_specs")
    layout = runtime.show_artifact("layout_plans")
    pages = receipt[1]["pages"]
    paths = tuple(workspace / str(item["path"]) for item in pages)
    slide_ids = [str(item["slide_id"]) for item in specs["slides"]]
    representation_kinds = sorted(
        {str(item["representation"]["kind"]) for item in specs["slides"]}
    )
    required_coverage = [
        *[f"slide_{slide_id.lower().replace('-', '')}" for slide_id in slide_ids],
        *[f"representation_{kind}" for kind in representation_kinds],
    ]
    dependency = planning_admission_dependency_key(policy[1], receipt[1])
    proposal = provider.review(
        paths,
        {
            "review_stage": "planning",
            "mode": "semantic_planning_admission",
            "policy": policy[1],
            "preview_receipt": receipt[1],
            "deck_outline": outline,
            "slide_specs": specs,
            "layout_plans": layout,
            "required_coverage": required_coverage,
            "rules": {
                "reviewer_emits_findings_not_approval": True,
                "evaluate": [
                    "carrier_fitness",
                    "focal_hierarchy",
                    "page_distinction",
                    "deck_rhythm",
                ],
            },
        },
    )
    image_set = [
        {
            "slide_id": str(item["slide_id"]),
            "kind": "semantic_preview",
            "path": str(item["path"]),
            "sha256": str(item["sha256"]),
        }
        for item in pages
    ]
    review_path, review = persist_visual_quality_review(
        workspace,
        stage="planning",
        dependency_key=dependency,
        provider=provider,
        image_set=image_set,
        coverage=required_coverage,
        proposal=proposal,
        author_identities=author_identities,
    )
    decision_path, decision = derive_visual_quality_decision(
        workspace,
        review_path=review_path,
        required_coverage=required_coverage,
    )
    return SemanticPlanningAdmissionResult(
        review_path=review_path,
        decision_path=decision_path,
        review=review,
        decision=decision,
    )
