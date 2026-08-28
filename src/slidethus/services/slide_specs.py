from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import PlanningError, SlideSpecPlanningError
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
from slidethus.planning_rules import (
    block_content_hash,
    evidence_qualification_text,
    evidence_requires_qualification,
    outline_slide_content_hash,
    planning_content_units,
    slide_specs_gate_reasons,
    usable_evidence_map,
)
from slidethus.protocols import PlanningLimits, PlanningProvider


@dataclass(frozen=True)
class SlideSpecPlanningResult:
    """One versioned Production Slide Specs result."""

    slide_specs: dict[str, Any]
    changed: bool
    version: int
    gate_reasons: tuple[str, ...]


def _text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _generated_at(graph: dict[str, dict[str, Any]]) -> str:
    values = [
        str(item.get("updated_at") or "")
        for item in graph.values()
        if item.get("updated_at")
    ]
    return max(values) if values else utc_now()


def _block_number(block_id: str) -> int:
    try:
        return int(block_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


class SlideSpecPlanningService:
    """Expand current Outline sticky notes into evidence-safe page specifications."""

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
        self.provider_name = _text(getattr(self.provider, "name", ""), limit=128)
        self.provider_version = _text(
            getattr(self.provider, "version", ""), limit=128
        )
        if not self.provider_name or not self.provider_version:
            raise SlideSpecPlanningError(
                "Planning provider must declare bounded name and version"
            )

    def _proposal(self, context: dict[str, Any], limits: PlanningLimits):
        try:
            proposal = self.provider.propose("slide_specs", context, limits)
        except PlanningError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SlideSpecPlanningError(f"Planning provider failed: {exc}") from exc
        if _text(getattr(self.provider, "name", ""), limit=128) != self.provider_name or _text(
            getattr(self.provider, "version", ""), limit=128
        ) != self.provider_version:
            raise SlideSpecPlanningError(
                "Planning provider identity changed during Slide Specs generation"
            )
        return admit_planning_proposal(
            proposal,
            artifact_type="slide_specs",
            limits=limits,
        )

    def _admit_block(
        self,
        raw: dict[str, Any],
        *,
        slide_id: str,
        outline_evidence: set[str],
        usable: dict[str, dict[str, Any]],
        existing_blocks: list[dict[str, Any]],
        used_ids: set[str],
        next_number: int,
    ) -> tuple[dict[str, Any], int]:
        evidence_ids = list(
            dict.fromkeys(
                str(item)
                for item in raw.get("evidence_ids", [])
                if str(item) in usable
            )
        )
        raw_evidence_ids = [str(item) for item in raw.get("evidence_ids", [])]
        rejected = sorted(set(raw_evidence_ids) - set(evidence_ids))
        if rejected:
            raise SlideSpecPlanningError(
                f"Block on {slide_id} references unusable Evidence: "
                + ", ".join(rejected)
            )
        if not set(evidence_ids).issubset(outline_evidence):
            raise SlideSpecPlanningError(
                f"Block on {slide_id} references Evidence not declared by Outline"
            )
        requirement = str(
            raw.get("evidence_requirement")
            or ("required" if evidence_ids else "none")
        )
        if requirement not in {"required", "optional", "none"}:
            raise SlideSpecPlanningError(
                f"Block on {slide_id} has invalid Evidence requirement"
            )
        claim_mode = str(raw.get("claim_mode") or ("fact" if evidence_ids else "label"))
        if claim_mode not in {"label", "fact", "interpretation", "instruction", "asset"}:
            raise SlideSpecPlanningError(f"Block on {slide_id} has invalid claim_mode")
        if claim_mode == "fact" and not evidence_ids:
            raise SlideSpecPlanningError(f"Factual block on {slide_id} has no Evidence")
        if requirement == "required" and not evidence_ids:
            raise SlideSpecPlanningError(f"Required block on {slide_id} has no Evidence")
        if requirement == "none":
            evidence_ids = []
        qualification_parts = [
            evidence_qualification_text(usable[evidence_id])
            for evidence_id in evidence_ids
            if evidence_requires_qualification(usable[evidence_id])
        ]
        qualification = (
            _text(raw.get("evidence_qualification"), limit=1000)
            or "；".join(dict.fromkeys(item for item in qualification_parts if item))
            or None
        )
        content = copy.deepcopy(raw.get("content"))
        content_type = str(raw.get("content_type", "text"))
        if content_type != "spacer" and planning_content_units(content) < 1:
            raise SlideSpecPlanningError(f"Non-spacer block on {slide_id} has blank content")
        block: dict[str, Any] = {
            "block_id": "",
            "semantic_role": str(raw.get("semantic_role", "body")),
            "content_type": content_type,
            "priority": str(raw.get("priority", "secondary")),
            "content": content,
            "evidence_ids": evidence_ids,
            "evidence_requirement": requirement,
            "evidence_qualification": qualification,
            "claim_mode": claim_mode,
            "content_hash": "",
            "origin": (
                str(raw.get("origin"))
                if str(raw.get("origin")) in {"provider", "manual", "repair"}
                else "provider"
            ),
            "asset_refs": list(
                dict.fromkeys(str(item) for item in raw.get("asset_refs", []))
            ),
            "notes": list(
                dict.fromkeys(
                    _text(item, limit=500)
                    for item in raw.get("notes", [])
                    if _text(item, limit=500)
                )
            ),
        }
        block["content_hash"] = block_content_hash(block)
        matching_ids = [
            str(item["block_id"])
            for item in existing_blocks
            if item.get("content_hash") == block["content_hash"]
            and str(item.get("block_id")) not in used_ids
        ]
        if len(matching_ids) == 1:
            block_id = matching_ids[0]
        else:
            while f"BLK-{slide_id.replace('-', '')}-{next_number:02d}" in used_ids:
                next_number += 1
            if next_number > 99:
                raise SlideSpecPlanningError(f"Block ID space exhausted for {slide_id}")
            block_id = f"BLK-{slide_id.replace('-', '')}-{next_number:02d}"
            next_number += 1
        block["block_id"] = block_id
        used_ids.add(block_id)
        return block, next_number

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
        outline = graph["deck_outline"]["data"]
        evidence = graph["evidence_ledger"]["data"]
        usable = usable_evidence_map(evidence)
        active_outline = sorted(
            (item for item in outline.get("slides", []) if item.get("status") != "excluded"),
            key=lambda item: int(item.get("ordinal", 0)),
        )
        raw_by_id = {
            str(item.get("slide_id")): item
            for item in proposal_content.get("slides", [])
        }
        existing_snapshot = graph.get("slide_specs")
        existing = (
            copy.deepcopy(existing_snapshot["data"])
            if existing_snapshot is not None
            else None
        )
        if existing and existing.get("status") == "frozen":
            raise SlideSpecPlanningError(
                "Frozen Slide Specs require explicit repair operations, not regeneration"
            )
        existing_by_id = {
            str(item["slide_id"]): item for item in existing.get("slides", [])
        } if existing else {}
        slides: list[dict[str, Any]] = []
        for outline_slide in active_outline:
            slide_id = str(outline_slide["slide_id"])
            raw = raw_by_id.get(slide_id)
            if raw is None:
                raise SlideSpecPlanningError(
                    f"Planning provider omitted active Outline slide {slide_id}"
                )
            outline_hash = outline_slide_content_hash(outline_slide)
            prior = existing_by_id.get(slide_id)
            if prior and prior.get("status") == "frozen":
                if prior.get("outline_slide_ref", {}).get("content_hash") != outline_hash:
                    raise SlideSpecPlanningError(
                        f"Frozen Slide Spec {slide_id} is stale for current Outline"
                    )
                slides.append(copy.deepcopy(prior))
                continue
            raw_blocks = list(raw.get("content_blocks", []))
            if not 1 <= len(raw_blocks) <= limits.max_blocks_per_slide:
                raise SlideSpecPlanningError(
                    f"Slide {slide_id} block count exceeds admitted limits"
                )
            existing_blocks = list(prior.get("content_blocks", [])) if prior else []
            used_ids: set[str] = set()
            next_number = max(
                (_block_number(str(item.get("block_id", ""))) for item in existing_blocks),
                default=0,
            ) + 1
            outline_evidence = set(str(item) for item in outline_slide.get("evidence_ids", []))
            blocks: list[dict[str, Any]] = []
            for raw_block in raw_blocks:
                block, next_number = self._admit_block(
                    raw_block,
                    slide_id=slide_id,
                    outline_evidence=outline_evidence,
                    usable=usable,
                    existing_blocks=existing_blocks,
                    used_ids=used_ids,
                    next_number=next_number,
                )
                blocks.append(block)
            units = sum(planning_content_units(item["content"]) for item in blocks)
            if units > limits.max_words_per_slide:
                raise SlideSpecPlanningError(
                    f"Slide {slide_id} content exceeds max_words_per_slide={limits.max_words_per_slide}"
                )
            raw_budget = dict(raw.get("density_budget", {}))
            budget_max_blocks = int(raw_budget.get("max_blocks", len(blocks)))
            budget_max_words = int(raw_budget.get("max_words", max(units, 1)))
            if budget_max_blocks < len(blocks):
                raise SlideSpecPlanningError(
                    f"Slide {slide_id} provider budget is below its block count"
                )
            if budget_max_words < units:
                raise SlideSpecPlanningError(
                    f"Slide {slide_id} provider budget is below its content density"
                )
            budget = {
                "max_blocks": min(limits.max_blocks_per_slide, budget_max_blocks),
                "max_words": min(limits.max_words_per_slide, budget_max_words),
                "min_body_pt": max(12, float(raw_budget.get("min_body_pt", 18))),
            }
            visual = dict(raw.get("visual_intent", {}))
            families = list(
                dict.fromkeys(
                    _text(item, limit=120)
                    for item in visual.get("suggested_layout_families", [])
                    if _text(item, limit=120)
                )
            )
            if not families:
                raise SlideSpecPlanningError(f"Slide {slide_id} has no layout-family intent")
            slides.append(
                {
                    "slide_id": slide_id,
                    "section_id": str(outline_slide["section_id"]),
                    "slide_type": str(outline_slide["slide_type"]),
                    "status": "approved",
                    "outline_slide_ref": {
                        "slide_id": slide_id,
                        "content_hash": outline_hash,
                    },
                    "revision_note": _text(
                        prior.get("revision_note") if prior else "",
                        limit=500,
                    ),
                    "audience_question": str(outline_slide["audience_question"]),
                    "core_message": str(outline_slide["takeaway"]),
                    "content_blocks": blocks,
                    "visual_intent": {
                        "relationship": _text(visual.get("relationship"), limit=300),
                        "suggested_layout_families": families,
                        "avoid": list(
                            dict.fromkeys(
                                _text(item, limit=300)
                                for item in visual.get("avoid", [])
                                if _text(item, limit=300)
                            )
                        ),
                    },
                    "speaker_notes": _text(raw.get("speaker_notes"), limit=2000),
                    "density_budget": budget,
                    "editability_intent": str(
                        brief["constraints"]["editability_target"]
                    ),
                }
            )
        lineage_inputs = {
            "deck_outline": graph["deck_outline"],
            "evidence_ledger": graph["evidence_ledger"],
            "project_brief": graph["project_brief"],
        }
        lineage = build_planning_lineage(
            lineage_inputs,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            proposal=copy.deepcopy(proposal_content),
            policy={"service": "slide_specs", "limits": asdict(limits)},
            generated_at=_generated_at(lineage_inputs),
            warnings=warnings,
            assumptions=assumptions,
        )
        lineage = reuse_semantically_current_lineage(
            lineage,
            existing.get("planning_lineage") if existing else None,
            lineage_inputs,
            required_inputs=("deck_outline", "evidence_ledger", "project_brief"),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": brief["project_id"],
            "deck_id": str(outline["deck_id"]),
            "status": "approved",
            "repair_ids": list(existing.get("repair_ids", [])) if existing else [],
            "planning_lineage": lineage,
            "slides": slides,
        }

    def generate(
        self,
        *,
        limits: PlanningLimits | None = None,
        force: bool = False,
        created_by: str = "slide-spec-planning-service",
    ) -> SlideSpecPlanningResult:
        """Generate or idempotently reuse current Production Slide Specs."""

        admitted_limits = limits or PlanningLimits()
        validate_planning_limits(admitted_limits)
        g4 = evaluate_gate(self.workspace, "G4")
        if not g4.passed:
            raise SlideSpecPlanningError(
                "G4 must pass before Slide Specs generation: " + "; ".join(g4.reasons)
            )
        graph = self.runtime.read_artifact_graph_snapshot(
            (
                "project_brief",
                "evidence_ledger",
                "deck_outline",
                "slide_specs",
            ),
            optional_artifact_types=("slide_specs",),
        )
        existing = graph.get("slide_specs")
        current_policy = {"service": "slide_specs", "limits": asdict(admitted_limits)}
        if (
            not force
            and existing is not None
            and planning_artifact_reusable(
                existing["data"],
                graph,
                required_inputs=("deck_outline", "evidence_ledger", "project_brief"),
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                policy=current_policy,
            )
        ):
            reasons = slide_specs_gate_reasons(
                brief=graph["project_brief"]["data"],
                evidence=graph["evidence_ledger"]["data"],
                outline=graph["deck_outline"]["data"],
                slide_specs=existing["data"],
                graph=graph,
            )
            if not reasons:
                return SlideSpecPlanningResult(
                    slide_specs=copy.deepcopy(existing["data"]),
                    changed=False,
                    version=int(existing["version"]),
                    gate_reasons=(),
                )
        context = {
            "project_brief": copy.deepcopy(graph["project_brief"]["data"]),
            "evidence_ledger": copy.deepcopy(graph["evidence_ledger"]["data"]),
            "deck_outline": copy.deepcopy(graph["deck_outline"]["data"]),
        }
        proposal = self._proposal(context, admitted_limits)
        candidate = self._admit(
            proposal.content,
            graph=graph,
            warnings=proposal.warnings,
            assumptions=proposal.assumptions,
            limits=admitted_limits,
        )
        reasons = slide_specs_gate_reasons(
            brief=graph["project_brief"]["data"],
            evidence=graph["evidence_ledger"]["data"],
            outline=graph["deck_outline"]["data"],
            slide_specs=candidate,
            graph=graph,
        )
        if reasons:
            raise SlideSpecPlanningError(
                "Slide Specs proposal does not meet Production gate: "
                + "; ".join(reasons)
            )
        existing = graph.get("slide_specs")
        if existing is not None and existing["data"] == candidate:
            return SlideSpecPlanningResult(
                slide_specs=copy.deepcopy(candidate),
                changed=False,
                version=int(existing["version"]),
                gate_reasons=(),
            )
        expected_version = int(existing["version"]) if existing is not None else 0
        entry = self.runtime.write_artifact(
            "slide_specs",
            candidate,
            expected_version=expected_version,
            status="approved",
            created_by=created_by,
        )
        return SlideSpecPlanningResult(
            slide_specs=self.runtime.show_artifact("slide_specs"),
            changed=True,
            version=int(entry["version"]),
            gate_reasons=(),
        )

    def audit(self) -> tuple[str, ...]:
        """Audit current Production Slide Specs against current Outline/Evidence."""

        graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "evidence_ledger", "deck_outline", "slide_specs")
        )
        return slide_specs_gate_reasons(
            brief=graph["project_brief"]["data"],
            evidence=graph["evidence_ledger"]["data"],
            outline=graph["deck_outline"]["data"],
            slide_specs=graph["slide_specs"]["data"],
            graph=graph,
        )
