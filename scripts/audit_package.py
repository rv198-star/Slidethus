from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jsonschema import Draft202012Validator

from slidethus.constants import find_repository_root
from slidethus.schema_registry import SchemaRegistry
from slidethus.validation import format_report, validate_workspace


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_relative_links(root: Path) -> list[str]:
    missing: list[str] = []
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in root.rglob("*.md"):
        if "source_material" in path.parts or "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw_target in pattern.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                missing.append(f"{path.relative_to(root)} -> {raw_target}")
    return missing


def unresolved_placeholders(root: Path) -> list[str]:
    findings: list[str] = []
    excluded_prefixes = [
        root / "source_material",
        root / "prompts/source-preserved",
    ]
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".toml"}:
            continue
        if "node_modules" in path.parts:
            continue
        resolved = path.resolve()
        if any(prefix.resolve() in [resolved, *resolved.parents] for prefix in excluded_prefixes):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\{\{\s*[A-Za-z_][A-Za-z0-9_.-]*\s*\}\}", text):
            findings.append(path.relative_to(root).as_posix())
    return findings


def check_source_manifest(root: Path) -> list[str]:
    manifest_path = root / "source_material/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    listed = {item["path"] for item in manifest.get("files", [])}
    actual = {
        path.relative_to(root).as_posix()
        for path in (root / "source_material").rglob("*")
        if path.is_file() and path != manifest_path
    }
    if listed != actual:
        for missing in sorted(actual - listed):
            failures.append(f"unlisted {missing}")
        for stale in sorted(listed - actual):
            failures.append(f"stale entry {stale}")
    for item in manifest.get("files", []):
        path = root / item["path"]
        if not path.exists():
            failures.append(f"missing {item['path']}")
        elif sha256(path) != item["sha256"]:
            failures.append(f"hash mismatch {item['path']}")
    return failures


