from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import StageReviewError
from slidethus.io_utils import atomic_create_json, read_json
from slidethus.protocols import StageReviewProvider
from slidethus.schema_registry import SchemaRegistry
from slidethus.stage_ai_reviews import (
    STAGE_FOCUS_ARTIFACTS,
    STAGES,
    application_output_refs,
    derive_failure_facts,
    stage_is_applicable,
    stage_issue_id,
    stage_review_file_key,
    stage_review_id,
    stage_review_reference_errors,
    validate_stage_review_data,
    workflow_report_ref,
)
from slidethus.workflow_application_reports import workflow_report_reference_errors

_CODE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")
_STAGE_ORDER = {stage: index for index, stage in enumerate(STAGES)}
_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "suggestion": 3}
_FORBIDDEN_ISSUE_FIELDS = {
    "recommended_fix",
    "repair",
    "repairability",
    "patch",
    "mutation",
    "new_value",
    "replacement",
}


@dataclass(frozen=True)
class StageAIReviewResult:
    path: Path
    report: dict[str, Any]
    changed: bool


def _provider_identity(provider: StageReviewProvider | None) -> dict[str, str] | None:
    if provider is None:
        return None
    name = str(getattr(provider, "name", "")).strip()
    version = str(getattr(provider, "version", "")).strip()
    if not name or not version:
        raise StageReviewError("StageReviewProvider must declare non-empty name/version")
    return {"name": name, "version": version}


