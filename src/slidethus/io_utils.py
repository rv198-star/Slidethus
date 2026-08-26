from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from slidethus.errors import WorkspaceError


def read_json(path: Path) -> Any:
    """Read UTF-8 JSON from path."""

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable JSON bytes for hashing."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def ensure_within(root: Path, candidate: Path) -> Path:
    """Resolve candidate and reject paths outside root."""

    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if candidate_resolved != root_resolved and root_resolved not in candidate_resolved.parents:
        raise WorkspaceError(f"Path escapes workspace: {candidate}")
    return candidate_resolved


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory after a replace operation."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Atomically replace a file with fsynced bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path: Path, value: Any, *, backup: bool = False) -> None:
    """Atomically write JSON in the destination directory.

    A temporary file is fsynced and replaced into place. Optional backups are
    deterministic `.bak` files and should not be treated as active artifacts.
    """

    if backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        atomic_write_bytes(backup_path, path.read_bytes())

    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)
