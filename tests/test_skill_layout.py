from __future__ import annotations

from slidethus.constants import find_repository_root


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    _, raw, _ = text.split("---", 2)
    result: dict[str, str] = {}
    for line in raw.strip().splitlines():
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def test_skill_is_repo_discoverable_and_has_required_frontmatter() -> None:
    root = find_repository_root()
    skill = root / ".agents/skills/slidethus/SKILL.md"
    assert skill.exists()
    data = _frontmatter(skill.read_text(encoding="utf-8"))
    assert data["name"] == "slidethus"
    assert "presentation" in data["description"].lower()
    assert (skill.parent / "agents/openai.yaml").exists()
    assert len(list((skill.parent / "workflows").glob("*.md"))) >= 6
    assert len(list((skill.parent / "references").glob("*.md"))) >= 6