def _text(value: Any, field: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        raise StageReviewError(f"Stage AI Review issue requires {field}")
    return normalized


class StageAIReviewService:
    """Run retrospective, non-mutating stage lenses over one terminated Workflow Attempt."""

    def __init__(
        self,
        workspace: Path,
        workflow_report_id: str,
        *,
        provider: StageReviewProvider | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.workflow_report_id = workflow_report_id
        self.provider = provider
        self.provider_identity = _provider_identity(provider)
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.workflow_path, self.workflow = self._load_workflow()
        self.inputs = sorted(
            [dict(item) for item in self.workflow.get("artifacts_after", [])],
            key=lambda item: str(item["artifact_type"]),
        )
        self.artifacts = self._artifact_context()
        self.application_outputs = application_output_refs(self.workspace, self.workflow)
        self.application_reports = {
            str(ref["kind"]): read_json(self.workspace / str(ref["path"]))
            for ref in self.application_outputs
        }
        self.failure_facts = derive_failure_facts(self.workspace, self.workflow)
        self.report_root = self.workspace / ".slidethus/review/stage-ai" / self.workflow_report_id

    def _load_workflow(self) -> tuple[Path, dict[str, Any]]:
        root = self.workspace / ".slidethus/workflows/runs"
        for path in sorted(root.glob("*.json")):
            report = read_json(path)
            if report.get("report_id") != self.workflow_report_id:
                continue
            errors = workflow_report_reference_errors(self.workspace, path, self.schemas.schema_dir)
            if errors:
                raise StageReviewError("Workflow Application Report is invalid: " + "; ".join(errors))
            if report.get("status") not in {"ready", "blocked", "failed"}:
                raise StageReviewError("Stage AI Review requires a terminated Workflow Application Report")
            return path, report
        raise StageReviewError(f"Unknown Workflow Application Report: {self.workflow_report_id}")

    def _artifact_context(self) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for ref in self.inputs:
            artifact_type = str(ref["artifact_type"])
            version = int(ref["version"])
            data = self.runtime.show_artifact(artifact_type, version=version)
            output[artifact_type] = data
        return output

    def _scope_indexes(self) -> tuple[set[str], dict[str, str], dict[str, str]]:
        outline = self.artifacts.get("deck_outline", {})
        slide_specs = self.artifacts.get("slide_specs", {})
        layouts = self.artifacts.get("layout_plans", {})
        slides = {
            str(item["slide_id"])
            for item in outline.get("slides", [])
            if item.get("status") != "excluded"
        }
        blocks = {
            str(block["block_id"]): str(slide["slide_id"])
            for slide in slide_specs.get("slides", [])
            for block in slide.get("content_blocks", [])
        }
        plans = layouts.get("plans", layouts.get("slides", []))
        regions = {
            str(region["region_id"]): str(slide["slide_id"])
            for slide in plans
            for region in slide.get("regions", [])
        }
        return slides, blocks, regions

    def _admit_issue(self, raw: dict[str, Any], stage: str) -> dict[str, Any]:
        forbidden = sorted(_FORBIDDEN_ISSUE_FIELDS.intersection(raw))
        if forbidden:
            raise StageReviewError(
                "Stage AI Review cannot propose repair/mutation fields before synthesis: "
                + ", ".join(forbidden)
            )
        code = str(raw.get("code", "")).strip()
        if not _CODE.fullmatch(code):
            raise StageReviewError(f"Invalid Stage AI issue code: {code}")
        severity = str(raw.get("severity", ""))
        if severity not in _SEVERITY_ORDER:
            raise StageReviewError(f"Unsupported Stage AI issue severity: {severity}")
        earliest = str(raw.get("earliest_phase", ""))
        if earliest not in _STAGE_ORDER:
            raise StageReviewError(f"Unsupported Stage AI issue earliest_phase: {earliest}")
        if _STAGE_ORDER[earliest] > _STAGE_ORDER[stage]:
            raise StageReviewError(
                f"Stage AI issue cannot route later than observed stage: {earliest} > {stage}"
            )
        artifact_type = raw.get("artifact_type")
        if artifact_type is not None:
            artifact_type = str(artifact_type)
            if artifact_type not in self.artifacts:
                raise StageReviewError(f"Stage AI issue references unknown artifact: {artifact_type}")
            if artifact_type not in STAGE_FOCUS_ARTIFACTS[stage]:
                raise StageReviewError(
                    f"Stage {stage} issue must locate on its owned artifact(s): {artifact_type}"
                )
        slides, blocks, regions = self._scope_indexes()
        slide_id = str(raw["slide_id"]) if raw.get("slide_id") is not None else None
        block_id = str(raw["block_id"]) if raw.get("block_id") is not None else None
        region_id = str(raw["region_id"]) if raw.get("region_id") is not None else None
        if slide_id is not None and slide_id not in slides:
            raise StageReviewError(f"Stage AI issue references unknown slide: {slide_id}")
        if block_id is not None:
            if block_id not in blocks:
                raise StageReviewError(f"Stage AI issue references unknown block: {block_id}")
            if slide_id is None or blocks[block_id] != slide_id:
                raise StageReviewError("Stage AI issue block/slide reference is inconsistent")
        if region_id is not None:
            if region_id not in regions:
                raise StageReviewError(f"Stage AI issue references unknown region: {region_id}")
            if slide_id is None or regions[region_id] != slide_id:
                raise StageReviewError("Stage AI issue region/slide reference is inconsistent")
        scope = str(raw.get("scope", ""))
        if scope not in {"local", "multi_slide", "artifact", "cross_artifact", "cross_stage", "attempt_wide"}:
            raise StageReviewError(f"Unsupported Stage AI issue scope: {scope}")
        issue: dict[str, Any] = {
            "issue_id": "",
            "code": code,
            "severity": severity,
            "status": "open",
            "observed_stage": stage,
            "earliest_phase": earliest,
            "artifact_type": artifact_type,
            "slide_id": slide_id,
            "block_id": block_id,
            "region_id": region_id,
            "scope": scope,
            "finding": _text(raw.get("finding"), "finding"),
            "impact": _text(raw.get("impact"), "impact"),
            "generalized_pattern_hint": _text(
                raw.get("generalized_pattern_hint"), "generalized_pattern_hint"
            ),
            "verification": _text(raw.get("verification"), "verification"),
        }
        issue["issue_id"] = stage_issue_id(issue)
        return issue

    def _context(self, stage: str) -> dict[str, Any]:
        return {
            "mode": "retrospective_stage_open_issue",
            "stage": stage,
            "attempt": self.workflow,
            "focus_artifact_types": list(STAGE_FOCUS_ARTIFACTS[stage]),
            "artifacts": self.artifacts,
            "application_reports": self.application_reports,
            "failure_facts": self.failure_facts,
            "rules": {
                "retrospective_only": True,
                "scores_forbidden": True,
                "repairs_forbidden": True,
                "mutations_forbidden": True,
                "review_task": (
                    "Observe this stage's owned facts in the completed/blocked attempt, explain impact, "
                    "route to the earliest responsible phase, and state only a generalized failure-pattern hint."
                ),
                "issue_fields": [
                    "code",
                    "severity",
                    "earliest_phase",
                    "artifact_type",
                    "slide_id",
                    "block_id",
                    "region_id",
                    "scope",
                    "finding",
                    "impact",
                    "generalized_pattern_hint",
                    "verification",
                ],
            },
        }

    def review(self, stage: str, *, persist: bool = True) -> StageAIReviewResult:
        if stage not in STAGES:
            raise StageReviewError(f"Unsupported Stage AI Review stage: {stage}")
        state = self.runtime.show_artifact("project_state")
        applicable = stage_is_applicable(stage, self.workflow)
        if not applicable:
            issues: list[dict[str, Any]] = []
            capability = {
                "status": "not_applicable",
                "detail": f"Attempt ended before {stage} produced reviewable owned facts.",
            }
            status = "not_applicable"
        elif self.provider is None:
            issues = []
            capability = {
                "status": "missing",
                "detail": "No StageReviewProvider was injected; retrospective AI review is unavailable.",
            }
            status = "blocked"
        else:
            context = self._context(stage)
            proposal = self.provider.review(context)
            if not isinstance(proposal, dict) or not isinstance(proposal.get("issues", []), list):
                raise StageReviewError("StageReviewProvider must return an object with issues[]")
            forbidden_top = sorted(
                key
                for key in ("scores", "dimensions", "repairs", "patches", "mutations")
                if proposal.get(key)
            )
            if forbidden_top:
                raise StageReviewError(
                    "Stage AI Review proposal contains forbidden pre-synthesis fields: "
                    + ", ".join(forbidden_top)
                )
            issues = [self._admit_issue(item, stage) for item in proposal.get("issues", [])]
            ids = [str(item["issue_id"]) for item in issues]
            if len(ids) != len(set(ids)):
                raise StageReviewError("StageReviewProvider proposed duplicate issue identities")
            issues.sort(key=lambda item: (_SEVERITY_ORDER[item["severity"]], item["issue_id"]))
            capability = {
                "status": "available",
                "detail": (
                    f"Retrospective {stage} review admitted from "
                    f"{self.provider_identity['name']} {self.provider_identity['version']}."
                ),
            }
            status = "issues" if issues else "pass"
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(state["project_id"]),
            "report_id": "",
            "review_mode": "retrospective_stage_open_issue",
            "stage": stage,
            "provider": self.provider_identity if applicable else None,
            "capability": capability,
            "workflow_report": workflow_report_ref(self.workspace, self.workflow_path, self.workflow),
            "inputs": self.inputs,
            "application_outputs": self.application_outputs,
            "failure_facts": self.failure_facts,
            "issues": issues,
            "summary": {
                "critical_count": sum(item["severity"] == "critical" for item in issues),
                "major_count": sum(item["severity"] == "major" for item in issues),
                "minor_count": sum(item["severity"] == "minor" for item in issues),
                "suggestion_count": sum(item["severity"] == "suggestion" for item in issues),
                "open_count": len(issues),
            },
            "status": status,
        }
        report["report_id"] = stage_review_id(report)
        errors = validate_stage_review_data(report, self.schemas.schema_dir)
        if errors:
            raise StageReviewError("Invalid Stage AI Review Report: " + "; ".join(errors))
        path = self.report_root / f"{stage_review_file_key(report)}.json"
        if not persist:
            return StageAIReviewResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise StageReviewError(f"Immutable Stage AI Review contains different content: {path}")
        return StageAIReviewResult(path=path, report=report, changed=changed)

    def review_all(self, *, persist: bool = True) -> tuple[StageAIReviewResult, ...]:
        return tuple(self.review(stage, persist=persist) for stage in STAGES)


def load_unique_stage_review_set(
    workspace: Path,
    workflow_report_id: str,
    *,
    schema_registry: SchemaRegistry | None = None,
) -> tuple[StageAIReviewResult, ...]:
    """Load exactly one immutable Stage AI Review per lens for one attempt."""

    workspace = workspace.resolve()
    schemas = schema_registry or SchemaRegistry()
    root = workspace / ".slidethus/review/stage-ai" / workflow_report_id
    if not root.exists():
        raise StageReviewError(f"No Stage AI Review set for attempt: {workflow_report_id}")
    by_stage: dict[str, StageAIReviewResult] = {}
    for path in sorted(root.glob("*.json")):
        errors = stage_review_reference_errors(workspace, path, schemas.schema_dir)
        if errors:
            raise StageReviewError(
                f"Invalid Stage AI Review {path.name}: " + "; ".join(errors)
            )
        report = read_json(path)
        stage = str(report.get("stage", ""))
        if stage in by_stage:
            raise StageReviewError(
                f"Multiple Stage AI Reviews exist for {stage}; select a new attempt before synthesis"
            )
        by_stage[stage] = StageAIReviewResult(path=path, report=report, changed=False)
    missing = [stage for stage in STAGES if stage not in by_stage]
    if missing:
        raise StageReviewError("Incomplete Stage AI Review set: " + ", ".join(missing))
    return tuple(by_stage[stage] for stage in STAGES)
