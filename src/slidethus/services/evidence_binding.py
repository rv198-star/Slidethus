from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import EvidenceBindingError, EvidenceGapError
from slidethus.evidence_binding_rules import (
    block_evidence_requirement,
    evidence_requires_qualification,
    evidence_usable,
    slide_evidence_requirement,
)
from slidethus.evidence_gaps import (
    gap_issue_id,
    gap_query_id,
    gap_report_file_key,
    gap_report_id,
    validate_gap_report_data,
)
from slidethus.io_utils import atomic_create_json, read_json
from slidethus.protocols import ResearchLimits, ResearchPlan
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.research import plan_explicit_targeted_research
from slidethus.state_machine import Phase

_BLOCKING_SEVERITIES = {"critical", "major"}


@dataclass(frozen=True)
class EvidenceGapAnalysisResult:
    report: dict[str, Any]
    path: Path | None
    changed: bool


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return _normalized_text(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return _normalized_text(" ".join(_content_text(item) for item in value))
    if isinstance(value, dict):
        return _normalized_text(
            " ".join(_content_text(value[key]) for key in sorted(value))
        )
    return ""


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


class EvidenceBindingService:
    """Audit Outline/Slide block Evidence bindings and route bounded rework."""

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
        self.report_dir = self.workspace / ".slidethus/evidence/gaps"

    def _graph(self) -> dict[str, dict[str, Any]]:
        return self.runtime.read_artifact_graph_snapshot(
            (
                "project_state",
                "project_brief",
                "source_ledger",
                "evidence_ledger",
                "deck_outline",
                "slide_specs",
            ),
            optional_artifact_types=("slide_specs",),
        )

    @staticmethod
    def _add_issue(
        issues: list[dict[str, Any]],
        *,
        code: str,
        severity: str,
        message: str,
        slide_id: str | None,
        block_id: str | None,
        evidence_ids: list[str] | tuple[str, ...] = (),
        earliest_phase: str,
        suggested_action: str,
    ) -> str:
        payload = {
            "code": code,
            "slide_id": slide_id,
            "block_id": block_id,
            "evidence_ids": sorted(set(evidence_ids)),
            "earliest_phase": earliest_phase,
        }
        issue_id = gap_issue_id(payload)
        issue = {
            "issue_id": issue_id,
            "code": code,
            "severity": severity,
            "message": _normalized_text(message)[:4000],
            "slide_id": slide_id,
            "block_id": block_id,
            "evidence_ids": payload["evidence_ids"],
            "earliest_phase": earliest_phase,
            "suggested_action": _normalized_text(suggested_action)[:4000],
            "status": "open",
        }
        if issue_id not in {item["issue_id"] for item in issues}:
            issues.append(issue)
        return issue_id

    @staticmethod
    def _external_tiers(brief: dict[str, Any]) -> tuple[str, ...]:
        admitted = set(brief.get("source_policy", {}).get("allowed_source_tiers", []))
        return tuple(
            tier for tier in ("primary", "secondary", "community", "unknown") if tier in admitted
        )

    def _query_suggestion(
        self,
        suggestions: list[dict[str, Any]],
        *,
        brief: dict[str, Any],
        outline_version: int,
        slide: dict[str, Any],
        block: dict[str, Any] | None,
        reason_code: str,
        purpose: str,
    ) -> str | None:
        policy = brief.get("source_policy", {})
        tiers = self._external_tiers(brief)
        if not policy.get("external_research") or not tiers:
            return None
        block_id = str(block.get("block_id")) if block is not None else None
        content = _content_text(block.get("content")) if block is not None else ""
        query = _normalized_text(
            " ".join(
                value
                for value in (
                    str(brief.get("title", "")),
                    str(slide.get("headline", "")),
                    str(slide.get("takeaway", "")),
                    content,
                )
                if _normalized_text(value)
            )
        )[:600]
        if not query:
            return None
        payload = {
            "slide_id": slide["slide_id"],
            "block_id": block_id,
            "query": query,
            "reason_code": reason_code,
            "outline_version": outline_version,
        }
        query_id = gap_query_id(payload)
        suggestion = {
            "query_id": query_id,
            "slide_id": str(slide["slide_id"]),
            "block_id": block_id,
            "query": query,
            "purpose": _normalized_text(purpose)[:2000],
            "reason_code": reason_code,
            "outline_version": outline_version,
            "preferred_source_tiers": list(tiers),
            "freshness_requirement": policy.get("freshness_requirement"),
        }
        if query_id not in {item["query_id"] for item in suggestions}:
            suggestions.append(suggestion)
        return query_id

    @staticmethod
    def _binding_issues(
        *,
        evidence_ids: list[str],
        evidence_map: dict[str, dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        unknown = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_map]
        unusable = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id in evidence_map and not evidence_usable(evidence_map[evidence_id])
        ]
        qualified = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id in evidence_map
            and evidence_usable(evidence_map[evidence_id])
            and evidence_requires_qualification(evidence_map[evidence_id])
        ]
        return unknown, unusable, qualified

    def _build_report(
        self,
        graph: dict[str, dict[str, Any]],
        *,
        require_targeted_cycle: bool,
    ) -> dict[str, Any]:
        brief = graph["project_brief"]["data"]
        evidence = graph["evidence_ledger"]["data"]
        outline = graph["deck_outline"]["data"]
        specs = graph.get("slide_specs", {}).get("data")
        outline_version = int(graph["deck_outline"]["version"])
        evidence_map = {
            str(item["evidence_id"]): item for item in evidence.get("claims", [])
        }
        spec_map = {
            str(item["slide_id"]): item for item in (specs or {}).get("slides", [])
        }
        active_slides = [
            item for item in outline.get("slides", []) if item.get("status") != "excluded"
        ]

        issues: list[dict[str, Any]] = []
        suggestions: list[dict[str, Any]] = []
        slide_reports: list[dict[str, Any]] = []
        analyzed_blocks = 0
        factual_blocks = 0
        bound_blocks = 0

        state = graph["project_state"]["data"]
        current_versions = {
            artifact_type: int(graph[artifact_type]["version"])
            for artifact_type in ("project_brief", "source_ledger", "evidence_ledger")
        }
        g2_summary = next(
            (
                item
                for item in state.get("completed_gates", [])
                if item.get("gate_id") == "G2"
                and item.get("status") in {"pass", "waived"}
            ),
            None,
        )
        g2_versions = {
            str(item.get("artifact_type")): int(item.get("version", 0))
            for item in (g2_summary or {}).get("artifact_versions", [])
        }
        if g2_summary is None or any(
            g2_versions.get(artifact_type) != version
            for artifact_type, version in current_versions.items()
        ):
            self._add_issue(
                issues,
                code="g2_not_current",
                severity="major",
                message=(
                    "Current Brief/Source/Evidence versions are not covered by a passing G2."
                ),
                slide_id=None,
                block_id=None,
                earliest_phase="P2",
                suggested_action="Re-adjudicate current Evidence and record G2 before G5A.",
            )

        targeted_complete = any(
            cycle.get("kind") == "targeted"
            and cycle.get("status") in {"complete", "waived"}
            and cycle.get("outline_version") == outline_version
            for cycle in evidence.get("research_cycles", [])
        )
        if require_targeted_cycle and not targeted_complete:
            self._add_issue(
                issues,
                code="targeted_cycle_incomplete",
                severity="major",
                message=f"Targeted evidence cycle is incomplete for Outline version {outline_version}.",
                slide_id=None,
                block_id=None,
                earliest_phase="P2",
                suggested_action=(
                    "Complete an outline-versioned targeted review using current user materials or execute a targeted Research Plan."
                ),
            )

        for slide in active_slides:
            slide_id = str(slide["slide_id"])
            requirement = slide_evidence_requirement(slide)
            outline_ids = list(dict.fromkeys(str(item) for item in slide.get("evidence_ids", [])))
            slide_issue_ids: list[str] = []
            slide_query_ids: list[str] = []
            block_ids: list[str] = []

            if requirement == "required" and not outline_ids:
                issue_id = self._add_issue(
                    issues,
                    code="required_slide_evidence_missing",
                    severity="major",
                    message=f"{slide_id} requires Evidence but the Outline has no evidence IDs.",
                    slide_id=slide_id,
                    block_id=None,
                    earliest_phase="P4",
                    suggested_action="Bind usable Evidence or return to P2 to fill the slide-level proof gap.",
                )
                slide_issue_ids.append(issue_id)
                query_id = self._query_suggestion(
                    suggestions,
                    brief=brief,
                    outline_version=outline_version,
                    slide=slide,
                    block=None,
                    reason_code="required_slide_evidence_missing",
                    purpose=f"Find direct support for the factual burden of {slide_id}.",
                )
                if query_id:
                    slide_query_ids.append(query_id)

            unknown, unusable, _qualified = self._binding_issues(
                evidence_ids=outline_ids,
                evidence_map=evidence_map,
            )
            if unknown:
                slide_issue_ids.append(
                    self._add_issue(
                        issues,
                        code="outline_unknown_evidence",
                        severity="major",
                        message=f"{slide_id} references unknown Evidence IDs: {', '.join(unknown)}.",
                        slide_id=slide_id,
                        block_id=None,
                        evidence_ids=unknown,
                        earliest_phase="P4",
                        suggested_action="Remove stale IDs or publish the missing Evidence before continuing.",
                    )
                )
            if unusable:
                slide_issue_ids.append(
                    self._add_issue(
                        issues,
                        code="outline_unusable_evidence",
                        severity="major",
                        message=f"{slide_id} references policy-blocked Evidence: {', '.join(unusable)}.",
                        slide_id=slide_id,
                        block_id=None,
                        evidence_ids=unusable,
                        earliest_phase="P2",
                        suggested_action="Resolve the support/conflict/source policy or replace the Evidence.",
                    )
                )
                query_id = self._query_suggestion(
                    suggestions,
                    brief=brief,
                    outline_version=outline_version,
                    slide=slide,
                    block=None,
                    reason_code="outline_unusable_evidence",
                    purpose=f"Replace unusable Evidence for {slide_id} with admitted support.",
                )
                if query_id:
                    slide_query_ids.append(query_id)

            spec = spec_map.get(slide_id)
            block_bound_ids: set[str] = set()
            if spec is None:
                slide_issue_ids.append(
                    self._add_issue(
                        issues,
                        code="slide_specs_not_available",
                        severity="minor",
                        message=f"{slide_id} has no current Slide Spec; block-level binding was not analyzed.",
                        slide_id=slide_id,
                        block_id=None,
                        earliest_phase="P5A",
                        suggested_action="Create current Slide Specs before G5A block-level acceptance.",
                    )
                )
            else:
                for block in spec.get("content_blocks", []):
                    analyzed_blocks += 1
                    block_id = str(block["block_id"])
                    block_ids.append(block_id)
                    block_requirement = block_evidence_requirement(block)
                    if block_requirement == "required":
                        factual_blocks += 1
                    block_evidence = list(
                        dict.fromkeys(str(item) for item in block.get("evidence_ids", []))
                    )
                    block_bound_ids.update(block_evidence)
                    if block_evidence:
                        bound_blocks += 1
                    if block_requirement == "required" and not block_evidence:
                        issue_id = self._add_issue(
                            issues,
                            code="required_block_evidence_missing",
                            severity="major",
                            message=f"{block_id} is factual/required but has no Evidence binding.",
                            slide_id=slide_id,
                            block_id=block_id,
                            earliest_phase="P5A",
                            suggested_action="Bind usable Evidence or route the block proof gap to P2.",
                        )
                        slide_issue_ids.append(issue_id)
                        query_id = self._query_suggestion(
                            suggestions,
                            brief=brief,
                            outline_version=outline_version,
                            slide=slide,
                            block=block,
                            reason_code="required_block_evidence_missing",
                            purpose=f"Find support for factual block {block_id}.",
                        )
                        if query_id:
                            slide_query_ids.append(query_id)
                    unknown, unusable, qualified = self._binding_issues(
                        evidence_ids=block_evidence,
                        evidence_map=evidence_map,
                    )
                    if unknown:
                        slide_issue_ids.append(
                            self._add_issue(
                                issues,
                                code="block_unknown_evidence",
                                severity="major",
                                message=f"{block_id} references unknown Evidence IDs: {', '.join(unknown)}.",
                                slide_id=slide_id,
                                block_id=block_id,
                                evidence_ids=unknown,
                                earliest_phase="P5A",
                                suggested_action="Replace stale IDs with current Evidence.",
                            )
                        )
                    if unusable:
                        slide_issue_ids.append(
                            self._add_issue(
                                issues,
                                code="block_unusable_evidence",
                                severity="major",
                                message=f"{block_id} references unusable Evidence: {', '.join(unusable)}.",
                                slide_id=slide_id,
                                block_id=block_id,
                                evidence_ids=unusable,
                                earliest_phase="P2",
                                suggested_action="Resolve or replace policy-blocked Evidence.",
                            )
                        )
                        query_id = self._query_suggestion(
                            suggestions,
                            brief=brief,
                            outline_version=outline_version,
                            slide=slide,
                            block=block,
                            reason_code="block_unusable_evidence",
                            purpose=f"Replace unusable support for block {block_id}.",
                        )
                        if query_id:
                            slide_query_ids.append(query_id)
                    if qualified and not _normalized_text(block.get("evidence_qualification")):
                        slide_issue_ids.append(
                            self._add_issue(
                                issues,
                                code="block_qualification_missing",
                                severity=(
                                    "major"
                                    if block_requirement == "required" or requirement == "required"
                                    else "minor"
                                ),
                                message=(
                                    f"{block_id} uses qualified Evidence without an explicit qualification: "
                                    + ", ".join(qualified)
                                    + "."
                                ),
                                slide_id=slide_id,
                                block_id=block_id,
                                evidence_ids=qualified,
                                earliest_phase="P5A",
                                suggested_action="Add a visible/notes qualification or obtain stronger Evidence.",
                            )
                        )
                    undeclared = sorted(set(block_evidence) - set(outline_ids))
                    if undeclared:
                        slide_issue_ids.append(
                            self._add_issue(
                                issues,
                                code="block_evidence_not_declared_in_outline",
                                severity=(
                                    "major"
                                    if block_requirement == "required" or requirement == "required"
                                    else "minor"
                                ),
                                message=f"{block_id} uses Evidence not declared on {slide_id}: {', '.join(undeclared)}.",
                                slide_id=slide_id,
                                block_id=block_id,
                                evidence_ids=undeclared,
                                earliest_phase="P4",
                                suggested_action="Align Outline evidence coverage with the approved block binding.",
                            )
                        )

                unbound_outline = sorted(set(outline_ids) - block_bound_ids)
                if unbound_outline and requirement != "none":
                    slide_issue_ids.append(
                        self._add_issue(
                            issues,
                            code="outline_evidence_not_bound_to_block",
                            severity=("major" if requirement == "required" else "minor"),
                            message=f"{slide_id} declares Evidence not bound to any block: {', '.join(unbound_outline)}.",
                            slide_id=slide_id,
                            block_id=None,
                            evidence_ids=unbound_outline,
                            earliest_phase="P5A",
                            suggested_action="Bind the Evidence to the responsible block or remove it from the Outline.",
                        )
                    )

            if require_targeted_cycle and not targeted_complete and requirement != "none":
                query_id = self._query_suggestion(
                    suggestions,
                    brief=brief,
                    outline_version=outline_version,
                    slide=slide,
                    block=None,
                    reason_code="targeted_cycle_incomplete",
                    purpose=f"Perform the outline-driven evidence check for {slide_id}.",
                )
                if query_id:
                    slide_query_ids.append(query_id)

            slide_issues = [
                item for item in issues if item["issue_id"] in set(slide_issue_ids)
            ]
            if any(item["severity"] in _BLOCKING_SEVERITIES for item in slide_issues):
                slide_status = "gap"
            elif any(item["severity"] == "minor" for item in slide_issues):
                slide_status = "warning"
            elif spec is None:
                slide_status = "not_analyzed"
            else:
                slide_status = "pass"
            slide_reports.append(
                {
                    "slide_id": slide_id,
                    "status": slide_status,
                    "evidence_requirement": requirement,
                    "outline_evidence_ids": outline_ids,
                    "block_ids": block_ids,
                    "issue_ids": sorted(set(slide_issue_ids)),
                    "query_suggestion_ids": sorted(set(slide_query_ids)),
                }
            )

        issues.sort(key=lambda item: (item["severity"], item["issue_id"]))
        suggestions.sort(key=lambda item: item["query_id"])
        slide_reports.sort(key=lambda item: item["slide_id"])
        blocking_count = sum(
            1 for item in issues if item["severity"] in _BLOCKING_SEVERITIES
        )
        warning_count = sum(1 for item in issues if item["severity"] == "minor")
        generated_at = max(
            (
                str(item.get("updated_at"))
                for item in graph.values()
                if item.get("updated_at")
            ),
            default=utc_now(),
        )
        inputs = {
            "project_brief": _artifact_ref(graph["project_brief"], "project_brief"),
            "source_ledger": _artifact_ref(graph["source_ledger"], "source_ledger"),
            "evidence_ledger": _artifact_ref(graph["evidence_ledger"], "evidence_ledger"),
            "deck_outline": _artifact_ref(graph["deck_outline"], "deck_outline"),
            "slide_specs": (
                _artifact_ref(graph["slide_specs"], "slide_specs")
                if "slide_specs" in graph
                else None
            ),
        }
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(brief["project_id"]),
            "report_id": "",
            "generated_at": generated_at,
            "inputs": inputs,
            "status": "gaps" if blocking_count else "pass",
            "requires_rework": blocking_count > 0,
            "target_phase": "EVIDENCE_READY" if blocking_count else None,
            "summary": {
                "slide_count": len(active_slides),
                "analyzed_block_count": analyzed_blocks,
                "factual_block_count": factual_blocks,
                "bound_block_count": bound_blocks,
                "blocking_issue_count": blocking_count,
                "warning_count": warning_count,
                "query_suggestion_count": len(suggestions),
            },
            "issues": issues,
            "query_suggestions": suggestions,
            "slides": slide_reports,
        }
        report["report_id"] = gap_report_id(report)
        errors = validate_gap_report_data(report, self.schemas.schema_dir)
        if errors:
            raise EvidenceGapError("Invalid Evidence Gap Report: " + "; ".join(errors))
        return report

    def analyze(
        self,
        *,
        persist: bool = True,
        require_targeted_cycle: bool = True,
    ) -> EvidenceGapAnalysisResult:
        """Analyze current Outline/Specs bindings and optionally persist an immutable report."""

        report = self._build_report(
            self._graph(),
            require_targeted_cycle=require_targeted_cycle,
        )
        if not persist:
            return EvidenceGapAnalysisResult(report=report, path=None, changed=False)
        key = gap_report_file_key(report)
        path = self.report_dir / f"{key}.json"
        created = atomic_create_json(path, report)
        if not created and read_json(path) != report:
            raise EvidenceGapError(
                f"Immutable Evidence Gap Report path contains different content: {path}"
            )
        return EvidenceGapAnalysisResult(report=report, path=path, changed=created)

    def build_targeted_plan(
        self,
        *,
        cycle_id: str | None = None,
        limits: ResearchLimits | None = None,
    ) -> ResearchPlan:
        """Convert current deterministic gap suggestions into an M2.3 Research Plan."""

        report = self.analyze(persist=True, require_targeted_cycle=True).report
        suggestions = list(report.get("query_suggestions", []))
        if not suggestions:
            raise EvidenceGapError("Current Evidence Gap Report has no external query suggestions")
        candidates = [
            (
                str(item["query"]),
                str(item["purpose"]),
                str(item["slide_id"]),
            )
            for item in suggestions
        ]
        return plan_explicit_targeted_research(
            self.workspace,
            candidates,
            cycle_id=cycle_id,
            limits=limits,
        )

    def complete_user_material_targeted_cycle(self) -> dict[str, Any]:
        """Complete a current-outline targeted cycle when user-material bindings have no gaps."""

        analysis = self.analyze(persist=True, require_targeted_cycle=False)
        blocking = [
            item
            for item in analysis.report.get("issues", [])
            if item.get("severity") in _BLOCKING_SEVERITIES
        ]
        if blocking:
            raise EvidenceBindingError(
                "Cannot complete user-material targeted cycle while binding gaps remain: "
                + ", ".join(item["code"] for item in blocking)
            )
        graph = self._graph()
        current_inputs = {
            "project_brief": _artifact_ref(graph["project_brief"], "project_brief"),
            "source_ledger": _artifact_ref(graph["source_ledger"], "source_ledger"),
            "evidence_ledger": _artifact_ref(
                graph["evidence_ledger"], "evidence_ledger"
            ),
            "deck_outline": _artifact_ref(graph["deck_outline"], "deck_outline"),
            "slide_specs": (
                _artifact_ref(graph["slide_specs"], "slide_specs")
                if "slide_specs" in graph
                else None
            ),
        }
        if analysis.report.get("inputs") != current_inputs:
            raise EvidenceBindingError(
                "Artifact graph changed after Evidence Gap analysis; recompute before completion"
            )
        if "slide_specs" not in graph:
            raise EvidenceBindingError(
                "User-material targeted completion requires current Slide Specs"
            )
        from slidethus.gates import evaluate_gate

        g2 = evaluate_gate(self.workspace, "G2")
        if not g2.passed:
            raise EvidenceBindingError(
                "User-material targeted completion requires a passing G2: "
                + "; ".join(g2.reasons)
            )
        evidence = graph["evidence_ledger"]["data"]
        evidence_version = int(graph["evidence_ledger"]["version"])
        outline = graph["deck_outline"]["data"]
        outline_version = int(graph["deck_outline"]["version"])
        specs = graph.get("slide_specs", {}).get("data", {})
        evidence_ids = {
            str(evidence_id)
            for slide in outline.get("slides", [])
            if slide.get("status") != "excluded"
            for evidence_id in slide.get("evidence_ids", [])
        }
        evidence_ids.update(
            str(evidence_id)
            for slide in specs.get("slides", [])
            for block in slide.get("content_blocks", [])
            for evidence_id in block.get("evidence_ids", [])
        )
        claims = {
            str(item["evidence_id"]): item for item in evidence.get("claims", [])
        }
        source_ids = sorted(
            {
                str(ref["source_id"])
                for evidence_id in evidence_ids
                for ref in claims.get(evidence_id, {}).get("source_refs", [])
            }
        )
        source_ledger = graph["source_ledger"]["data"]
        source_map = {
            str(item["source_id"]): item for item in source_ledger.get("sources", [])
        }
        web_sources = [
            source_id
            for source_id in source_ids
            if source_map.get(source_id, {}).get("kind") == "web"
        ]
        if web_sources:
            raise EvidenceBindingError(
                "Web-backed targeted completion requires Research Run lineage: "
                + ", ".join(web_sources)
            )

        cycles = copy.deepcopy(evidence.get("research_cycles", []))
        targeted = next(
            (
                item
                for item in cycles
                if item.get("kind") == "targeted"
                and item.get("outline_version") == outline_version
            ),
            None,
        )
        if targeted is None:
            numbers = [
                int(str(item["cycle_id"]).split("-")[-1])
                for item in cycles
                if str(item.get("cycle_id", "")).startswith("RSC-")
            ]
            next_number = max(numbers, default=0) + 1
            if next_number > 999:
                raise EvidenceBindingError("Research cycle ID space is exhausted")
            targeted = {
                "cycle_id": f"RSC-{next_number:03d}",
                "kind": "targeted",
                "status": "pending",
                "basis": "none_required",
                "outline_version": outline_version,
                "source_ids": [],
                "run_ids": [],
                "query_count": 0,
                "waiver_reason": None,
                "notes": [],
            }
            cycles.append(targeted)
        updated = copy.deepcopy(targeted)
        if updated.get("run_ids"):
            raise EvidenceBindingError(
                "Existing Research Run lineage must be completed through the Evidence Engine, "
                "not the user-material-only completion path"
            )
        updated.update(
            {
                "status": "complete",
                "basis": "user_materials" if source_ids else "none_required",
                "source_ids": source_ids,
                "run_ids": [],
                "query_count": 0,
                "waiver_reason": None,
            }
        )
        note = (
            f"Targeted evidence review completed from current user materials for Outline version "
            f"{outline_version}; no blocking binding gaps remained."
        )
        notes = list(updated.get("notes", []))
        if note not in notes:
            notes.append(note)
        updated["notes"] = notes
        candidate = copy.deepcopy(evidence)
        candidate["research_cycles"] = sorted(
            [
                updated if item.get("cycle_id") == updated["cycle_id"] else item
                for item in cycles
            ],
            key=lambda item: int(str(item["cycle_id"]).split("-")[-1]),
        )
        if candidate == evidence:
            return copy.deepcopy(evidence)
        self.runtime.write_artifact(
            "evidence_ledger",
            candidate,
            expected_version=evidence_version,
            status="approved",
            created_by="evidence-binding-service",
        )
        return self.runtime.show_artifact("evidence_ledger")

    def route_rework(self, *, reason: str | None = None) -> dict[str, Any]:
        """Route current blocking gaps to the formal P2 rework phase."""

        analysis = self.analyze(persist=True, require_targeted_cycle=True)
        if not analysis.report.get("requires_rework"):
            raise EvidenceBindingError("Current Evidence Gap Report does not require rework")
        current_phase = Phase(
            self.runtime.show_artifact("project_state")["current_phase"]
        )
        if current_phase not in {Phase.OUTLINE_READY, Phase.SLIDE_SPECS_READY}:
            raise EvidenceBindingError(
                f"Evidence-gap rework is only admitted from OUTLINE_READY/SLIDE_SPECS_READY, got {current_phase}"
            )
        codes = sorted(
            {
                str(item["code"])
                for item in analysis.report.get("issues", [])
                if item.get("severity") in _BLOCKING_SEVERITIES
            }
        )
        expected_versions = {
            str(ref["artifact_type"]): int(ref["version"])
            for ref in analysis.report.get("inputs", {}).values()
            if ref is not None
        }
        return self.runtime.route_rework(
            Phase.EVIDENCE_READY,
            reason=(
                reason
                or f"Evidence Gap Report {analysis.report['report_id']}: {', '.join(codes)}"
            ),
            expected_artifact_versions=expected_versions,
        )
