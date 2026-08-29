from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import M5ApplicationError, SlidethusError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import atomic_create_json, read_json, sha256_file, sha256_json
from slidethus.m5_application_reports import (
    m5_report_file_key,
    m5_report_id,
    validate_m5_report_data,
)
from slidethus.protocols import SemanticReviewProvider, VisualReviewProvider
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.deterministic_review import DeterministicReviewService
from slidethus.services.quality_review import ProductionQualityReviewService
from slidethus.services.review_regression import ReviewRegressionService
from slidethus.services.review_repair import (
    RepairExecutionResult,
    ReviewRepairExecutionService,
    ReviewRepairPlanService,
)
from slidethus.services.semantic_review import SemanticReviewService
from slidethus.services.visual_review import VisualReviewService


@dataclass(frozen=True)
class M5ApplicationRunResult:
    report: dict[str, Any]
    path: Path
    changed: bool


def _provider_label(provider: object | None) -> str | None:
    if provider is None:
        return None
    return f"{getattr(provider, 'name', '')}@{getattr(provider, 'version', '')}"


class M5ApplicationService:
    """Single M5 orchestrator from independent review through regression and G8."""

    def __init__(
        self,
        workspace: Path,
        *,
        semantic_provider: SemanticReviewProvider | None = None,
        visual_provider: VisualReviewProvider | None = None,
        renderer_root: Path | None = None,
        node: str | None = None,
        font_match: str | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.semantic_provider = semantic_provider
        self.visual_provider = visual_provider
        self.renderer_root = renderer_root
        self.node = node
        self.font_match = font_match
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.run_dir = self.workspace / ".slidethus/m5/runs"
        self.quality_snapshot_dir = self.workspace / ".slidethus/m5/quality"

    @staticmethod
    def _add_action(
        actions: list[dict[str, Any]],
        *,
        stage: str,
        status: str,
        detail: str,
        refs: tuple[str, ...] = (),
    ) -> None:
        actions.append(
            {
                "action_id": f"M5A-{len(actions) + 1:03d}",
                "stage": stage,
                "status": status,
                "detail": detail,
                "refs": list(refs),
            }
        )

    @staticmethod
    def _ref(workspace: Path, path: Path, report: dict[str, Any], id_key: str) -> dict[str, Any]:
        return {
            "id": str(report[id_key]),
            "path": path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(path),
            "status": str(report["status"]),
        }

    def _quality_snapshot(self, report: dict[str, Any]) -> Path:
        digest = sha256_json(report)
        path = self.quality_snapshot_dir / f"{digest}.json"
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise M5ApplicationError(f"Immutable M5 Quality snapshot contains different content: {path}")
        return path

    def _persist(
        self,
        *,
        config: dict[str, Any],
        status: str,
        actions: list[dict[str, Any]],
        blockers: list[dict[str, str]],
        reviews: dict[str, Any],
        capabilities: list[dict[str, str]],
        g8: dict[str, Any],
    ) -> M5ApplicationRunResult:
        state = self.runtime.show_artifact("project_state")
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(state["project_id"]),
            "report_id": "",
            "config": config,
            "config_hash": f"sha256:{sha256_json(config)}",
            "status": status,
            "final_phase": str(state["current_phase"]),
            "capabilities": sorted(capabilities, key=lambda item: item["capability"]),
            "actions": actions,
            "blockers": blockers,
            "reviews": reviews,
            "g8": g8,
            "project_state": {
                "revision": int(state["revision"]),
                "content_hash": f"sha256:{sha256_json(state)}",
            },
        }
        report["report_id"] = m5_report_id(report)
        errors = validate_m5_report_data(report, self.schemas.schema_dir)
        if errors:
            raise M5ApplicationError("Invalid M5 Application Report: " + "; ".join(errors))
        path = self.run_dir / f"{m5_report_file_key(report)}.json"
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise M5ApplicationError(f"Immutable M5 Application Report contains different content: {path}")
        return M5ApplicationRunResult(report=report, path=path, changed=changed)

    def run(self, *, auto_repair: bool = True) -> M5ApplicationRunResult:
        """Run/resume M5 with explicit provider capabilities and bounded automatic repair."""

        config = {
            "auto_repair": bool(auto_repair),
            "semantic_provider": _provider_label(self.semantic_provider),
            "visual_provider": _provider_label(self.visual_provider),
        }
        actions: list[dict[str, Any]] = []
        blockers: list[dict[str, str]] = []
        capabilities = [
            {
                "capability": "semantic_review",
                "status": "available" if self.semantic_provider is not None else "missing",
                "detail": "Injected SemanticReviewProvider is available."
                if self.semantic_provider is not None
                else "No SemanticReviewProvider was injected.",
            },
            {
                "capability": "visual_review",
                "status": "available" if self.visual_provider is not None else "missing",
                "detail": "Injected VisualReviewProvider is available."
                if self.visual_provider is not None
                else "No VisualReviewProvider was injected.",
            },
        ]
        reviews: dict[str, Any] = {
            "deterministic": None,
            "semantic": None,
            "scorecard": None,
            "visual": None,
            "repair_plan": None,
            "repair_report": None,
            "regression": None,
            "quality": None,
        }
        applied_repair: RepairExecutionResult | None = None

        try:
            deterministic = DeterministicReviewService(self.workspace).analyze()
            reviews["deterministic"] = self._ref(
                self.workspace, deterministic.path, deterministic.report, "review_id"
            )
            self._add_action(
                actions,
                stage="deterministic_review",
                status="complete",
                detail=f"M5.1 deterministic review status={deterministic.report['status']}.",
                refs=(str(deterministic.report["review_id"]),),
            )
            if deterministic.report["status"] != "pass":
                plan = ReviewRepairPlanService(self.workspace).plan(deterministic)
                reviews["repair_plan"] = self._ref(
                    self.workspace, plan.path, plan.plan, "plan_id"
                )
                automatic = bool(plan.plan.get("actions")) and all(
                    bool(item.get("automatic")) for item in plan.plan.get("actions", [])
                )
                if auto_repair and automatic:
                    applied_repair = ReviewRepairExecutionService(
                        self.workspace,
                        renderer_root=self.renderer_root,
                        node=self.node,
                        font_match=self.font_match,
                    ).execute(plan)
                    reviews["repair_report"] = self._ref(
                        self.workspace, applied_repair.path, applied_repair.report, "repair_id"
                    )
                    self._add_action(
                        actions,
                        stage="deterministic_repair",
                        status="complete" if applied_repair.report["status"] == "applied" else "failed",
                        detail=f"Bounded deterministic repair status={applied_repair.report['status']}.",
                        refs=(str(applied_repair.report["repair_id"]),),
                    )
                    if applied_repair.report["status"] != "applied":
                        blockers.append({"code": "deterministic_repair_failed", "message": "Automatic deterministic repair did not restore a passing M5.1 review."})
                    else:
                        deterministic = DeterministicReviewService(self.workspace).analyze()
                        reviews["deterministic"] = self._ref(
                            self.workspace, deterministic.path, deterministic.report, "review_id"
                        )
                else:
                    blockers.append(
                        {
                            "code": "deterministic_review_requires_repair",
                            "message": "M5.1 found issues that require assisted/manual repair or auto_repair is disabled.",
                        }
                    )
            if deterministic.report["status"] != "pass" or blockers:
                self._add_action(actions, stage="semantic_review", status="blocked", detail="Semantic review waits for deterministic integrity.")
                return self._persist(
                    config=config,
                    status="blocked",
                    actions=actions,
                    blockers=blockers or [{"code": "deterministic_review_failed", "message": "Deterministic review remains non-passing."}],
                    reviews=reviews,
                    capabilities=capabilities,
                    g8={"status": "not_run", "reasons": ["deterministic review did not pass"]},
                )

            semantic_service = SemanticReviewService(
                self.workspace,
                provider=self.semantic_provider,
            )
            semantic = semantic_service.open_issues()
            reviews["semantic"] = self._ref(self.workspace, semantic.path, semantic.report, "report_id")
            self._add_action(actions, stage="semantic_open_issue", status="complete" if semantic.report["status"] != "blocked" else "blocked", detail=f"M5.2 semantic Round A status={semantic.report['status']}.", refs=(str(semantic.report["report_id"]),))
            if semantic.report["status"] == "blocked":
                blockers.append({"code": "semantic_provider_missing", "message": "M5.2 requires an injected SemanticReviewProvider."})
                return self._persist(config=config, status="blocked", actions=actions, blockers=blockers, reviews=reviews, capabilities=capabilities, g8={"status": "not_run", "reasons": ["semantic review capability missing"]})

            scorecard = semantic_service.scorecard(semantic)
            reviews["scorecard"] = self._ref(self.workspace, scorecard.path, scorecard.report, "report_id")
            self._add_action(actions, stage="semantic_scorecard", status="complete", detail=f"M5.3 scorecard status={scorecard.report['status']}.", refs=(str(scorecard.report["report_id"]),))

            visual = VisualReviewService(
                self.workspace,
                provider=self.visual_provider,
            ).analyze(semantic, scorecard)
            reviews["visual"] = self._ref(self.workspace, visual.path, visual.report, "report_id")
            self._add_action(actions, stage="visual_review", status="complete" if visual.report["status"] != "blocked" else "blocked", detail=f"M5.4 visual review status={visual.report['status']}.", refs=(str(visual.report["report_id"]),))
            if visual.report["status"] == "blocked":
                blockers.append({"code": "visual_provider_missing", "message": "M5.4 requires an injected VisualReviewProvider."})
                return self._persist(config=config, status="blocked", actions=actions, blockers=blockers, reviews=reviews, capabilities=capabilities, g8={"status": "not_run", "reasons": ["visual review capability missing"]})

            blocking_issues = [
                item
                for report in (semantic.report, visual.report)
                for item in report.get("issues", [])
                if item.get("status") == "open" and item.get("severity") in {"critical", "major"}
            ]
            if blocking_issues:
                plan = ReviewRepairPlanService(self.workspace).plan(
                    deterministic,
                    semantic,
                    visual,
                )
                reviews["repair_plan"] = self._ref(self.workspace, plan.path, plan.plan, "plan_id")
                repair = ReviewRepairExecutionService(self.workspace).execute(plan)
                reviews["repair_report"] = self._ref(self.workspace, repair.path, repair.report, "repair_id")
                self._add_action(actions, stage="review_repair", status="blocked" if repair.report["status"] == "blocked" else "complete", detail=f"M5.5 review repair status={repair.report['status']}.", refs=(str(repair.report["repair_id"]),))
                blockers.append(
                    {
                        "code": "review_requires_rework",
                        "message": f"{len(blocking_issues)} Critical/Major semantic/visual issue(s) require root-phase repair before G8.",
                    }
                )
                return self._persist(config=config, status="blocked", actions=actions, blockers=blockers, reviews=reviews, capabilities=capabilities, g8={"status": "not_run", "reasons": ["Critical/Major review issues remain"]})

            regression = ReviewRegressionService(self.workspace).run(
                deterministic,
                semantic,
                scorecard,
                visual,
                repair=applied_repair,
            )
            reviews["regression"] = self._ref(self.workspace, regression.path, regression.report, "regression_id")
            self._add_action(actions, stage="cross_deck_regression", status="complete" if regression.report["status"] == "pass" else "failed", detail=f"M5.6 regression status={regression.report['status']}.", refs=(str(regression.report["regression_id"]),))
            if regression.report["status"] != "pass":
                blockers.append({"code": "regression_failed", "message": "Cross-deck regression did not pass."})
                return self._persist(config=config, status="failed", actions=actions, blockers=blockers, reviews=reviews, capabilities=capabilities, g8={"status": "not_run", "reasons": ["cross-deck regression failed"]})

            quality = ProductionQualityReviewService(self.workspace).publish(
                deterministic,
                semantic,
                scorecard,
                visual,
                regression,
                repair=applied_repair,
            )
            quality_path = self._quality_snapshot(quality.report)
            reviews["quality"] = self._ref(
                self.workspace,
                quality_path,
                quality.report,
                "review_id",
            )
            g8 = evaluate_gate(self.workspace, "G8")
            self._add_action(actions, stage="quality_g8", status="complete" if g8.status == "pass" else "failed", detail=f"Production Quality Report and G8 status={g8.status}.", refs=(str(quality.report["review_id"]),))
            if g8.status != "pass":
                blockers.append({"code": "g8_failed", "message": "; ".join(g8.reasons) or "G8 did not pass."})
                return self._persist(config=config, status="failed", actions=actions, blockers=blockers, reviews=reviews, capabilities=capabilities, g8={"status": g8.status, "reasons": list(g8.reasons)})
            return self._persist(config=config, status="ready", actions=actions, blockers=[], reviews=reviews, capabilities=capabilities, g8={"status": "pass", "reasons": []})
        except SlidethusError as exc:
            blockers.append({"code": "m5_execution_failed", "message": str(exc)})
            self._add_action(actions, stage="m5", status="failed", detail=str(exc))
            return self._persist(config=config, status="failed", actions=actions, blockers=blockers, reviews=reviews, capabilities=capabilities, g8={"status": "not_run", "reasons": [str(exc)]})


def evaluate_m5_workspace_gate(workspace: Path) -> dict[str, Any]:
    """Evaluate current Production M5 readiness without mutating the workspace."""

    g8 = evaluate_gate(workspace.resolve(), "G8")
    return {
        "status": "pass" if g8.status == "pass" else "fail",
        "reasons": list(g8.reasons),
        "g8": {"status": g8.status, "reasons": list(g8.reasons)},
    }
