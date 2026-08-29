from __future__ import annotations

from slidethus.layout_geometry import build_layout_plan
from slidethus.text_capacity import estimated_text_height, fitting_font_size


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


def test_matrix_reserves_full_width_for_one_high_cardinality_list() -> None:
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

    assert list_region["w"] == 1120.0
    assert list_region["h"] >= 240.0
