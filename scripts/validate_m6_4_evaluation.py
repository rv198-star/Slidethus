from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.io_utils import read_json


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


_WORKFLOWS = {"create", "rebuild", "improve", "audit", "revise", "extract_style"}


def _schema(root: Path, name: str) -> dict[str, Any]:
    path = root / "schemas" / name
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def evaluate_m6_4(root: Path, *, run_quick: bool = True) -> tuple[Check, ...]:
    root = root.resolve()
    checks: list[Check] = []

    required = (
        "evals/m6/suite.json",
        "schemas/evaluation_suite.schema.json",
        "src/slidethus/_schemas/evaluation_suite.schema.json",
        "docs/compatibility-matrix.json",
        "schemas/compatibility_matrix.schema.json",
        "src/slidethus/_schemas/compatibility_matrix.schema.json",
        "examples/workflows/README.md",
        "examples/workflows/create/source.md",
        "docs/14-installation-and-workflows.md",
        "docs/15-evaluation-and-compatibility.md",
        "scripts/run_m6_evals.py",
    )
    missing = [item for item in required if not (root / item).is_file()]
    checks.append(
        Check(
            "required_evidence",
            not missing,
            "evaluation corpus, examples, compatibility matrix and docs are present"
            if not missing
            else "; ".join(missing),
        )
    )

    schema_errors: list[str] = []
    for name in ("evaluation_suite.schema.json", "compatibility_matrix.schema.json"):
        source = root / "schemas" / name
        mirror = root / "src/slidethus/_schemas" / name
        try:
            _schema(root, name)
        except Exception as exc:  # noqa: BLE001
            schema_errors.append(f"{name}: {exc}")
        if source.is_file() and mirror.is_file() and source.read_bytes() != mirror.read_bytes():
            schema_errors.append(f"mirror:{name}")
    checks.append(
        Check(
            "schema_mirrors",
            not schema_errors,
            "evaluation/compatibility schemas are valid and packaged mirrors match"
            if not schema_errors
            else "; ".join(schema_errors),
        )
    )

    try:
        suite = read_json(root / "evals/m6/suite.json")
        suite_errors = list(
            Draft202012Validator(_schema(root, "evaluation_suite.schema.json")).iter_errors(suite)
        )
    except Exception as exc:  # noqa: BLE001
        suite = {}
        suite_errors = [exc]
    cases = list(suite.get("cases", [])) if isinstance(suite, dict) else []
    workflows = {str(item.get("workflow")) for item in cases}
    case_ids = [str(item.get("case_id")) for item in cases]
    selectors_ok = True
    selector_errors: list[str] = []
    for case in cases:
        selector = str(case.get("pytest_selector", ""))
        path_part = selector.split("::", 1)[0]
        if not path_part or not (root / path_part).is_file():
            selectors_ok = False
            selector_errors.append(selector or str(case.get("case_id")))
    corpus_ok = (
        not suite_errors
        and workflows == _WORKFLOWS
        and len(case_ids) == len(set(case_ids)) == 6
        and selectors_ok
    )
    detail = (
        "six unique workflow cases cover Create/Rebuild/Improve/Audit/Revise/Extract Style with valid selectors"
        if corpus_ok
        else f"workflows={sorted(workflows)}; selectors={selector_errors}; schema_errors={len(suite_errors)}"
    )
    checks.append(Check("six_workflow_corpus", corpus_ok, detail))

    try:
        matrix = read_json(root / "docs/compatibility-matrix.json")
        matrix_errors = list(
            Draft202012Validator(_schema(root, "compatibility_matrix.schema.json")).iter_errors(matrix)
        )
    except Exception as exc:  # noqa: BLE001
        matrix = {}
        matrix_errors = [exc]
    capabilities = list(matrix.get("capabilities", [])) if isinstance(matrix, dict) else []
    platforms = list(matrix.get("platforms", [])) if isinstance(matrix, dict) else []
    matrix_ok = not matrix_errors and len(capabilities) >= 6 and len(platforms) >= 3
    checks.append(
        Check(
            "compatibility_matrix",
            matrix_ok,
            f"compatibility matrix records {len(capabilities)} capabilities and {len(platforms)} platform rows"
            if matrix_ok
            else f"matrix schema/errors={len(matrix_errors)} capabilities={len(capabilities)} platforms={len(platforms)}",
        )
    )

    docs = (root / "docs/15-evaluation-and-compatibility.md").read_text(encoding="utf-8") if (root / "docs/15-evaluation-and-compatibility.md").is_file() else ""
    docs_ok = "--tier quick" in docs and "--tier production" in docs and "bounded groups" in docs
    checks.append(
        Check(
            "evaluation_docs",
            docs_ok,
            "docs distinguish quick validation from bounded Production workflow evaluation"
            if docs_ok
            else "evaluation docs do not preserve quick/production execution boundaries",
        )
    )

    if run_quick:
        process = subprocess.run(
            [sys.executable, str(root / "scripts/run_m6_evals.py"), "--tier", "quick"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        quick_ok = process.returncode == 0
        quick_detail = "quick evaluation validates the full corpus and executes the offline quick case" if quick_ok else (process.stdout + process.stderr).strip()[-4000:]
    else:
        quick_ok = True
        quick_detail = "quick execution skipped for static negative control"
    checks.append(Check("quick_evaluation", quick_ok, quick_detail))

    return tuple(checks)


def main() -> int:
    checks = evaluate_m6_4(find_repository_root())
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(item.ok for item in checks)
    print(f"M6.4 EVALUATION: {passed}/{len(checks)} checks passed")
    return 0 if all(item.ok for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
