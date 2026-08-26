from __future__ import annotations

from pathlib import Path

from slidethus.constants import find_repository_root
from slidethus.wireframe import render_wireframes


def test_wireframe_renderer_outputs_three_valid_svg_files(tmp_path: Path) -> None:
    root = find_repository_root()
    outputs = render_wireframes(root / "examples/minimal_project", tmp_path)
    assert [path.name for path in outputs] == ["S-001.svg", "S-002.svg", "S-003.svg"]
    for output in outputs:
        text = output.read_text(encoding="utf-8")
        assert 'viewBox="0 0 1280 720"' in text
        assert "planning wireframe" in text
        assert "REG-" in text
        assert "BLK-" in text
