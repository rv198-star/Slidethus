from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.deterministic_reviews import deterministic_review_reference_errors
from slidethus.errors import SemanticReviewError
from slidethus.io_utils import atomic_create_json, read_json, sha256_file
from slidethus.protocols import SemanticReviewProvider
from slidethus.schema_registry import SchemaRegistry
from slidethus.semantic_reviews import (
    SEMANTIC_DIMENSIONS,
    report_file_key,
    semantic_issue_id,
    semantic_review_id,
    semantic_scorecard_id,
    target_phase_for_issues,
    validate_semantic_review_data,
    validate_semantic_scorecard_data,
)
from slidethus.services.deterministic_review import DeterministicReviewService

_ARTIFACT_TYPES = (
    "deck_outline",
    "evidence_ledger",
    "layout_plans",
    "narrative_blueprint",
    "project_brief",
    "slide_specs",
    "source_ledger",
)
_PHASE_ORDER = {phase: index for index, phase in enumerate(("P0", "P1", "P2", "P3", "P4", "P5A", "P5B"))}
_ARTIFACT_OWNER = {
    "project_brief": "P0",
    "source_ledger": "P1",
    "evidence_ledger": "P2",
    "narrative_blueprint": "P3",
    "deck_outline": "P4",
    "slide_specs": "P5A",
    "layout_plans": "P5B",
}
_AUTOMATIC_CODES: set[str] = set()


@dataclass(frozen=True)
class SemanticReviewResult:
    path: Path
    report: dict[str, Any]
    changed: bool


@dataclass(frozen=True)
class SemanticScorecardResult:
    path: Path
    report: dict[str, Any]
    changed: bool


def _provider_identity(provider: SemanticReviewProvider | None) -> dict[str, str] | None:
    if provider is None:
        return None
    name = str(getattr(provider, "name", "")).strip()
    version = str(getattr(provider, "version", "")).strip()
    if not name or not version:
        raise SemanticReviewError("SemanticReviewProvider must declare non-empty name/version")
    return {"name": name, "version": version}


def _artifact_refs(runtime: ArtifactRuntime) -> list[dict[str, Any]]:
    state = runtime.show_artifact("project_state")
    entries = {
        str(item.get("artifact_type")): item for item in state.get("artifacts", [])
    }
    refs: list[dict[str, Any]] = []
    for artifact_type in _ARTIFACT_TYPES:
        _data, version = runtime.read_artifact_snapshot(artifact_type)
        entry = entries.get(artifact_type)
        if entry is None:
            raise SemanticReviewError(f"Current artifact is not registered: {artifact_type}")
        refs.append(
            {
                "artifact_type": artifact_type,
                "version": version,
                "content_hash": str(entry["content_hash"]),
            }
        )
    return sorted(refs, key=lambda item: item["artifact_type"])


def _runtime_ref(workspace: Path, path: Path, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": str(report["review_id"]),
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "status": str(report["status"]),
    }


def _score_source_ref(workspace: Path, path: Path, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": str(report["report_id"]),
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "status": str(report["status"]),
    }