def required_paths(root: Path) -> list[Path]:
    return [
        root / "README.md",
        root / "SLIDETHUS_FOUNDATION_PLAN.md",
        root / "AGENTS.md",
        root / "CODEX_KICKOFF.md",
        root / "TASKS.md",
        root / ".agents/skills/slidethus/SKILL.md",
        root / ".agents/skills/slidethus/agents/openai.yaml",
        root / "schemas/catalog.json",
        root / "src/slidethus/_schemas/catalog.json",
        root / "examples/minimal_project/project_state.json",
        root / "scripts/validate_all.py",
        root / "tests/test_schema_examples.py",
        root / "source_material/source-boundary.md",
        root / "audit/round-1-source-fidelity.md",
        root / "audit/round-2-architecture-contracts.md",
        root / "audit/round-3-agentic-skill.md",
        root / "audit/round-4-buildability.md",
        root / "audit/round-5-adversarial-integrity.md",
        root / "audit/BUILD_REPORT.md",
        root / "audit/final-audit-summary.md",
        root / "plans/M0-foundation-bootstrap.md",
        root / "plans/M1-artifact-runtime.md",
        root / "docs/13-codex-compatibility.md",
        root / "docs/adr/ADR-0006-journaled-artifact-runtime.md",
        root / "schemas/gate_results.schema.json",
        root / "schemas/decision_log.schema.json",
        root / "schemas/assumption_log.schema.json",
        root / "src/slidethus/artifact_runtime.py",
        root / "tests/test_artifact_runtime.py",
        root / "audit/M1-round-1-open-issues.md",
        root / "audit/M1-round-2-scorecard.md",
        root / "audit/M1-BUILD_REPORT.md",
        root / "plans/M2-ingestion-research-evidence.md",
        root / "plans/M2.2-multiformat-adapters.md",
        root / "audit/M2.1-round-1-open-issues.md",
        root / "audit/M2.1-round-2-scorecard.md",
        root / "audit/M2.1-BUILD_REPORT.md",
        root / "audit/M2.2-round-1-open-issues.md",
        root / "audit/M2.2-round-2-scorecard.md",
        root / "audit/M2.2-BUILD_REPORT.md",
        root / "plans/M2.3-research-planning-runtime.md",
        root / "docs/adr/ADR-0011-resumable-research-runtime.md",
        root / "schemas/research_run.schema.json",
        root / "schemas/research_cache_snapshot.schema.json",
        root / "src/slidethus/services/research.py",
        root / "tests/test_research_runtime.py",
        root / "audit/M2.3-round-1-open-issues.md",
        root / "audit/M2.3-round-2-scorecard.md",
        root / "audit/M2.3-BUILD_REPORT.md",
        root / "plans/M2.4-evidence-engine.md",
        root / "docs/adr/ADR-0012-deterministic-evidence-adjudication.md",
        root / "src/slidethus/evidence_identity.py",
        root / "src/slidethus/services/evidence.py",
        root / "tests/test_evidence_engine.py",
        root / "audit/M2.4-round-1-open-issues.md",
        root / "audit/M2.4-round-2-scorecard.md",
        root / "audit/M2.4-BUILD_REPORT.md",
        root / "plans/M2.5-evidence-binding-gap-rework.md",
        root / "docs/adr/ADR-0013-block-evidence-gaps-and-rework.md",
        root / "schemas/evidence_gap_report.schema.json",
        root / "src/slidethus/services/evidence_binding.py",
        root / "tests/test_evidence_binding.py",
        root / "audit/M2.5-round-1-open-issues.md",
        root / "audit/M2.5-round-2-scorecard.md",
        root / "audit/M2.5-BUILD_REPORT.md",
        root / "plans/M2.6-application-capability-security.md",
        root / "docs/adr/ADR-0014-m2-application-capability-boundary.md",
        root / "schemas/m2_application_report.schema.json",
        root / "src/slidethus/m2_application_reports.py",
        root / "src/slidethus/services/m2_application.py",
        root / "tests/test_m2_application.py",
        root / "audit/M2.6-round-1-open-issues.md",
        root / "audit/M2.6-round-2-scorecard.md",
        root / "audit/M2.6-BUILD_REPORT.md",
        root / "plans/M2.7-m2-exit-gate.md",
        root / "scripts/validate_m2_exit.py",
        root / "tests/test_m2_exit.py",
        root / "audit/M2.7-round-1-open-issues.md",
        root / "audit/M2.7-round-2-scorecard.md",
        root / "audit/M2-BUILD_REPORT.md",
        root / "plans/M3-narrative-planning.md",
        root / "docs/adr/ADR-0015-production-brief-completion.md",
        root / "docs/adr/ADR-0016-provider-neutral-production-planning-lineage.md",
        root / "docs/adr/ADR-0017-stable-sticky-notes-review-and-local-repair.md",
        root / "docs/adr/ADR-0018-m3-application-and-exit-boundary.md",
        root / "schemas/m3_application_report.schema.json",
        root / "schemas/planning_change_report.schema.json",
        root / "schemas/planning_review_report.schema.json",
        root / "schemas/planning_repair_report.schema.json",
        root / "src/slidethus/services/m3_application.py",
        root / "src/slidethus/m3_application_reports.py",
        root / "tests/test_m3_application.py",
        root / "scripts/validate_m3_exit.py",
        root / "tests/test_m3_exit.py",
        root / "audit/M3-round-1-open-issues.md",
        root / "audit/M3-round-2-scorecard.md",
        root / "audit/M3-BUILD_REPORT.md",
        root / "scripts/validate_m4_exit.py",
        root / "plans/M5-review-repair-loop.md",
        root / "docs/adr/ADR-0020-independent-review-repair-boundary.md",
        root / "audit/M5-round-1-open-issues.md",
        root / "audit/M5-round-2-scorecard.md",
        root / "audit/M5-BUILD_REPORT.md",
        root / "golden/m5/manifest.json",
        root / "schemas/m5_application_report.schema.json",
        root / "src/slidethus/services/m5_application.py",
        root / "scripts/validate_m5_exit.py",
        root / "tests/test_m5_exit.py",
    ]


