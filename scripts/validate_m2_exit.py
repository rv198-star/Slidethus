from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.io_utils import read_json
from slidethus.services.m2_application import evaluate_m2_workspace_gate
from slidethus.validation import validate_workspace


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


_REQUIRED_PATHS = (
    "plans/M2-ingestion-research-evidence.md",
    "plans/M2.2-multiformat-adapters.md",
    "plans/M2.3-research-planning-runtime.md",
    "plans/M2.4-evidence-engine.md",
    "plans/M2.5-evidence-binding-gap-rework.md",
    "plans/M2.6-application-capability-security.md",
    "plans/M2.7-m2-exit-gate.md",
    "scripts/validate_m2_exit.py",
    "tests/test_m2_exit.py",
    "audit/M2.1-round-1-open-issues.md",
    "audit/M2.1-round-2-scorecard.md",
    "audit/M2.1-BUILD_REPORT.md",
    "audit/M2.2-round-1-open-issues.md",
    "audit/M2.2-round-2-scorecard.md",
    "audit/M2.2-BUILD_REPORT.md",
    "audit/M2.3-round-1-open-issues.md",
    "audit/M2.3-round-2-scorecard.md",
    "audit/M2.3-BUILD_REPORT.md",
    "audit/M2.4-round-1-open-issues.md",
    "audit/M2.4-round-2-scorecard.md",
    "audit/M2.4-BUILD_REPORT.md",
    "audit/M2.5-round-1-open-issues.md",
    "audit/M2.5-round-2-scorecard.md",
    "audit/M2.5-BUILD_REPORT.md",
    "audit/M2.6-round-1-open-issues.md",
    "audit/M2.6-round-2-scorecard.md",
    "audit/M2.6-BUILD_REPORT.md",
    "audit/M2.7-round-1-open-issues.md",
    "audit/M2.7-round-2-scorecard.md",
    "audit/M2-BUILD_REPORT.md",
    "docs/adr/ADR-0009-immutable-ingestion-snapshots.md",
    "docs/adr/ADR-0010-safe-multiformat-source-adapters.md",
    "docs/adr/ADR-0011-resumable-research-runtime.md",
    "docs/adr/ADR-0012-deterministic-evidence-adjudication.md",
    "docs/adr/ADR-0013-block-evidence-gaps-and-rework.md",
    "docs/adr/ADR-0014-m2-application-capability-boundary.md",
    "schemas/source_snapshot.schema.json",
    "schemas/research_run.schema.json",
    "schemas/research_cache_snapshot.schema.json",
    "schemas/evidence_gap_report.schema.json",
    "schemas/m2_application_report.schema.json",
    "src/slidethus/services/source_ingestion.py",
    "src/slidethus/services/research.py",
    "src/slidethus/services/evidence.py",
    "src/slidethus/services/evidence_binding.py",
    "src/slidethus/services/m2_application.py",
    "src/slidethus/m2_application_reports.py",
    "tests/test_source_ingestion.py",
    "tests/test_multiformat_ingestion.py",
    "tests/test_research_runtime.py",
    "tests/test_evidence_engine.py",
    "tests/test_evidence_binding.py",
    "tests/test_m2_application.py",
)

_RUNTIME_SCHEMAS = (
    "source_snapshot.schema.json",
    "research_run.schema.json",
    "research_cache_snapshot.schema.json",
    "evidence_gap_report.schema.json",
    "m2_application_report.schema.json",
)


def _section(text: str, heading: str, next_heading: str) -> str:
    try:
        return text.split(heading, 1)[1].split(next_heading, 1)[0]
    except IndexError:
        return ""


