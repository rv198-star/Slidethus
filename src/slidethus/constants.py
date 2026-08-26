from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = "0.1.0"
PROJECT_STATE_SCHEMA_VERSION = "0.2.0"
DEFAULT_CANVAS_WIDTH = 1280
DEFAULT_CANVAS_HEIGHT = 720
DEFAULT_SAFE_AREA = {"top": 48, "right": 56, "bottom": 44, "left": 56}


def find_repository_root(start: Path | None = None) -> Path:
    """Find a checkout containing both pyproject.toml and schemas/catalog.json."""

    candidates = []
    if start is not None:
        candidates.append(start.resolve())
    candidates.extend([Path.cwd().resolve(), Path(__file__).resolve().parents[2]])

    seen: set[Path] = set()
    for candidate in candidates:
        for current in [candidate, *candidate.parents]:
            if current in seen:
                continue
            seen.add(current)
            if (current / "pyproject.toml").exists() and (current / "schemas" / "catalog.json").exists():
                return current
    raise FileNotFoundError("Could not locate a Slidethus repository root")
