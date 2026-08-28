from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from slidethus.constants import find_repository_root

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_m4_exit.py"
_SPEC = importlib.util.spec_from_file_location("slidethus_validate_m4_exit", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"Cannot load M4 Exit validator: {_SCRIPT}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
evaluate_m4_exit = _MODULE.evaluate_m4_exit


def _copy_repository(tmp_path: Path) -> Path:
    source = find_repository_root()
    target = tmp_path / "repository"
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "dist",
            "*.egg-info",
            "*.pyc",
        ),
    )
    return target


def _checks(root: Path) -> dict[str, object]:
    return {item.name: item for item in evaluate_m4_exit(root, run_runtime_checks=False)}


def test_repository_m4_exit_contract_passes() -> None:
    checks = evaluate_m4_exit(find_repository_root())

    assert checks
    assert all(item.ok for item in checks), "\n".join(
        f"{item.name}: {item.detail}" for item in checks if not item.ok
    )


def test_m4_exit_rejects_schema_mirror_drift(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    mirror = root / "src/slidethus/_schemas/renderer_ir.schema.json"
    mirror.write_text(mirror.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    checks = _checks(root)

    assert not checks["runtime_schemas"].ok
    assert "mirror:renderer_ir.schema.json" in checks["runtime_schemas"].detail


def test_m4_exit_rejects_stale_task_state(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    tasks = root / "TASKS.md"
    text = tasks.read_text(encoding="utf-8").replace(
        "- [x] 最终 SVG renderer",
        "- [ ] 最终 SVG renderer",
        1,
    )
    tasks.write_text(text, encoding="utf-8")

    assert not _checks(root)["tasks_m4_complete"].ok


def test_m4_exit_rejects_unlocked_sidecar(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / "renderers/pptxgenjs/package-lock.json").unlink()

    checks = _checks(root)

    assert not checks["required_evidence"].ok
    assert not checks["node_sidecar_locked"].ok


def test_m4_exit_rejects_renderer_owned_planning_truth(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    renderer = root / "renderers/pptxgenjs/render.mjs"
    renderer.write_text(
        renderer.read_text(encoding="utf-8") + "\n// deck_outline must be read here\n",
        encoding="utf-8",
    )

    assert not _checks(root)["backend_independence"].ok
