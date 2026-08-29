from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.io_utils import read_json
from slidethus.protocols import BriefCompletionHints
from slidethus.services.m3_application import (
    M3ApplicationService,
    evaluate_m3_workspace_gate,
)
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


_REQUIRED_PATHS = (
    "plans/M3-narrative-planning.md",
    "audit/M3-round-1-open-issues.md",
    "audit/M3-round-2-scorecard.md",
    "audit/M3-BUILD_REPORT.md",
    "docs/adr/ADR-0015-production-brief-completion.md",
    "docs/adr/ADR-0016-provider-neutral-production-planning-lineage.md",
    "docs/adr/ADR-0017-stable-sticky-notes-review-and-local-repair.md",
    "docs/adr/ADR-0018-m3-application-and-exit-boundary.md",
    "schemas/m3_application_report.schema.json",
    "schemas/planning_change_report.schema.json",
    "schemas/planning_review_report.schema.json",
    "schemas/planning_repair_report.schema.json",
    "src/slidethus/brief_completion.py",
    "src/slidethus/planning_limits.py",
    "src/slidethus/planning_lineage.py",
    "src/slidethus/planning_provider.py",
    "src/slidethus/planning_rules.py",
    "src/slidethus/planning_changes.py",
    "src/slidethus/planning_reviews.py",
    "src/slidethus/planning_repairs.py",
    "src/slidethus/services/brief_completion.py",
    "src/slidethus/services/narrative.py",
    "src/slidethus/services/outline.py",
    "src/slidethus/services/outline_changes.py",
    "src/slidethus/services/slide_specs.py",
    "src/slidethus/services/layout.py",
    "src/slidethus/services/planning_review.py",
    "src/slidethus/services/planning_repair.py",
    "src/slidethus/services/m3_application.py",
    "src/slidethus/m3_application_reports.py",
    "tests/test_brief_completion.py",
    "tests/test_narrative_planning.py",
    "tests/test_outline_planning.py",
    "tests/test_outline_changes.py",
    "tests/test_slide_spec_planning.py",
    "tests/test_layout_planning.py",
    "tests/test_planning_review.py",
    "tests/test_planning_repair.py",
    "tests/test_m3_application.py",
    "tests/test_m3_exit.py",
    "scripts/validate_m3_exit.py",
)

_RUNTIME_SCHEMAS = (
    "m3_application_report.schema.json",
    "planning_change_report.schema.json",
    "planning_review_report.schema.json",
    "planning_repair_report.schema.json",
)


def _section(text: str, heading: str, next_heading: str) -> str:
    try:
        return text.split(heading, 1)[1].split(next_heading, 1)[0]
    except IndexError:
        return ""


