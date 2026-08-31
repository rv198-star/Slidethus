from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
import zipfile
from pathlib import Path

import pytest

from slidethus import __version__
from slidethus.cli import main
from slidethus.constants import find_repository_root
from slidethus.distribution import (
    SKILL_NAMES,
    DistributionError,
    bootstrap_renderer,
    build_plugin_bundle,
    materialize_skill,
    renderer_source_root,
    skill_source_root,
    skill_source_roots,
)
from slidethus.render_backends.node_toolchain import renderer_root


def test_release_version_agrees_across_package_runtime_and_readme() -> None:
    root = find_repository_root()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert project["project"]["version"] == __version__
    assert readme.startswith(f"# Slidethus v{__version__} —")
    assert f"包版本：`{__version__}`" in readme


def _fake_node(tmp_path: Path) -> Path:
    path = tmp_path / "node"
    path.write_text("#!/bin/sh\nprintf 'v22.0.0\\n'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_npm(tmp_path: Path) -> Path:
    path = tmp_path / "npm"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('10.9.8')\n"
        "    raise SystemExit(0)\n"
        "versions = {'pptxgenjs': '4.0.1', '@resvg/resvg-js': '2.6.2', 'pdf-lib': '1.17.1'}\n"
        "root = pathlib.Path.cwd() / 'node_modules'\n"
        "for name, version in versions.items():\n"
        "    target = root / name / 'package.json'\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text(json.dumps({'name': name, 'version': version}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_plugin_bundle_is_byte_reproducible_and_manifested(tmp_path: Path) -> None:
    first = build_plugin_bundle(tmp_path / "first.zip")
    second = build_plugin_bundle(tmp_path / "second.zip")

    assert first.sha256 == second.sha256
    assert first.path.read_bytes() == second.path.read_bytes()
    with zipfile.ZipFile(first.path) as archive:
        names = set(archive.namelist())
        for name in SKILL_NAMES:
            assert f".agents/skills/{name}/SKILL.md" in names
            assert f".agents/skills/{name}/agents/openai.yaml" in names
        assert ".agents/skills/slidethus/SKILL.md" in names
        assert ".agents/skills/slidethus/scripts/render_artifact.mjs" in names
        assert ".agents/skills/slidethus/references/host-create.md" in names
        assert "schemas/host_design_response.schema.json" in names
        assert "schemas/host_candidate_receipt.schema.json" in names
        assert ".agents/skills/slidethus/providers/art-direction/taste/SKILL.md" in names
        assert ".agents/skills/slidethus/providers/art-direction/taste/LICENSE" in names
        assert ".agents/skills/slidethus/providers/art-direction/taste/PROVENANCE.json" in names
        assert "renderers/pptxgenjs/package-lock.json" in names
        assert "schemas/project_state.schema.json" in names
        assert "LICENSE" in names
        assert "NOTICE.md" in names
        assert "THIRD_PARTY_NOTICES.md" in names
        assert "release/rights-policy.json" in names
        assert "release/sbom.spdx.json" in names
        assert not any(name.startswith("source_material/") for name in names)
        assert not any("node_modules/" in name for name in names)
        rights = json.loads(archive.read("release/rights-policy.json"))
        assert rights["project_license"] == "Apache-2.0"
        sbom = json.loads(archive.read("release/sbom.spdx.json"))
        assert sbom["spdxVersion"] == "SPDX-2.3"
        assert any(
            item["name"] == "@resvg/resvg-js" and item["licenseDeclared"] == "MPL-2.0"
            for item in sbom["packages"]
        )
        manifest = json.loads(archive.read("plugin-manifest.json"))
        assert manifest["manifest_id"].startswith("PLG-")
        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
        assert manifest["requirements"]["node"] == ">=20"
        assert manifest["requirements"]["default_art_direction_provider"] == "taste-skill"
        assert manifest["requirements"]["art_direction_provider_sha256"] == (
            "aa194351b246b8b4799099d4ed7b033d29eab6e6e3d58d8d2172978be7b3ec89"
        )
        assert first.file_count == len(names)


def test_materialize_skill_is_idempotent_and_refuses_modified_tree(tmp_path: Path) -> None:
    source = skill_source_root()
    host = tmp_path / "host"
    installed = materialize_skill(host)

    assert installed == host / ".agents/skills/slidethus"
    assert (installed / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert (installed / "providers/art-direction/taste/SKILL.md").is_file()
    assert (installed / "providers/art-direction/taste/LICENSE").is_file()
    for name, root in skill_source_roots().items():
        for path in root.rglob("*"):
            if path.is_file():
                assert (installed.parent / name / path.relative_to(root)).read_bytes() == path.read_bytes()
    assert materialize_skill(host) == installed

    (installed / "SKILL.md").write_text("modified\n", encoding="utf-8")
    with pytest.raises(DistributionError, match="Refusing to overwrite modified Skill file"):
        materialize_skill(host)


def test_renderer_bootstrap_materializes_pinned_cache_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("SLIDETHUS_CACHE_HOME", str(cache))
    node = _fake_node(tmp_path)
    npm = _fake_npm(tmp_path)

    first = bootstrap_renderer(cache_home=cache, npm=str(npm), node=str(node))
    second = bootstrap_renderer(cache_home=cache, npm=str(npm), node=str(node))

    assert first.changed is True
    assert second.changed is False
    assert first.root == second.root
    assert first.dependency_sha256 == second.dependency_sha256
    assert renderer_root() == first.root
    for name, version in {
        "pptxgenjs": "4.0.1",
        "@resvg/resvg-js": "2.6.2",
        "pdf-lib": "1.17.1",
    }.items():
        package = json.loads((first.root / "node_modules" / name / "package.json").read_text(encoding="utf-8"))
        assert package["version"] == version

    injected = first.root / "node_modules/pptxgenjs/tampered.js"
    injected.write_text("tampered", encoding="utf-8")
    third = bootstrap_renderer(cache_home=cache, npm=str(npm), node=str(node))
    assert third.changed is True
    assert not injected.exists()
    assert third.dependency_sha256 == first.dependency_sha256


def test_renderer_bootstrap_rejects_dependency_pin_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = renderer_source_root()
    drifted = tmp_path / "renderer"
    shutil.copytree(source, drifted, ignore=shutil.ignore_patterns("node_modules"))
    package_path = drifted / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["dependencies"]["pptxgenjs"] = "9.9.9"
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setenv("SLIDETHUS_RENDERER_SOURCE_ROOT", str(drifted))

    with pytest.raises(DistributionError, match="must pin pptxgenjs@4.0.1"):
        bootstrap_renderer(
            cache_home=tmp_path / "cache",
            npm=str(_fake_npm(tmp_path)),
            node=str(_fake_node(tmp_path)),
        )


def test_plugin_cli_status_build_and_skill_install(tmp_path: Path, capsys) -> None:
    assert main(["plugin", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["renderer_source_root"]
    assert status["skill_root"]
    assert set(status["skill_roots"]) == set(SKILL_NAMES)
    assert Path(status["entry_skill_root"]).name == "using-slidethus"

    bundle = tmp_path / "slidethus-plugin.zip"
    assert main(["plugin", "build", str(bundle)]) == 0
    built = json.loads(capsys.readouterr().out)
    assert bundle.is_file()
    assert built["sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()

    host = tmp_path / "host"
    assert main(["plugin", "install-skill", str(host)]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert Path(installed["skill_root"]) / "SKILL.md" == host / ".agents/skills/slidethus/SKILL.md"
    assert (host / ".agents/skills/slidethus/SKILL.md").is_file()
    assert Path(installed["entry_skill_root"]) == host / ".agents/skills/using-slidethus"


def test_suite_conflict_preflight_does_not_partially_install(tmp_path: Path) -> None:
    host = tmp_path / "host"
    conflict = host / ".agents/skills/slidethus-review"
    shutil.copytree(skill_source_roots()["slidethus-review"], conflict)
    modified = conflict / "SKILL.md"
    modified.write_text("user custom review", encoding="utf-8")
    before = {path.relative_to(host): path.read_bytes() for path in host.rglob("*") if path.is_file()}
    with pytest.raises(DistributionError, match="Refusing to overwrite modified"):
        materialize_skill(host)
    assert before == {path.relative_to(host): path.read_bytes() for path in host.rglob("*") if path.is_file()}
    assert not (host / ".agents/skills/slidethus").exists()


def test_incomplete_suite_fails_before_install_or_bundle(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    for name, root in skill_source_roots().items():
        if name != "slidethus-research":
            shutil.copytree(root, source / name)
    monkeypatch.setenv("SLIDETHUS_SKILL_ROOT", str(source / "slidethus"))
    with pytest.raises(DistributionError, match="suite is incomplete: slidethus-research"):
        materialize_skill(tmp_path / "host")
    with pytest.raises(DistributionError, match="suite is incomplete"):
        build_plugin_bundle(tmp_path / "bad.zip")
    assert not (tmp_path / "host").exists()
    assert not (tmp_path / "bad.zip").exists()


def test_suite_allowlist_never_packages_unrelated_sibling_skills(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    for name, root in skill_source_roots().items():
        shutil.copytree(root, source / name)
    private = source / "unrelated-private-skill"
    private.mkdir()
    (private / "SKILL.md").write_text("private user notes", encoding="utf-8")
    monkeypatch.setenv("SLIDETHUS_SKILL_ROOT", str(source / "slidethus"))
    with zipfile.ZipFile(build_plugin_bundle(tmp_path / "suite.zip").path) as archive:
        assert not any("unrelated-private-skill" in name for name in archive.namelist())
    installed = materialize_skill(tmp_path / "host")
    assert not (installed.parent / private.name).exists()


@pytest.mark.parametrize("relative", [".agents", ".agents/skills", ".agents/skills/slidethus-review"])
def test_suite_install_refuses_symlinked_destinations(tmp_path: Path, relative: str) -> None:
    external = tmp_path / "external"
    external.mkdir()
    link = tmp_path / "host" / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(external, target_is_directory=True)
    with pytest.raises(DistributionError, match="symlinked"):
        materialize_skill(tmp_path / "host")
    assert not list(external.iterdir())


def test_legacy_installed_skill_discovery_remains_compatible(tmp_path: Path, monkeypatch) -> None:
    import slidethus.distribution as distribution

    shutil.copytree(skill_source_root(), tmp_path / "skill")
    monkeypatch.delenv("SLIDETHUS_SKILL_ROOT", raising=False)
    monkeypatch.setattr(distribution, "_repository_root", lambda: None)
    monkeypatch.setattr(distribution, "installed_share_root", lambda: tmp_path)
    assert distribution.skill_source_root() == tmp_path / "skill"
    assert distribution.taste_skill_identity()["license"] == "MIT"
    # Discovery compatibility does not misrepresent a single legacy tree as a full suite.
    with pytest.raises(DistributionError, match="suite is incomplete"):
        distribution.materialize_skill(tmp_path / "host")
