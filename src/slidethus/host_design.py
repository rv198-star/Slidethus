"""File bridge for reasoning performed by the host, never a model impersonator."""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.art_direction import TasteSkillArtDirectionProvider
from slidethus.art_direction_seed import (
    compile_art_direction_seed,
    load_art_direction_seed,
    validate_seed_reference_for_graph,
)
from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import ArtifactError, PlanningError
from slidethus.io_utils import atomic_create_json, canonical_json_bytes, read_json, sha256_json
from slidethus.planning_rules import planning_content_units
from slidethus.protocols import (
    ArtDirectionLimits,
    ArtDirectionProposal,
    ArtDirectionSeedProposal,
    PlanningLimits,
    PlanningProposal,
    PreLayoutArtDirection,
)
from slidethus.render_backends.artifact_tool_contract import (
    artifact_tool_host_contract,
)
from slidethus.schema_registry import SchemaRegistry


class HostDesignRequired(PlanningError):
    """A current stage awaits an explicit host response, not a fallback."""


_LAYOUT_FAMILY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_STORY_ARCS = {
    "problem-solution-proof-action",
    "situation-complication-resolution",
    "why-what-how",
    "chronological",
    "question-answer",
    "portfolio",
    "teaching",
    "custom",
}
_SLIDE_TYPES = {
    "cover",
    "agenda",
    "section",
    "statement",
    "evidence",
    "process",
    "comparison",
    "timeline",
    "matrix",
    "architecture",
    "chart",
    "case",
    "quote",
    "summary",
    "action",
    "appendix",
}
_EVIDENCE_REQUIREMENTS = {"required", "optional", "none"}
_CLAIM_MODES = {"label", "fact", "interpretation", "instruction", "asset"}
_REGION_FIELDS = {
    "block_id",
    "x",
    "y",
    "w",
    "h",
    "z",
    "align",
    "valign",
    "overflow_strategy",
}


def _contract_error(path: str, message: str) -> str:
    return f"{path}: {message}"


def _raise_contract_errors(prefix: str, findings: list[str]) -> None:
    stable = sorted(set(findings))
    if stable:
        raise PlanningError(prefix + ":\n- " + "\n- ".join(stable))


