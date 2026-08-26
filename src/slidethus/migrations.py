from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from slidethus.errors import MigrationError

MigrationFunction = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class MigrationStep:
    """One explicit, reversible-by-backup schema migration step."""

    artifact_type: str
    from_version: str
    to_version: str
    migrate: MigrationFunction


class MigrationRegistry:
    """Resolve and execute explicit schema-version migration chains."""

    def __init__(self) -> None:
        self._steps: dict[tuple[str, str], MigrationStep] = {}

    def register(self, step: MigrationStep) -> None:
        key = (step.artifact_type, step.from_version)
        if key in self._steps:
            raise MigrationError(f"Duplicate migration from {step.artifact_type} {step.from_version}")
        self._steps[key] = step

    def plan(self, artifact_type: str, from_version: str, to_version: str) -> tuple[MigrationStep, ...]:
        """Return the only registered forward chain, or fail explicitly."""

        if from_version == to_version:
            return ()
        planned: list[MigrationStep] = []
        current = from_version
        seen: set[str] = set()
        while current != to_version:
            if current in seen:
                raise MigrationError(f"Migration cycle for {artifact_type} at {current}")
            seen.add(current)
            step = self._steps.get((artifact_type, current))
            if step is None:
                raise MigrationError(
                    f"No migration path for {artifact_type}: {from_version} -> {to_version} (stopped at {current})"
                )
            planned.append(step)
            current = step.to_version
        return tuple(planned)

    def migrate(
        self,
        artifact_type: str,
        data: dict[str, Any],
        to_version: str,
    ) -> tuple[dict[str, Any], tuple[MigrationStep, ...]]:
        """Apply a registered chain without writing files."""

        from_version = str(data.get("schema_version", ""))
        steps = self.plan(artifact_type, from_version, to_version)
        migrated = data
        for step in steps:
            migrated = step.migrate(migrated)
            if migrated.get("schema_version") != step.to_version:
                raise MigrationError(
                    f"Migration {artifact_type} {step.from_version}->{step.to_version} produced wrong schema_version"
                )
        return migrated, steps


def _project_state_010_to_020(data: dict[str, Any]) -> dict[str, Any]:
    migrated = {**data, "schema_version": "0.2.0"}
    return migrated


DEFAULT_MIGRATIONS = MigrationRegistry()
DEFAULT_MIGRATIONS.register(
    MigrationStep(
        artifact_type="project_state",
        from_version="0.1.0",
        to_version="0.2.0",
        migrate=_project_state_010_to_020,
    )
)
