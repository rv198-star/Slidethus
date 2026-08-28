from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import NarrativePlanningError, PlanningError
from slidethus.gates import evaluate_gate
from slidethus.planning_limits import (
    admit_planning_proposal,
    validate_planning_limits,
)
from slidethus.planning_lineage import (
    build_planning_lineage,
    planning_artifact_reusable,
    reuse_semantically_current_lineage,
)
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.planning_rules import narrative_gate_reasons, usable_evidence_map
from slidethus.protocols import PlanningLimits, PlanningProvider


@dataclass(frozen=True)
class NarrativePlanningResult:
    """One versioned Production Narrative result."""

    narrative: dict[str, Any]
    changed: bool
    version: int
    gate_reasons: tuple[str, ...]


def _bounded_text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _planning_generated_at(graph: dict[str, dict[str, Any]]) -> str:
    values = [
        str(item.get("updated_at") or "")
        for item in graph.values()
        if item.get("updated_at")
    ]
    return max(values) if values else utc_now()


class NarrativePlanningService:
    """Generate and validate the current Production Narrative Blueprint."""

    def __init__(
        self,
        workspace,
        *,
        provider: PlanningProvider | None = None,
        runtime: ArtifactRuntime | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.provider = provider or DeterministicPlanningProvider()
        self.provider_name = _bounded_text(getattr(self.provider, "name", ""), limit=128)
        self.provider_version = _bounded_text(
            getattr(self.provider, "version", ""), limit=128
        )
        if not self.provider_name or not self.provider_version:
            raise NarrativePlanningError(
                "Planning provider must declare bounded name and version"
            )

    def _proposal(self, context: dict[str, Any], limits: PlanningLimits):
        try:
            proposal = self.provider.propose(
                "narrative_blueprint",
                context,
                limits,
            )
        except PlanningError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NarrativePlanningError(f"Planning provider failed: {exc}") from exc
        if _bounded_text(getattr(self.provider, "name", ""), limit=128) != self.provider_name or _bounded_text(
            getattr(self.provider, "version", ""), limit=128
        ) != self.provider_version:
            raise NarrativePlanningError(
                "Planning provider identity changed during Narrative generation"
            )
        return admit_planning_proposal(
            proposal,
            artifact_type="narrative_blueprint",
            limits=limits,
        )

    def _admit(
        self,
        proposal_content: dict[str, Any],
        *,
        graph: dict[str, dict[str, Any]],
        warnings: tuple[str, ...],
        assumptions: tuple[str, ...],
        limits: PlanningLimits,
    ) -> dict[str, Any]:
        brief = graph["project_brief"]["data"]
        evidence = graph["evidence_ledger"]["data"]
        usable = usable_evidence_map(evidence)
        raw_sections = list(proposal_content.get("sections", []))[: limits.max_sections]
        if len(raw_sections) < 2:
            raise NarrativePlanningError(
                "Production Narrative proposal requires at least two sections"
            )
        target = int(brief["constraints"]["page_count"]["target"])
        sections: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_sections, start=1):
            evidence_ids = list(
                dict.fromkeys(
                    str(item)
                    for item in raw.get("evidence_ids", [])
                    if str(item) in usable
                )
            )
            budget = int(raw.get("slide_budget", 1) or 1)
            sections.append(
                {
                    "section_id": f"SEC-{index:02d}",
                    "ordinal": index,
                    "title": _bounded_text(raw.get("title"), limit=120),
                    "purpose": _bounded_text(raw.get("purpose"), limit=600),
                    "key_questions": [
                        _bounded_text(item, limit=300)
                        for item in raw.get("key_questions", [])
                        if _bounded_text(item, limit=300)
                    ][:6],
                    "evidence_ids": evidence_ids,
                    "transition": _bounded_text(raw.get("transition"), limit=500),
                    "thesis": _bounded_text(
                        raw.get("thesis") or raw.get("purpose"), limit=600
                    ),
                    "audience_shift": _bounded_text(
                        raw.get("audience_shift")
                        or (raw.get("key_questions") or [raw.get("purpose")])[0],
                        limit=500,
                    ),
                    "proof_strategy": _bounded_text(
                        raw.get("proof_strategy")
                        or "使用当前 policy-usable Evidence；证据不足时明确限定。",
                        limit=700,
                    ),
                    "slide_budget": max(1, min(budget, limits.max_slides)),
                    "status": "approved",
                }
            )
        if any(not item["title"] or not item["purpose"] for item in sections):
            raise NarrativePlanningError("Narrative section title/purpose must not be blank")
        if any(not item["key_questions"] for item in sections):
            raise NarrativePlanningError("Every Narrative section requires a key question")
        if any(not item["transition"] for item in sections[:-1]):
            raise NarrativePlanningError("Narrative section transitions must not be blank")

        desired_budget = max(len(sections), target - 2)
        current_budget = sum(int(item["slide_budget"]) for item in sections)
        if current_budget != desired_budget:
            for item in sections:
                item["slide_budget"] = 1
            remaining = max(0, desired_budget - len(sections))
            index = 0
            while remaining:
                sections[index % len(sections)]["slide_budget"] += 1
                remaining -= 1
                index += 1

        audiences = brief.get("audiences", [])
        audience_ids = [str(item["audience_id"]) for item in audiences]
        objections = []
        for index, raw in enumerate(proposal_content.get("objections", []), start=1):
            objection = _bounded_text(raw.get("objection"), limit=500)
            response = _bounded_text(raw.get("response_strategy"), limit=800)
            if not objection or not response:
                continue
            objections.append(
                {
                    "objection_id": f"OBJ-{index:03d}",
                    "objection": objection,
                    "response_strategy": response,
                    "evidence_ids": list(
                        dict.fromkeys(
                            str(item)
                            for item in raw.get("evidence_ids", [])
                            if str(item) in usable
                        )
                    ),
                    "audience_ids": [
                        str(item)
                        for item in raw.get("audience_ids", audience_ids)
                        if str(item) in set(audience_ids)
                    ],
                    "severity": (
                        str(raw.get("severity"))
                        if str(raw.get("severity"))
                        in {"critical", "high", "medium", "low"}
                        else "medium"
                    ),
                }
            )

        content = copy.deepcopy(proposal_content)
        lineage_inputs = {
            "evidence_ledger": graph["evidence_ledger"],
            "project_brief": graph["project_brief"],
        }
        lineage = build_planning_lineage(
            lineage_inputs,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            proposal=content,
            policy={"service": "narrative", "limits": asdict(limits)},
            generated_at=_planning_generated_at(lineage_inputs),
            warnings=warnings,
            assumptions=assumptions,
        )
        existing_snapshot = graph.get("narrative_blueprint")
        lineage = reuse_semantically_current_lineage(
            lineage,
            (
                existing_snapshot["data"].get("planning_lineage")
                if existing_snapshot is not None
                else None
            ),
            lineage_inputs,
            required_inputs=("evidence_ledger", "project_brief"),
        )
        narrative = {
            "schema_version": SCHEMA_VERSION,
            "project_id": brief["project_id"],
            "central_thesis": _bounded_text(
                proposal_content.get("central_thesis"), limit=700
            ),
            "story_arc": str(proposal_content.get("story_arc", "custom")),
            "story_rationale": _bounded_text(
                proposal_content.get("story_rationale"), limit=800
            ),
            "proof_strategy": _bounded_text(
                proposal_content.get("proof_strategy"), limit=1000
            ),
            "call_to_action": _bounded_text(
                proposal_content.get("call_to_action"), limit=500
            ),
            "status": "approved",
            "audience_journey": [
                _bounded_text(item, limit=500)
                for item in proposal_content.get("audience_journey", [])
                if _bounded_text(item, limit=500)
            ][:8],
            "sections": sections,
            "objections": objections,
            "excluded_content": list(
                dict.fromkeys(
                    _bounded_text(item, limit=500)
                    for item in proposal_content.get("excluded_content", [])
                    if _bounded_text(item, limit=500)
                )
            ),
            "notes": list(
                dict.fromkeys(
                    [
                        *(
                            _bounded_text(item, limit=500)
                            for item in proposal_content.get("notes", [])
                            if _bounded_text(item, limit=500)
                        ),
                        *warnings,
                    ]
                )
            ),
            "planning_lineage": lineage,
        }
        return narrative

    def generate(
        self,
        *,
        limits: PlanningLimits | None = None,
        force: bool = False,
        created_by: str = "narrative-planning-service",
    ) -> NarrativePlanningResult:
        """Generate or idempotently reuse the current Production Narrative."""

        admitted_limits = limits or PlanningLimits()
        validate_planning_limits(admitted_limits)
        g0 = evaluate_gate(self.workspace, "G0")
        if not g0.passed:
            raise NarrativePlanningError("G0 must pass before Narrative generation: " + "; ".join(g0.reasons))
        g2 = evaluate_gate(self.workspace, "G2")
        if not g2.passed:
            raise NarrativePlanningError("G2 must pass before Narrative generation: " + "; ".join(g2.reasons))
        graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "evidence_ledger", "narrative_blueprint"),
            optional_artifact_types=("narrative_blueprint",),
        )
        existing_snapshot = graph.get("narrative_blueprint")
        current_policy = {"service": "narrative", "limits": asdict(admitted_limits)}
        if (
            not force
            and existing_snapshot is not None
            and planning_artifact_reusable(
                existing_snapshot["data"],
                graph,
                required_inputs=("evidence_ledger", "project_brief"),
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                policy=current_policy,
            )
        ):
            reasons = narrative_gate_reasons(
                brief=graph["project_brief"]["data"],
                evidence=graph["evidence_ledger"]["data"],
                narrative=existing_snapshot["data"],
                graph=graph,
            )
            if not reasons:
                return NarrativePlanningResult(
                    narrative=copy.deepcopy(existing_snapshot["data"]),
                    changed=False,
                    version=int(existing_snapshot["version"]),
                    gate_reasons=(),
                )
        context = {
            "project_brief": copy.deepcopy(graph["project_brief"]["data"]),
            "evidence_ledger": copy.deepcopy(graph["evidence_ledger"]["data"]),
        }
        proposal = self._proposal(context, admitted_limits)
        candidate = self._admit(
            proposal.content,
            graph=graph,
            warnings=proposal.warnings,
            assumptions=proposal.assumptions,
            limits=admitted_limits,
        )
        reasons = narrative_gate_reasons(
            brief=graph["project_brief"]["data"],
            evidence=graph["evidence_ledger"]["data"],
            narrative=candidate,
            graph=graph,
        )
        if reasons:
            raise NarrativePlanningError(
                "Narrative proposal does not meet Production gate: " + "; ".join(reasons)
            )
        existing_snapshot = graph.get("narrative_blueprint")
        if existing_snapshot is not None and existing_snapshot["data"] == candidate:
            return NarrativePlanningResult(
                narrative=copy.deepcopy(candidate),
                changed=False,
                version=int(existing_snapshot["version"]),
                gate_reasons=(),
            )
        expected_version = (
            int(existing_snapshot["version"]) if existing_snapshot is not None else 0
        )
        entry = self.runtime.write_artifact(
            "narrative_blueprint",
            candidate,
            expected_version=expected_version,
            status="approved",
            created_by=created_by,
        )
        return NarrativePlanningResult(
            narrative=self.runtime.show_artifact("narrative_blueprint"),
            changed=True,
            version=int(entry["version"]),
            gate_reasons=(),
        )

    def audit(self) -> tuple[str, ...]:
        """Audit current Narrative against current Brief/Evidence lineage."""

        graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "evidence_ledger", "narrative_blueprint")
        )
        return narrative_gate_reasons(
            brief=graph["project_brief"]["data"],
            evidence=graph["evidence_ledger"]["data"],
            narrative=graph["narrative_blueprint"]["data"],
            graph=graph,
        )