def _planning_proposal_findings(
    artifact_type: str,
    raw: dict[str, Any],
    context: dict[str, Any],
    limits: PlanningLimits,
) -> list[str]:
    """Return all deterministic pre-admission findings visible in one Host proposal."""

    findings: list[str] = []
    allowed = {"content", "warnings", "assumptions"}
    extras = sorted(set(raw) - allowed)
    if extras:
        findings.append(
            _contract_error("proposal", "unexpected fields: " + ", ".join(extras))
        )
    content = raw.get("content")
    if not isinstance(content, dict):
        findings.append(_contract_error("proposal.content", "must be an object"))
        return findings
    for field in ("warnings", "assumptions"):
        values = raw.get(field, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            findings.append(
                _contract_error(f"proposal.{field}", "must be a list of strings")
            )

    if artifact_type == "narrative_blueprint":
        for field in ("central_thesis", "story_rationale", "proof_strategy"):
            if not isinstance(content.get(field), str) or not content[field].strip():
                findings.append(
                    _contract_error(f"content.{field}", "must be non-empty text")
                )
        arc = content.get("story_arc")
        if arc not in _STORY_ARCS:
            findings.append(
                _contract_error(
                    "content.story_arc",
                    "must be one of: " + ", ".join(sorted(_STORY_ARCS)),
                )
            )
        journey = content.get("audience_journey")
        if not isinstance(journey, list):
            findings.append(
                _contract_error("content.audience_journey", "must be an array")
            )
        else:
            if len(journey) < 3:
                findings.append(
                    _contract_error(
                        "content.audience_journey", "must contain at least three stages"
                    )
                )
            if any(not isinstance(item, str) or not item.strip() for item in journey):
                findings.append(
                    _contract_error(
                        "content.audience_journey", "entries must be non-empty text"
                    )
                )
            if len(journey) != len(set(map(str, journey))):
                findings.append(
                    _contract_error(
                        "content.audience_journey", "must not contain duplicate stages"
                    )
                )
        sections = content.get("sections")
        if not isinstance(sections, list):
            findings.append(_contract_error("content.sections", "must be an array"))
        else:
            if not 2 <= len(sections) <= limits.max_sections:
                findings.append(
                    _contract_error(
                        "content.sections",
                        f"must contain 2..{limits.max_sections} sections",
                    )
                )
            for index, section in enumerate(sections):
                path = f"content.sections[{index}]"
                if not isinstance(section, dict):
                    findings.append(_contract_error(path, "must be an object"))
                    continue
                for field in ("title", "purpose"):
                    if not isinstance(section.get(field), str) or not section[field].strip():
                        findings.append(
                            _contract_error(f"{path}.{field}", "must be non-empty text")
                        )
                questions = section.get("key_questions")
                if not isinstance(questions, list) or not questions:
                    findings.append(
                        _contract_error(
                            f"{path}.key_questions", "must contain at least one question"
                        )
                    )
                evidence = section.get("evidence_ids")
                if not isinstance(evidence, list):
                    findings.append(
                        _contract_error(f"{path}.evidence_ids", "must be an array")
                    )
                if index < len(sections) - 1 and (
                    not isinstance(section.get("transition"), str)
                    or not section["transition"].strip()
                ):
                    findings.append(
                        _contract_error(
                            f"{path}.transition",
                            "must be non-empty before the final section",
                        )
                    )
        return findings

    if artifact_type == "deck_outline":
        slides = content.get("slides")
        if not isinstance(slides, list):
            findings.append(_contract_error("content.slides", "must be an array"))
            return findings
        if not 3 <= len(slides) <= limits.max_slides:
            findings.append(
                _contract_error(
                    "content.slides", f"must contain 3..{limits.max_slides} slides"
                )
            )
        for index, slide in enumerate(slides):
            path = f"content.slides[{index}]"
            if not isinstance(slide, dict):
                findings.append(_contract_error(path, "must be an object"))
                continue
            for field in (
                "section_index",
                "slide_type",
                "headline",
                "takeaway",
                "purpose",
                "audience_question",
                "evidence_ids",
                "evidence_requirement",
            ):
                if field not in slide:
                    findings.append(_contract_error(f"{path}.{field}", "is required"))
            if slide.get("slide_type") not in _SLIDE_TYPES:
                findings.append(
                    _contract_error(
                        f"{path}.slide_type",
                        "must be one of: " + ", ".join(sorted(_SLIDE_TYPES)),
                    )
                )
            if slide.get("evidence_requirement") not in _EVIDENCE_REQUIREMENTS:
                findings.append(
                    _contract_error(
                        f"{path}.evidence_requirement",
                        "must be required, optional, or none",
                    )
                )
            for field in ("headline", "takeaway", "purpose", "audience_question"):
                if field in slide and (
                    not isinstance(slide[field], str) or not slide[field].strip()
                ):
                    findings.append(
                        _contract_error(f"{path}.{field}", "must be non-empty text")
                    )
            if "evidence_ids" in slide and not isinstance(slide["evidence_ids"], list):
                findings.append(
                    _contract_error(f"{path}.evidence_ids", "must be an array")
                )
        if slides:
            if isinstance(slides[0], dict) and slides[0].get("slide_type") != "cover":
                findings.append(
                    _contract_error("content.slides[0].slide_type", "must be cover")
                )
            if isinstance(slides[-1], dict) and slides[-1].get("slide_type") not in {
                "action",
                "summary",
            }:
                findings.append(
                    _contract_error(
                        f"content.slides[{len(slides) - 1}].slide_type",
                        "must be action or summary",
                    )
                )
        return findings

    if artifact_type == "slide_specs":
        slides = content.get("slides")
        if not isinstance(slides, list):
            findings.append(_contract_error("content.slides", "must be an array"))
            return findings
        expected_ids = [
            str(item["slide_id"])
            for item in context.get("deck_outline", {}).get("slides", [])
            if item.get("status") != "excluded"
        ]
        submitted_ids = [
            str(item.get("slide_id", "")) if isinstance(item, dict) else ""
            for item in slides
        ]
        if submitted_ids != expected_ids:
            findings.append(
                _contract_error(
                    "content.slides",
                    "must cover active Deck Outline slide IDs once and in order",
                )
            )
        for index, slide in enumerate(slides):
            path = f"content.slides[{index}]"
            if not isinstance(slide, dict):
                findings.append(_contract_error(path, "must be an object"))
                continue
            for field in (
                "slide_id",
                "content_blocks",
                "visual_intent",
                "density_budget",
                "speaker_notes",
                "editability_intent",
            ):
                if field not in slide:
                    findings.append(_contract_error(f"{path}.{field}", "is required"))
            blocks = slide.get("content_blocks")
            if not isinstance(blocks, list):
                findings.append(
                    _contract_error(f"{path}.content_blocks", "must be an array")
                )
                blocks = []
            elif not 1 <= len(blocks) <= limits.max_blocks_per_slide:
                findings.append(
                    _contract_error(
                        f"{path}.content_blocks",
                        f"must contain 1..{limits.max_blocks_per_slide} blocks",
                    )
                )
            for block_index, block in enumerate(blocks):
                block_path = f"{path}.content_blocks[{block_index}]"
                if not isinstance(block, dict):
                    findings.append(_contract_error(block_path, "must be an object"))
                    continue
                for field in (
                    "semantic_role",
                    "content_type",
                    "priority",
                    "content",
                    "evidence_ids",
                    "evidence_requirement",
                    "claim_mode",
                ):
                    if field not in block:
                        findings.append(
                            _contract_error(f"{block_path}.{field}", "is required")
                        )
                if block.get("evidence_requirement") not in _EVIDENCE_REQUIREMENTS:
                    findings.append(
                        _contract_error(
                            f"{block_path}.evidence_requirement",
                            "must be required, optional, or none",
                        )
                    )
                if block.get("claim_mode") not in _CLAIM_MODES:
                    findings.append(
                        _contract_error(
                            f"{block_path}.claim_mode",
                            "must be label, fact, interpretation, instruction, or asset",
                        )
                    )
            visual = slide.get("visual_intent")
            if not isinstance(visual, dict):
                findings.append(
                    _contract_error(f"{path}.visual_intent", "must be an object")
                )
            else:
                families = visual.get("suggested_layout_families")
                if not isinstance(families, list) or not families:
                    findings.append(
                        _contract_error(
                            f"{path}.visual_intent.suggested_layout_families",
                            "must contain at least one semantic family",
                        )
                    )
                else:
                    invalid = [
                        str(item)
                        for item in families
                        if not isinstance(item, str)
                        or _LAYOUT_FAMILY_PATTERN.fullmatch(item) is None
                    ]
                    if invalid:
                        findings.append(
                            _contract_error(
                                f"{path}.visual_intent.suggested_layout_families",
                                "contains invalid semantic family names: "
                                + ", ".join(invalid),
                            )
                        )
                    if len(families) != len(set(map(str, families))):
                        findings.append(
                            _contract_error(
                                f"{path}.visual_intent.suggested_layout_families",
                                "must not contain duplicates",
                            )
                        )
            budget = slide.get("density_budget")
            if not isinstance(budget, dict):
                findings.append(
                    _contract_error(f"{path}.density_budget", "must be an object")
                )
            else:
                for field in ("max_blocks", "max_words", "min_body_pt"):
                    if field not in budget:
                        findings.append(
                            _contract_error(f"{path}.density_budget.{field}", "is required")
                        )
                max_blocks = budget.get("max_blocks")
                if not isinstance(max_blocks, int) or max_blocks < len(blocks):
                    findings.append(
                        _contract_error(
                            f"{path}.density_budget.max_blocks",
                            "must be an integer at least equal to the block count",
                        )
                    )
                units = sum(
                    planning_content_units(block.get("content"))
                    for block in blocks
                    if isinstance(block, dict)
                )
                max_words = budget.get("max_words")
                if (
                    not isinstance(max_words, int)
                    or max_words < units
                    or max_words > limits.max_words_per_slide
                ):
                    findings.append(
                        _contract_error(
                            f"{path}.density_budget.max_words",
                            f"must cover {units} content units and not exceed {limits.max_words_per_slide}",
                        )
                    )
                min_body = budget.get("min_body_pt")
                if (
                    not isinstance(min_body, (int, float))
                    or isinstance(min_body, bool)
                    or not math.isfinite(float(min_body))
                    or float(min_body) < 8
                ):
                    findings.append(
                        _contract_error(
                            f"{path}.density_budget.min_body_pt",
                            "must be a finite number of at least 8",
                        )
                    )
        return findings

    if artifact_type == "layout_plans":
        plans = content.get("plans")
        if not isinstance(plans, list):
            findings.append(_contract_error("content.plans", "must be an array"))
            return findings
        specs = context.get("slide_specs", {}).get("slides", [])
        expected_ids = [str(item.get("slide_id", "")) for item in specs]
        submitted_ids = [
            str(item.get("slide_id", "")) if isinstance(item, dict) else ""
            for item in plans
        ]
        if submitted_ids != expected_ids:
            findings.append(
                _contract_error(
                    "content.plans",
                    "must cover current Slide Specs once and in order",
                )
            )
        specs_by_id = {str(item.get("slide_id")): item for item in specs}
        for index, plan in enumerate(plans):
            path = f"content.plans[{index}]"
            if not isinstance(plan, dict):
                findings.append(_contract_error(path, "must be an object"))
                continue
            for field in ("slide_id", "layout_family", "rationale", "regions"):
                if field not in plan:
                    findings.append(_contract_error(f"{path}.{field}", "is required"))
            slide_id = str(plan.get("slide_id", ""))
            family = plan.get("layout_family")
            if not isinstance(family, str) or _LAYOUT_FAMILY_PATTERN.fullmatch(family) is None:
                findings.append(
                    _contract_error(
                        f"{path}.layout_family", "must be a bounded semantic name"
                    )
                )
            spec = specs_by_id.get(slide_id, {})
            suggested = set(
                map(
                    str,
                    spec.get("visual_intent", {}).get(
                        "suggested_layout_families", []
                    ),
                )
            )
            if family not in suggested:
                findings.append(
                    _contract_error(
                        f"{path}.layout_family",
                        "must be declared by the matching Slide Spec",
                    )
                )
            regions = plan.get("regions")
            if not isinstance(regions, list):
                findings.append(_contract_error(f"{path}.regions", "must be an array"))
                continue
            expected_blocks = [
                str(item.get("block_id", ""))
                for item in spec.get("content_blocks", [])
            ]
            submitted_blocks = [
                str(item.get("block_id", "")) if isinstance(item, dict) else ""
                for item in regions
            ]
            if sorted(submitted_blocks) != sorted(expected_blocks) or len(
                submitted_blocks
            ) != len(set(submitted_blocks)):
                findings.append(
                    _contract_error(
                        f"{path}.regions",
                        "must map every current content Block exactly once",
                    )
                )
            for region_index, region in enumerate(regions):
                region_path = f"{path}.regions[{region_index}]"
                if not isinstance(region, dict):
                    findings.append(_contract_error(region_path, "must be an object"))
                    continue
                if set(region) != _REGION_FIELDS:
                    findings.append(
                        _contract_error(
                            region_path,
                            "must contain exactly: "
                            + ", ".join(sorted(_REGION_FIELDS)),
                        )
                    )
                for field in ("x", "y", "w", "h"):
                    value = region.get(field)
                    if (
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not math.isfinite(float(value))
                        or (field in {"w", "h"} and float(value) <= 0)
                    ):
                        findings.append(
                            _contract_error(
                                f"{region_path}.{field}",
                                "must be finite geometry with positive width/height",
                            )
                        )
        return findings

    return findings


class HostDesignBridge:
    """Persist content-bound stage requests and read bounded host proposals."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".slidethus/host-design"
        self.pending: dict[str, Any] | None = None
        self.last_submission: dict[str, Any] | None = None

    def exchange(self, stage: str, context: dict[str, Any], limits: Any) -> dict[str, Any]:
        request = {
            "schema_version": "0.1.0",
            "stage": stage,
            "context": copy.deepcopy(context),
            "limits": asdict(limits),
        }
        digest = sha256_json(request)
        request_path = self.root / "requests" / f"{digest}.json"
        response_path = self.root / "responses" / f"{digest}.json"
        atomic_create_json(request_path, request)
        if read_json(request_path) != request:
            raise PlanningError("Host request content hash mismatch")
        self.pending = {
            "stage": stage,
            "request_hash": f"sha256:{digest}",
            "request_path": str(request_path),
            "response_path": str(response_path),
        }
        if not response_path.is_file():
            raise HostDesignRequired(
                f"Host design required for {stage}: read {request_path}; "
                f"submit a response bound to sha256:{digest} at {response_path}. "
                "No deterministic design fallback was used."
            )
        if response_path.stat().st_size > limits.max_provider_payload_bytes:
            raise PlanningError("Host response exceeds stage payload limit")
        try:
            response = read_json(response_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PlanningError(f"Cannot read host response: {exc}") from exc
        try:
            json.dumps(response, allow_nan=False)
        except ValueError as exc:
            raise PlanningError("Host response contains non-finite numbers") from exc
        schema = read_json(SchemaRegistry().schema_dir / "host_design_response.schema.json")
        schema_errors = sorted(
            Draft202012Validator(schema).iter_errors(response),
            key=lambda item: (list(item.absolute_path), item.message),
        )
        findings = [
            _contract_error(error.json_path, error.message) for error in schema_errors
        ]
        if "request_hash" in response and response.get("request_hash") != f"sha256:{digest}":
            findings.append(
                _contract_error(
                    "$.request_hash", "is stale or belongs to a different request"
                )
            )
        if "stage" in response and response.get("stage") != stage:
            findings.append(
                _contract_error("$.stage", "belongs to a different Host stage")
            )
        _raise_contract_errors("Invalid host response", findings)
        if len(canonical_json_bytes(response)) > limits.max_provider_payload_bytes:
            raise PlanningError("Host response exceeds stage payload limit")
        proposal = copy.deepcopy(response["proposal"])
        # Submission history is inspectable; stage admission has not happened yet.
        response_hash = sha256_json(response)
        received_path = self.root / "received" / f"{response_hash}.json"
        atomic_create_json(received_path, response)
        self.last_submission = {
            "stage": stage,
            "request_hash": f"sha256:{digest}",
            "request_path": str(request_path),
            "response_path": str(response_path),
            "response_hash": f"sha256:{response_hash}",
            "proposal_hash": f"sha256:{sha256_json(proposal)}",
            "received_path": str(received_path),
        }
        self.pending = None
        return proposal

    def restore_last_pending(self) -> None:
        """Restore the current request after proposal pre-admission rejects a response."""

        if self.last_submission is None:
            return
        self.pending = {
            key: self.last_submission[key]
            for key in ("stage", "request_hash", "request_path", "response_path")
        }


def _messages(raw: dict[str, Any], field: str) -> tuple[str, ...]:
    values = raw.get(field, [])
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise PlanningError(f"Host proposal {field} must be a list of strings")
    return tuple(values)


class HostPlanningProvider:
    """Use current host-authored proposals through the existing planning services."""

    name = "host-authored-planning"
    version = "1.0.0"

    def __init__(
        self,
        bridge: HostDesignBridge,
        *,
        art_direction_provider: HostArtDirectionProvider | None = None,
    ) -> None:
        self.bridge = bridge
        self.art_direction_provider = art_direction_provider
        self._revision_stage: str | None = None
        self._prepared_art_direction_seed: PreLayoutArtDirection | None = None

    def request_revision(self, artifact_type: str) -> None:
        """Bind the next matching proposal request to the superseded artifact."""

        if artifact_type not in {
            "narrative_blueprint",
            "deck_outline",
            "slide_specs",
            "layout_plans",
        }:
            raise PlanningError(f"Unsupported Host planning revision stage: {artifact_type}")
        self._revision_stage = artifact_type

    def _revision_context(self, artifact_type: str) -> dict[str, Any]:
        graph = ArtifactRuntime(self.bridge.workspace).read_artifact_graph_snapshot(
            (artifact_type,),
            optional_artifact_types=(artifact_type,),
        )
        snapshot = graph.get(artifact_type)
        if snapshot is None:
            raise PlanningError(
                f"Cannot revise missing Host planning artifact: {artifact_type}"
            )
        return {
            "requested": True,
            "supersedes": {
                "artifact_type": artifact_type,
                "version": int(snapshot["version"]),
                "content_hash": str(snapshot["content_hash"]),
            },
        }

    def prepare_art_direction_seed(
        self,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> PreLayoutArtDirection | None:
        """Freeze host-authored visual direction before Slide Specs choose their carriers."""

        if self.art_direction_provider is None:
            return None
        runtime = ArtifactRuntime(self.bridge.workspace)
        graph = runtime.read_artifact_graph_snapshot(
            ("project_brief", "deck_outline")
        )
        prepared = self._prepared_art_direction_seed
        if (
            prepared is not None
            and context.get("art_direction_seed") in (None, prepared.seed)
        ):
            try:
                current = validate_seed_reference_for_graph(
                    self.bridge.workspace,
                    prepared.reference,
                    graph,
                    schema_registry=runtime.registry,
                )
            except ArtifactError:
                self._prepared_art_direction_seed = None
            else:
                if current == prepared.seed:
                    return copy.deepcopy(prepared)
        if not self.art_direction_provider.seed_revision_requested:
            try:
                current_specs = runtime.show_artifact("slide_specs")
                current_reference = current_specs.get("art_direction_seed")
                if not isinstance(current_reference, dict):
                    raise ArtifactError(
                        "Current Slide Specs do not reference an Art Direction Seed"
                    )
                current_seed = validate_seed_reference_for_graph(
                    self.bridge.workspace,
                    current_reference,
                    graph,
                    schema_registry=runtime.registry,
                )
            except ArtifactError:
                pass
            else:
                if context.get("art_direction_seed") in (None, current_seed):
                    prepared = PreLayoutArtDirection(
                        reference=copy.deepcopy(current_reference),
                        seed=current_seed,
                    )
                    self._prepared_art_direction_seed = copy.deepcopy(prepared)
                    return prepared
        compiled = compile_art_direction_seed(
            self.bridge.workspace,
            graph,
            provider=self.art_direction_provider,
            limits=ArtDirectionLimits(
                max_provider_payload_bytes=min(
                    ArtDirectionLimits().max_provider_payload_bytes,
                    limits.max_provider_payload_bytes,
                )
            ),
        )
        prepared = PreLayoutArtDirection(
            reference=compiled.reference,
            seed=compiled.seed,
        )
        self._prepared_art_direction_seed = copy.deepcopy(prepared)
        return prepared

    def propose(
        self, artifact_type: str, context: dict[str, Any], limits: PlanningLimits
    ) -> PlanningProposal:
        request_context = copy.deepcopy(context)
        seed_reference = None
        if artifact_type == "slide_specs" and self.art_direction_provider is not None:
            prepared = self.prepare_art_direction_seed(request_context, limits)
            if prepared is None:
                raise PlanningError("Host planning has no Art Direction Seed provider")
            if request_context.get("art_direction_seed") != prepared.seed:
                raise PlanningError(
                    "Slide Specs request is missing the current frozen Art Direction Seed"
                )
            seed_reference = prepared.reference
            request_context["target_backend_contract"] = artifact_tool_host_contract()
        if self._revision_stage == artifact_type:
            request_context["revision_request"] = self._revision_context(artifact_type)
        raw = self.bridge.exchange(artifact_type, request_context, limits)
        findings = _planning_proposal_findings(
            artifact_type, raw, request_context, limits
        )
        if findings:
            self.bridge.restore_last_pending()
            _raise_contract_errors(
                f"Invalid Host {artifact_type} proposal",
                findings,
            )
        if self._revision_stage == artifact_type:
            self._revision_stage = None
        if artifact_type == "layout_plans":
            plans = raw["content"].get("plans", [])
            if not isinstance(plans, list) or not plans or any(
                not isinstance(plan, dict) or "regions" not in plan for plan in plans
            ):
                raise PlanningError("Host Layout proposals require explicit regions for every slide")
        return PlanningProposal(
            artifact_type=artifact_type,
            content=raw["content"],
            warnings=_messages(raw, "warnings"),
            assumptions=_messages(raw, "assumptions"),
            art_direction_seed=seed_reference,
        )


class HostArtDirectionProvider:
    """Admit host art direction; a pinned resource is not proof of a native prototype."""

    name = "host-authored-art-direction"
    version = "1.0.0"
    mode = "host-authored"

    def __init__(
        self,
        bridge: HostDesignBridge,
        *,
        require_taste_generated: bool = False,
    ) -> None:
        self.bridge = bridge
        self.require_taste_generated = require_taste_generated
        self._seed_revision_requested = False

    def request_seed_revision(self) -> None:
        """Make the next Seed exchange explicit and distinct from initial admission."""

        self._seed_revision_requested = True

    @property
    def seed_revision_requested(self) -> bool:
        """Return whether the next Seed exchange must bypass the frozen current Seed."""

        return self._seed_revision_requested

    def resource_identity(self) -> dict[str, Any]:
        return TasteSkillArtDirectionProvider().resource_identity()

    def propose_seed(
        self,
        context: dict[str, Any],
        limits: ArtDirectionLimits,
    ) -> ArtDirectionSeedProposal:
        """Request a real pre-layout design direction from the host."""

        self.resource_identity()
        request_context = copy.deepcopy(context)
        request_context["target_backend_contract"] = artifact_tool_host_contract()
        if self._seed_revision_requested:
            try:
                current_specs = ArtifactRuntime(self.bridge.workspace).show_artifact(
                    "slide_specs"
                )
            except ArtifactError:
                current_seed = None
            else:
                current_seed = current_specs.get("art_direction_seed")
            request_context["revision_request"] = {
                "requested": True,
                "supersedes": copy.deepcopy(current_seed),
            }
        raw = self.bridge.exchange("art_direction_seed", request_context, limits)
        self._seed_revision_requested = False
        required = {"design_read", "dials", "foundation", "direction"}
        if not required.issubset(raw) or set(raw) - required - {"warnings", "assumptions"}:
            raise PlanningError(
                "Art Direction Seed requires design_read, dials, foundation and direction"
            )
        if (
            not isinstance(raw["design_read"], str)
            or not isinstance(raw["dials"], dict)
            or not isinstance(raw["foundation"], dict)
            or not isinstance(raw["direction"], dict)
        ):
            raise PlanningError("Art Direction Seed fields have invalid types")
        if (
            self.require_taste_generated
            and raw["foundation"].get("kind") != "taste-generated"
        ):
            raise PlanningError(
                "Host Create requires a Taste-generated native visual prototype; "
                "taste-informed fallback is not admitted on this path"
            )
        return ArtDirectionSeedProposal(
            design_read=raw["design_read"],
            dials=raw["dials"],
            foundation=raw["foundation"],
            direction=raw["direction"],
            warnings=_messages(raw, "warnings"),
            assumptions=_messages(raw, "assumptions"),
        )

    def propose(
        self, context: dict[str, Any], limits: ArtDirectionLimits
    ) -> ArtDirectionProposal:
        self.resource_identity()
        request_context = copy.deepcopy(context)
        seed_ref = request_context.get("slide_specs", {}).get("art_direction_seed")
        if seed_ref is not None:
            request_context["art_direction_seed"] = load_art_direction_seed(
                self.bridge.workspace,
                seed_ref,
            )
        raw = self.bridge.exchange("art_direction", request_context, limits)
        required = {"design_read", "dials", "direction"}
        if not required.issubset(raw) or set(raw) - required - {"warnings", "assumptions"}:
            raise PlanningError("Art direction requires design_read, dials and direction")
        if not isinstance(raw["direction"], dict) or not raw["direction"].get("page_designs"):
            raise PlanningError("Host art direction requires explicit page_designs, not only tokens")
        return ArtDirectionProposal(
            design_read=raw["design_read"],
            dials=raw["dials"],
            direction=raw["direction"],
            warnings=_messages(raw, "warnings"),
            assumptions=_messages(raw, "assumptions"),
        )
