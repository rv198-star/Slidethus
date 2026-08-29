from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.errors import ReviewSynthesisError
from slidethus.io_utils import atomic_create_json, read_json, sha256_file
from slidethus.protocols import ReviewSynthesisProvider
from slidethus.review_syntheses import (
    cluster_scope,
    max_severity,
    promotion_decision,
    synthesis_cluster_id,
    synthesis_file_key,
    synthesis_report_id,
    validate_synthesis_data,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.stage_ai_review import StageAIReviewResult
from slidethus.stage_ai_reviews import STAGES, stage_review_reference_errors

_CODE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")
_ORDER = {stage: i for i, stage in enumerate(STAGES)}
_FORBIDDEN = {
    "recommended_fix", "repair", "repairability", "patch", "mutation",
    "replacement", "new_value", "promotion_eligible", "promotion_reason",
    "max_severity", "scope",
}


@dataclass(frozen=True)
class ReviewSynthesisResult:
    path: Path
    report: dict[str, Any]
    changed: bool


def _identity(provider: ReviewSynthesisProvider | None) -> dict[str, str] | None:
    if provider is None:
        return None
    name = str(getattr(provider, "name", "")).strip()
    version = str(getattr(provider, "version", "")).strip()
    if not name or not version:
        raise ReviewSynthesisError("ReviewSynthesisProvider requires name/version")
    return {"name": name, "version": version}


def _text(value: Any, field: str) -> str:
    value = " ".join(str(value or "").split()).strip()
    if not value:
        raise ReviewSynthesisError(f"Review Synthesis requires {field}")
    return value


class ReviewSynthesisService:
    """Attribute one completed review set; never mutate Production artifacts."""

    def __init__(
        self,
        workspace: Path,
        workflow_report_id: str,
        *,
        provider: ReviewSynthesisProvider | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.workflow_report_id = workflow_report_id
        self.provider = provider
        self.provider_identity = _identity(provider)
        self.schemas = schema_registry or SchemaRegistry()
        self.report_dir = self.workspace / ".slidethus/review/synthesis"

    def _inputs(
        self, reviews: tuple[StageAIReviewResult, ...]
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        by_stage: dict[str, StageAIReviewResult] = {}
        issue_map: dict[str, dict[str, Any]] = {}
        refs: list[dict[str, Any]] = []
        for result in reviews:
            report = result.report
            stage = str(report.get("stage", ""))
            if stage not in STAGES or stage in by_stage:
                raise ReviewSynthesisError(f"Duplicate/invalid Stage AI Review stage: {stage}")
            if str(report.get("workflow_report", {}).get("report_id", "")) != self.workflow_report_id:
                raise ReviewSynthesisError("Stage AI Review belongs to a different attempt")
            if not result.path.is_file():
                raise ReviewSynthesisError("Synthesis requires persisted Stage AI Review facts")
            errors = stage_review_reference_errors(self.workspace, result.path, self.schemas.schema_dir)
            if errors:
                raise ReviewSynthesisError(f"Invalid Stage AI Review {stage}: " + "; ".join(errors))
            by_stage[stage] = result
            refs.append({
                "report_id": str(report["report_id"]),
                "stage": stage,
                "path": result.path.relative_to(self.workspace).as_posix(),
                "sha256": sha256_file(result.path),
                "status": str(report["status"]),
            })
            for issue in report.get("issues", []):
                issue_id = str(issue["issue_id"])
                if issue_id in issue_map:
                    raise ReviewSynthesisError(f"Duplicate Stage AI issue: {issue_id}")
                issue_map[issue_id] = issue
        missing = [stage for stage in STAGES if stage not in by_stage]
        if missing:
            raise ReviewSynthesisError("Missing stage lenses: " + ", ".join(missing))
        refs.sort(key=lambda item: _ORDER[item["stage"]])
        return refs, issue_map

    def _cluster(
        self, raw: dict[str, Any], issue_map: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        forbidden = sorted(_FORBIDDEN.intersection(raw))
        if forbidden:
            raise ReviewSynthesisError(
                "Synthesis cannot prescribe repair/promotion internals: " + ", ".join(forbidden)
            )
        code = str(raw.get("pattern_code", "")).strip()
        if not _CODE.fullmatch(code):
            raise ReviewSynthesisError(f"Invalid synthesis pattern_code: {code}")
        issue_ids = sorted(set(str(item) for item in raw.get("issue_ids", [])))
        if not issue_ids or not set(issue_ids).issubset(issue_map):
            raise ReviewSynthesisError("Synthesis cluster has missing/unknown issue_ids")
        issues = [issue_map[item] for item in issue_ids]
        classification = str(raw.get("classification", ""))
        if classification not in {"case_local", "systemic_candidate"}:
            raise ReviewSynthesisError(f"Invalid synthesis classification: {classification}")
        root = str(raw.get("root_phase", ""))
        if root not in _ORDER:
            raise ReviewSynthesisError(f"Invalid synthesis root_phase: {root}")
        earliest = min((str(item["earliest_phase"]) for item in issues), key=_ORDER.__getitem__)
        if _ORDER[root] > _ORDER[earliest]:
            raise ReviewSynthesisError("Synthesis root cannot move later than admitted earliest responsibility")
        statement = _text(raw.get("scenario_independent_statement"), "scenario_independent_statement")
        eligible, reason = promotion_decision(classification, statement, issues)
        cluster: dict[str, Any] = {
            "cluster_id": "",
            "pattern_code": code,
            "title": _text(raw.get("title"), "title"),
            "scenario_independent_statement": statement,
            "issue_ids": issue_ids,
            "max_severity": max_severity(issues),
            "root_phase": root,
            "attribution": _text(raw.get("attribution"), "attribution"),
            "scope": cluster_scope(issues),
            "classification": classification,
            "promotion_eligible": eligible,
            "promotion_reason": reason,
        }
        cluster["cluster_id"] = synthesis_cluster_id(cluster)
        return cluster

    def _context(
        self, reviews: tuple[StageAIReviewResult, ...], issue_map: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "mode": "whole_attempt_attribution",
            "workflow_report": reviews[0].report["workflow_report"],
            "stage_reviews": [result.report for result in reviews],
            "issues": [issue_map[key] for key in sorted(issue_map)],
            "rules": {
                "attribution_before_change": True,
                "repairs_forbidden": True,
                "all_issues_must_be_accounted_for": True,
                "anti_overfit_question": (
                    "After removing topic, exact wording, slide IDs and business scenario, "
                    "does the systemic statement remain a valid production rule?"
                ),
            },
        }

    def synthesize(
        self, reviews: tuple[StageAIReviewResult, ...], *, persist: bool = True
    ) -> ReviewSynthesisResult:
        if not reviews:
            raise ReviewSynthesisError("Review Synthesis requires Stage AI Review inputs")
        refs, issue_map = self._inputs(reviews)
        workflow_ref = dict(reviews[0].report["workflow_report"])
        project_id = str(reviews[0].report["project_id"])
        blocked = [str(r.report["stage"]) for r in reviews if r.report.get("status") == "blocked"]
        if blocked:
            clusters: list[dict[str, Any]] = []
            unclustered = sorted(issue_map)
            capability = {
                "status": "missing",
                "detail": "Stage AI Review capability missing for: " + ", ".join(blocked),
            }
            status = "blocked"
        elif not issue_map:
            clusters, unclustered = [], []
            capability = {"status": "available", "detail": "Stage reviews found no open issues."}
            status = "pass"
        elif self.provider is None:
            clusters, unclustered = [], sorted(issue_map)
            capability = {"status": "missing", "detail": "No ReviewSynthesisProvider was injected."}
            status = "blocked"
        else:
            proposal = self.provider.synthesize(self._context(reviews, issue_map))
            if not isinstance(proposal, dict) or not isinstance(proposal.get("clusters", []), list):
                raise ReviewSynthesisError("ReviewSynthesisProvider must return clusters[]")
            if any(proposal.get(key) for key in ("repairs", "patches", "mutations", "recommended_fixes")):
                raise ReviewSynthesisError("Review Synthesis proposal contains repair fields")
            clusters = [self._cluster(item, issue_map) for item in proposal.get("clusters", [])]
            clusters.sort(key=lambda item: (_ORDER[item["root_phase"]], item["pattern_code"], item["cluster_id"]))
            clustered = [str(issue) for cluster in clusters for issue in cluster["issue_ids"]]
            if len(clustered) != len(set(clustered)):
                raise ReviewSynthesisError("One issue was assigned to multiple synthesis clusters")
            raw_unclustered = proposal.get("unclustered_issue_ids")
            if not isinstance(raw_unclustered, list):
                raise ReviewSynthesisError("Provider must explicitly return unclustered_issue_ids[]")
            unclustered = sorted(set(str(item) for item in raw_unclustered))
            if not set(unclustered).issubset(issue_map) or set(clustered).intersection(unclustered):
                raise ReviewSynthesisError("Invalid unclustered issue membership")
            if set(clustered) | set(unclustered) != set(issue_map):
                raise ReviewSynthesisError("Synthesis must account for every Stage AI issue")
            capability = {
                "status": "available",
                "detail": f"Attribution admitted from {self.provider_identity['name']} {self.provider_identity['version']}.",
            }
            status = "issues" if clusters or unclustered else "pass"
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": project_id,
            "report_id": "",
            "review_mode": "whole_attempt_attribution",
            "provider": self.provider_identity if self.provider is not None else None,
            "capability": capability,
            "workflow_report": workflow_ref,
            "stage_reviews": refs,
            "clusters": clusters,
            "unclustered_issue_ids": unclustered,
            "summary": {
                "stage_review_count": len(refs),
                "issue_count": len(issue_map),
                "cluster_count": len(clusters),
                "systemic_candidate_count": sum(c["classification"] == "systemic_candidate" for c in clusters),
                "case_local_count": sum(c["classification"] == "case_local" for c in clusters),
                "unclustered_count": len(unclustered),
            },
            "status": status,
        }
        report["report_id"] = synthesis_report_id(report)
        errors = validate_synthesis_data(report, self.schemas.schema_dir)
        if errors:
            raise ReviewSynthesisError("Invalid Review Synthesis Report: " + "; ".join(errors))
        path = self.report_dir / f"{synthesis_file_key(report)}.json"
        if not persist:
            return ReviewSynthesisResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise ReviewSynthesisError(f"Immutable Review Synthesis conflict: {path}")
        return ReviewSynthesisResult(path=path, report=report, changed=changed)
