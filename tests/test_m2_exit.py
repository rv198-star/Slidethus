from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from slidethus.constants import find_repository_root

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/validate_m2_exit.py"
_SPEC = importlib.util.spec_from_file_location("slidethus_validate_m2_exit", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import machinery guard
    raise RuntimeError(f"Cannot load M2 Exit validator: {_SCRIPT_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
evaluate_m2_exit = _MODULE.evaluate_m2_exit


def _copy_repository(tmp_path: Path) -> Path:
    source = find_repository_root()
    target = tmp_path / "repository"
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
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


def _check_map(root: Path) -> dict[str, object]:
    return {check.name: check for check in evaluate_m2_exit(root)}


def test_repository_m2_exit_contract_passes() -> None:
    checks = evaluate_m2_exit(find_repository_root())

    assert checks
    assert all(check.ok for check in checks), "\n".join(
        f"{check.name}: {check.detail}" for check in checks if not check.ok
    )


def test_m2_exit_rejects_missing_final_evidence(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / "audit/M2-BUILD_REPORT.md").unlink()

    checks = _check_map(root)

    assert not checks["required_evidence"].ok
    assert "audit/M2-BUILD_REPORT.md" in checks["required_evidence"].detail


def test_m2_exit_rejects_stale_task_state(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    tasks_path = root / "TASKS.md"
    tasks = tasks_path.read_text(encoding="utf-8")
    tasks = tasks.replace(
        "- [x] PDF/DOCX/HTML/PPTX/图片/表格输入适配器",
        "- [ ] PDF/DOCX/HTML/PPTX/图片/表格输入适配器",
        1,
    )
    tasks_path.write_text(tasks, encoding="utf-8")

    checks = _check_map(root)

    assert not checks["tasks_m2_complete"].ok


def test_m2_exit_rejects_bundled_network_client(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    application_path = root / "src/slidethus/services/m2_application.py"
    application_path.write_text(
        "import requests\n" + application_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    checks = _check_map(root)

    assert not checks["provider_neutrality"].ok
