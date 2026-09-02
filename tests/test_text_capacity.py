from __future__ import annotations

from slidethus.layout_geometry import build_layout_plan
from slidethus.text_capacity import estimated_text_height, fit_text, fitting_font_size


def test_shared_capacity_estimate_handles_non_latin_lists_and_font_floor() -> None:
    items = [
        "Входящие запросы проходят проверку",
        "Исключения передаются владельцу",
        "Качество решения измеряется",
    ]

    preferred = estimated_text_height(
        items,
        "list",
        width=300,
        font_size=20,
        line_height=1.28,
    )
    floor = estimated_text_height(
        items,
        "list",
        width=300,
        font_size=18,
        line_height=1.28,
    )

    assert floor < preferred
    assert fitting_font_size(
        items,
        "list",
        width=300,
        height=floor,
        preferred=20,
        floor=18,
        line_height=1.28,
    ) == 18
    assert fitting_font_size(
        items,
        "list",
        width=300,
        height=floor - 1,
        preferred=20,
        floor=18,
        line_height=1.28,
    ) is None


def test_matrix_reserves_full_height_framework_rail_for_high_cardinality_list() -> None:
    blocks = [
        {
            "block_id": "BLK-S001-01",
            "content_hash": "sha256:" + "1" * 64,
            "semantic_role": "headline",
            "content_type": "text",
            "content": "Operational controls form one system",
        },
        {
            "block_id": "BLK-S001-02",
            "content_hash": "sha256:" + "2" * 64,
            "semantic_role": "evidence",
            "content_type": "text",
            "content": "One supporting observation",
        },
        {
            "block_id": "BLK-S001-03",
            "content_hash": "sha256:" + "3" * 64,
            "semantic_role": "evidence",
            "content_type": "list",
            "content": ["Intake", "Policy", "Routing", "Tools", "Quality"],
        },
    ]
    plan = build_layout_plan(
        {
            "slide_id": "S-001",
            "content_blocks": blocks,
            "density_budget": {"min_body_pt": 18},
            "visual_intent": {"relationship": "classification"},
        },
        family="matrix",
        canvas={"width": 1280, "height": 720},
        safe_area={"top": 60.0, "right": 80.0, "bottom": 60.0, "left": 80.0},
    )
    list_region = next(
        region for region in plan["regions"] if region["block_id"] == "BLK-S001-03"
    )

    assert list_region["w"] > 500.0
    assert list_region["h"] == 456.0
    support_region = next(
        region for region in plan["regions"] if region["block_id"] == "BLK-S001-02"
    )
    assert list_region["x"] > support_region["x"] + support_region["w"]


def test_office_point_scale_is_included_in_text_capacity() -> None:
    height = estimated_text_height(
        ["数据、流程、规则、工具与权限", "验证标准与人工接管"],
        "list",
        width=320,
        font_size=18,
        line_height=1.2,
        qualification="internal",
    )

    assert height >= 18 * (4 / 3) * 1.2 * 2 + 32 + 24


def test_failed_fit_reports_reason_and_minimum_height_adjustment() -> None:
    fit = fit_text(
        ["A long operating requirement", "A second operating requirement"],
        "list",
        width=180,
        height=40,
        preferred=18,
        floor=18,
        line_height=1.28,
        qualification="internal",
    )

    assert not fit.fits
    assert fit.failure_reason == "required_height_exceeds_available_at_floor"
    assert fit.required_height_increase == fit.required_height - fit.available_height


def test_renderer_profile_uses_the_insets_the_adapter_actually_emits() -> None:
    generic = fit_text(
        "Internal scenario",
        "text",
        width=1120,
        height=48,
        preferred=15,
        floor=15,
        line_height=1.28,
    )
    artifact_tool = fit_text(
        "Internal scenario",
        "text",
        width=1120,
        height=48,
        preferred=15,
        floor=15,
        line_height=1.28,
        horizontal_padding=0,
        vertical_padding=0,
    )

    assert not generic.fits
    assert generic.vertical_padding == 24
    assert artifact_tool.fits
    assert artifact_tool.vertical_padding == 0


def test_generated_stack_reallocates_whitespace_before_capacity_failure() -> None:
    blocks = [
        {
            "block_id": "BLK-S001-01",
            "content_hash": "sha256:" + "1" * 64,
            "semantic_role": "headline",
            "content_type": "text",
            "content": "Operational model",
        },
        {
            "block_id": "BLK-S001-02",
            "content_hash": "sha256:" + "2" * 64,
            "semantic_role": "body",
            "content_type": "list",
            "content": [
                "This operating step has explanatory detail that wraps over one visual line"
            ]
            * 6,
        },
        {
            "block_id": "BLK-S001-03",
            "content_hash": "sha256:" + "3" * 64,
            "semantic_role": "body",
            "content_type": "text",
            "content": "Short support",
        },
    ]

    plan = build_layout_plan(
        {
            "slide_id": "S-001",
            "content_blocks": blocks,
            "density_budget": {"min_body_pt": 18},
            "visual_intent": {"relationship": "sequence"},
        },
        family="hero",
        canvas={"width": 1280, "height": 720},
        safe_area={"top": 60.0, "right": 80.0, "bottom": 60.0, "left": 80.0},
    )

    heights = {region["block_id"]: region["h"] for region in plan["regions"]}
    assert heights["BLK-S001-02"] > heights["BLK-S001-03"]
    assert plan["diagnostics"]["warnings"] == [
        "Deterministic text capacity repair reallocated stacked whitespace without "
        "crossing the approved font floors."
    ]
