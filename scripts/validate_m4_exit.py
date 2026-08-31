from __future__ import annotations

import re
import shutil
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
from slidethus.services.m3_application import M3ApplicationService
from slidethus.services.m4_application import M4ApplicationService, evaluate_m4_workspace_gate
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


_REQUIRED_PATHS = (
    "plans/M4-rendering-backends.md",
    "audit/M4-round-1-open-issues.md",
    "audit/M4-round-2-scorecard.md",
    "audit/M4-BUILD_REPORT.md",
    "docs/adr/ADR-0019-production-rendering-boundary.md",
    "schemas/renderer_ir.schema.json",
    "schemas/render_preflight_report.schema.json",
    "schemas/m4_application_report.schema.json",
    "schemas/render_manifest.schema.json",
    "schemas/asset_manifest.schema.json",
    "schemas/visual_system.schema.json",
    "src/slidethus/render_ir.py",
    "src/slidethus/render_preflight.py",
    "src/slidethus/render_manifest.py",
    "src/slidethus/rendering_rules.py",
    "src/slidethus/render_backends/final_svg.py",
    "src/slidethus/render_backends/pptxgenjs.py",
    "src/slidethus/render_backends/svg_export.py",
    "src/slidethus/services/visual_system.py",
    "src/slidethus/services/render_compile.py",
    "src/slidethus/services/render_preflight.py",
    "src/slidethus/services/render_assets.py",
    "src/slidethus/services/font_resolution.py",
    "src/slidethus/services/render_manifest.py",
    "src/slidethus/services/m4_application.py",
    "renderers/pptxgenjs/package.json",
    "renderers/pptxgenjs/package-lock.json",
    "renderers/pptxgenjs/render.mjs",
    "renderers/pptxgenjs/preview.mjs",
    "tests/test_render_compile.py",
    "tests/test_final_svg.py",
    "tests/test_final_svg_complex.py",
    "tests/test_pptxgenjs_renderers.py",
    "tests/test_render_assets_fonts.py",
    "tests/test_render_preflight.py",
    "tests/test_svg_export.py",
    "tests/test_m4_application.py",
    "tests/test_m4_cli.py",
    "tests/test_m4_exit.py",
    "scripts/validate_m4_exit.py",
)

_RUNTIME_SCHEMAS = (
    "renderer_ir.schema.json",
    "render_preflight_report.schema.json",
    "m4_application_report.schema.json",
    "render_manifest.schema.json",
    "asset_manifest.schema.json",
    "visual_system.schema.json",
)


