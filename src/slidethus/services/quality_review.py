from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ArtifactError, ReviewRegressionError
from slidethus.io_utils import sha256_file, sha256_json
from slidethus.quality_reviews import production_quality_reference_errors
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.deterministic_review import DeterministicReviewResult
from slidethus.services.review_regression import RegressionResult
from slidethus.services.review_repair import RepairExecutionResult
from slidethus.services.semantic_review import SemanticReviewResult, SemanticScorecardResult
from slidethus.services.visual_review import VisualReviewResult
from slidethus.state_machine import Phase


@dataclass(frozen=True)
class QualityReviewResult:
    report: dict[str, Any]
    changed: bool


def _review_ref(
    workspace: Path,
    path: Path,
    report: dict[str, Any],
    *,
    id_key: str,
) -> dict[str, Any]:
    return {
        "report_id": str(report[id_key]),
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "status": str(report["status"]),
    }


def _quality_issue(
    quality_id: str,
    source_type: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    category = f"{source_type}:{source.get('code', 'issue')}"
    return {
        "issue_id": quality_id,
        "severity": str(source["severity"]),
        "category": category,
        "phase": str(source["earliest_phase"]),
        "slide_id": source.get("slide_id"),
        "block_id": source.get("block_id") if source_type == "semantic" else None,
        "region_id": source.get("region_id"),
        "finding": str(source["finding"]),
        "impact": str(source["impact"]),
        "recommended_fix": str(source["recommended_fix"]),
        "verification": str(source["verification"]),
        "status": "open",
    }


class ProductionQualityReviewService:
    """Aggregate current immutable M5 review facts into the catalog Quality Report and G8."""

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

    def publish(
        self,
        deterministic: DeterministicReviewResult,
        semantic: SemanticReviewResult,
        scorecard: SemanticScorecardResult,
        visual: VisualReviewResult,
        regression: RegressionResult,
        *,
        repair: RepairExecutionResult | None = None,
    ) -> QualityReviewResult:
        """Publish one Production Quality Report; G8 advances only on current passing evidence."""

        state = self.runtime.show_artifact("project_state")
        source_rows: list[tuple[str, str, dict[str, Any]]] = []
        for item in semantic.report.get("issues", []):
            if item.get("status") == "open":
                source_rows.append(("semantic", str(item["issue_id"]), item))
        for item in visual.report.get("issues", []):
            if item.get("status") == "open":
                source_rows.append(("visual", str(item["issue_id"]), item))
        source_rows.sort(key=lambda row: (row[0], row[1]))

        source_to_quality: dict[str, str] = {}
        issues: list[dict[str, Any]] = []
        issue_sources: list[dict[str, str]] = []
        for index, (source_type, source_id, source) in enumerate(source_rows, start=1):
            quality_id = f"ISS-{index:03d}"
            source_to_quality[source_id] = quality_id
            issues.append(_quality_issue(quality_id, source_type, source))
            issue_sources.append(
                {
                    "quality_issue_id": quality_id,
                    "source_issue_id": source_id,
                    "source_type": source_type,
                }
            )

        scores = []
        for dimension in scorecard.report.get("dimensions", []):
            unresolved = sorted(
                source_to_quality[source_id]
                for source_id in dimension.get("issue_ids", [])
                if source_id in source_to_quality
            )
            scores.append(
                {
                    "dimension": str(dimension["dimension"]),
                    "score": float(dimension["score"]),
                    "evidence": str(dimension["rationale"]),
                    "unresolved": unresolved,
                }
            )
        scores.sort(key=lambda item: item["dimension"])

        production_review = {
            "deterministic_review": _review_ref(
                self.workspace, deterministic.path, deterministic.report, id_key="review_id"
            ),
            "semantic_review": _review_ref(
                self.workspace, semantic.path, semantic.report, id_key="report_id"
            ),
            "semantic_scorecard": _review_ref(
                self.workspace, scorecard.path, scorecard.report, id_key="report_id"
            ),
            "visual_review": _review_ref(
                self.workspace, visual.path, visual.report, id_key="report_id"
            ),
            "repair_report": (
                _review_ref(self.workspace, repair.path, repair.report, id_key="repair_id")
                if repair is not None
                else None
            ),
            "regression_report": _review_ref(
                self.workspace, regression.path, regression.report, id_key="regression_id"
            ),
            "issue_sources": issue_sources,
        }

        blockers = [
            item for item in issues if item["severity"] in {"critical", "major"}
        ]
        capability_blocked = any(
            report.get("status") == "blocked"
            for report in (semantic.report, scorecard.report, visual.report, regression.report)
        )
        deterministic_failed = deterministic.report.get("status") != "pass"
        regression_failed = regression.report.get("status") != "pass"
        repair_failed = repair is not None and repair.report.get("status") in {"blocked", "failed"}
        if capability_blocked or deterministic_failed or regression.report.get("status") == "blocked" or repair_failed:
            status = "blocked"
            gate_status = "blocked"
        elif blockers or regression_failed:
            status = "fail"
            gate_status = "fail"
        else:
            status = "pass"
            gate_status = "pass"
        reasons: list[str] = []
        if deterministic_failed:
            reasons.append("deterministic review is not pass")
        if semantic.report.get("status") == "blocked":
            reasons.append("semantic review capability is blocked")
        if scorecard.report.get("status") == "blocked":
            reasons.append("semantic scorecard capability is blocked")
        if visual.report.get("status") == "blocked":
            reasons.append("visual review capability is blocked")
        if regression.report.get("status") != "pass":
            reasons.append(f"cross-deck regression status={regression.report.get('status')}")
        if repair_failed:
            reasons.append(f"repair status={repair.report.get('status')}")
        if blockers:
            reasons.append(f"{len(blockers)} Critical/Major review issue(s) remain open")

        identity = sha256_json(
            {
                "project_id": state["project_id"],
                "production_review": production_review,
                "issues": issues,
                "scores": scores,
                "status": status,
            }
        )[:16].upper()
        report: dict[str, Any] = {
            "schema_version": "0.2.0",
            "project_id": str(state["project_id"]),
            "review_id": f"REV-M5-{identity}",
            "review_mode": "combined",
            "reviewer": "m5-production-review",
            "issues": issues,
            "scores": scores,
            "production_review": production_review,
            "gate_result": {
                "gate_id": "G8",
                "status": gate_status,
                "reasons": reasons,
            },
            "status": status,
        }
        schema_errors = [
            error.message
            for error in self.schemas.validator("quality_report").iter_errors(report)
        ]
        if schema_errors:
            raise ReviewRegressionError(
                "Invalid Production Quality Report: " + "; ".join(schema_errors)
            )
        lineage_errors = production_quality_reference_errors(
            self.workspace,
            report,
            self.schemas.schema_dir,
        )
        if lineage_errors and status == "pass":
            raise ReviewRegressionError(
                "Passing Production Quality Report has invalid lineage: "
                + "; ".join(lineage_errors)
            )

        try:
            current, version = self.runtime.read_artifact_snapshot("quality_report")
        except ArtifactError:
            current, version = None, 0
        if current == report:
            changed = False
        else:
            self.runtime.write_artifact(
                "quality_report",
                report,
                expected_version=version,
                status="approved" if status == "pass" else "reviewed",
                created_by="m5-production-review",
            )
            changed = True
        latest_state = self.runtime.show_artifact("project_state")
        existing_g8 = next(
            (
                item
                for item in latest_state.get("completed_gates", [])
                if item.get("gate_id") == "G8" and item.get("status") in {"pass", "waived"}
            ),
            None,
        )
        if status == "pass" and existing_g8 is None:
            gate = self.runtime.record_gate("G8", target_phase=Phase.REVIEWED)
            if gate.status != "pass":
                raise ReviewRegressionError(
                    "Production Quality Report is pass but persisted G8 failed: "
                    + "; ".join(gate.reasons)
                )
        elif status != "pass":
            self.runtime.record_gate("G8")
        return QualityReviewResult(report=report, changed=changed)
