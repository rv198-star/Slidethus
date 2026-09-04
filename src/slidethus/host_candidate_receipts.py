"""Validation for mutable render-attempt receipts and their bound bytes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.io_utils import ensure_within, read_json, sha256_file


def _file_ref_error(workspace: Path, reference: dict[str, Any]) -> str | None:
    try:
        raw = Path(str(reference["path"]))
        path = ensure_within(workspace, raw if raw.is_absolute() else workspace / raw)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    if not path.is_file():
        return f"missing file: {path}"
    if sha256_file(path) != reference.get("sha256"):
        return f"hash mismatch: {path}"
    return None


def host_candidate_receipt_workspace_errors(
    workspace: Path, schema_dir: Path
) -> tuple[tuple[str, str], ...]:
    """Validate every Host Candidate Receipt and all local byte references."""

    workspace = workspace.resolve()
    root = workspace / "outputs/host-candidates"
    if not root.exists():
        return ()
    schema = read_json(schema_dir / "host_candidate_receipt.schema.json")
    validator = Draft202012Validator(schema)
    errors: list[tuple[str, str]] = []
    for path in sorted(root.glob("candidate-*/receipt*.json")):
        relative = path.relative_to(workspace).as_posix()
        try:
            receipt = read_json(path)
            for error in sorted(
                validator.iter_errors(receipt), key=lambda item: list(item.absolute_path)
            ):
                errors.append((relative, f"schema:{error.json_path}:{error.message}"))
            refs = [
                receipt.get("renderer_ir", {}),
                receipt.get("preflight", {}),
                *receipt.get("outputs", []),
                *receipt.get("office", {}).get("pages", []),
            ]
            if isinstance(receipt.get("input"), dict):
                refs.append(receipt["input"])
            for reference in refs:
                message = _file_ref_error(workspace, reference)
                if message:
                    errors.append((relative, message))
        except Exception as exc:  # noqa: BLE001
            errors.append((relative, f"receipt cannot be read: {exc}"))
    return tuple(errors)
