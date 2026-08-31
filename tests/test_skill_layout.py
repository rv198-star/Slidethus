from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from slidethus.constants import find_repository_root
from slidethus.distribution import SKILL_NAMES, build_plugin_bundle, materialize_skill


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


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_module_has_discoverable_name_description_and_ui(name: str) -> None:
    root = find_repository_root() / ".agents/skills" / name
    data = _frontmatter((root / "SKILL.md").read_text(encoding="utf-8"))
    assert data["name"] == name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", name)
    assert data["description"]
    ui = (root / "agents/openai.yaml").read_text(encoding="utf-8")
    short = re.search(r'  short_description: "(.+)"', ui)
    assert short and 25 <= len(short[1]) <= 64
    assert f"${name}" in ui
    assert "allow_implicit_invocation: true" in ui


def _check_link_closure(skills: Path) -> None:
    """Resolve the actual installed relative references, not repository fallbacks."""
    for name in SKILL_NAMES:
        for path in (skills / name).rglob("*.md"):
            for raw in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                target = raw.split("#", 1)[0]
                if not target or target.startswith(("https://", "http://", "mailto:")):
                    continue
                resolved = (path.parent / target).resolve()
                assert resolved.is_relative_to(skills.resolve()), (path, target)
                assert resolved.exists(), (path, target)


def test_materialized_and_bundled_suite_references_are_self_contained(tmp_path: Path) -> None:
    import zipfile

    installed = materialize_skill(tmp_path / "host")
    _check_link_closure(installed.parent)
    bundle = build_plugin_bundle(tmp_path / "suite.zip")
    with zipfile.ZipFile(bundle.path) as archive:
        archive.extractall(tmp_path / "bundle")
    _check_link_closure(tmp_path / "bundle/.agents/skills")
    entry = installed.parent / "using-slidethus/SKILL.md"
    linked_modules = {
        (entry.parent / target).resolve().parent.name
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", entry.read_text(encoding="utf-8"))
        if target.endswith("/SKILL.md")
    }
    assert linked_modules == set(SKILL_NAMES) - {"slidethus", "using-slidethus"}


def test_wheel_data_preserves_complete_sibling_skill_layout(tmp_path: Path, monkeypatch) -> None:
    import slidethus.distribution as distribution

    root = find_repository_root()
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    mapped: dict[str, str] = {}
    for destination, sources in data["tool"]["setuptools"]["data-files"].items():
        for source in sources:
            target = Path(destination) / Path(source).name
            installed = tmp_path / target
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_bytes((root / source).read_bytes())
            if not source.startswith(".agents/skills/"):
                continue
            relative = Path(source).relative_to(".agents/skills")
            assert target == Path("share/slidethus/skills") / relative
            assert source not in mapped
            mapped[source] = str(target)
    expected = {
        path.relative_to(root).as_posix()
        for name in SKILL_NAMES
        for path in (root / ".agents/skills" / name).rglob("*") if path.is_file()
    }
    assert set(mapped) == expected
    monkeypatch.delenv("SLIDETHUS_SKILL_ROOT", raising=False)
    monkeypatch.setattr(distribution, "_repository_root", lambda: None)
    monkeypatch.setattr(distribution, "installed_share_root", lambda: tmp_path / "share/slidethus")
    assert distribution.skill_source_root() == tmp_path / "share/slidethus/skills/slidethus"
    installed = distribution.materialize_skill(tmp_path / "outside-repo")
    _check_link_closure(installed.parent)
    assert distribution.taste_skill_identity()["license"] == "MIT"
    assert distribution.build_plugin_bundle(tmp_path / "installed-suite.zip").path.is_file()


def test_one_shot_brief_recipe_persists_auto_without_running_planning(tmp_path: Path) -> None:
    from slidethus.artifact_runtime import ArtifactRuntime
    from slidethus.protocols import BriefCompletionHints
    from slidethus.services.brief_completion import BriefCompletionService
    from slidethus.workspace import init_workspace

    workspace = init_workspace(tmp_path / "brief", title="Skill intake recipe")
    runtime = ArtifactRuntime(workspace)
    original_state = runtime.show_artifact("project_state")
    outline_path = workspace / "outline/deck_outline.json"
    assert not outline_path.exists()
    assert runtime.show_artifact("project_brief")["approval_mode"] == "checkpoint"
    result = BriefCompletionService(workspace).complete(BriefCompletionHints(approval_mode="auto"))
    assert result.brief["approval_mode"] == "auto"
    assert runtime.show_artifact("project_brief")["approval_mode"] == "auto"
    assert runtime.show_artifact("project_state")["current_phase"] == original_state["current_phase"]
    assert not outline_path.exists()
    assert result.blocking_questions