def _read(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _m3_smoke(root: Path) -> tuple[bool, str]:
    try:
        with tempfile.TemporaryDirectory(prefix="slidethus-m3-exit-") as directory:
            base = Path(directory)
            workspace = init_workspace(base / "workspace", title="M3 Exit Smoke")
            source = base / "source.md"
            source.write_text(
                "# Enterprise responsibility\n\n"
                "Enterprises should build data, knowledge, process, rules, tools, permissions and evaluation standards.\n\n"
                "# Risk\n\nAdding more agents does not automatically improve task quality.\n",
                encoding="utf-8",
            )
            result = M3ApplicationService(workspace).run(
                (source,),
                brief_hints=BriefCompletionHints(
                    request_text=(
                        "Create an 8-page decision presentation for management about an "
                        "enterprise agent operating model and request project approval"
                    )
                ),
            )
            validation = validate_workspace(workspace, check_hashes=True)
            gate = evaluate_m3_workspace_gate(workspace)
            ok = (
                result.report.get("status") == "ready"
                and result.report.get("planning_level") == "P5B"
                and validation.ok
                and gate.get("status") == "pass"
                and len(result.report.get("outputs", {}).get("wireframes", [])) >= 3
            )
            detail = (
                "temporary Production M3 run reaches reviewed P5B with valid wireframes"
                if ok
                else (
                    f"status={result.report.get('status')}; "
                    f"level={result.report.get('planning_level')}; "
                    f"validation_ok={validation.ok}; gate={gate}"
                )
            )
            return ok, detail
    except Exception as exc:  # noqa: BLE001
        return False, f"M3 smoke failed: {exc}"


def evaluate_m3_exit(
    root: Path,
    *,
    run_runtime_checks: bool = True,
) -> tuple[Check, ...]:
    """Evaluate repository-wide M3 completion without mutating the repository."""

    root = root.resolve()
    checks: list[Check] = []

    missing = [relative for relative in _REQUIRED_PATHS if not (root / relative).is_file()]
    checks.append(
        Check(
            "required_evidence",
            not missing,
            "all M3 plans, audits, ADRs, schemas, services and tests are present"
            if not missing
            else "; ".join(missing),
        )
    )

    schema_errors: list[str] = []
    mirror_errors: list[str] = []
    for name in _RUNTIME_SCHEMAS:
        root_path = root / "schemas" / name
        packaged = root / "src/slidethus/_schemas" / name
        if not root_path.is_file() or not packaged.is_file():
            continue
        try:
            Draft202012Validator.check_schema(read_json(root_path))
        except Exception as exc:  # noqa: BLE001
            schema_errors.append(f"{name}: {exc}")
        if root_path.read_bytes() != packaged.read_bytes():
            mirror_errors.append(name)
    checks.append(
        Check(
            "runtime_schemas",
            not schema_errors and not mirror_errors,
            "all M3 runtime schemas are valid and packaged mirrors match"
            if not schema_errors and not mirror_errors
            else "; ".join([*schema_errors, *(f"mirror:{item}" for item in mirror_errors)]),
        )
    )

    plan = _read(root, "plans/M3-narrative-planning.md")
    incomplete_plan = re.findall(
        r"\| M3\.[1-7] \|[^\n]+\| (?:pending|in_progress) \|",
        plan,
    )
    checks.append(
        Check(
            "master_plan_complete",
            not incomplete_plan and "M3 Exit Gate：PASS" in plan,
            "M3.1–M3.7 and the M3 Exit Gate are recorded complete"
            if not incomplete_plan and "M3 Exit Gate：PASS" in plan
            else "M3 plan contains incomplete state or lacks Exit PASS",
        )
    )

    tasks = _read(root, "TASKS.md")
    tasks_m3 = _section(tasks, "## M3 — Narrative and Planning", "## M4 —")
    checks.append(
        Check(
            "tasks_m3_complete",
            bool(tasks_m3)
            and not re.findall(r"^- \[ \]", tasks_m3, re.MULTILINE)
            and "Exit Gate：PASS" in tasks_m3,
            "TASKS.md records every M3 task and Exit Gate complete"
            if bool(tasks_m3)
            and not re.findall(r"^- \[ \]", tasks_m3, re.MULTILINE)
            and "Exit Gate：PASS" in tasks_m3
            else "TASKS.md M3 section is incomplete or lacks Exit PASS",
        )
    )

    roadmap = _read(root, "docs/09-roadmap.md")
    roadmap_ok = (
        "M3 Exit Gate：PASS" in roadmap
        and "M4" in roadmap
        and "Narrative" in roadmap
        and "Planning" in roadmap
    )
    checks.append(
        Check(
            "roadmap_m3_complete",
            roadmap_ok,
            "roadmap records Production M3 complete and M4 next"
            if roadmap_ok
            else "roadmap does not record M3 Exit PASS and M4 handoff",
        )
    )

    kickoff = _read(root, "CODEX_KICKOFF.md")
    kickoff_ok = (
        "M3 Exit Gate: PASS" in kickoff
        and any(
            marker in kickoff
            for marker in (
                "M4 Exit Gate: PASS",
                "M5 Exit Gate: PASS",
                "M6 Productization and Distribution",
                "M4 Rendering Backends",
            )
        )
        and any(
            marker in kickoff
            for marker in (
                "不要重做 M2 或 M3",
                "不要重做 M2、M3 或 M4",
                "不要重做 M2、M3、M4 或 M5",
                "不要重做 M2–M5",
            )
        )
    )
    checks.append(
        Check(
            "kickoff_handoff",
            kickoff_ok,
            "Codex kickoff preserves the frozen M3 boundary and advances monotonically"
            if kickoff_ok
            else "Codex kickoff loses the frozen M3 boundary or forward handoff",
        )
    )

    readme = _read(root, "README.md")
    skill = _read(root, ".agents/skills/slidethus/SKILL.md")
    truth_ok = (
        "M3 Exit Gate：PASS" in readme
        and "不是生产级端到端 PPT 产品" in readme
        and "M4" in readme
        and "M3 Exit Gate: PASS" in skill
        and "PlanningProvider" in skill
        and "Research Result" in skill
    )
    checks.append(
        Check(
            "capability_truthfulness",
            truth_ok,
            "README and Skill declare M3 planning complete while preserving M4–M5 limits"
            if truth_ok
            else "README/Skill M3 completion or non-goal wording is incomplete",
        )
    )

    protocols = _read(root, "src/slidethus/protocols.py")
    provider = _read(root, "src/slidethus/planning_provider.py")
    application = _read(root, "src/slidethus/services/m3_application.py")
    forbidden_import = re.compile(
        r"^\s*(?:from|import)\s+(?:openai|anthropic|google\.generativeai|requests|httpx|aiohttp|urllib\.request)\b",
        re.MULTILINE,
    )
    provider_ok = (
        "class PlanningProvider(Protocol)" in protocols
        and "class DeterministicPlanningProvider" in provider
        and not forbidden_import.search(provider)
        and not forbidden_import.search(application)
    )
    checks.append(
        Check(
            "provider_neutrality",
            provider_ok,
            "Planning remains protocol-driven with no bundled model/network client"
            if provider_ok
            else "Planning provider neutrality or no-bundled-client contract drift",
        )
    )

    alignment_files = {
        "lineage": _read(root, "src/slidethus/planning_lineage.py"),
        "changes": _read(root, "src/slidethus/planning_changes.py"),
        "reviews": _read(root, "src/slidethus/planning_reviews.py"),
        "repairs": _read(root, "src/slidethus/planning_repairs.py"),
        "app_reports": _read(root, "src/slidethus/m3_application_reports.py"),
        "gates": _read(root, "src/slidethus/gates.py"),
    }
    alignment_ok = (
        "planning_lineage_reference_errors" in alignment_files["lineage"]
        and "idempotency key was already used" in _read(
            root, "src/slidethus/services/outline_changes.py"
        )
        and "planning_review_reference_errors" in alignment_files["reviews"]
        and "planning_provider" in alignment_files["repairs"]
        and "ready M3 report Planning Review does not bind" in alignment_files["app_reports"]
        and "layout_gate_reasons" in alignment_files["gates"]
    )
    checks.append(
        Check(
            "planning_contract_alignment",
            alignment_ok,
            "lineage, sticky-note operations, review, repair, reports and Gates align"
            if alignment_ok
            else "M3 cross-module planning contract drift",
        )
    )

    if run_runtime_checks:
        process = subprocess.run(
            [sys.executable, str(root / "scripts/validate_m2_exit.py")],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        m2_ok = process.returncode == 0
        m2_detail = (
            "M2 Exit Gate remains PASS"
            if m2_ok
            else (process.stdout + process.stderr).strip()[-4000:]
        )
    else:
        m2_ok = True
        m2_detail = "runtime M2 regression skipped for static negative control"
    checks.append(Check("m2_exit_regression", m2_ok, m2_detail))

    if run_runtime_checks:
        smoke_ok, smoke_detail = _m3_smoke(root)
    else:
        smoke_ok, smoke_detail = True, "runtime M3 smoke skipped for static negative control"
    checks.append(Check("m3_application_smoke", smoke_ok, smoke_detail))

    round2 = root / "audit/M3-round-2-scorecard.md"
    round2_text = _read(root, "audit/M3-round-2-scorecard.md")
    audit_ok = (
        round2.is_file()
        and re.search(r"Critical open issues:\s*0", round2_text, re.I) is not None
        and re.search(r"Major open issues:\s*0", round2_text, re.I) is not None
        and "M3 Exit Gate: PASS" in round2_text
    )
    checks.append(
        Check(
            "m3_audit_evidence",
            audit_ok,
            "M3 Round B records zero open Critical/Major and Exit PASS"
            if audit_ok
            else "M3 Round B audit evidence is missing or incomplete",
        )
    )

    makefile = _read(root, "Makefile")
    package_audit = _read(root, "scripts/audit_package.py")
    persistent_ok = (
        "validate_m3_exit.py" in makefile
        and "validate_m3_exit.py" in package_audit
        and "M3-BUILD_REPORT.md" in package_audit
    )
    checks.append(
        Check(
            "persistent_verification",
            persistent_ok,
            "Makefile and package audit persist the M3 Exit Gate"
            if persistent_ok
            else "M3 Exit validation is not wired into persistent checks",
        )
    )

    return tuple(checks)


def main() -> int:
    root = find_repository_root()
    checks = evaluate_m3_exit(root)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(check.ok for check in checks)
    print(f"M3 EXIT: {passed}/{len(checks)} checks passed")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
