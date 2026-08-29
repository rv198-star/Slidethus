from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.distribution import build_plugin_bundle


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


_REQUIRED_PATHS = (
    "plans/M6-productization-distribution.md",
    "plans/M6.6-preview-hardening-root-fixes.md",
    "audit/M6.6-preview-hardening-handoff.md",
    "audit/M6.6-round-5-synthesis.md",
    "audit/M6.6-round-6-synthesis.md",
    "audit/M6-round-1-open-issues.md",
    "audit/M6-round-2-scorecard.md",
    "audit/M6-BUILD_REPORT.md",
    "docs/adr/ADR-0021-workflow-productization-boundary.md",
    "docs/adr/ADR-0022-workflow-operational-controls.md",
    "docs/adr/ADR-0023-plugin-and-renderer-distribution.md",
    "docs/adr/ADR-0024-evaluation-and-compatibility-corpus.md",
    "docs/adr/ADR-0025-license-rights-and-sbom-boundary.md",
    "docs/adr/ADR-0026-stage-ai-review-and-systemic-repair-promotion.md",
    "release/rights-policy.json",
    "scripts/validate_m6_3_distribution.py",
    "scripts/validate_m6_4_evaluation.py",
    "scripts/validate_m6_5_licenses.py",
    "scripts/validate_m6_exit.py",
    "tests/test_m6_exit.py",
)

_REGRESSION_VALIDATORS = (
    "validate_m2_exit.py",
    "validate_m3_exit.py",
    "validate_m4_exit.py",
    "validate_m5_exit.py",
    "validate_m6_3_distribution.py",
    "validate_m6_4_evaluation.py",
    "validate_m6_5_licenses.py",
)


