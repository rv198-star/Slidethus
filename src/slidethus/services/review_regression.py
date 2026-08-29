from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ReviewRegressionError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import (
    atomic_create_json,
    ensure_within,
    read_json,
    sha256_file,
    sha256_json,
)
from slidethus.review_regressions import (
    regression_file_key,
    regression_id,
    validate_regression_data,
)
from slidethus.review_repairs import repair_report_reference_errors
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.deterministic_review import DeterministicReviewResult
from slidethus.services.review_repair import RepairExecutionResult
from slidethus.services.semantic_review import SemanticReviewResult, SemanticScorecardResult
from slidethus.services.visual_review import VisualReviewResult

_SLIDE_FROM_NAME = re.compile(r"^(S-[0-9]{3})-")
_GATE_IDS = ("G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6", "G7")


@dataclass(frozen=True)
class RegressionResult:
    path: Path
    report: dict[str, Any]
    changed: bool


def _review_ref(workspace: Path, review_type: str, path: Path, report: dict[str, Any]) -> dict[str, Any]:
    report_id = report.get("review_id") if review_type == "deterministic" else report.get("report_id")
    return {
        "review_type": review_type,
        "report_id": str(report_id),
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "status": str(report["status"]),
    }


def _artifact_from_ref(workspace: Path, ref: dict[str, Any]) -> dict[str, Any]:
    state = read_json(workspace / "project_state.json")
    artifact_type = str(ref["artifact_type"])
    entry = next((item for item in state.get("artifacts", []) if item.get("artifact_type") == artifact_type), None)
    if entry is None:
        raise ReviewRegressionError(f"Regression references unknown artifact: {artifact_type}")
    version = int(ref["version"])
    current = int(entry["version"])
    if version == current:
        path = workspace / str(entry["path"])
    elif 1 <= version < current:
        path = workspace / ".slidethus/history" / artifact_type / f"{version:06d}.json"
    else:
        raise ReviewRegressionError(f"Regression references unknown {artifact_type} version {version}")
    path = ensure_within(workspace, path)
    data = read_json(path)
    if f"sha256:{sha256_json(data)}" != ref.get("content_hash"):
        raise ReviewRegressionError(f"Regression artifact hash mismatch: {artifact_type}")
    return data


def _current_refs(runtime: ArtifactRuntime) -> list[dict[str, Any]]:
    state = runtime.show_artifact("project_state")
    refs = [
        {
            "artifact_type": str(item["artifact_type"]),
            "version": int(item["version"]),
            "content_hash": str(item["content_hash"]),
        }
        for item in state.get("artifacts", [])
        if item.get("artifact_type")
        in {
            "asset_manifest", "deck_outline", "evidence_ledger", "layout_plans",
            "narrative_blueprint", "project_brief", "render_manifest", "slide_specs",
            "source_ledger", "visual_system",
        }
    ]
    return sorted(refs, key=lambda item: item["artifact_type"])


def _by_type(refs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["artifact_type"]): item for item in refs}