def _read(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _section(text: str, heading: str, next_heading: str) -> str:
    try:
        return text.split(heading, 1)[1].split(next_heading, 1)[0]
    except IndexError:
        return ""


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


def _m4_smoke(root: Path) -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:
        return False, "Node.js is unavailable for the Production M4 smoke"
    try:
        with tempfile.TemporaryDirectory(prefix="slidethus-m4-exit-") as directory:
            base = Path(directory)
            workspace = init_workspace(base / "workspace", title="M4 Exit Smoke")
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
                return False, f"M3 prerequisite smoke is not ready: {m3.report.get('status')}"
            result = M4ApplicationService(
                workspace,
                renderer_root=root / "renderers/pptxgenjs",
                node=node,
                font_match=str(_fake_font_match(base)),
            ).run()
            validation = validate_workspace(workspace, check_hashes=True)
            gate = evaluate_m4_workspace_gate(workspace)
            roles = {str(item.get("role")) for item in result.report.get("outputs", [])}
            required_roles = {
                "final_svg",
                "native_pptx",
                "hybrid_pptx",
                "export_png",
                "export_pdf",
                "backend_measurement",
            }
            ok = (
                result.report.get("status") == "ready"
                and result.report.get("final_phase") == "DRAFT_RENDERED"
                and result.report.get("g7", {}).get("status") == "pass"
                and required_roles.issubset(roles)
                and validation.ok
                and gate.get("status") == "pass"
            )
            detail = (
                "temporary M3 graph renders through Final SVG, Native, Hybrid and PNG/PDF to passing G7"
                if ok
                else (
                    f"status={result.report.get('status')}; phase={result.report.get('final_phase')}; "
                    f"g7={result.report.get('g7')}; validation_ok={validation.ok}; gate={gate}"
                )
            )
            return ok, detail
    except Exception as exc:  # noqa: BLE001
        return False, f"M4 smoke failed: {exc}"


def _node_tests(root: Path) -> tuple[bool, str]:
    node = shutil.which("node")
    tests = sorted((root / "renderers/pptxgenjs/test").glob("*.test.mjs"))
    if not node:
        return False, "Node.js is unavailable"
    if not tests:
        return False, "PptxGenJS sidecar tests are missing"
    process = subprocess.run(
        [node, "--test", *[str(path) for path in tests]],
        cwd=root / "renderers/pptxgenjs",
        check=False,
        capture_output=True,
        text=True,
    )
    detail = (process.stdout + process.stderr).strip()
    return process.returncode == 0, (
        "Node renderer/export tests pass" if process.returncode == 0 else detail[-4000:]
    )


def evaluate_m4_exit(root: Path, *, run_runtime_checks: bool = True) -> tuple[Check, ...]:
    """Evaluate repository-wide M4 completion without mutating the repository."""

    root = root.resolve()
    checks: list[Check] = []

    missing = [relative for relative in _REQUIRED_PATHS if not (root / relative).is_file()]
    checks.append(
        Check(
            "required_evidence",
            not missing,
            "all M4 plans, audits, ADR, schemas, services, sidecar and tests are present"
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
            "M4 schemas are valid and packaged mirrors match"
            if not schema_errors and not mirror_errors
            else "; ".join([*schema_errors, *(f"mirror:{item}" for item in mirror_errors)]),
        )
    )

    plan = _read(root, "plans/M4-rendering-backends.md")
    incomplete = re.findall(r"\| M4\.[1-7] \|[^\n]+\| (?:pending|in_progress) \|", plan)
    plan_ok = not incomplete and "M4 Exit Gate：PASS" in plan
    checks.append(
        Check(
            "master_plan_complete",
            plan_ok,
            "M4.1–M4.7 and M4 Exit are recorded complete" if plan_ok else "M4 plan is incomplete",
        )
    )

    tasks = _section(_read(root, "TASKS.md"), "## M4 — Rendering Backends", "## M5 —")
    task_ok = bool(tasks) and not re.findall(r"^- \[ \]", tasks, re.MULTILINE) and "Exit Gate：PASS" in tasks
    checks.append(
        Check(
            "tasks_m4_complete",
            task_ok,
            "TASKS.md records all M4 tasks complete" if task_ok else "TASKS.md M4 is incomplete",
        )
    )

    roadmap = _read(root, "docs/09-roadmap.md")
    roadmap_ok = "M4 Exit Gate：PASS" in roadmap and "M5" in roadmap and "Rendering" in roadmap
    checks.append(
        Check(
            "roadmap_m4_complete",
            roadmap_ok,
            "roadmap records M4 complete and M5 next" if roadmap_ok else "roadmap lacks M4 → M5 handoff",
        )
    )

    kickoff = _read(root, "CODEX_KICKOFF.md")
    kickoff_ok = (
        "M4 Exit Gate: PASS" in kickoff
        and any(
            marker in kickoff
            for marker in (
                "M5 Review and Repair Loop",
                "M5 Exit Gate: PASS",
                "M6 Productization and Distribution",
            )
        )
        and any(
            marker in kickoff
            for marker in (
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
            "Codex kickoff freezes M2–M4 and hands off to M5" if kickoff_ok else "Codex kickoff lacks M4 → M5 handoff",
        )
    )

    readme = _read(root, "README.md")
    skill = _read(root, ".agents/skills/slidethus/references/shared-contract.md")
    truth_ok = (
        "M4 Exit Gate：PASS" in readme
        and "M5" in readme
        and "M4 Exit Gate: PASS" in skill
        and "不是生产级端到端 PPT 产品" in readme
    )
    checks.append(
        Check(
            "capability_truthfulness",
            truth_ok,
            "README/Skill declare M4 rendering complete without claiming M5 visual approval"
            if truth_ok
            else "M4 capability/non-goal wording is incomplete",
        )
    )

    render_compile = _read(root, "src/slidethus/services/render_compile.py")
    final_svg = _read(root, "src/slidethus/render_backends/final_svg.py")
    pptx = _read(root, "src/slidethus/render_backends/pptxgenjs.py")
    node_source = _read(root, "renderers/pptxgenjs/render.mjs")
    independence_ok = (
        "Renderer IR" in render_compile
        and "RenderCompileService" in final_svg
        and "RenderCompileService" in pptx
        and "narrative_blueprint" not in node_source
        and "deck_outline" not in node_source
        and "slide_specs" not in node_source
        and "layout_plans" not in node_source
    )
    checks.append(
        Check(
            "backend_independence",
            independence_ok,
            "Final SVG/Native/Hybrid consume Renderer IR without renderer-owned planning truth"
            if independence_ok
            else "Production renderer independence contract drift",
        )
    )

    package_text = _read(root, "renderers/pptxgenjs/package.json")
    lock_text = _read(root, "renderers/pptxgenjs/package-lock.json")
    sidecar_ok = (
        '"pptxgenjs": "4.0.1"' in package_text
        and '"@resvg/resvg-js": "2.6.2"' in package_text
        and '"pdf-lib": "1.17.1"' in package_text
        and '"lockfileVersion"' in lock_text
        and (root / "renderers/pptxgenjs/render.mjs").is_file()
        and (root / "renderers/pptxgenjs/preview.mjs").is_file()
    )
    checks.append(
        Check(
            "node_sidecar_locked",
            sidecar_ok,
            "PptxGenJS/preview sidecar dependencies are pinned by package-lock"
            if sidecar_ok
            else "Node sidecar dependency lock is incomplete",
        )
    )

    if run_runtime_checks:
        node_ok, node_detail = _node_tests(root)
    else:
        node_ok, node_detail = True, "Node tests skipped for static negative control"
    checks.append(Check("node_renderer_tests", node_ok, node_detail))

    for milestone in ("m2", "m3"):
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
        smoke_ok, smoke_detail = _m4_smoke(root)
    else:
        smoke_ok, smoke_detail = True, "M4 smoke skipped for static negative control"
    checks.append(Check("m4_application_smoke", smoke_ok, smoke_detail))

    round2 = _read(root, "audit/M4-round-2-scorecard.md")
    audit_ok = (
        re.search(r"Critical open issues:\s*0", round2, re.I) is not None
        and re.search(r"Major open issues:\s*0", round2, re.I) is not None
        and "M4 Exit Gate: PASS" in round2
    )
    checks.append(
        Check(
            "m4_audit_evidence",
            audit_ok,
            "M4 Round B records zero open Critical/Major and Exit PASS"
            if audit_ok
            else "M4 Round B audit evidence is incomplete",
        )
    )

    makefile = _read(root, "Makefile")
    package_audit = _read(root, "scripts/audit_package.py")
    persistent_ok = (
        "validate_m4_exit.py" in makefile
        and "renderer-test" in makefile
        and "validate_m4_exit.py" in package_audit
        and "production_renderer_contract" in package_audit
    )
    checks.append(
        Check(
            "persistent_verification",
            persistent_ok,
            "Makefile/package audit persist M4 and Node renderer verification"
            if persistent_ok
            else "M4 persistent verification is incomplete",
        )
    )

    return tuple(checks)


def main() -> int:
    checks = evaluate_m4_exit(find_repository_root())
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(check.ok for check in checks)
    print(f"M4 EXIT: {passed}/{len(checks)} checks passed")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
