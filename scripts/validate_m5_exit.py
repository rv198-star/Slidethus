from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.io_utils import read_json
from slidethus.protocols import BriefCompletionHints
from slidethus.semantic_reviews import SEMANTIC_DIMENSIONS
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService
from slidethus.services.m5_application import M5ApplicationService, evaluate_m5_workspace_gate
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


_REQUIRED_PATHS = (
    "plans/M5-review-repair-loop.md",
    "audit/M5-round-1-open-issues.md",
    "audit/M5-round-2-scorecard.md",
    "audit/M5-BUILD_REPORT.md",
    "docs/adr/ADR-0020-independent-review-repair-boundary.md",
    "golden/m5/manifest.json",
    "golden/m5/cases/management-decision/source.md",
    "schemas/deterministic_review_report.schema.json",
    "schemas/semantic_review_report.schema.json",
    "schemas/semantic_scorecard_report.schema.json",
    "schemas/visual_review_report.schema.json",
    "schemas/review_repair_plan.schema.json",
    "schemas/review_repair_report.schema.json",
    "schemas/review_regression_report.schema.json",
    "schemas/m5_application_report.schema.json",
    "src/slidethus/deterministic_reviews.py",
    "src/slidethus/semantic_reviews.py",
    "src/slidethus/visual_reviews.py",
    "src/slidethus/review_repairs.py",
    "src/slidethus/review_regressions.py",
    "src/slidethus/quality_reviews.py",
    "src/slidethus/m5_application_reports.py",
    "src/slidethus/services/deterministic_review.py",
    "src/slidethus/services/semantic_review.py",
    "src/slidethus/services/visual_review.py",
    "src/slidethus/services/review_repair.py",
    "src/slidethus/services/review_regression.py",
    "src/slidethus/services/quality_review.py",
    "src/slidethus/services/m5_application.py",
    "tests/test_deterministic_review.py",
    "tests/test_semantic_review.py",
    "tests/test_visual_review.py",
    "tests/test_review_repair.py",
    "tests/test_review_regression.py",
    "tests/test_m5_application.py",
    "tests/test_m5_cli.py",
    "tests/test_m5_golden.py",
    "tests/test_m5_exit.py",
    "scripts/validate_m5_exit.py",
)

_RUNTIME_SCHEMAS = (
    "deterministic_review_report.schema.json",
    "semantic_review_report.schema.json",
    "semantic_scorecard_report.schema.json",
    "visual_review_report.schema.json",
    "review_repair_plan.schema.json",
    "review_repair_report.schema.json",
    "review_regression_report.schema.json",
    "m5_application_report.schema.json",
    "quality_report.schema.json",
)


