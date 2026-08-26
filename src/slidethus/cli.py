from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from slidethus import __version__
from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import find_repository_root
from slidethus.errors import SlidethusError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import read_json
from slidethus.mvp import MvpBuildConfig, build_minimal_mvp
from slidethus.schema_registry import SchemaRegistry
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