def _read(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_validator(root: Path, name: str) -> Check:
    process = subprocess.run(
        [sys.executable, str(root / "scripts" / name)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    detail = (process.stdout + process.stderr).strip()
    return Check(
        name.removeprefix("validate_").removesuffix(".py") + "_regression",
        process.returncode == 0,
        detail.splitlines()[-1] if process.returncode == 0 and detail else detail[-4000:],
    )


def _formal_environment() -> tuple[Check, Check]:
    python_ok = sys.version_info[:2] == (3, 11)
    python = Check(
        "python_release_baseline",
        python_ok,
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        + (" is the frozen 3.11 baseline" if python_ok else " is not the frozen 3.11 baseline"),
    )
    node = shutil.which("node")
    if not node:
        return python, Check("node_release_baseline", False, "Node.js is unavailable")
    process = subprocess.run(
        [node, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    version = process.stdout.strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
    node_ok = process.returncode == 0 and match is not None and match.group(1) == "22"
    return python, Check(
        "node_release_baseline",
        node_ok,
        f"Node {version} is the frozen major-22 baseline"
        if node_ok
        else f"Node {version or 'unknown'} is not the frozen major-22 baseline",
    )


def _reproducible_plugin() -> Check:
    with tempfile.TemporaryDirectory(prefix="slidethus-m6-plugin-") as directory:
        root = Path(directory)
        first = build_plugin_bundle(root / "first.zip")
        second = build_plugin_bundle(root / "second.zip")
        ok = first.sha256 == second.sha256 and first.path.read_bytes() == second.path.read_bytes()
        return Check(
            "plugin_release_reproducible",
            ok,
            f"two Plugin builds are byte-identical at sha256={first.sha256}"
            if ok
            else "Plugin release bytes drift across identical builds",
        )


def _build_wheel(root: Path, output: Path) -> tuple[subprocess.CompletedProcess[str], Path | None]:
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = "315532800"
    pip = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    uv = shutil.which("uv")
    if pip.returncode == 0:
        command = [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(output),
        ]
    elif uv:
        command = [uv, "build", "--wheel", "--out-dir", str(output)]
        environment["UV_PYTHON"] = sys.executable
    else:
        return pip, None
    process = subprocess.run(
        command,
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    wheels = sorted(output.glob("slidethus-*.whl"))
    return process, wheels[0] if len(wheels) == 1 else None


def _reproducible_wheel(root: Path) -> Check:
    with tempfile.TemporaryDirectory(prefix="slidethus-m6-wheel-") as directory:
        temporary = Path(directory)
        first_process, first = _build_wheel(root, temporary / "first")
        second_process, second = _build_wheel(root, temporary / "second")
        if first_process.returncode or second_process.returncode or first is None or second is None:
            detail = (first_process.stdout + first_process.stderr + second_process.stdout + second_process.stderr).strip()
            return Check("wheel_release_reproducible", False, detail[-4000:])
        ok = first.name == second.name and first.read_bytes() == second.read_bytes()
        return Check(
            "wheel_release_reproducible",
            ok,
            f"two wheels are byte-identical at sha256={_sha256(first)}"
            if ok
            else f"wheel bytes drift: {_sha256(first)} != {_sha256(second)}",
        )


def evaluate_m6_exit(root: Path, *, run_runtime_checks: bool = True) -> tuple[Check, ...]:
    """Evaluate M6 completion and v1.0 release readiness without changing repository files."""

    root = root.resolve()
    checks: list[Check] = []

    missing = [relative for relative in _REQUIRED_PATHS if not (root / relative).is_file()]
    checks.append(
        Check(
            "required_evidence",
            not missing,
            "all M6 plans, ADRs, Preview syntheses, release audits, policies and validators are present"
            if not missing
            else "; ".join(missing),
        )
    )

    pyproject = tomllib.loads(_read(root, "pyproject.toml"))
    package_version = str(pyproject.get("project", {}).get("version", ""))
    runtime_match = re.search(r'^__version__\s*=\s*"([^"]+)"', _read(root, "src/slidethus/__init__.py"), re.M)
    runtime_version = runtime_match.group(1) if runtime_match else ""
    readme = _read(root, "README.md")
    version_ok = (
        package_version == "1.0.0"
        and runtime_version == "1.0.0"
        and "# Slidethus v1.0.0" in readme
        and "包版本：`1.0.0`" in readme
    )
    checks.append(
        Check(
            "release_version_identity",
            version_ok,
            "pyproject, runtime and README agree on v1.0.0"
            if version_ok
            else f"version drift: pyproject={package_version}, runtime={runtime_version}",
        )
    )

    synthesis = _read(root, "audit/M6.6-round-6-synthesis.md")
    preview_ok = (
        "SYN-E17A689D3096E148" in synthesis
        and "open Critical systemic candidates: `0`" in synthesis
        and "open Major systemic candidates: `0`" in synthesis
        and "explicitly case-local" in synthesis
        and "Minor and not promotion-eligible" in synthesis
        and "Do not open a seventh fix batch" in synthesis
    )
    checks.append(
        Check(
            "preview_hardening_converged",
            preview_ok,
            "Round 6 retrospective SYN has no Critical/Major systemic candidate and preserves case-local/Minor boundaries"
            if preview_ok
            else "Round 6 convergence evidence is missing or does not satisfy the hardening stop rule",
        )
    )

    plan = _read(root, "plans/M6-productization-distribution.md")
    root_plan = _read(root, "plans/M6.6-preview-hardening-root-fixes.md")
    plan_ok = (
        "| M6.6 |" in plan
        and "| complete" in plan.split("| M6.6 |", 1)[1].splitlines()[0]
        and "M6 Exit Gate：PASS" in plan
        and "| 8 | M6.6 final release gate" in root_plan
        and "| complete" in root_plan.split("| 8 | M6.6 final release gate", 1)[1].splitlines()[0]
    )
    checks.append(
        Check(
            "master_plan_complete",
            plan_ok,
            "M6.1–M6.6 and M6 Exit are recorded complete"
            if plan_ok
            else "M6 plans remain incomplete or lack an Exit PASS",
        )
    )

    tasks = _read(root, "TASKS.md")
    roadmap = _read(root, "docs/09-roadmap.md")
    docs_ok = (
        "- [x] **M6.6 v1.0 Preview Hardening & Release Gate**" in tasks
        and "M6 Exit Gate：PASS" in tasks
        and "- [x] M6.6 v1.0 Preview Hardening & Release Gate" in roadmap
        and "M6 Exit Gate：PASS" in roadmap
        and "v1.0 Release Gate：PASS" in readme
        and "SemanticReviewProvider" in readme
        and "capability boundary" in readme
    )
    checks.append(
        Check(
            "release_document_truth",
            docs_ok,
            "TASKS, roadmap and README agree on M6/v1.0 readiness without hiding the semantic-provider boundary"
            if docs_ok
            else "release documents are stale, inconsistent, or overclaim the semantic-review capability",
        )
    )

    round2 = _read(root, "audit/M6-round-2-scorecard.md")
    build_report = _read(root, "audit/M6-BUILD_REPORT.md")
    audit_ok = (
        re.search(r"Critical open issues:\s*0", round2, re.I) is not None
        and re.search(r"Major systemic open issues:\s*0", round2, re.I) is not None
        and "M6 Exit Gate: PASS" in round2
        and "M6 Exit Gate: PASS" in build_report
        and "Python 3.11" in build_report
        and "Node 22" in build_report
    )
    checks.append(
        Check(
            "release_audit_evidence",
            audit_ok,
            "Round B and build report record zero Critical/Major systemic blockers on the frozen baseline"
            if audit_ok
            else "M6 release audit evidence is incomplete",
        )
    )

    makefile = _read(root, "Makefile")
    package_audit = _read(root, "scripts/audit_package.py")
    persistent_ok = (
        "m6-exit:" in makefile
        and re.search(r"^verify:.*\bm6-exit\b", makefile, re.M) is not None
        and 'root / "scripts/validate_m6_exit.py"' in package_audit
        and 'root / "tests/test_m6_exit.py"' in package_audit
        and 'root / "audit/M6-BUILD_REPORT.md"' in package_audit
    )
    checks.append(
        Check(
            "persistent_verification",
            persistent_ok,
            "Makefile verify and Package Audit persist the M6 Exit Gate and final evidence"
            if persistent_ok
            else "M6 Exit is not persisted by Makefile verify and Package Audit",
        )
    )

    if run_runtime_checks:
        checks.extend(_formal_environment())
        checks.extend(_run_validator(root, name) for name in _REGRESSION_VALIDATORS)
        checks.append(_reproducible_plugin())
        checks.append(_reproducible_wheel(root))
    else:
        checks.extend(
            (
                Check("python_release_baseline", True, "runtime check skipped"),
                Check("node_release_baseline", True, "runtime check skipped"),
            )
        )

    return tuple(checks)


def main() -> int:
    checks = evaluate_m6_exit(find_repository_root())
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(check.ok for check in checks)
    print(f"M6 EXIT: {passed}/{len(checks)} checks passed")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