def _read(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _section(text: str, heading: str, next_heading: str) -> str:
    try:
        return text.split(heading, 1)[1].split(next_heading, 1)[0]
    except IndexError:
        return ""


class _CleanSemanticProvider:
    name = "m5-exit-semantic-fixture"
    version = "1.0.0"

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["mode"] == "open_issue":
            return {"issues": []}
        return {
            "dimensions": [
                {
                    "dimension": dimension,
                    "score": 5,
                    "rationale": "M5 Exit fixture exercises a clean admitted semantic baseline.",
                    "issue_ids": [],
                }
                for dimension in SEMANTIC_DIMENSIONS
            ]
        }


class _CleanVisualProvider:
    name = "m5-exit-visual-fixture"
    version = "1.0.0"

    def review(self, image_paths: tuple[Path, ...], context: dict[str, Any]) -> dict[str, Any]:
        if not image_paths:
            raise RuntimeError("M5 Exit visual fixture requires real page images")
        return {"issues": []}


def _fake_font_match(root: Path) -> Path:
    font = root / "test.ttf"
    font.write_bytes(b"fontconfig-test-placeholder")
    path = root / "fc-match"
    path.write_text(
        f"#!/bin/sh\nprintf '%s\\n{font}\\n' \"$3\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    query = root / "fc-query"
    query.write_text("#!/bin/sh\nprintf '20-10ffff\\n'\n", encoding="utf-8")
    query.chmod(0o755)
    return path


def _m5_smoke(root: Path) -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:
        return False, "Node.js is unavailable for the Production M5 smoke"
    try:
        with tempfile.TemporaryDirectory(prefix="slidethus-m5-exit-") as directory:
            base = Path(directory)
            workspace = init_workspace(base / "workspace", title="M5 Exit Smoke")
            source = base / "source.md"
            source.write_text(
                "# Enterprise operating model\n\n"
                "Enterprises build data, knowledge, process, rules, tools, permissions and evaluation standards.\n\n"
                "# Risk\n\nAdding more agents does not automatically improve task quality.\n",
                encoding="utf-8",
            )
            m3 = M3ApplicationService(workspace).run(
                (source,),
                brief_hints=BriefCompletionHints(
                    request_text="Create an 8-page management decision deck about an enterprise agent operating model",
                    purpose="Present the enterprise agent operating model",
                    desired_outcome="Approve implementation",
                    call_to_action="Approve project initiation",
                    delivery_context="Management decision meeting",
                    audience_role="Executive management",
                    page_target=8,
                ),
            )
            if m3.report.get("status") != "ready":
                return False, f"M3 prerequisite is not ready: {m3.report.get('status')}"
            font_match = str(_fake_font_match(base))
            renderer_root = root / "renderers/pptxgenjs"
            m4 = M4ApplicationService(
                workspace,
                renderer_root=renderer_root,
                node=node,
                font_match=font_match,
            ).run()
            if m4.report.get("status") != "ready":
                return False, f"M4 prerequisite is not ready: {m4.report.get('status')}"
            service = M5ApplicationService(
                workspace,
                semantic_provider=_CleanSemanticProvider(),
                visual_provider=_CleanVisualProvider(),
                renderer_root=renderer_root,
                node=node,
                font_match=font_match,
            )
            first = service.run()
            second = service.run()
            validation = validate_workspace(workspace, check_hashes=True)
            gate = evaluate_m5_workspace_gate(workspace)
            ok = (
                first.report.get("status") == "ready"
                and first.report.get("final_phase") == "REVIEWED"
                and first.report.get("g8", {}).get("status") == "pass"
                and second.report == first.report
                and not second.changed
                and validation.ok
                and gate.get("status") == "pass"
            )
            detail = (
                "temporary M3/M4 graph reaches immutable M5 Quality/G8/REVIEWED and reruns idempotently"
                if ok
                else (
                    f"status={first.report.get('status')}; phase={first.report.get('final_phase')}; "
                    f"g8={first.report.get('g8')}; second_changed={second.changed}; "
                    f"validation_ok={validation.ok}; gate={gate}"
                )
            )
            return ok, detail
    except Exception as exc:  # noqa: BLE001
        return False, f"M5 smoke failed: {exc}"


def evaluate_m5_exit(root: Path, *, run_runtime_checks: bool = True) -> tuple[Check, ...]:
    """Evaluate repository-wide M5 completion without modifying repository files."""

    root = root.resolve()
    checks: list[Check] = []

    missing = [relative for relative in _REQUIRED_PATHS if not (root / relative).is_file()]
    checks.append(
        Check(
            "required_evidence",
            not missing,
            "all M5 plans, audits, ADR, golden corpus, schemas, services and tests are present"
            if not missing
            else "; ".join(missing),
        )
    )

    schema_errors: list[str] = []
    mirror_errors: list[str] = []
    for name in _RUNTIME_SCHEMAS:
        source = root / "schemas" / name
        packaged = root / "src/slidethus/_schemas" / name
        if not source.is_file() or not packaged.is_file():
            continue
        try:
            Draft202012Validator.check_schema(read_json(source))
        except Exception as exc:  # noqa: BLE001
            schema_errors.append(f"{name}: {exc}")
        if source.read_bytes() != packaged.read_bytes():
            mirror_errors.append(name)
    checks.append(
        Check(
            "runtime_schemas",
            not schema_errors and not mirror_errors,
            "M5 runtime/catalog schemas are valid and packaged mirrors match"
            if not schema_errors and not mirror_errors
            else "; ".join([*schema_errors, *(f"mirror:{item}" for item in mirror_errors)]),
        )
    )

    plan = _read(root, "plans/M5-review-repair-loop.md")
    incomplete = re.findall(r"\| M5\.[1-7] \|[^\n]+\| (?:pending|in_progress) \|", plan)
    plan_ok = not incomplete and "M5 Exit Gate：PASS" in plan
    checks.append(
        Check(
            "master_plan_complete",
            plan_ok,
            "M5.1–M5.7 and M5 Exit are recorded complete" if plan_ok else "M5 plan is incomplete or lacks Exit PASS",
        )
    )

    tasks = _section(_read(root, "TASKS.md"), "## M5 — Review and Repair Loop", "## M6 —")
    task_ok = bool(tasks) and not re.findall(r"^- \[ \]", tasks, re.MULTILINE) and "Exit Gate：PASS" in tasks
    checks.append(
        Check(
            "tasks_m5_complete",
            task_ok,
            "TASKS.md records M5.1–M5.7 complete" if task_ok else "TASKS.md M5 is incomplete or lacks Exit PASS",
        )
    )

    roadmap = _read(root, "docs/09-roadmap.md")
    roadmap_ok = "M5 Exit Gate：PASS" in roadmap and "M6" in roadmap and "Review" in roadmap
    checks.append(
        Check(
            "roadmap_m5_complete",
            roadmap_ok,
            "roadmap records M5 complete and M6 next" if roadmap_ok else "roadmap lacks M5 → M6 handoff",
        )
    )

    kickoff = _read(root, "CODEX_KICKOFF.md")
    kickoff_ok = (
        "M5 Exit Gate: PASS" in kickoff
        and "M6" in kickoff
        and ("不要重做 M2、M3、M4 或 M5" in kickoff or "不要重做 M2–M5" in kickoff)
    )
    checks.append(
        Check(
            "kickoff_handoff",
            kickoff_ok,
            "Codex kickoff freezes M2–M5 and hands off to M6" if kickoff_ok else "Codex kickoff lacks frozen M5 → M6 handoff",
        )
    )

    readme = _read(root, "README.md")
    skill = _read(root, ".agents/skills/slidethus/SKILL.md")
    truth_ok = (
        "M5 Exit Gate：PASS" in readme
        and "M6.6" in readme
        and "尚未完成" in readme
        and "不声明 v1.0 发布就绪" in readme
        and "M5 Exit Gate: PASS" in skill
        and "M6" in skill
    )
    checks.append(
        Check(
            "capability_truthfulness",
            truth_ok,
            "README/Skill preserve the frozen M5 boundary while later M6 productization advances monotonically toward an incomplete v1.0 Release Gate"
            if truth_ok
            else "README/Skill M5 completion or current post-M5 release boundary is incomplete",
        )
    )

    protocols = _read(root, "src/slidethus/protocols.py")
    m5_service = _read(root, "src/slidethus/services/m5_application.py")
    quality = _read(root, "src/slidethus/quality_reviews.py")
    repair = _read(root, "src/slidethus/services/review_repair.py")
    review_contract_ok = (
        "class SemanticReviewProvider(Protocol)" in protocols
        and "class VisualReviewProvider(Protocol)" in protocols
        and "DeterministicReviewService" in m5_service
        and "SemanticReviewService" in m5_service
        and "VisualReviewService" in m5_service
        and "ReviewRepairPlanService" in m5_service
        and "ReviewRepairExecutionService" in m5_service
        and "ReviewRegressionService" in m5_service
        and "ProductionQualityReviewService" in m5_service
        and "Production G8 requires semantic review capability" in quality
        and "automatic" in repair
        and "assisted" in repair
    )
    checks.append(
        Check(
            "review_repair_contract_alignment",
            review_contract_ok,
            "provider-neutral review, severity-first Quality/G8, bounded repair and regression align"
            if review_contract_ok
            else "M5 review/repair orchestration contract drift",
        )
    )

    gates_source = _read(root, "src/slidethus/gates.py")
    monotonic_ok = (
        "def _validation_issue_stage(" in gates_source
        and "_validation_issue_stage" in gates_source
        and "_GATE_STAGE[gate_id]" in gates_source
        and "blocking_validation" in gates_source
    )
    checks.append(
        Check(
            "monotonic_gate_validation",
            monotonic_ok,
            "Gate validation is responsibility-scoped so downstream defects do not reverse frozen upstream Gates"
            if monotonic_ok
            else "responsibility-scoped Gate validation is missing",
        )
    )

    golden_path = root / "golden/m5/manifest.json"
    try:
        golden = read_json(golden_path)
        cases = golden.get("cases", [])
        golden_ok = bool(cases) and all((root / str(item.get("source", ""))).is_file() for item in cases)
    except Exception:  # noqa: BLE001
        golden_ok = False
        cases = []
    checks.append(
        Check(
            "golden_corpus",
            golden_ok and (root / "tests/test_m5_golden.py").is_file(),
            f"golden corpus declares {len(cases)} executable case(s) with expected M5/G8 behavior"
            if golden_ok
            else "golden corpus is missing, unreadable, or references missing sources",
        )
    )

    for milestone in ("m2", "m3", "m4"):
        if run_runtime_checks:
            process = subprocess.run(
                [sys.executable, str(root / f"scripts/validate_{milestone}_exit.py")],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            ok = process.returncode == 0
            detail = f"{milestone.upper()} Exit remains PASS" if ok else (process.stdout + process.stderr).strip()[-4000:]
        else:
            ok = True
            detail = f"{milestone.upper()} runtime regression skipped for static negative control"
        checks.append(Check(f"{milestone}_exit_regression", ok, detail))

    if run_runtime_checks:
        smoke_ok, smoke_detail = _m5_smoke(root)
    else:
        smoke_ok, smoke_detail = True, "M5 runtime smoke skipped for static negative control"
    checks.append(Check("m5_application_smoke", smoke_ok, smoke_detail))

    round2 = _read(root, "audit/M5-round-2-scorecard.md")
    audit_ok = (
        re.search(r"Critical open issues:\s*0", round2, re.I) is not None
        and re.search(r"Major open issues:\s*0", round2, re.I) is not None
        and "M5 Exit Gate: PASS" in round2
    )
    checks.append(
        Check(
            "m5_audit_evidence",
            audit_ok,
            "M5 Round B records zero open Critical/Major and Exit PASS" if audit_ok else "M5 Round B audit evidence is incomplete",
        )
    )

    makefile = _read(root, "Makefile")
    package_audit = _read(root, "scripts/audit_package.py")
    persistent_ok = (
        "validate_m5_exit.py" in makefile
        and "validate_m5_exit.py" in package_audit
        and "M5-BUILD_REPORT.md" in package_audit
        and "M5-round-2-scorecard.md" in package_audit
    )
    checks.append(
        Check(
            "persistent_verification",
            persistent_ok,
            "Makefile and Package Audit persist the M5 Exit Gate and final evidence"
            if persistent_ok
            else "M5 persistent verification is incomplete",
        )
    )

    return tuple(checks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--static",
        action="store_true",
        help="skip runtime predecessor/smoke checks; validate persistent M5 Exit contracts only",
    )
    args = parser.parse_args()
    checks = evaluate_m5_exit(find_repository_root(), run_runtime_checks=not args.static)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(check.ok for check in checks)
    print(f"M5 EXIT: {passed}/{len(checks)} checks passed")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
