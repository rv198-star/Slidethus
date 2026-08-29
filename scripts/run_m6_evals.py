from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.distribution import prepared_renderer_root
from slidethus.io_utils import read_json

_WORKFLOWS = {"create", "rebuild", "improve", "audit", "revise", "extract_style"}


def _schema_errors(data: dict, schema_path: Path) -> list[str]:
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    return [
        f"{error.json_path}: {error.message}"
        for error in sorted(
            Draft202012Validator(schema).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]


def _selector_exists(root: Path, selector: str) -> bool:
    raw_path, function = selector.split("::", 1)
    path = root / raw_path
    if not path.is_file():
        return False
    return f"def {function}(" in path.read_text(encoding="utf-8", errors="replace")


def validate_corpus(root: Path) -> tuple[dict, dict, list[str]]:
    suite = read_json(root / "evals/m6/suite.json")
    compatibility = read_json(root / "docs/compatibility-matrix.json")
    errors = [
        *(f"suite:{item}" for item in _schema_errors(suite, root / "schemas/evaluation_suite.schema.json")),
        *(
            f"compatibility:{item}"
            for item in _schema_errors(
                compatibility,
                root / "schemas/compatibility_matrix.schema.json",
            )
        ),
    ]

    cases = list(suite.get("cases", []))
    case_ids = [str(item.get("case_id", "")) for item in cases]
    workflows = [str(item.get("workflow", "")) for item in cases]
    if len(case_ids) != len(set(case_ids)):
        errors.append("suite:duplicate case IDs")
    if set(workflows) != _WORKFLOWS or len(workflows) != len(_WORKFLOWS):
        errors.append("suite:must contain exactly one case for each product workflow")
    by_id = {str(item.get("case_id")): item for item in cases}
    for case in cases:
        case_id = str(case.get("case_id"))
        fixture = case.get("fixture", {})
        raw_path = fixture.get("path")
        if raw_path is not None:
            relative = Path(str(raw_path))
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"{case_id}:unsafe fixture path")
            elif not (root / relative).is_file():
                errors.append(f"{case_id}:missing fixture path {relative.as_posix()}")
        base_case = fixture.get("base_case")
        if base_case is not None:
            if base_case not in by_id:
                errors.append(f"{case_id}:unknown base case {base_case}")
            elif base_case == case_id:
                errors.append(f"{case_id}:cannot depend on itself")
        selector = str(case.get("pytest_selector", ""))
        if not _selector_exists(root, selector):
            errors.append(f"{case_id}:missing pytest selector {selector}")

    capability_names = [
        str(item.get("capability", "")) for item in compatibility.get("capabilities", [])
    ]
    platform_names = [
        str(item.get("platform", "")) for item in compatibility.get("platforms", [])
    ]
    if len(capability_names) != len(set(capability_names)):
        errors.append("compatibility:duplicate capability rows")
    if len(platform_names) != len(set(platform_names)):
        errors.append("compatibility:duplicate platform rows")
    if compatibility.get("release_baseline") != {
        "python": "3.11",
        "node": "22",
        "npm": "10",
    }:
        errors.append("compatibility:release baseline must match the frozen M6 baseline")
    return suite, compatibility, errors


def _renderer_for_production(root: Path) -> Path | None:
    prepared = prepared_renderer_root()
    if prepared is not None:
        return prepared
    repository = root / "renderers/pptxgenjs"
    if (repository / "node_modules/pptxgenjs/package.json").is_file():
        return repository
    return None


def run_tier(root: Path, suite: dict, tier: str) -> int:
    cases = list(suite["cases"])
    selected = (
        [item for item in cases if item["execution_tier"] == "quick"]
        if tier == "quick"
        else cases
    )
    selectors = [str(item["pytest_selector"]) for item in selected]
    env = os.environ.copy()
    if tier == "production":
        renderer = _renderer_for_production(root)
        if renderer is None:
            print(
                "FAIL production renderer is not prepared; run `slidethus plugin bootstrap-renderer` "
                "or install repository renderer dependencies before production evaluation",
                file=sys.stderr,
            )
            return 2
        env["SLIDETHUS_PPTXGENJS_TEST_ROOT"] = str(renderer)
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *selectors],
        cwd=root,
        env=env,
        check=False,
    )
    return process.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and execute the M6 workflow evaluation corpus")
    parser.add_argument("--tier", choices=["quick", "production"], default="quick")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)

    root = find_repository_root()
    suite, compatibility, errors = validate_corpus(root)
    if errors:
        for item in errors:
            print(f"FAIL {item}")
        return 1
    print(
        f"PASS corpus: {len(suite['cases'])} workflows; "
        f"{len(compatibility['capabilities'])} capability rows; "
        f"{len(compatibility['platforms'])} platform rows"
    )
    if args.validate_only:
        return 0
    selected = [
        item for item in suite["cases"]
        if args.tier == "production" or item["execution_tier"] == "quick"
    ]
    print(f"RUN tier={args.tier}: {len(selected)} case(s)")
    return run_tier(root, suite, args.tier)


if __name__ == "__main__":
    raise SystemExit(main())
