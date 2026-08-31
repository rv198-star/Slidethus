from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from slidethus.constants import find_repository_root
from slidethus.distribution import build_plugin_bundle, materialize_skill, skill_source_root
from slidethus.sbom import _design_reference_package, build_sbom


def _library() -> Path:
    return skill_source_root() / "references/design-library"


def test_design_reference_index_is_small_and_cards_have_pinned_provenance() -> None:
    root = find_repository_root()
    library = _library()
    provenance = json.loads((library / "PROVENANCE.json").read_text(encoding="utf-8"))
    index = (library / "index.md").read_text(encoding="utf-8")
    paths = re.findall(r"\]\((cards/[^)]+\.md)\)", index)
    references = provenance["references"]
    catalog = (root / "source_material/source-preserved/open-kimi-ppt-skill/theme.md").read_text(encoding="utf-8")
    upstream_paths = re.findall(r"\]\((skills/[^)]+\.md)\)", catalog)
    upstream_ids = re.findall(r"^#### `([^`]+)`", catalog, flags=re.MULTILINE)
    assert len(paths) == len(set(paths)) == len(references) == len(upstream_ids) == 44
    assert {item["id"] for item in references} == set(upstream_ids)
    assert {item["upstream_path"] for item in references} == set(upstream_paths)
    catalog_paths = dict(zip(upstream_ids, upstream_paths, strict=True))
    assert set(paths) == {item["card_path"] for item in references}
    assert set(paths) == {str(p.relative_to(library)) for p in (library / "cards").glob("*.md")}
    # Full coverage stays cheap: only descriptors/links in the index, not manuals.
    assert len(index.encode("utf-8")) <= 8192
    assert not re.search(r"!\[[^\]]*\]\(", index)
    assert provenance["library_revision"] in index
    commit = provenance["upstream_commit"]
    assert re.fullmatch(r"[a-f0-9]{40}", commit)
    source_total = 0
    card_sizes = []
    for item in references:
        assert item["card_path"] == f"cards/{item['id']}.md"
        assert item["upstream_path"] == catalog_paths[item["id"]]
        card_path = library / item["card_path"]
        assert card_path.resolve().is_relative_to(library.resolve())
        card = card_path.read_bytes()
        card_sizes.append(len(card))
        assert len(card) <= 4096
        # A text-only index/card read cannot preload a contact sheet.
        assert not re.search(rb"!\[[^\]]*\]\(", card)
        source_path = root / item["preserved_path"]
        assert source_path.resolve().is_relative_to((root / "source_material/source-preserved").resolve())
        original = source_path.read_bytes()
        source_total += len(original)
        assert hashlib.sha256(original).hexdigest() == item["source_sha256"]
        blob = b"blob " + str(len(original)).encode() + b"\0" + original
        assert hashlib.sha1(blob).hexdigest() == item["source_git_blob"]
        text = card.decode("utf-8")
        assert f"/blob/{commit}/{item['upstream_path']}" in text
        assert item["preview_url"] in text
        assert f"/{commit}/docs/themes/" in item["preview_url"]
        assert re.fullmatch(r"[a-f0-9]{40}", item["preview_git_blob"])
    # Measures available reading volume only; it does not claim an Agent obeyed a budget.
    assert len(index.encode("utf-8")) + sum(sorted(card_sizes, reverse=True)[:3]) < source_total / 4
    assert len(index.encode("utf-8")) + sum(sorted(card_sizes, reverse=True)[:3]) <= 16384
    license_bytes = (library / "LICENSE").read_bytes()
    assert provenance["files"]["LICENSE"] == "sha256:" + hashlib.sha256(license_bytes).hexdigest()
    assert license_bytes == (root / "source_material/source-preserved/open-kimi-ppt-skill/LICENSE").read_bytes()


def test_design_reference_cards_are_offline_installed_and_manifested(tmp_path: Path) -> None:
    installed = materialize_skill(tmp_path / "host")
    expected = {str(p.relative_to(_library())): p.read_bytes() for p in _library().rglob("*") if p.is_file()}
    for relative, data in expected.items():
        assert (installed / "references/design-library" / relative).read_bytes() == data
    bundle = build_plugin_bundle(tmp_path / "plugin.zip")
    with zipfile.ZipFile(bundle.path) as archive:
        names = set(archive.namelist())
        for relative, data in expected.items():
            assert archive.read(f".agents/skills/slidethus/references/design-library/{relative}") == data
        assert not any(name.startswith("source_material/") for name in names)
        assert not any(name.endswith((".jpg", ".png", ".ttf", ".otf")) and "design-library/" in name for name in names)
        sbom = json.loads(archive.read("release/sbom.spdx.json"))
        reference = next(p for p in sbom["packages"] if p["name"] == "open-kimi-ppt-design-references")
        assert reference["licenseDeclared"] == "MIT"
        assert any(r["relationshipType"] == "CONTAINS" and r["relatedSpdxElement"] == reference["SPDXID"] for r in sbom["relationships"])
        rights = json.loads(archive.read("release/rights-policy.json"))
        assert any(p["scope"].endswith("references/design-library/cards/") and p["license"] == "MIT" for p in rights["included_third_party"])


@pytest.mark.parametrize("prefix", [".agents/skills/slidethus", "skills/slidethus", "skill"])
def test_design_reference_sbom_resolves_packaging_roots_and_refuses_missing_provenance(
    tmp_path: Path, prefix: str,
) -> None:
    destination = tmp_path / prefix / "references/design-library"
    shutil.copytree(_library(), destination)
    expected = _design_reference_package(find_repository_root())
    assert _design_reference_package(tmp_path) == expected
    (destination / "PROVENANCE.json").unlink()
    with pytest.raises(FileNotFoundError, match="design reference provenance"):
        _design_reference_package(tmp_path)


def test_reference_library_revision_changes_source_sbom_identity(tmp_path: Path) -> None:
    # Scope this test to bundled-reference identity; no network or provider calls.
    destination = tmp_path / "skills/slidethus/references/design-library"
    shutil.copytree(_library(), destination)
    before = _design_reference_package(tmp_path)
    provenance_path = destination / "PROVENANCE.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["library_revision"] = "test-next-revision"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    after = _design_reference_package(tmp_path)
    assert before["SPDXID"] != after["SPDXID"]
    assert before["versionInfo"] != after["versionInfo"]
    assert any(p["SPDXID"] == before["SPDXID"] for p in build_sbom(find_repository_root())["packages"])
