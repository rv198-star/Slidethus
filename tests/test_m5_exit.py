from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from slidethus.constants import find_repository_root

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_m5_exit.py"
_SPEC = importlib.util.spec_from_file_location("slidethus_validate_m5_exit", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"Cannot load M5 Exit validator: {_SCRIPT}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
evaluate_m5_exit = _MODULE.evaluate_m5_exit


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
    return {item.name: item for item in evaluate_m5_exit(root, run_runtime_checks=False)}


def test_repository_m5_exit_contract_passes() -> None:
    checks = evaluate_m5_exit(find_repository_root())

    assert checks
    assert all(item.ok for item in checks), "\n".join(
        f"{item.name}: {item.detail}" for item in checks if not item.ok
    )


def test_m5_exit_rejects_schema_mirror_drift(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    mirror = root / "src/slidethus/_schemas/visual_review_report.schema.json"
    mirror.write_text(mirror.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    checks = _checks(root)

    assert not checks["runtime_schemas"].ok
    assert "mirror:visual_review_report.schema.json" in checks["runtime_schemas"].detail


def test_m5_exit_rejects_stale_task_state(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    tasks = root / "TASKS.md"
    text = tasks.read_text(encoding="utf-8").replace(
        "- [x] **M5.4 Full-page Visual Review**",
        "- [ ] **M5.4 Full-page Visual Review**",
        1,
    )
    tasks.write_text(text, encoding="utf-8")

    assert not _checks(root)["tasks_m5_complete"].ok


def test_m5_exit_rejects_missing_golden_source(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / "golden/m5/cases/management-decision/source.md").unlink()

    checks = _checks(root)

    assert not checks["required_evidence"].ok
    assert not checks["golden_corpus"].ok


def test_m5_exit_rejects_review_provider_contract_drift(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    protocols = root / "src/slidethus/protocols.py"
    protocols.write_text(
        protocols.read_text(encoding="utf-8").replace(
            "class SemanticReviewProvider(Protocol):",
            "class RemovedSemanticReviewProvider(Protocol):",
            1,
        ),
        encoding="utf-8",
    )

    assert not _checks(root)["review_repair_contract_alignment"].ok


def test_m5_exit_rejects_non_monotonic_gate_validation(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    gates = root / "src/slidethus/gates.py"
    gates.write_text(
        gates.read_text(encoding="utf-8").replace(
            "def _validation_issue_stage(",
            "def _removed_validation_issue_stage(",
            1,
        ),
        encoding="utf-8",
    )

    assert not _checks(root)["monotonic_gate_validation"].ok


def test_m5_exit_rejects_release_claim_without_capability_boundary(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace("capability boundary", "implicit success"),
        encoding="utf-8",
    )

    assert not _checks(root)["capability_truthfulness"].ok