def evaluate_m2_exit(root: Path) -> tuple[Check, ...]:
    """Evaluate repository-wide M2 completion contracts without modifying files."""

    root = root.resolve()
    checks: list[Check] = []

    missing = [relative for relative in _REQUIRED_PATHS if not (root / relative).is_file()]
    checks.append(
        Check(
            "required_evidence",
            not missing,
            "all M2 plans, audits, ADRs, runtime schemas, services, and tests are present"
            if not missing
            else "; ".join(missing),
        )
    )

    schema_errors: list[str] = []
    mirror_errors: list[str] = []
    for name in _RUNTIME_SCHEMAS:
        root_path = root / "schemas" / name
        packaged_path = root / "src/slidethus/_schemas" / name
        if not root_path.is_file() or not packaged_path.is_file():
            continue
        try:
            Draft202012Validator.check_schema(read_json(root_path))
        except Exception as exc:  # noqa: BLE001
            schema_errors.append(f"{name}: {exc}")
        if root_path.read_bytes() != packaged_path.read_bytes():
            mirror_errors.append(name)
    checks.append(
        Check(
            "runtime_schemas",
            not schema_errors and not mirror_errors,
            "all M2 runtime schemas are valid and packaged mirrors match"
            if not schema_errors and not mirror_errors
            else "; ".join([*schema_errors, *(f"mirror:{name}" for name in mirror_errors)]),
        )
    )

    master_plan = (root / "plans/M2-ingestion-research-evidence.md").read_text(
        encoding="utf-8", errors="replace"
    ) if (root / "plans/M2-ingestion-research-evidence.md").is_file() else ""
    plan_pending = re.findall(r"\| M2\.[1-7] \|[^\n]+\| (?:pending|in_progress) \|", master_plan)
    checks.append(
        Check(
            "master_plan_complete",
            not plan_pending and "六个 Submodule Gate" in master_plan and "M2 Exit Gate：PASS" in master_plan,
            "M2.1–M2.7 and the M2 Exit Gate are recorded complete"
            if not plan_pending and "M2 Exit Gate：PASS" in master_plan
            else "master M2 plan still contains incomplete state or lacks Exit PASS",
        )
    )

    tasks_text = (root / "TASKS.md").read_text(encoding="utf-8", errors="replace") if (root / "TASKS.md").is_file() else ""
    tasks_m2 = _section(tasks_text, "## M2 — Ingestion, Research, Evidence", "## M3 —")
    unchecked_tasks = re.findall(r"^- \[ \]", tasks_m2, re.MULTILINE)
    checks.append(
        Check(
            "tasks_m2_complete",
            bool(tasks_m2) and not unchecked_tasks and "Exit Gate：PASS" in tasks_m2,
            "TASKS.md records every M2 task and Exit Gate complete"
            if bool(tasks_m2) and not unchecked_tasks and "Exit Gate：PASS" in tasks_m2
            else "TASKS.md M2 section is missing, unchecked, or lacks Exit PASS",
        )
    )

    roadmap_text = (root / "docs/09-roadmap.md").read_text(encoding="utf-8", errors="replace") if (root / "docs/09-roadmap.md").is_file() else ""
    roadmap_m2 = _section(roadmap_text, "## v0.5 Planning Pipeline", "## v0.6 Rendering")
    unchecked_roadmap = re.findall(r"^- \[ \]", roadmap_m2, re.MULTILINE)
    checks.append(
        Check(
            "roadmap_m2_complete",
            bool(roadmap_m2) and not unchecked_roadmap and "Exit Gate：PASS" in roadmap_m2,
            "roadmap records M2 complete without widening M3"
            if bool(roadmap_m2) and not unchecked_roadmap and "Exit Gate：PASS" in roadmap_m2
            else "roadmap M2 section is missing, unchecked, or lacks Exit PASS",
        )
    )

    kickoff = (root / "CODEX_KICKOFF.md").read_text(encoding="utf-8", errors="replace") if (root / "CODEX_KICKOFF.md").is_file() else ""
    checks.append(
        Check(
            "kickoff_handoff",
            "M2 Exit Gate: PASS" in kickoff and "M3" in kickoff and "不要重做 M2" in kickoff,
            "Codex kickoff hands off from frozen M2 to M3"
            if "M2 Exit Gate: PASS" in kickoff and "不要重做 M2" in kickoff
            else "Codex kickoff still points at M2 or lacks frozen-M2 handoff",
        )
    )

    readme = (root / "README.md").read_text(encoding="utf-8", errors="replace") if (root / "README.md").is_file() else ""
    skill_contract = root / ".agents/skills/slidethus/references/shared-contract.md"
    skill = skill_contract.read_text(encoding="utf-8", errors="replace") if skill_contract.is_file() else ""
    checks.append(
        Check(
            "capability_truthfulness",
            "M2 Exit Gate：PASS" in readme
            and "不是生产级端到端 PPT 产品" in readme
            and "Research Result" in skill
            and "external-disclosure approval" in skill
            and "never generate or silently edit" in skill,
            "README and Skill preserve the frozen M2 boundary while allowing later milestones"
            if "M2 Exit Gate：PASS" in readme
            else "README/Skill M2 completion or non-goal wording is incomplete",
        )
    )

    protocols = (root / "src/slidethus/protocols.py").read_text(encoding="utf-8", errors="replace") if (root / "src/slidethus/protocols.py").is_file() else ""
    research = (root / "src/slidethus/services/research.py").read_text(encoding="utf-8", errors="replace") if (root / "src/slidethus/services/research.py").is_file() else ""
    application = (root / "src/slidethus/services/m2_application.py").read_text(encoding="utf-8", errors="replace") if (root / "src/slidethus/services/m2_application.py").is_file() else ""
    evidence = (root / "src/slidethus/services/evidence.py").read_text(encoding="utf-8", errors="replace") if (root / "src/slidethus/services/evidence.py").is_file() else ""
    application_reports = (root / "src/slidethus/m2_application_reports.py").read_text(encoding="utf-8", errors="replace") if (root / "src/slidethus/m2_application_reports.py").is_file() else ""
    gates = (root / "src/slidethus/gates.py").read_text(encoding="utf-8", errors="replace") if (root / "src/slidethus/gates.py").is_file() else ""
    cli = (root / "src/slidethus/cli.py").read_text(encoding="utf-8", errors="replace") if (root / "src/slidethus/cli.py").is_file() else ""
    m2_report_schema_text = (root / "schemas/m2_application_report.schema.json").read_text(encoding="utf-8", errors="replace") if (root / "schemas/m2_application_report.schema.json").is_file() else ""
    forbidden_network_import = re.compile(
        r"^\s*(?:from|import)\s+(?:requests|httpx|aiohttp|urllib\.request|boto3|googleapiclient)\b",
        re.MULTILINE,
    )
    checks.append(
        Check(
            "provider_neutrality",
            "class ResearchProvider(Protocol)" in protocols
            and not forbidden_network_import.search(research)
            and not forbidden_network_import.search(application)
            and "approve_external_disclosure" in application,
            "Research remains protocol-driven with explicit disclosure and no bundled network client"
            if "class ResearchProvider(Protocol)" in protocols
            and not forbidden_network_import.search(research)
            and not forbidden_network_import.search(application)
            else "provider-neutral or no-bundled-network contract drift",
        )
    )

    safety_markers = (
        "allow_high_risk_source_evidence" in evidence
        and "build_source_risks" in evidence
        and "high_risk_source_requires_qualification" in evidence
        and "reconcile_current_evidence" in evidence
        and "allow-high-risk-source-evidence" in cli
        and "citation policy requires at least one usable source-backed claim" in gates
        and "_snapshot_research_runs" in application
        and "research_runs" in m2_report_schema_text
        and "ensure_within" in application_reports
        and ".slidethus/m2/research-runs" in application_reports
    )
    checks.append(
        Check(
            "cross_module_safety_alignment",
            safety_markers,
            "direct Evidence paths, high-risk Research summaries, repair, G2 and archived Run lineage align"
            if safety_markers
            else "M2 cross-module high-risk/repair/report-lineage contract drift",
        )
    )

    example = root / "examples/minimal_project"
    if example.is_dir():
        validation = validate_workspace(example, check_hashes=True)
        gate = evaluate_m2_workspace_gate(example)
        example_ok = validation.ok and gate["status"] == "pass"
        detail = (
            "example workspace validates and current G1/G2/G5A pass"
            if example_ok
            else f"validation_ok={validation.ok}; gate={gate}"
        )
    else:
        example_ok = False
        detail = "examples/minimal_project is missing"
    checks.append(Check("example_m2_gate", example_ok, detail))

    round2_files = [
        root / f"audit/M2.{index}-round-2-scorecard.md" for index in range(1, 7)
    ]
    round2_files.append(root / "audit/M2.7-round-2-scorecard.md")
    audit_failures: list[str] = []
    for path in round2_files:
        if not path.is_file():
            audit_failures.append(path.name)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "PASS" not in text or not re.search(r"Critical open issues:\s*0", text, re.I):
            audit_failures.append(path.name)
        if not re.search(r"Major open issues:\s*0", text, re.I):
            audit_failures.append(path.name)
    checks.append(
        Check(
            "submodule_and_exit_audits",
            not audit_failures,
            "M2.1–M2.7 audits record zero open Critical/Major and PASS"
            if not audit_failures
            else "; ".join(sorted(set(audit_failures))),
        )
    )

    makefile = (root / "Makefile").read_text(encoding="utf-8", errors="replace") if (root / "Makefile").is_file() else ""
    package_audit = (root / "scripts/audit_package.py").read_text(encoding="utf-8", errors="replace") if (root / "scripts/audit_package.py").is_file() else ""
    checks.append(
        Check(
            "persistent_verification",
            "validate_m2_exit.py" in makefile
            and "validate_m2_exit.py" in package_audit
            and "M2-BUILD_REPORT.md" in package_audit,
            "make/package verification persist the M2 Exit Gate"
            if "validate_m2_exit.py" in makefile and "validate_m2_exit.py" in package_audit
            else "M2 Exit validation is not wired into persistent checks",
        )
    )

    return tuple(checks)


def main() -> int:
    root = find_repository_root()
    checks = evaluate_m2_exit(root)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(check.ok for check in checks)
    print(f"M2 EXIT: {passed}/{len(checks)} checks passed")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
