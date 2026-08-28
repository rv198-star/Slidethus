from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import platform
import sys
from dataclasses import asdict
from pathlib import Path

from slidethus import __version__
from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import find_repository_root
from slidethus.errors import SlidethusError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import read_json
from slidethus.m2_application_reports import (
    inspect_m2_application_report,
    list_m2_application_reports,
)
from slidethus.m3_application_reports import (
    inspect_m3_application_report,
    list_m3_application_reports,
)
from slidethus.m4_application_reports import (
    inspect_m4_application_report,
    list_m4_application_reports,
)
from slidethus.mvp import MvpBuildConfig, build_minimal_mvp
from slidethus.protocols import (
    BriefCompletionHints,
    PlanningLimits,
    ResearchLimits,
    SourceParseLimits,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.brief_completion import BriefCompletionService
from slidethus.services.evidence import EvidenceEngine
from slidethus.services.evidence_binding import EvidenceBindingService
from slidethus.services.m2_application import (
    M2ApplicationLimits,
    M2ApplicationService,
    evaluate_m2_workspace_gate,
)
from slidethus.services.m3_application import (
    M3ApplicationService,
    evaluate_m3_workspace_gate,
)
from slidethus.services.m4_application import (
    M4ApplicationService,
    evaluate_m4_workspace_gate,
)
from slidethus.services.research import (
    inspect_research_run,
    invalidate_research_run,
    list_research_runs,
    plan_orientation_research,
    plan_targeted_research,
)
from slidethus.services.source_ingestion import SourceIngestionService
from slidethus.validation import format_report, validate_workspace
from slidethus.wireframe import render_wireframes
from slidethus.workspace import init_workspace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slidethus", description="Slidethus deterministic project foundation")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize a stage-0 workspace")
    init.add_argument("workspace", type=Path)
    init.add_argument("--title", required=True)
    init.add_argument("--language", default="zh-CN")
    init.add_argument("--force", action="store_true")

    validate = sub.add_parser("validate", help="validate a workspace")
    validate.add_argument("workspace", type=Path)
    validate.add_argument("--check-hashes", action="store_true")

    status = sub.add_parser("status", help="show project state")
    status.add_argument("workspace", type=Path)

    gate = sub.add_parser("gate", help="evaluate a deterministic gate")
    gate.add_argument("workspace", type=Path)
    gate.add_argument("gate_id", choices=["G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7", "G8", "G9"])

    render = sub.add_parser("render-wireframe", help="render gray SVG planning drafts")
    render.add_argument("workspace", type=Path)
    render.add_argument("--output-dir", type=Path)

    mvp = sub.add_parser(
        "mvp",
        help="build planning, debug, design, final, preview, QA, and delivery outputs",
    )
    mvp.add_argument("workspace", type=Path)
    mvp.add_argument("--source", type=Path, required=True)
    mvp.add_argument("--title")
    mvp.add_argument("--language", default="zh-CN")
    mvp.add_argument("--max-slides", type=int, default=6)
    mvp.add_argument("--require-preview", action="store_true")

    sub.add_parser("doctor", help="check local foundation prerequisites")
    sub.add_parser("schemas", help="list known artifact schemas")

    artifact = sub.add_parser("artifact", help="inspect and maintain versioned artifacts")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)

    artifact_list = artifact_sub.add_parser("list", help="list registry metadata")
    artifact_list.add_argument("workspace", type=Path)

    artifact_show = artifact_sub.add_parser("show", help="show an artifact version")
    artifact_show.add_argument("workspace", type=Path)
    artifact_show.add_argument("artifact_type")
    artifact_show.add_argument("--version", type=int)

    artifact_validate = artifact_sub.add_parser("validate", help="validate one artifact or the complete graph")
    artifact_validate.add_argument("workspace", type=Path)
    artifact_validate.add_argument("artifact_type", nargs="?")

    artifact_migrate = artifact_sub.add_parser("migrate", help="migrate the workspace runtime schema")
    artifact_migrate.add_argument("workspace", type=Path)
    artifact_migrate.add_argument("--dry-run", action="store_true")

    artifact_recover = artifact_sub.add_parser("recover", help="recover interrupted artifact transactions")
    artifact_recover.add_argument("workspace", type=Path)

    source = sub.add_parser("source", help="ingest and inspect source snapshots")
    source_sub = source.add_subparsers(dest="source_command", required=True)

    source_ingest = source_sub.add_parser("ingest", help="parse one local source into the Source Ledger")
    source_ingest.add_argument("workspace", type=Path)
    source_ingest.add_argument("file", type=Path)
    source_ingest.add_argument("--source-id")
    source_ingest.add_argument("--title")
    source_ingest.add_argument(
        "--ownership",
        choices=["user_owned", "licensed", "public_reference", "unknown"],
    )
    source_ingest.add_argument(
        "--confidentiality",
        choices=["public", "internal", "confidential", "restricted"],
    )
    source_ingest.add_argument(
        "--authority-tier",
        choices=["user", "primary", "secondary", "community", "unknown"],
    )
    source_ingest.add_argument(
        "--allowed-use",
        choices=["full", "internal_only", "citation_only", "metadata_only", "do_not_use"],
    )
    source_ingest.add_argument("--max-source-bytes", type=int, default=50 * 1024 * 1024)
    source_ingest.add_argument("--max-chunks", type=int, default=5000)
    source_ingest.add_argument("--max-chunk-chars", type=int, default=12_000)
    source_ingest.add_argument("--max-risks", type=int, default=10_000)
    source_ingest.add_argument("--max-pages", type=int, default=500)
    source_ingest.add_argument("--max-slides", type=int, default=500)
    source_ingest.add_argument("--max-sheets", type=int, default=100)
    source_ingest.add_argument("--max-rows", type=int, default=100_000)
    source_ingest.add_argument("--max-cells", type=int, default=1_000_000)
    source_ingest.add_argument("--max-archive-entries", type=int, default=10_000)
    source_ingest.add_argument(
        "--max-archive-member-bytes",
        type=int,
        default=64 * 1024 * 1024,
    )
    source_ingest.add_argument(
        "--max-uncompressed-bytes",
        type=int,
        default=512 * 1024 * 1024,
    )
    source_ingest.add_argument("--max-image-pixels", type=int, default=100_000_000)

    source_show = source_sub.add_parser("show", help="verify and show one persisted source snapshot")
    source_show.add_argument("workspace", type=Path)
    source_show.add_argument("source_id")

    research = sub.add_parser("research", help="plan and inspect research runtime state")
    research_sub = research.add_subparsers(dest="research_command", required=True)

    research_plan = research_sub.add_parser("plan", help="build a bounded research plan")
    research_plan.add_argument("workspace", type=Path)
    research_plan.add_argument("kind", choices=["orientation", "targeted"])
    research_plan.add_argument("--cycle-id")
    research_plan.add_argument("--slide-id", action="append", dest="slide_ids")
    research_plan.add_argument("--max-queries", type=int, default=24)
    research_plan.add_argument("--max-results-per-query", type=int, default=12)
    research_plan.add_argument("--max-total-results", type=int, default=120)
    research_plan.add_argument("--cache-ttl-seconds", type=int, default=86_400)

    research_list = research_sub.add_parser("list", help="list verified research runs")
    research_list.add_argument("workspace", type=Path)

    research_show = research_sub.add_parser("show", help="show and verify one research run")
    research_show.add_argument("workspace", type=Path)
    research_show.add_argument("run_id")

    research_invalidate = research_sub.add_parser(
        "invalidate", help="invalidate research query cache without deleting history"
    )
    research_invalidate.add_argument("workspace", type=Path)
    research_invalidate.add_argument("run_id")
    research_invalidate.add_argument("--query-id", action="append", dest="query_ids")
    research_invalidate.add_argument("--reason", required=True)

    evidence = sub.add_parser("evidence", help="materialize and adjudicate production evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)

    evidence_source = evidence_sub.add_parser(
        "source", help="adjudicate persisted Source Chunks into Evidence"
    )
    evidence_source.add_argument("workspace", type=Path)
    evidence_source.add_argument("source_id")
    evidence_source.add_argument("--freshness-cutoff")
    evidence_source.add_argument("--allow-high-risk-source-evidence", action="store_true")

    evidence_research = evidence_sub.add_parser(
        "research", help="materialize one complete Research Run and adjudicate its results"
    )
    evidence_research.add_argument("workspace", type=Path)
    evidence_research.add_argument("run_id")
    evidence_research.add_argument("--freshness-cutoff")
    evidence_research.add_argument("--no-complete-cycle", action="store_true")
    evidence_research.add_argument("--allow-high-risk-source-evidence", action="store_true")

    evidence_show = evidence_sub.add_parser("show", help="show the current Evidence Ledger or one claim")
    evidence_show.add_argument("workspace", type=Path)
    evidence_show.add_argument("evidence_id", nargs="?")

    evidence_reconcile = evidence_sub.add_parser(
        "reconcile",
        help="re-evaluate current Production Evidence against current Source lineage and policy",
    )
    evidence_reconcile.add_argument("workspace", type=Path)
    evidence_reconcile.add_argument("--freshness-cutoff")

    evidence_gaps = evidence_sub.add_parser(
        "gaps", help="recompute Outline/Block Evidence gaps for current artifact versions"
    )
    evidence_gaps.add_argument("workspace", type=Path)
    evidence_gaps.add_argument("--no-persist", action="store_true")
    evidence_gaps.add_argument("--ignore-targeted-cycle", action="store_true")

    evidence_targeted_plan = evidence_sub.add_parser(
        "targeted-plan", help="build an M2.3 targeted Research Plan from current gap suggestions"
    )
    evidence_targeted_plan.add_argument("workspace", type=Path)
    evidence_targeted_plan.add_argument("--cycle-id")
    evidence_targeted_plan.add_argument("--max-queries", type=int, default=24)
    evidence_targeted_plan.add_argument("--max-results-per-query", type=int, default=12)
    evidence_targeted_plan.add_argument("--max-total-results", type=int, default=120)
    evidence_targeted_plan.add_argument("--cache-ttl-seconds", type=int, default=86_400)

    evidence_complete_user = evidence_sub.add_parser(
        "complete-user-targeted",
        help="complete current targeted review from gap-free user-material Evidence",
    )
    evidence_complete_user.add_argument("workspace", type=Path)

    evidence_rework = evidence_sub.add_parser(
        "rework", help="route current blocking Evidence gaps to EVIDENCE_READY"
    )
    evidence_rework.add_argument("workspace", type=Path)
    evidence_rework.add_argument("--reason")

    m2 = sub.add_parser("m2", help="run and inspect the integrated M2 application boundary")
    m2_sub = m2.add_subparsers(dest="m2_command", required=True)

    m2_run = m2_sub.add_parser(
        "run",
        help="run/resume local or explicitly degraded M2 orchestration",
    )
    m2_run.add_argument("workspace", type=Path)
    m2_run.add_argument("--source", action="append", dest="sources", type=Path)
    m2_run.add_argument("--allow-research-degraded", action="store_true")
    m2_run.add_argument("--allow-high-risk-source-evidence", action="store_true")
    m2_run.add_argument("--no-planning-revalidation", action="store_true")
    m2_run.add_argument("--max-sources", type=int, default=64)
    m2_run.add_argument("--max-total-source-bytes", type=int, default=1024 * 1024 * 1024)
    m2_run.add_argument("--max-source-bytes", type=int, default=50 * 1024 * 1024)
    m2_run.add_argument("--max-chunks", type=int, default=5000)
    m2_run.add_argument("--max-chunk-chars", type=int, default=12_000)
    m2_run.add_argument("--max-queries", type=int, default=24)
    m2_run.add_argument("--max-results-per-query", type=int, default=12)
    m2_run.add_argument("--max-total-results", type=int, default=120)
    m2_run.add_argument("--cache-ttl-seconds", type=int, default=86_400)

    m2_list = m2_sub.add_parser("list", help="list verified M2 Application Reports")
    m2_list.add_argument("workspace", type=Path)

    m2_show = m2_sub.add_parser("show", help="show one verified M2 Application Report")
    m2_show.add_argument("workspace", type=Path)
    m2_show.add_argument("report_id")

    m2_gate = m2_sub.add_parser("gate", help="evaluate the current workspace M2 Gate")
    m2_gate.add_argument("workspace", type=Path)

    m3 = sub.add_parser(
        "m3",
        help="run and inspect Production Narrative and Planning orchestration",
    )
    m3_sub = m3.add_subparsers(dest="m3_command", required=True)

    m3_run = m3_sub.add_parser(
        "run",
        help="run/resume Brief, M2 Evidence, Narrative, Outline, Specs, Layout, and review",
    )
    m3_run.add_argument("workspace", type=Path)
    m3_run.add_argument("--source", action="append", dest="sources", type=Path)
    m3_run.add_argument("--request", default="")
    m3_run.add_argument("--purpose")
    m3_run.add_argument("--desired-outcome")
    m3_run.add_argument("--call-to-action")
    m3_run.add_argument("--delivery-context")
    m3_run.add_argument("--presentation-mode", choices=["live", "read", "both"])
    m3_run.add_argument("--audience-role")
    m3_run.add_argument("--audience-need", action="append", dest="audience_needs")
    m3_run.add_argument(
        "--audience-objection",
        action="append",
        dest="audience_objections",
    )
    m3_run.add_argument(
        "--decision-power",
        choices=["none", "influencer", "decision_maker", "mixed"],
    )
    m3_run.add_argument(
        "--knowledge-level",
        choices=["novice", "intermediate", "expert", "mixed"],
    )
    m3_run.add_argument("--page-target", type=int)
    m3_run.add_argument("--duration-minutes", type=float)
    m3_run.add_argument(
        "--output-format",
        action="append",
        dest="output_formats",
        choices=["pptx", "pdf", "svg", "png", "html", "artifacts_only"],
    )
    m3_run.add_argument("--editability-target", choices=["E0", "E1", "E2", "E3", "E4"])
    m3_run.add_argument("--approval-mode", choices=["auto", "checkpoint", "strict"])
    m3_run.add_argument("--quality-profile", choices=["draft", "standard", "critical"])
    m3_run.add_argument("--allow-research-degraded", action="store_true")
    m3_run.add_argument("--allow-high-risk-source-evidence", action="store_true")
    m3_run.add_argument("--no-auto-repair", action="store_true")
    m3_run.add_argument("--max-repair-passes", type=int, default=2)
    m3_run.add_argument("--max-blocking-questions", type=int, default=3)
    m3_run.add_argument("--max-assumptions", type=int, default=24)
    m3_run.add_argument("--max-sections", type=int, default=12)
    m3_run.add_argument("--max-slides", type=int, default=120)
    m3_run.add_argument("--max-blocks-per-slide", type=int, default=12)
    m3_run.add_argument("--max-words-per-slide", type=int, default=240)
    m3_run.add_argument("--max-provider-payload-bytes", type=int, default=2 * 1024 * 1024)
    m3_run.add_argument("--max-change-targets", type=int, default=64)

    m3_answer = m3_sub.add_parser(
        "answer",
        help="answer one material Brief question and recompute the minimum-question contract",
    )
    m3_answer.add_argument("workspace", type=Path)
    m3_answer.add_argument("question_id")
    m3_answer.add_argument("answer")

    m3_list = m3_sub.add_parser("list", help="list verified M3 Application Reports")
    m3_list.add_argument("workspace", type=Path)

    m3_show = m3_sub.add_parser("show", help="show one verified M3 Application Report")
    m3_show.add_argument("workspace", type=Path)
    m3_show.add_argument("report_id")

    m3_gate = m3_sub.add_parser("gate", help="evaluate current M3 planning readiness")
    m3_gate.add_argument("workspace", type=Path)

    m4 = sub.add_parser(
        "m4",
        help="run and inspect Production multi-backend rendering",
    )
    m4_sub = m4.add_subparsers(dest="m4_command", required=True)

    m4_run = m4_sub.add_parser(
        "run",
        help="render Final SVG, Native PPTX, Hybrid PPTX, PNG/PDF and G7",
    )
    m4_run.add_argument("workspace", type=Path)
    m4_run.add_argument("--renderer-root", type=Path)
    m4_run.add_argument("--node")
    m4_run.add_argument("--font-match")
    m4_run.add_argument("--require-office-preview", action="store_true")

    m4_list = m4_sub.add_parser("list", help="list verified M4 Application Reports")
    m4_list.add_argument("workspace", type=Path)

    m4_show = m4_sub.add_parser("show", help="show one verified M4 Application Report")
    m4_show.add_argument("workspace", type=Path)
    m4_show.add_argument("report_id")

    m4_gate = m4_sub.add_parser("gate", help="evaluate current Production M4 readiness")
    m4_gate.add_argument("workspace", type=Path)
    return parser


def _doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python", sys.version_info >= (3, 11), platform.python_version()))
    try:
        root = find_repository_root()
        checks.append(("repository", True, str(root)))
    except FileNotFoundError:
        checks.append(("repository", True, "not required in installed mode"))
    try:
        registry = SchemaRegistry()
        checks.append(("schemas", bool(registry.entries), f"{len(registry.entries)} entries from {registry.schema_dir}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("schemas", False, str(exc)))
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    optional_adapters = {
        "pdf": ("pypdf", "pypdf"),
        "docx": ("python-docx", "docx"),
        "xlsx": ("openpyxl", "openpyxl"),
        "image": ("Pillow", "PIL"),
    }
    for capability, (distribution_name, module_name) in optional_adapters.items():
        try:
            version = importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            version = None
        module_available = importlib.util.find_spec(module_name) is not None
        available = version is not None and module_available
        status = "PASS" if available else "OPTIONAL"
        detail = (
            f"available ({version})"
            if available
            else "install slidethus[ingestion]"
        )
        print(f"{status} ingestion:{capability}: {detail}")
    print("PASS ingestion:html-csv-pptx: available in the base install")
    return 0 if all(ok for _, ok, _ in checks) else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            path = init_workspace(args.workspace, title=args.title, language=args.language, force=args.force)
            print(path)
            return 0
        if args.command == "validate":
            report = validate_workspace(args.workspace, check_hashes=args.check_hashes)
            print(format_report(report))
            return 0 if report.ok else 1
        if args.command == "status":
            state = read_json(args.workspace.resolve() / "project_state.json")
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.command == "gate":
            result = evaluate_gate(args.workspace, args.gate_id)
            print(json.dumps({"gate_id": result.gate_id, "status": result.status, "reasons": list(result.reasons)}, ensure_ascii=False, indent=2))
            return 0 if result.passed else 1
        if args.command == "render-wireframe":
            outputs = render_wireframes(args.workspace, args.output_dir)
            for output in outputs:
                print(output)
            return 0
        if args.command == "mvp":
            title = args.title or args.source.stem
            result = build_minimal_mvp(
                MvpBuildConfig(
                    workspace=args.workspace,
                    source=args.source,
                    title=title,
                    language=args.language,
                    max_slides=args.max_slides,
                    require_preview=args.require_preview,
                )
            )
            print(
                json.dumps(
                    {
                        "status": result.status,
                        "workspace": str(result.workspace),
                        "output": str(result.output_path),
                        "current_phase": result.current_phase,
                        "planning_previews": [
                            str(path) for path in result.planning_previews
                        ],
                        "layout_diagnostics": str(result.diagnostics_path),
                        "debug_output": str(result.debug_output_path),
                        "debug_previews": [str(path) for path in result.debug_previews],
                        "design_previews": [str(path) for path in result.design_previews],
                        "independent_previews": [
                            str(path) for path in result.independent_previews
                        ],
                        "limitations": list(result.limitations),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1 if result.status == "blocked" else 0
        if args.command == "doctor":
            return _doctor()
        if args.command == "schemas":
            registry = SchemaRegistry()
            for artifact_type, entry in sorted(registry.entries.items()):
                print(f"{artifact_type}: {entry.default_path} <- {entry.schema_path.name}")
            return 0
        if args.command == "source":
            service = SourceIngestionService(args.workspace)
            if args.source_command == "ingest":
                result = service.ingest(
                    args.file,
                    source_id=args.source_id,
                    title=args.title,
                    ownership=args.ownership,
                    confidentiality=args.confidentiality,
                    authority_tier=args.authority_tier,
                    allowed_use=args.allowed_use,
                    limits=SourceParseLimits(
                        max_source_bytes=args.max_source_bytes,
                        max_chunks=args.max_chunks,
                        max_chunk_chars=args.max_chunk_chars,
                        max_risks=args.max_risks,
                        max_pages=args.max_pages,
                        max_slides=args.max_slides,
                        max_sheets=args.max_sheets,
                        max_rows=args.max_rows,
                        max_cells=args.max_cells,
                        max_archive_entries=args.max_archive_entries,
                        max_archive_member_bytes=args.max_archive_member_bytes,
                        max_uncompressed_bytes=args.max_uncompressed_bytes,
                        max_image_pixels=args.max_image_pixels,
                    ),
                )
            else:
                result = service.load(args.source_id)
            print(
                json.dumps(
                    {
                        "source_id": result.source_id,
                        "changed": result.changed,
                        "source": result.source_record,
                        "snapshot": str(result.snapshot_path),
                        "chunk_count": len(result.chunks),
                        "warnings": list(result.warnings),
                        "risks": list(result.risks),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "research":
            if args.research_command == "plan":
                limits = ResearchLimits(
                    max_queries=args.max_queries,
                    max_results_per_query=args.max_results_per_query,
                    max_total_results=args.max_total_results,
                    cache_ttl_seconds=args.cache_ttl_seconds,
                )
                plan = (
                    plan_orientation_research(
                        args.workspace,
                        cycle_id=args.cycle_id,
                        limits=limits,
                    )
                    if args.kind == "orientation"
                    else plan_targeted_research(
                        args.workspace,
                        cycle_id=args.cycle_id,
                        slide_ids=args.slide_ids,
                        limits=limits,
                    )
                )
                print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
                return 0
            if args.research_command == "list":
                print(
                    json.dumps(
                        list(list_research_runs(args.workspace)),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.research_command == "show":
                print(
                    json.dumps(
                        inspect_research_run(args.workspace, args.run_id),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.research_command == "invalidate":
                print(
                    json.dumps(
                        invalidate_research_run(
                            args.workspace,
                            args.run_id,
                            query_ids=args.query_ids,
                            reason=args.reason,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
        if args.command == "evidence":
            engine = EvidenceEngine(args.workspace)
            if args.evidence_command == "source":
                published = engine.adjudicate(
                    engine.candidates_from_source(args.source_id),
                    freshness_cutoff=args.freshness_cutoff,
                    allow_high_risk_source_evidence=args.allow_high_risk_source_evidence,
                )
                print(
                    json.dumps(
                        {
                            "changed": published.changed,
                            "evidence_ids": list(published.evidence_ids),
                            "claims": [
                                item
                                for item in published.ledger.get("claims", [])
                                if item.get("evidence_id") in set(published.evidence_ids)
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.evidence_command == "research":
                materialized, published = engine.materialize_and_adjudicate_research(
                    args.run_id,
                    freshness_cutoff=args.freshness_cutoff,
                    complete_cycle=not args.no_complete_cycle,
                    allow_high_risk_source_evidence=args.allow_high_risk_source_evidence,
                )
                print(
                    json.dumps(
                        {
                            "run_id": materialized.run_id,
                            "source_ids": list(materialized.source_ids),
                            "result_ids": list(materialized.result_ids),
                            "evidence_ids": list(published.evidence_ids),
                            "claims": [
                                item
                                for item in published.ledger.get("claims", [])
                                if item.get("evidence_id") in set(published.evidence_ids)
                            ],
                            "cycle_completed": not args.no_complete_cycle,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.evidence_command == "reconcile":
                reconciled = engine.reconcile_current_evidence(
                    freshness_cutoff=args.freshness_cutoff,
                )
                print(
                    json.dumps(
                        {
                            "changed": reconciled.changed,
                            "evidence_ids": list(reconciled.evidence_ids),
                            "ledger": reconciled.ledger,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.evidence_command == "gaps":
                result = EvidenceBindingService(args.workspace).analyze(
                    persist=not args.no_persist,
                    require_targeted_cycle=not args.ignore_targeted_cycle,
                )
                print(
                    json.dumps(
                        {
                            "path": str(result.path) if result.path is not None else None,
                            "changed": result.changed,
                            "report": result.report,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1 if result.report.get("requires_rework") else 0
            if args.evidence_command == "targeted-plan":
                limits = ResearchLimits(
                    max_queries=args.max_queries,
                    max_results_per_query=args.max_results_per_query,
                    max_total_results=args.max_total_results,
                    cache_ttl_seconds=args.cache_ttl_seconds,
                )
                plan = EvidenceBindingService(args.workspace).build_targeted_plan(
                    cycle_id=args.cycle_id,
                    limits=limits,
                )
                print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
                return 0
            if args.evidence_command == "complete-user-targeted":
                ledger = EvidenceBindingService(
                    args.workspace
                ).complete_user_material_targeted_cycle()
                print(json.dumps(ledger, ensure_ascii=False, indent=2))
                return 0
            if args.evidence_command == "rework":
                state = EvidenceBindingService(args.workspace).route_rework(
                    reason=args.reason,
                )
                print(json.dumps(state, ensure_ascii=False, indent=2))
                return 0
            if args.evidence_command == "show":
                ledger = ArtifactRuntime(args.workspace).show_artifact("evidence_ledger")
                if args.evidence_id is None:
                    payload = ledger
                else:
                    payload = next(
                        (
                            item
                            for item in ledger.get("claims", [])
                            if item.get("evidence_id") == args.evidence_id
                        ),
                        None,
                    )
                    if payload is None:
                        raise KeyError(f"Unknown evidence ID: {args.evidence_id}")
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
        if args.command == "m2":
            if args.m2_command == "run":
                result = M2ApplicationService(args.workspace).run(
                    tuple(args.sources or ()),
                    limits=M2ApplicationLimits(
                        max_sources=args.max_sources,
                        max_total_source_bytes=args.max_total_source_bytes,
                        source=SourceParseLimits(
                            max_source_bytes=args.max_source_bytes,
                            max_chunks=args.max_chunks,
                            max_chunk_chars=args.max_chunk_chars,
                        ),
                        research=ResearchLimits(
                            max_queries=args.max_queries,
                            max_results_per_query=args.max_results_per_query,
                            max_total_results=args.max_total_results,
                            cache_ttl_seconds=args.cache_ttl_seconds,
                        ),
                    ),
                    allow_research_degraded=args.allow_research_degraded,
                    allow_high_risk_source_evidence=args.allow_high_risk_source_evidence,
                    advance_existing_planning=not args.no_planning_revalidation,
                )
                print(
                    json.dumps(
                        {
                            "report_id": result.report["report_id"],
                            "path": str(result.path),
                            "changed": result.changed,
                            "report": result.report,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0 if result.report["status"] in {"ready", "degraded"} else 1
            if args.m2_command == "list":
                print(
                    json.dumps(
                        list(list_m2_application_reports(args.workspace)),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.m2_command == "show":
                print(
                    json.dumps(
                        inspect_m2_application_report(args.workspace, args.report_id),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.m2_command == "gate":
                result = evaluate_m2_workspace_gate(args.workspace)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "pass" else 1
        if args.command == "m3":
            if args.m3_command == "run":
                result = M3ApplicationService(args.workspace).run(
                    tuple(args.sources or ()),
                    brief_hints=BriefCompletionHints(
                        request_text=args.request,
                        purpose=args.purpose,
                        desired_outcome=args.desired_outcome,
                        call_to_action=args.call_to_action,
                        delivery_context=args.delivery_context,
                        presentation_mode=args.presentation_mode,
                        audience_role=args.audience_role,
                        audience_needs=tuple(args.audience_needs or ()),
                        audience_objections=tuple(args.audience_objections or ()),
                        decision_power=args.decision_power,
                        knowledge_level=args.knowledge_level,
                        page_target=args.page_target,
                        duration_minutes=args.duration_minutes,
                        output_formats=tuple(args.output_formats or ()),
                        editability_target=args.editability_target,
                        approval_mode=args.approval_mode,
                        quality_profile=args.quality_profile,
                    ),
                    planning_limits=PlanningLimits(
                        max_blocking_questions=args.max_blocking_questions,
                        max_assumptions=args.max_assumptions,
                        max_sections=args.max_sections,
                        max_slides=args.max_slides,
                        max_blocks_per_slide=args.max_blocks_per_slide,
                        max_words_per_slide=args.max_words_per_slide,
                        max_provider_payload_bytes=args.max_provider_payload_bytes,
                        max_change_targets=args.max_change_targets,
                    ),
                    allow_research_degraded=args.allow_research_degraded,
                    allow_high_risk_source_evidence=args.allow_high_risk_source_evidence,
                    auto_repair=not args.no_auto_repair,
                    max_repair_passes=args.max_repair_passes,
                )
                print(
                    json.dumps(
                        {
                            "report_id": result.report["report_id"],
                            "path": str(result.path),
                            "changed": result.changed,
                            "report": result.report,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0 if result.report["status"] == "ready" else 1
            if args.m3_command == "answer":
                result = BriefCompletionService(args.workspace).answer(
                    args.question_id,
                    args.answer,
                )
                print(
                    json.dumps(
                        {
                            "status": result.status,
                            "changed": result.changed,
                            "version": result.version,
                            "blocking_questions": list(result.blocking_questions),
                            "brief": result.brief,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0 if result.status == "resolved" else 1
            if args.m3_command == "list":
                print(
                    json.dumps(
                        list(list_m3_application_reports(args.workspace)),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.m3_command == "show":
                print(
                    json.dumps(
                        inspect_m3_application_report(args.workspace, args.report_id),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.m3_command == "gate":
                result = evaluate_m3_workspace_gate(args.workspace)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "pass" else 1
        if args.command == "m4":
            if args.m4_command == "run":
                result = M4ApplicationService(
                    args.workspace,
                    renderer_root=args.renderer_root,
                    node=args.node,
                    font_match=args.font_match,
                ).run(require_office_preview=args.require_office_preview)
                print(
                    json.dumps(
                        {
                            "report_id": result.report["report_id"],
                            "path": str(result.path),
                            "changed": result.changed,
                            "report": result.report,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0 if result.report["status"] == "ready" else 1
            if args.m4_command == "list":
                print(
                    json.dumps(
                        list(list_m4_application_reports(args.workspace)),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.m4_command == "show":
                print(
                    json.dumps(
                        inspect_m4_application_report(args.workspace, args.report_id),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.m4_command == "gate":
                result = evaluate_m4_workspace_gate(args.workspace)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "pass" else 1
        if args.command == "artifact":
            runtime = ArtifactRuntime(args.workspace)
            if args.artifact_command == "list":
                print(json.dumps(list(runtime.list_artifacts()), ensure_ascii=False, indent=2))
                return 0
            if args.artifact_command == "show":
                print(json.dumps(runtime.show_artifact(args.artifact_type, version=args.version), ensure_ascii=False, indent=2))
                return 0
            if args.artifact_command == "validate":
                report = runtime.validate(args.artifact_type)
                print(format_report(report))
                return 0 if report.ok else 1
            if args.artifact_command == "migrate":
                result = runtime.migrate_workspace(dry_run=args.dry_run)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            if args.artifact_command == "recover":
                print(json.dumps({"recovered": list(runtime.recover())}, ensure_ascii=False, indent=2))
                return 0
    except (
        SlidethusError,
        FileNotFoundError,
        json.JSONDecodeError,
        KeyError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
