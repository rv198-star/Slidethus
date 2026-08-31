from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from slidethus import __version__
from slidethus.constants import find_repository_root

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_m6_exit.py"
_SPEC = importlib.util.spec_from_file_location("slidethus_validate_m6_exit", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"Cannot load M6 Exit validator: {_SCRIPT}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
evaluate_m6_exit = _MODULE.evaluate_m6_exit


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
    return {item.name: item for item in evaluate_m6_exit(root, run_runtime_checks=False)}


def test_repository_m6_exit_contract_is_truthfully_reopened() -> None:
    checks = evaluate_m6_exit(find_repository_root(), run_runtime_checks=False)

    assert checks
    by_name = {item.name: item for item in checks}
    assert not by_name["master_plan_complete"].ok
    assert not by_name["release_document_truth"].ok
    assert not by_name["release_audit_evidence"].ok


def test_m6_exit_rejects_version_drift(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            f'version = "{__version__}"', 'version = "99.0.0"', 1
        ),
        encoding="utf-8",
    )

    assert not _checks(root)["release_version_identity"].ok


def test_m6_exit_rejects_preview_systemic_blocker(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    synthesis = root / "audit/M6.6-round-6-synthesis.md"
    synthesis.write_text(
        synthesis.read_text(encoding="utf-8").replace(
            "open Major systemic candidates: `0`",
            "open Major systemic candidates: `1`",
            1,
        ),
        encoding="utf-8",
    )

    assert not _checks(root)["preview_hardening_converged"].ok


def test_m6_exit_rejects_stale_task_state(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    tasks = root / "TASKS.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8").replace(
            "- [x] **M6.6 v1.0 Preview Hardening & Release Gate**",
            "- [ ] **M6.6 v1.0 Preview Hardening & Release Gate**",
            1,
        ),
        encoding="utf-8",
    )

    assert not _checks(root)["release_document_truth"].ok


def test_m6_exit_preserves_semantic_provider_boundary(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace("SemanticReviewProvider", "BuiltInSemanticReview"),
        encoding="utf-8",
    )

    assert not _checks(root)["release_document_truth"].ok


def test_m6_exit_requires_persistent_verification(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    makefile = root / "Makefile"
    makefile.write_text(
        makefile.read_text(encoding="utf-8").replace(
            "verify: lint test validate m2-exit m3-exit m4-exit m5-exit m6-exit renderer-test audit",
            "verify: lint test validate m2-exit m3-exit m4-exit m5-exit renderer-test audit",
            1,
        ),
        encoding="utf-8",
    )

    assert not _checks(root)["persistent_verification"].ok
