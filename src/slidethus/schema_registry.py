from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.constants import find_repository_root
from slidethus.errors import SchemaError
from slidethus.io_utils import read_json


@dataclass(frozen=True)
class SchemaEntry:
    artifact_type: str
    schema_path: Path
    default_path: Path
    schema_version: str


class SchemaRegistry:
    """Load and validate the repository schema catalog."""

    def __init__(self, schema_dir: Path | None = None) -> None:
        if schema_dir is None:
            env_dir = os.environ.get("SLIDETHUS_SCHEMA_DIR")
            if env_dir:
                schema_dir = Path(env_dir)
            else:
                try:
                    schema_dir = find_repository_root() / "schemas"
                except FileNotFoundError:
                    schema_dir = Path(__file__).resolve().parent / "_schemas"
        self.schema_dir = schema_dir.resolve()
        catalog_path = self.schema_dir / "catalog.json"
        if not catalog_path.exists():
            raise SchemaError(f"Missing schema catalog: {catalog_path}")
        catalog = read_json(catalog_path)
        self.entries: dict[str, SchemaEntry] = {}
        for item in catalog.get("schemas", []):
            entry = SchemaEntry(
                artifact_type=item["artifact_type"],
                schema_path=self.schema_dir / item["path"],
                default_path=Path(item["default_path"]),
                schema_version=item.get("schema_version", "0.1.0"),
            )
            self.entries[entry.artifact_type] = entry
        if not self.entries:
            raise SchemaError("Schema catalog contains no entries")

    def entry(self, artifact_type: str) -> SchemaEntry:
        try:
            return self.entries[artifact_type]
        except KeyError as exc:
            raise SchemaError(f"Unknown artifact type: {artifact_type}") from exc

    def schema(self, artifact_type: str) -> dict[str, Any]:
        schema_path = self.entry(artifact_type).schema_path
        if not schema_path.exists():
            raise SchemaError(f"Missing schema file: {schema_path}")
        schema = read_json(schema_path)
        Draft202012Validator.check_schema(schema)
        return schema

    def validator(self, artifact_type: str) -> Draft202012Validator:
        return Draft202012Validator(self.schema(artifact_type))

    def artifact_type_for_path(self, relative_path: Path) -> str | None:
        normalized = relative_path.as_posix()
        for artifact_type, entry in self.entries.items():
            if entry.default_path.as_posix() == normalized:
                return artifact_type
        return None
