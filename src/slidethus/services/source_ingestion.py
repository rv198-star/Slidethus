from __future__ import annotations

from pathlib import Path

from slidethus.io_utils import sha256_file


def fingerprint_source(path: Path) -> dict[str, str | int]:
    """Return deterministic source metadata without parsing content."""

    stat = path.stat()
    return {"path": str(path), "sha256": sha256_file(path), "size_bytes": stat.st_size}
