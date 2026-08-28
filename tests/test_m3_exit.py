from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from slidethus.constants import find_repository_root

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/validate_m3_exit.py"
_SPEC = importlib.util.spec_from_file_location("slidethus_validate_m3_exit", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"Cannot load M3 Exit validator: {_SCRIPT_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
evaluate_m3_exit = _MODULE.evaluate_m3_exit


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
    return {
        check.name: check
        for check in evaluate_m3_exit(root, run_runtime_checks=False)
    }


def test_repository_m3_exit_contract_passes() -> None:
    checks = evaluate_m3_exit(find_repository_root())

    assert checks
    assert all(check.ok for check in checks), "\n".join(
        f"{check.name}: {check.detail}" for check in checks if not check.ok
    )


def test_m3_exit_rejects_missing_final_evidence(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / "audit/M3-BUILD_REPORT.md").unlink()

    checks = _check_map(root)

    assert not checks["required_evidence"].ok
    assert "audit/M3-BUILD_REPORT.md" in checks["required_evidence"].detail


def test_m3_exit_rejects_stale_task_state(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    tasks_path = root / "TASKS.md"
    tasks = tasks_path.read_text(encoding="utf-8")
    tasks = tasks.replace(
        "- [x] Project Brief 智能补全与最少提问策略",
        "- [ ] Project Brief 智能补全与最少提问策略",
        1,
    )
    tasks_path.write_text(tasks, encoding="utf-8")

    checks = _check_map(root)

    assert not checks["tasks_m3_complete"].ok


def test_m3_exit_rejects_bundled_model_or_network_client(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    provider_path = root / "src/slidethus/planning_provider.py"
    provider_path.write_text(
        "import openai\n" + provider_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    checks = _check_map(root)

    assert not checks["provider_neutrality"].ok


def test_m3_exit_rejects_runtime_schema_mirror_drift(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    mirror = root / "src/slidethus/_schemas/planning_review_report.schema.json"
    mirror.write_text(mirror.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    checks = _check_map(root)

    assert not checks["runtime_schemas"].ok
    assert "mirror:planning_review_report.schema.json" in checks["runtime_schemas"].detail