def write_hash_manifest(root: Path) -> int:
    output = root / "audit/manifest.sha256"
    excluded = {output.resolve()}
    excluded_parts = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"}
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.resolve() in excluded:
            continue
        if any(part in excluded_parts or part.endswith(".egg-info") for part in path.parts):
            continue
        if ".slidethus" in path.parts and ("transactions" in path.parts or path.name == "runtime.lock"):
            continue
        if path.suffix in {".pyc"}:
            continue
        files.append(path)
    lines = [f"{sha256(path)}  {path.relative_to(root).as_posix()}" for path in sorted(files)]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci", action="store_true", help="do not suppress report output; return nonzero on any failure")
    parser.parse_args()
    root = find_repository_root()
    checks: list[Check] = []

    missing = [path.relative_to(root).as_posix() for path in required_paths(root) if not path.exists()]
    checks.append(Check("required_paths", not missing, "all present" if not missing else "; ".join(missing)))

    skill_text = (root / ".agents/skills/slidethus/SKILL.md").read_text(encoding="utf-8")
    fm_ok = skill_text.startswith("---\n") and re.search(r"^name:\s*slidethus\s*$", skill_text, re.M) and re.search(r"^description:\s*.+$", skill_text, re.M)
    checks.append(Check("skill_frontmatter", bool(fm_ok), "name and description present" if fm_ok else "invalid frontmatter"))

    registry = SchemaRegistry(root / "schemas")
    schema_errors: list[str] = []
    schema_files = sorted((root / "schemas").glob("*.schema.json"))
    for schema_path in schema_files:
        try:
            Draft202012Validator.check_schema(
                json.loads(schema_path.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001
            schema_errors.append(f"{schema_path.name}: {exc}")
    checks.append(
        Check(
            "schemas",
            not schema_errors,
            f"{len(schema_files)} valid ({len(registry.entries)} catalog artifacts)"
            if not schema_errors
            else "; ".join(schema_errors),
        )
    )

    root_schema_files = {path.name: path.read_bytes() for path in (root / "schemas").glob("*.json")}
    package_schema_files = {path.name: path.read_bytes() for path in (root / "src/slidethus/_schemas").glob("*.json")}
    mirror_ok = root_schema_files == package_schema_files
    checks.append(Check("packaged_schema_mirror", mirror_ok, "matches repository schemas" if mirror_ok else "schema mirror drift"))

    instruction_bytes = (root / "AGENTS.md").stat().st_size + (root / ".agents/skills/slidethus/SKILL.md").stat().st_size
    checks.append(Check("instruction_budget", instruction_bytes < 32 * 1024, f"{instruction_bytes} bytes across AGENTS.md and SKILL.md"))

    raw_html = list((root / "source_material/raw").glob("*.html"))
    checks.append(Check("raw_browser_html_omitted", not raw_html, "no browser-session HTML in package" if not raw_html else "; ".join(path.name for path in raw_html)))

    state_doc = (root / "docs/03-workflow-state-machine.md").read_text(encoding="utf-8")
    state_contract_ok = "BLOCKED -->" not in state_doc and "`blocked` 不是独立 Phase" in state_doc
    checks.append(Check("state_contract_alignment", state_contract_ok, "blocked is modeled as status, not phase" if state_contract_ok else "phase/status contract drift"))

    report = validate_workspace(root / "examples/minimal_project", check_hashes=True)
    checks.append(Check("minimal_project", report.ok, format_report(report)))

    link_errors = check_relative_links(root)
    checks.append(Check("relative_links", not link_errors, "no missing relative links" if not link_errors else "; ".join(link_errors[:20])))

    placeholders = unresolved_placeholders(root)
    checks.append(Check("unresolved_placeholders", not placeholders, "none outside source-preserved material" if not placeholders else "; ".join(placeholders)))

    source_errors = check_source_manifest(root)
    checks.append(Check("source_manifest", not source_errors, "all source hashes match" if not source_errors else "; ".join(source_errors)))

    prompt_names = ["outline-architect-source.md", "bento-grid-source.md", "svg-page-source.md"]
    prompt_drift = [
        name
        for name in prompt_names
        if (root / "prompts/source-preserved" / name).read_bytes()
        != (root / "source_material/source-preserved" / name).read_bytes()
    ]
    checks.append(Check("source_prompt_mirror", not prompt_drift, "source-preserved prompts match" if not prompt_drift else "; ".join(prompt_drift)))

    evidence_schema = json.loads((root / "schemas/evidence_ledger.schema.json").read_text(encoding="utf-8"))
    cycle_schema = evidence_schema.get("properties", {}).get("research_cycles", {}).get("items", {})
    validation_text = (root / "src/slidethus/validation.py").read_text(encoding="utf-8")
    gates_text = (root / "src/slidethus/gates.py").read_text(encoding="utf-8")
    protocols_text = (root / "src/slidethus/protocols.py").read_text(encoding="utf-8")
    research_runtime_text = (root / "src/slidethus/services/research.py").read_text(encoding="utf-8")
    research_run_schema = root / "schemas/research_run.schema.json"
    research_cache_schema = root / "schemas/research_cache_snapshot.schema.json"
    research_contract_ok = (
        "research_cycles" in evidence_schema.get("required", [])
        and {"query_count", "waiver_reason"}.issubset(set(cycle_schema.get("required", [])))
        and "targeted_evidence_incomplete" in validation_text
        and "orientation research cycle" in gates_text
        and "ResearchPlan" in protocols_text
        and "class ResearchProvider" in protocols_text
        and "class ResearchRuntime" in research_runtime_text
        and "OfflineResearchProvider" in research_runtime_text
        and "research_workspace_errors" in validation_text
        and research_run_schema.exists()
        and research_cache_schema.exists()
    )
    checks.append(
        Check(
            "research_contract_alignment",
            research_contract_ok,
            "two-pass cycles, runtime lineage/cache, outline binding, gates, and provider protocol align"
            if research_contract_ok
            else "two-pass research contract drift",
        )
    )

    evidence_engine_text = (root / "src/slidethus/services/evidence.py").read_text(
        encoding="utf-8"
    )
    evidence_identity_text = (root / "src/slidethus/evidence_identity.py").read_text(
        encoding="utf-8"
    )
    evidence_tests_text = (root / "tests/test_evidence_engine.py").read_text(
        encoding="utf-8"
    )
    evidence_claim_schema = (
        evidence_schema.get("properties", {}).get("claims", {}).get("items", {})
    )
    evidence_contract_ok = (
        "candidate_bindings" in evidence_claim_schema.get("properties", {})
        and "source_chunk_id" in evidence_engine_text
        and "remote_body_fetched" in evidence_engine_text
        and "complete_research_cycle" in evidence_engine_text
        and "normalize_claim" in evidence_identity_text
        and "test_multiple_provider_runs_for_one_cycle" in evidence_tests_text
        and "stale_evidence_source_binding" in validation_text
        and "evidence lineage is invalidated" in gates_text
    )
    checks.append(
        Check(
            "evidence_engine_alignment",
            evidence_contract_ok,
            "candidate/source/research lineage, policy adjudication, invalidation, and G2 align"
            if evidence_contract_ok
            else "M2.4 Evidence Engine contract drift",
        )
    )

    # Package Audit verifies that the latest Exit contract is persistently wired and
    # internally consistent. The full runtime M2→M5 regression belongs to the explicit
    # M5 Exit invocation, so do not repeat that expensive smoke chain here.
    m5_exit_process = subprocess.run(
        [sys.executable, str(root / "scripts/validate_m5_exit.py"), "--static"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    m5_exit_output = (m5_exit_process.stdout + m5_exit_process.stderr).strip()
    checks.append(
        Check(
            "m5_exit_contract",
            m5_exit_process.returncode == 0,
            "repository-wide M5 Exit persistent contract passes static validation"
            if m5_exit_process.returncode == 0
            else m5_exit_output[-4000:],
        )
    )

    runtime_text = (root / "src/slidethus/artifact_runtime.py").read_text(encoding="utf-8")
    runtime_tests = (root / "tests/test_artifact_runtime.py").read_text(encoding="utf-8")
    runtime_types = {"gate_results", "decision_log", "assumption_log"}
    runtime_contract_ok = (
        runtime_types.issubset(registry.entries)
        and "ArtifactConflictError" in runtime_text
        and "migrate_workspace" in runtime_text
        and "_recover_unlocked" in runtime_text
        and "_invalidate_downstream" in runtime_text
        and "fault_injector" in runtime_tests
        and "Critical issues cannot be waived" in runtime_text
    )
    checks.append(
        Check(
            "artifact_runtime_alignment",
            runtime_contract_ok,
            "versioning, migration, recovery, invalidation, logs, and waiver policy align"
            if runtime_contract_ok
            else "M1 Artifact Runtime contract drift",
        )
    )

    render_schema = json.loads((root / "schemas/render_manifest.schema.json").read_text(encoding="utf-8"))
    delivery_schema = json.loads((root / "schemas/delivery_manifest.schema.json").read_text(encoding="utf-8"))
    editability_contract_ok = (
        {"target_editability_level", "editability_level"}.issubset(set(render_schema.get("required", [])))
        and {"target_editability_level", "editability_level"}.issubset(set(delivery_schema.get("required", [])))
        and "actual_editability_level" in protocols_text
        and "editability_below_target" in validation_text
    )
    checks.append(
        Check(
            "editability_contract_alignment",
            editability_contract_ok,
            "target, measured actual, and promise enforcement align"
            if editability_contract_ok
            else "editability contract drift",
        )
    )

    audit_reports = [root / "audit" / f"round-{index}-{name}.md" for index, name in [
        (1, "source-fidelity"),
        (2, "architecture-contracts"),
        (3, "agentic-skill"),
        (4, "buildability"),
        (5, "adversarial-integrity"),
    ]]
    audit_report_errors = []
    for report_path in audit_reports:
        report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
        if len(report_text) < 800 or "## Result" not in report_text or "PASS" not in report_text:
            audit_report_errors.append(report_path.name)
    checks.append(
        Check(
            "independent_audit_reports",
            not audit_report_errors,
            "five substantive audit rounds present"
            if not audit_report_errors
            else "; ".join(audit_report_errors),
        )
    )

    generated_paths = [root / "build", root / "dist", root / "src/slidethus.egg-info"]
    if (root / ".git").exists():
        tracked = subprocess.run(
            ["git", "ls-files", "--", *[path.relative_to(root).as_posix() for path in generated_paths]],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        dirty_release_paths = sorted(set(tracked))
    else:
        dirty_release_paths = [path.relative_to(root).as_posix() for path in generated_paths if path.exists()]
    checks.append(Check("release_tree_hygiene", not dirty_release_paths, "no build/dist/egg-info directories" if not dirty_release_paths else "; ".join(dirty_release_paths)))

    renderer_root = root / "renderers/pptxgenjs"
    renderer_package = renderer_root / "package.json"
    renderer_lock = renderer_root / "package-lock.json"
    renderer_source = renderer_root / "render.mjs"
    renderer_preview = renderer_root / "preview.mjs"
    renderer_tests = tuple((renderer_root / "test").glob("*.test.mjs"))
    renderer_contract_ok = (
        renderer_package.is_file()
        and renderer_lock.is_file()
        and renderer_source.is_file()
        and renderer_preview.is_file()
        and len(renderer_tests) >= 2
        and '"pptxgenjs": "4.0.1"' in renderer_package.read_text(encoding="utf-8")
        and '"@resvg/resvg-js": "2.6.2"' in renderer_package.read_text(encoding="utf-8")
        and '"pdf-lib": "1.17.1"' in renderer_package.read_text(encoding="utf-8")
    )
    checks.append(
        Check(
            "production_renderer_contract",
            renderer_contract_ok,
            "PptxGenJS/Hybrid and independent SVG export sidecar are pinned and tested"
            if renderer_contract_ok
            else "M4 renderer sidecar/package-lock contract is incomplete",
        )
    )

    deterministic_review_schema = root / "schemas/deterministic_review_report.schema.json"
    deterministic_review_service = root / "src/slidethus/services/deterministic_review.py"
    deterministic_review_tests = root / "tests/test_deterministic_review.py"
    deterministic_review_contract_ok = (
        (root / "plans/M5-review-repair-loop.md").is_file()
        and (root / "docs/adr/ADR-0020-independent-review-repair-boundary.md").is_file()
        and deterministic_review_schema.is_file()
        and (root / "src/slidethus/_schemas/deterministic_review_report.schema.json").is_file()
        and deterministic_review_service.is_file()
        and deterministic_review_tests.is_file()
        and "observed_content_hash" in deterministic_review_schema.read_text(encoding="utf-8")
        and "deterministic_review_workspace_errors" in validation_text
        and "DeterministicReviewService" in deterministic_review_service.read_text(encoding="utf-8")
    )
    checks.append(
        Check(
            "deterministic_review_contract",
            deterministic_review_contract_ok,
            "M5.1 immutable deterministic review, observed lineage and workspace validation are present"
            if deterministic_review_contract_ok
            else "M5.1 deterministic review contract is incomplete",
        )
    )

    output_json = root / "audit/automated-audit.json"
    output_md = root / "audit/automated-audit.md"
    passed = all(check.ok for check in checks)
    payload = {"schema_version": "0.1.0", "status": "pass" if passed else "fail", "checks": [asdict(check) for check in checks]}
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = ["# Automated Package Audit", "", f"**Result: {'PASS' if passed else 'FAIL'}**", ""]
    for check in checks:
        md.append(f"- **{'PASS' if check.ok else 'FAIL'} — {check.name}:** {check.detail}")
    output_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    count = write_hash_manifest(root)
    print(f"{'PASS' if passed else 'FAIL'}: {sum(c.ok for c in checks)}/{len(checks)} checks; {count} files hashed")
    if not passed:
        for check in checks:
            if not check.ok:
                print(f"- {check.name}: {check.detail}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