def _slide_maps(workspace: Path, refs: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    mapping = _by_type(refs)
    outline = _artifact_from_ref(workspace, mapping["deck_outline"])
    specs = _artifact_from_ref(workspace, mapping["slide_specs"])
    layout = _artifact_from_ref(workspace, mapping["layout_plans"])
    outline_map = {
        str(item["slide_id"]): sha256_json(item)
        for item in outline.get("slides", [])
        if item.get("status") != "excluded"
    }
    specs_map = {str(item["slide_id"]): sha256_json(item) for item in specs.get("slides", [])}
    layout_map = {str(item["slide_id"]): sha256_json(item) for item in layout.get("plans", [])}
    return outline_map, specs_map, layout_map


def _render_slides(runtime: ArtifactRuntime) -> set[str]:
    manifest = runtime.show_artifact("render_manifest")
    final_svg: set[str] = set()
    png: set[str] = set()
    for output in manifest.get("outputs", []):
        if output.get("role") not in {"final_svg", "export_png"}:
            continue
        match = _SLIDE_FROM_NAME.match(Path(str(output.get("path", ""))).name)
        if match is None:
            continue
        if output.get("role") == "final_svg":
            final_svg.add(match.group(1))
        else:
            png.add(match.group(1))
    return final_svg & png


class ReviewRegressionService:
    """Verify repaired scope, untouched slides and full-deck Gate/render integrity."""

    def __init__(
        self,
        workspace: Path,
        *,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.report_dir = self.workspace / ".slidethus/review/regression"

    def run(
        self,
        deterministic: DeterministicReviewResult,
        semantic: SemanticReviewResult,
        scorecard: SemanticScorecardResult,
        visual: VisualReviewResult,
        *,
        repair: RepairExecutionResult | None = None,
        persist: bool = True,
    ) -> RegressionResult:
        review_inputs = sorted(
            [
                _review_ref(self.workspace, "deterministic", deterministic.path, deterministic.report),
                _review_ref(self.workspace, "semantic", semantic.path, semantic.report),
                _review_ref(self.workspace, "scorecard", scorecard.path, scorecard.report),
                _review_ref(self.workspace, "visual", visual.path, visual.report),
            ],
            key=lambda item: item["review_type"],
        )
        current = _current_refs(self.runtime)
        repair_ref: dict[str, Any] | None = None
        if repair is None:
            before = current
            after = current
            changed_slides: set[str] = set()
            allowed_artifacts: set[str] = set()
        else:
            errors = repair_report_reference_errors(self.workspace, repair.path, self.schemas.schema_dir)
            if errors:
                raise ReviewRegressionError("Regression requires a valid repair report: " + "; ".join(errors))
            repair_ref = {
                "repair_id": str(repair.report["repair_id"]),
                "path": repair.path.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(repair.path),
                "status": str(repair.report["status"]),
            }
            before = list(repair.report["before_inputs"])
            after = list(repair.report["after_inputs"])
            changed_slides = set(str(item) for item in repair.report.get("changed_slides", []))
            plan_path = ensure_within(
                self.workspace,
                self.workspace / Path(str(repair.report["plan"]["path"])),
            )
            plan = read_json(plan_path)
            allowed_artifacts = set(str(item) for item in plan.get("expected_invalidations", []))

        before_map = _by_type(before)
        after_map = _by_type(after)
        artifact_types = sorted(set(before_map) | set(after_map))
        artifact_changes: list[dict[str, Any]] = []
        for artifact_type in artifact_types:
            changed = before_map.get(artifact_type) != after_map.get(artifact_type)
            artifact_changes.append(
                {
                    "artifact_type": artifact_type,
                    "changed": changed,
                    "allowed": (not changed) or artifact_type in allowed_artifacts,
                }
            )

        gate_results: list[dict[str, Any]] = []
        for gate_id in _GATE_IDS:
            result = evaluate_gate(self.workspace, gate_id)
            gate_results.append(
                {"gate_id": gate_id, "status": result.status, "reasons": list(result.reasons)}
            )

        before_outline, before_specs, before_layout = _slide_maps(self.workspace, before)
        current_outline, current_specs, current_layout = _slide_maps(self.workspace, current)
        render_slides = _render_slides(self.runtime)
        slide_ids = sorted(current_outline)
        slide_results: list[dict[str, Any]] = []
        for slide_id in slide_ids:
            expected_change = slide_id in changed_slides
            semantic_unchanged = (
                before_outline.get(slide_id) == current_outline.get(slide_id)
                and before_specs.get(slide_id) == current_specs.get(slide_id)
            )
            layout_unchanged = before_layout.get(slide_id) == current_layout.get(slide_id)
            render_present = slide_id in render_slides
            passed = render_present and (expected_change or (semantic_unchanged and layout_unchanged))
            slide_results.append(
                {
                    "slide_id": slide_id,
                    "expected_change": expected_change,
                    "semantic_unchanged": semantic_unchanged,
                    "layout_unchanged": layout_unchanged,
                    "render_present": render_present,
                    "status": "pass" if passed else "fail",
                }
            )

        gate_failures = sum(item["status"] != "pass" for item in gate_results)
        unexpected = sum(item["changed"] and not item["allowed"] for item in artifact_changes)
        slide_failures = sum(item["status"] == "fail" for item in slide_results)
        blocked = any(item["status"] == "blocked" for item in review_inputs)
        if repair_ref is not None and repair_ref["status"] in {"blocked", "failed"}:
            blocked = True
        status = "blocked" if blocked else ("issues" if gate_failures or unexpected or slide_failures else "pass")
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(self.runtime.show_artifact("project_state")["project_id"]),
            "regression_id": "",
            "repair": repair_ref,
            "review_inputs": review_inputs,
            "gate_results": gate_results,
            "artifact_changes": artifact_changes,
            "slide_results": slide_results,
            "summary": {
                "gate_failures": gate_failures,
                "unexpected_artifact_changes": unexpected,
                "slide_failures": slide_failures,
                "changed_slide_count": len(changed_slides),
                "unchanged_slide_count": len(slide_results) - len(changed_slides),
            },
            "status": status,
        }
        report["regression_id"] = regression_id(report)
        errors = validate_regression_data(report, self.schemas.schema_dir)
        if errors:
            raise ReviewRegressionError("Invalid Review Regression Report: " + "; ".join(errors))
        path = self.report_dir / f"{regression_file_key(report)}.json"
        if not persist:
            return RegressionResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise ReviewRegressionError(f"Immutable Review Regression contains different content: {path}")
        return RegressionResult(path=path, report=report, changed=changed)
