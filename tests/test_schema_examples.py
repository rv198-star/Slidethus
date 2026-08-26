from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from slidethus.constants import find_repository_root
from slidethus.schema_registry import SchemaRegistry
from slidethus.validation import validate_workspace


def test_all_catalog_schemas_are_valid() -> None:
    root = find_repository_root()
    registry = SchemaRegistry(root / "schemas")
    assert len(registry.entries) == 16
    for artifact_type in registry.entries:
        Draft202012Validator.check_schema(registry.schema(artifact_type))


def test_supporting_schemas_are_valid() -> None:
    root = find_repository_root()
    for path in sorted((root / "schemas").glob("*.schema.json")):
        Draft202012Validator.check_schema(
            json.loads(path.read_text(encoding="utf-8"))
        )


def test_minimal_project_validates_with_hashes() -> None:
    root = find_repository_root()
    report = validate_workspace(root / "examples/minimal_project", check_hashes=True)
    assert report.ok, report.issues


def test_catalog_paths_are_unique() -> None:
    root = find_repository_root()
    catalog = json.loads((root / "schemas/catalog.json").read_text(encoding="utf-8"))
    artifact_types = [item["artifact_type"] for item in catalog["schemas"]]
    default_paths = [item["default_path"] for item in catalog["schemas"]]
    schema_paths = [item["path"] for item in catalog["schemas"]]
    assert len(artifact_types) == len(set(artifact_types))
    assert len(default_paths) == len(set(default_paths))
    assert len(schema_paths) == len(set(schema_paths))


def test_packaged_schema_mirror_matches_repository_schemas() -> None:
    root = find_repository_root()
    packaged = root / "src/slidethus/_schemas"
    root_files = {path.name: path.read_bytes() for path in (root / "schemas").glob("*.json")}
    packaged_files = {path.name: path.read_bytes() for path in packaged.glob("*.json")}
    assert packaged_files == root_files