def _text(value: Any, field: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        raise SemanticReviewError(f"Semantic review issue requires {field}")
    return normalized


class SemanticReviewService:
    """Admit provider-proposed semantic issues and scorecards as immutable M5 facts."""

    def __init__(
        self,
        workspace: Path,
        *,
        provider: SemanticReviewProvider | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.provider = provider
        self.provider_identity = _provider_identity(provider)
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.open_dir = self.workspace / ".slidethus/review/semantic/open-issue"
        self.score_dir = self.workspace / ".slidethus/review/semantic/scorecard"

    def _deterministic_input(self) -> tuple[Path, dict[str, Any]]:
        result = DeterministicReviewService(self.workspace).analyze()
        errors = deterministic_review_reference_errors(
            self.workspace,
            result.path,
            self.schemas.schema_dir,
        )
        if errors:
            raise SemanticReviewError("Current deterministic review is invalid: " + "; ".join(errors))
        if result.report.get("status") != "pass":
            raise SemanticReviewError(
                "Semantic review requires a passing current deterministic review"
            )
        return result.path, result.report

    def _context(self) -> dict[str, Any]:
        return {
            "mode": "open_issue",
            "artifacts": {
                artifact_type: self.runtime.show_artifact(artifact_type)
                for artifact_type in _ARTIFACT_TYPES
            },
            "rules": {
                "scores_forbidden": True,
                "issue_fields": [
                    "code", "severity", "artifact_type", "slide_id", "block_id",
                    "region_id", "earliest_phase", "finding", "impact", "evidence_ids",
                    "recommended_fix", "verification", "repairability",
                ],
            },
        }

    def _admit_issue(self, raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        artifact_type = str(raw.get("artifact_type", ""))
        if artifact_type not in _ARTIFACT_OWNER:
            raise SemanticReviewError(f"Semantic issue references unsupported artifact_type: {artifact_type}")
        earliest = str(raw.get("earliest_phase", ""))
        if earliest not in _PHASE_ORDER:
            raise SemanticReviewError(f"Semantic issue has unsupported earliest_phase: {earliest}")
        owner = _ARTIFACT_OWNER[artifact_type]
        if _PHASE_ORDER[earliest] > _PHASE_ORDER[owner]:
            raise SemanticReviewError(
                f"Semantic issue route is later than its referenced artifact owner: {earliest} > {owner}"
            )
        severity = str(raw.get("severity", ""))
        if severity not in {"critical", "major", "minor"}:
            raise SemanticReviewError(f"Semantic issue has unsupported severity: {severity}")
        slide_id = raw.get("slide_id")
        block_id = raw.get("block_id")
        region_id = raw.get("region_id")
        artifacts = context["artifacts"]
        slides = {
            str(item["slide_id"])
            for item in artifacts["deck_outline"].get("slides", [])
            if item.get("status") != "excluded"
        }
        blocks = {
            str(block["block_id"]): str(slide["slide_id"])
            for slide in artifacts["slide_specs"].get("slides", [])
            for block in slide.get("content_blocks", [])
        }
        regions = {
            str(region["region_id"]): str(slide["slide_id"])
            for slide in artifacts["layout_plans"].get("slides", [])
            for region in slide.get("regions", [])
        }
        known_evidence = {
            str(item["evidence_id"])
            for item in artifacts["evidence_ledger"].get("claims", [])
        }
        if slide_id is not None and str(slide_id) not in slides:
            raise SemanticReviewError(f"Semantic issue references unknown slide: {slide_id}")
        if block_id is not None:
            block_key = str(block_id)
            if block_key not in blocks:
                raise SemanticReviewError(f"Semantic issue references unknown block: {block_id}")
            if slide_id is None or blocks[block_key] != str(slide_id):
                raise SemanticReviewError("Semantic issue block/slide reference is inconsistent")
        if region_id is not None:
            region_key = str(region_id)
            if region_key not in regions:
                raise SemanticReviewError(f"Semantic issue references unknown region: {region_id}")
            if slide_id is None or regions[region_key] != str(slide_id):
                raise SemanticReviewError("Semantic issue region/slide reference is inconsistent")
        evidence_ids = sorted(set(str(item) for item in raw.get("evidence_ids", [])))
        unknown_evidence = sorted(set(evidence_ids) - known_evidence)
        if unknown_evidence:
            raise SemanticReviewError(
                "Semantic issue references unknown Evidence IDs: " + ", ".join(unknown_evidence)
            )
        code = str(raw.get("code", "")).strip()
        if not code:
            raise SemanticReviewError("Semantic issue requires code")
        repairability = str(raw.get("repairability", "assisted"))
        if repairability not in {"automatic", "assisted", "manual"}:
            raise SemanticReviewError(f"Semantic issue has unsupported repairability: {repairability}")
        if repairability == "automatic" and code not in _AUTOMATIC_CODES:
            repairability = "assisted"
        issue: dict[str, Any] = {
            "issue_id": "",
            "code": code,
            "severity": severity,
            "status": "open",
            "artifact_type": artifact_type,
            "slide_id": str(slide_id) if slide_id is not None else None,
            "block_id": str(block_id) if block_id is not None else None,
            "region_id": str(region_id) if region_id is not None else None,
            "earliest_phase": earliest,
            "finding": _text(raw.get("finding"), "finding"),
            "impact": _text(raw.get("impact"), "impact"),
            "evidence_ids": evidence_ids,
            "recommended_fix": _text(raw.get("recommended_fix"), "recommended_fix"),
            "verification": _text(raw.get("verification"), "verification"),
            "repairability": repairability,
        }
        issue["issue_id"] = semantic_issue_id(issue)
        return issue

    def open_issues(self, *, persist: bool = True) -> SemanticReviewResult:
        deterministic_path, deterministic = self._deterministic_input()
        state = self.runtime.show_artifact("project_state")
        dref = _runtime_ref(self.workspace, deterministic_path, deterministic)
        inputs = _artifact_refs(self.runtime)
        if self.provider is None:
            report: dict[str, Any] = {
                "schema_version": "0.1.0",
                "project_id": str(state["project_id"]),
                "report_id": "",
                "review_mode": "open_issue",
                "provider": None,
                "capability": {
                    "status": "missing",
                    "detail": "No SemanticReviewProvider was injected; semantic issue mining is blocked explicitly.",
                },
                "deterministic_review": dref,
                "inputs": inputs,
                "issues": [],
                "summary": {"critical_count": 0, "major_count": 0, "minor_count": 0, "open_count": 0},
                "status": "blocked",
                "target_phase": None,
            }
        else:
            context = self._context()
            proposal = self.provider.review(context)
            if not isinstance(proposal, dict) or not isinstance(proposal.get("issues", []), list):
                raise SemanticReviewError("SemanticReviewProvider must return an object with issues[]")
            if proposal.get("dimensions") or proposal.get("scores"):
                raise SemanticReviewError("Open issue mining cannot contain scores or dimensions")
            issues = [self._admit_issue(item, context) for item in proposal.get("issues", [])]
            issue_ids = [str(item["issue_id"]) for item in issues]
            if len(issue_ids) != len(set(issue_ids)):
                raise SemanticReviewError("Semantic provider proposed duplicate issue identities")
            issues.sort(key=lambda item: (item["severity"], item["issue_id"]))
            report = {
                "schema_version": "0.1.0",
                "project_id": str(state["project_id"]),
                "report_id": "",
                "review_mode": "open_issue",
                "provider": self.provider_identity,
                "capability": {
                    "status": "available",
                    "detail": f"Semantic review proposal admitted from {self.provider_identity['name']} {self.provider_identity['version']}.",
                },
                "deterministic_review": dref,
                "inputs": inputs,
                "issues": issues,
                "summary": {
                    "critical_count": sum(item["severity"] == "critical" for item in issues),
                    "major_count": sum(item["severity"] == "major" for item in issues),
                    "minor_count": sum(item["severity"] == "minor" for item in issues),
                    "open_count": len(issues),
                },
                "status": "issues" if issues else "pass",
                "target_phase": target_phase_for_issues(issues),
            }
        report["report_id"] = semantic_review_id(report)
        errors = validate_semantic_review_data(report, self.schemas.schema_dir)
        if errors:
            raise SemanticReviewError("Invalid Semantic Review Report: " + "; ".join(errors))
        path = self.open_dir / f"{report_file_key(report)}.json"
        if not persist:
            return SemanticReviewResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise SemanticReviewError(f"Immutable Semantic Review contains different content: {path}")
        return SemanticReviewResult(path=path, report=report, changed=changed)

    def scorecard(
        self,
        source: SemanticReviewResult | None = None,
        *,
        persist: bool = True,
    ) -> SemanticScorecardResult:
        source_result = source or self.open_issues()
        source_report = source_result.report
        source_ref = _score_source_ref(self.workspace, source_result.path, source_report)
        state = self.runtime.show_artifact("project_state")
        if source_report.get("status") == "blocked" or self.provider is None:
            report: dict[str, Any] = {
                "schema_version": "0.1.0",
                "project_id": str(state["project_id"]),
                "report_id": "",
                "review_mode": "scorecard",
                "provider": None,
                "capability": {
                    "status": "missing",
                    "detail": "Semantic scorecard requires an available SemanticReviewProvider and completed Round A.",
                },
                "source_review": source_ref,
                "dimensions": [
                    {"dimension": name, "score": 0, "rationale": "Capability unavailable.", "issue_ids": []}
                    for name in SEMANTIC_DIMENSIONS
                ],
                "summary": {"overall_score": 0.0, "blocking_count": 0, "minimum_score": 0},
                "status": "blocked",
            }
        else:
            context = {
                "mode": "scorecard",
                "artifacts": self._context()["artifacts"],
                "issues": source_report.get("issues", []),
                "dimensions": list(SEMANTIC_DIMENSIONS),
                "rules": {"no_new_issues": True, "blocking_severity_overrides_score": True},
            }
            proposal = self.provider.review(context)
            raw_dimensions = proposal.get("dimensions", []) if isinstance(proposal, dict) else []
            if not isinstance(raw_dimensions, list):
                raise SemanticReviewError("Semantic scorecard provider must return dimensions[]")
            known = {str(item["issue_id"]) for item in source_report.get("issues", [])}
            dimensions: list[dict[str, Any]] = []
            seen: set[str] = set()
            for raw in raw_dimensions:
                name = str(raw.get("dimension", ""))
                if name not in SEMANTIC_DIMENSIONS or name in seen:
                    raise SemanticReviewError(f"Invalid/duplicate semantic score dimension: {name}")
                seen.add(name)
                score = raw.get("score")
                if not isinstance(score, int) or not 0 <= score <= 5:
                    raise SemanticReviewError(f"Invalid semantic score for {name}: {score}")
                issue_ids = sorted(set(str(item) for item in raw.get("issue_ids", [])))
                unknown = sorted(set(issue_ids) - known)
                if unknown:
                    raise SemanticReviewError(
                        f"Semantic scorecard {name} references unknown issues: {', '.join(unknown)}"
                    )
                dimensions.append(
                    {
                        "dimension": name,
                        "score": score,
                        "rationale": _text(raw.get("rationale"), f"{name}.rationale"),
                        "issue_ids": issue_ids,
                    }
                )
            if seen != set(SEMANTIC_DIMENSIONS):
                missing = sorted(set(SEMANTIC_DIMENSIONS) - seen)
                raise SemanticReviewError("Semantic scorecard missing dimensions: " + ", ".join(missing))
            dimensions.sort(key=lambda item: item["dimension"])
            scores = [int(item["score"]) for item in dimensions]
            blockers = [
                item for item in source_report.get("issues", [])
                if item.get("status") == "open" and item.get("severity") in {"critical", "major"}
            ]
            report = {
                "schema_version": "0.1.0",
                "project_id": str(state["project_id"]),
                "report_id": "",
                "review_mode": "scorecard",
                "provider": self.provider_identity,
                "capability": {
                    "status": "available",
                    "detail": f"Semantic scorecard admitted from {self.provider_identity['name']} {self.provider_identity['version']} after Round A.",
                },
                "source_review": source_ref,
                "dimensions": dimensions,
                "summary": {
                    "overall_score": round(sum(scores) / len(scores), 2),
                    "blocking_count": len(blockers),
                    "minimum_score": min(scores),
                },
                "status": "issues" if blockers else "pass",
            }
        report["report_id"] = semantic_scorecard_id(report)
        errors = validate_semantic_scorecard_data(report, self.schemas.schema_dir, source_report)
        if errors:
            raise SemanticReviewError("Invalid Semantic Scorecard: " + "; ".join(errors))
        path = self.score_dir / f"{report_file_key(report)}.json"
        if not persist:
            return SemanticScorecardResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise SemanticReviewError(f"Immutable Semantic Scorecard contains different content: {path}")
        return SemanticScorecardResult(path=path, report=report, changed=changed)
