from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import OutlinePlanningError, PlanningReviewError
from slidethus.io_utils import canonical_json_bytes, sha256_json
from slidethus.planning_changes import (
    OUTLINE_CHANGE_PROVIDER_NAME,
    OUTLINE_CHANGE_PROVIDER_VERSION,
    find_planning_change_by_idempotency_key,
    find_planning_change_report,
    planning_change_file_key,
    planning_change_id,
    planning_change_request_hash,
    validate_planning_change_data,
)
from slidethus.planning_limits import validate_planning_limits
from slidethus.planning_lineage import build_planning_lineage
from slidethus.planning_rules import (
    evidence_qualification_text,
    evidence_requires_qualification,
    outline_gate_reasons,
    usable_evidence_map,
)
from slidethus.protocols import PlanningLimits
from slidethus.schema_registry import SchemaRegistry

_ALLOWED_LOCK_FIELDS = {
    "section_id",
    "slide_type",
    "headline",
    "takeaway",
    "purpose",
    "evidence_ids",
    "position",
    "all",
}
_DOWNSTREAM_TYPES = (
    "slide_specs",
    "layout_plans",
    "visual_system",
    "render_manifest",
    "quality_report",
    "delivery_manifest",
)


@dataclass(frozen=True)
class OutlineChangeResult:
    """One atomic digital-sticky-note change and its immutable report."""

    outline: dict[str, Any]
    report: dict[str, Any]
    path: Path
    changed: bool
    version: int


def _text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _active(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (item for item in slides if item.get("status") != "excluded"),
        key=lambda item: int(item.get("ordinal", 0)),
    )


def _excluded(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in slides if item.get("status") == "excluded"]


def _slide_map(slides: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["slide_id"]): item for item in slides}


def _next_slide_number(slides: list[dict[str, Any]]) -> int:
    return max(
        (
            int(str(item["slide_id"]).split("-")[-1])
            for item in slides
            if str(item.get("slide_id", "")).startswith("S-")
        ),
        default=0,
    ) + 1


def _assert_mutable(slide: dict[str, Any], fields: set[str]) -> None:
    locked = set(str(item) for item in slide.get("locked_fields", []))
    if "all" in locked or locked.intersection(fields):
        raise OutlinePlanningError(
            f"Slide {slide.get('slide_id')} locks fields required by this operation: "
            + ", ".join(sorted(locked.intersection(fields) or {"all"}))
        )


def _downstream_registered(runtime: ArtifactRuntime) -> list[str]:
    present = {
        str(item.get("artifact_type")) for item in runtime.list_artifacts()
    }
    return [item for item in _DOWNSTREAM_TYPES if item in present]


class OutlineChangeService:
    """Apply explicit insert/exclude/reorder/split/merge/freeze operations atomically."""

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
        self.report_dir = self.workspace / ".slidethus/planning/changes"

    def _graph(self) -> dict[str, dict[str, Any]]:
        return self.runtime.read_artifact_graph_snapshot(
            (
                "project_brief",
                "evidence_ledger",
                "narrative_blueprint",
                "deck_outline",
            )
        )

    @staticmethod
    def _request_payload(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation": operation,
            "payload": copy.deepcopy(payload),
        }

    def _new_slide(
        self,
        raw: dict[str, Any],
        *,
        slide_id: str,
        ordinal: int,
        graph: dict[str, dict[str, Any]],
        change_id: str,
        derived_from: list[str],
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = copy.deepcopy(fallback or {})
        base.update(copy.deepcopy(raw))
        narrative_sections = {
            str(item["section_id"]): item
            for item in graph["narrative_blueprint"]["data"].get("sections", [])
            if item.get("status") != "excluded"
        }
        section_id = str(
            base.get("narrative_section_ref") or base.get("section_id") or ""
        )
        if section_id not in narrative_sections:
            raise OutlinePlanningError(
                f"New slide references unknown Narrative section: {section_id}"
            )
        usable = usable_evidence_map(graph["evidence_ledger"]["data"])
        evidence_ids = list(
            dict.fromkeys(
                str(item)
                for item in base.get("evidence_ids", [])
                if str(item) in usable
            )
        )
        raw_evidence_ids = [str(item) for item in base.get("evidence_ids", [])]
        rejected = sorted(set(raw_evidence_ids) - set(evidence_ids))
        if rejected:
            raise OutlinePlanningError(
                "New slide references unusable Evidence: " + ", ".join(rejected)
            )
        requirement = str(
            base.get("evidence_requirement")
            or ("required" if evidence_ids else "none")
        )
        if requirement not in {"required", "optional", "none"}:
            raise OutlinePlanningError(
                f"Invalid Evidence requirement for new slide {slide_id}: {requirement}"
            )
        if requirement == "required" and not evidence_ids:
            raise OutlinePlanningError(
                f"New slide {slide_id} requires Evidence but has no usable Evidence"
            )
        if requirement == "none":
            evidence_ids = []
        qualification_parts = [
            evidence_qualification_text(usable[evidence_id])
            for evidence_id in evidence_ids
            if evidence_requires_qualification(usable[evidence_id])
        ]
        qualification = (
            _text(base.get("evidence_qualification"), limit=1000)
            or "；".join(dict.fromkeys(item for item in qualification_parts if item))
            or None
        )
        locked_fields = list(
            dict.fromkeys(str(item) for item in base.get("locked_fields", []))
        )
        if not set(locked_fields).issubset(_ALLOWED_LOCK_FIELDS):
            raise OutlinePlanningError(
                f"New slide {slide_id} contains unsupported locked_fields"
            )
        slide = {
            "slide_id": slide_id,
            "ordinal": ordinal,
            "section_id": section_id,
            "narrative_section_ref": section_id,
            "slide_type": str(base.get("slide_type", "statement")),
            "headline": _text(base.get("headline"), limit=180),
            "takeaway": _text(base.get("takeaway"), limit=500),
            "purpose": _text(base.get("purpose"), limit=600),
            "audience_question": _text(
                base.get("audience_question")
                or (narrative_sections[section_id].get("key_questions") or [
                    narrative_sections[section_id]["purpose"]
                ])[0],
                limit=400,
            ),
            "content_scope": list(
                dict.fromkeys(
                    _text(item, limit=400)
                    for item in base.get(
                        "content_scope",
                        [base.get("purpose"), base.get("takeaway")],
                    )
                    if _text(item, limit=400)
                )
            ),
            "evidence_ids": evidence_ids,
            "evidence_requirement": requirement,
            "evidence_qualification": qualification,
            "transition_from": None,
            "transition_to": None,
            "status": (
                "frozen" if base.get("status") == "frozen" else "approved"
            ),
            "derived_from_slide_ids": list(dict.fromkeys(derived_from)),
            "operation_id": change_id,
            "locked_fields": locked_fields,
            "estimated_minutes": base.get("estimated_minutes"),
            "revision_note": _text(base.get("revision_note"), limit=500),
            "notes": list(
                dict.fromkeys(
                    _text(item, limit=500)
                    for item in base.get("notes", [])
                    if _text(item, limit=500)
                )
            ),
        }
        if any(
            not slide[field]
            for field in ("headline", "takeaway", "purpose", "audience_question")
        ):
            raise OutlinePlanningError(
                f"New slide {slide_id} requires headline, takeaway, purpose, and audience_question"
            )
        return slide

    @staticmethod
    def _renumber(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Operation mutators express the intended active order directly. Sorting by
        # stale pre-change ordinals here would silently undo an explicit reorder.
        active = [item for item in slides if item.get("status") != "excluded"]
        excluded = _excluded(slides)
        for ordinal, slide in enumerate(active, start=1):
            slide["ordinal"] = ordinal
        for index, slide in enumerate(active):
            slide["transition_from"] = (
                None
                if index == 0
                else f"从“{active[index - 1]['headline']}”进入当前问题。"
            )
            slide["transition_to"] = (
                None
                if index == len(active) - 1
                else f"继续回答“{active[index + 1]['audience_question']}”。"
            )
        return [*active, *excluded]

    def _lineage(
        self,
        graph: dict[str, dict[str, Any]],
        *,
        request_payload: dict[str, Any],
        generated_at: str,
        limits: PlanningLimits,
    ) -> dict[str, Any]:
        inputs = {
            "evidence_ledger": graph["evidence_ledger"],
            "narrative_blueprint": graph["narrative_blueprint"],
            "project_brief": graph["project_brief"],
        }
        return build_planning_lineage(
            inputs,
            provider_name=OUTLINE_CHANGE_PROVIDER_NAME,
            provider_version=OUTLINE_CHANGE_PROVIDER_VERSION,
            proposal=request_payload,
            policy={"service": "outline", "limits": asdict(limits)},
            generated_at=generated_at,
            assumptions=("This Outline version was produced by an explicit sticky-note operation.",),
        )

    def _apply(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        reason: str,
        idempotency_key: str | None,
        mutator: Callable[
            [
                dict[str, Any],
                dict[str, dict[str, Any]],
                str,
                PlanningLimits,
            ],
            tuple[dict[str, Any], dict[str, Any]],
        ],
        limits: PlanningLimits | None = None,
        created_by: str = "outline-change-service",
    ) -> OutlineChangeResult:
        normalized_reason = _text(reason)
        if not normalized_reason:
            raise OutlinePlanningError("Outline change requires a reason")
        admitted_limits = limits or PlanningLimits()
        validate_planning_limits(admitted_limits)
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key) > 512
        ):
            raise OutlinePlanningError(
                "Outline change idempotency_key must contain 1..512 characters"
            )
        request_payload = self._request_payload(operation, payload)
        try:
            request_size = len(
                canonical_json_bytes(
                    {
                        "request": request_payload,
                        "reason": normalized_reason,
                        "idempotency_key": idempotency_key,
                        "planning_limits": asdict(admitted_limits),
                    }
                )
            )
        except (TypeError, ValueError) as exc:
            raise OutlinePlanningError(
                "Outline change request is not JSON-serializable"
            ) from exc
        if request_size > admitted_limits.max_provider_payload_bytes:
            raise OutlinePlanningError(
                "Outline change request exceeds max_provider_payload_bytes="
                f"{admitted_limits.max_provider_payload_bytes}"
            )
        state = self.runtime.show_artifact("project_state")
        project_id = str(state["project_id"])
        request_hash = planning_change_request_hash(
            project_id,
            operation,
            payload,
            normalized_reason,
            limits=admitted_limits,
            idempotency_key=idempotency_key,
        )
        change_id = planning_change_id(project_id, request_hash)
        existing_report = find_planning_change_report(
            self.workspace,
            change_id,
            schema_dir=self.schemas.schema_dir,
        )
        if existing_report is not None:
            path, report = existing_report
            current = self.runtime.read_artifact_graph_snapshot(("deck_outline",))[
                "deck_outline"
            ]
            return OutlineChangeResult(
                outline=copy.deepcopy(current["data"]),
                report=report,
                path=path,
                changed=False,
                version=int(current["version"]),
            )
        if idempotency_key is not None:
            owned = find_planning_change_by_idempotency_key(
                self.workspace,
                idempotency_key,
                schema_dir=self.schemas.schema_dir,
            )
            if owned is not None:
                _owned_path, owned_report = owned
                raise PlanningReviewError(
                    "Planning Change idempotency key was already used with a different "
                    f"request or policy: {idempotency_key} -> {owned_report['change_id']}"
                )

        graph = self._graph()
        input_snapshot = graph["deck_outline"]
        outline = copy.deepcopy(input_snapshot["data"])
        if change_id in outline.get("operations_applied", []):
            raise PlanningReviewError(
                f"Outline contains operation {change_id} but its Change Report is missing"
            )
        candidate, facts = mutator(
            outline,
            graph,
            change_id,
            admitted_limits,
        )
        generated_at = utc_now()
        operations = list(candidate.get("operations_applied", []))
        operations.append(change_id)
        candidate["operations_applied"] = list(dict.fromkeys(operations))
        candidate["slides"] = self._renumber(list(candidate.get("slides", [])))
        candidate["target_page_count"] = len(_active(candidate["slides"]))
        candidate["planning_lineage"] = self._lineage(
            graph,
            request_payload=request_payload,
            generated_at=generated_at,
            limits=admitted_limits,
        )
        candidate["status"] = str(outline.get("status", "approved"))

        reasons = outline_gate_reasons(
            brief=graph["project_brief"]["data"],
            evidence=graph["evidence_ledger"]["data"],
            narrative=graph["narrative_blueprint"]["data"],
            outline=candidate,
            graph=graph,
        )
        if reasons:
            raise OutlinePlanningError(
                "Outline change would violate G4: " + "; ".join(reasons)
            )
        input_ref = {
            "artifact_type": "deck_outline",
            "version": int(input_snapshot["version"]),
            "content_hash": str(input_snapshot["content_hash"]),
        }
        output_ref = {
            "artifact_type": "deck_outline",
            "version": int(input_snapshot["version"]) + 1,
            "content_hash": "sha256:" + sha256_json(candidate),
        }
        report = {
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "change_id": change_id,
            "generated_at": generated_at,
            "operation": operation,
            "status": "applied",
            "reason": normalized_reason,
            "planning_limits": asdict(admitted_limits),
            "request_payload": copy.deepcopy(payload),
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "input_outline": input_ref,
            "output_outline": output_ref,
            "target_slide_ids": list(facts.get("target_slide_ids", [])),
            "created_slide_ids": list(facts.get("created_slide_ids", [])),
            "excluded_slide_ids": list(facts.get("excluded_slide_ids", [])),
            "preserved_slide_ids": list(facts.get("preserved_slide_ids", [])),
            "mappings": list(facts.get("mappings", [])),
            "changed_fields": list(facts.get("changed_fields", [])),
            "downstream_invalidated": _downstream_registered(self.runtime),
            "result_summary": _text(facts.get("result_summary"), limit=4000),
        }
        report_errors = validate_planning_change_data(report, self.schemas.schema_dir)
        if report_errors:
            raise PlanningReviewError(
                "Invalid Planning Change Report: " + "; ".join(report_errors)
            )
        path = self.report_dir / f"{planning_change_file_key(report)}.json"
        entry, _fact_created = self.runtime.write_artifact_with_runtime_fact(
            "deck_outline",
            candidate,
            expected_version=int(input_snapshot["version"]),
            fact_path=path,
            fact_data=report,
            status="approved",
            created_by=created_by,
        )
        return OutlineChangeResult(
            outline=self.runtime.show_artifact("deck_outline"),
            report=copy.deepcopy(report),
            path=path,
            changed=True,
            version=int(entry["version"]),
        )

    def insert(
        self,
        slide: dict[str, Any],
        *,
        position: int,
        reason: str,
        idempotency_key: str | None = None,
        limits: PlanningLimits | None = None,
    ) -> OutlineChangeResult:
        """Insert one new stable slide at a 1-indexed active position."""

        payload = {"position": position, "slide": copy.deepcopy(slide)}

        def mutate(outline, graph, change_id, admitted_limits):
            active = _active(outline["slides"])
            if not 1 <= position <= len(active) + 1:
                raise OutlinePlanningError(
                    f"Insert position must be between 1 and {len(active) + 1}"
                )
            if len(active) + 1 > admitted_limits.max_slides:
                raise OutlinePlanningError("Insert would exceed max_slides")
            next_number = _next_slide_number(outline["slides"])
            if next_number > 999:
                raise OutlinePlanningError("Slide ID space is exhausted")
            slide_id = f"S-{next_number:03d}"
            created = self._new_slide(
                slide,
                slide_id=slide_id,
                ordinal=position,
                graph=graph,
                change_id=change_id,
                derived_from=[],
            )
            active.insert(position - 1, created)
            output = copy.deepcopy(outline)
            output["slides"] = [*active, *_excluded(outline["slides"])]
            return output, {
                "target_slide_ids": [],
                "created_slide_ids": [slide_id],
                "excluded_slide_ids": [],
                "preserved_slide_ids": [
                    str(item["slide_id"]) for item in active if item is not created
                ],
                "mappings": [{"from_slide_ids": [], "to_slide_ids": [slide_id]}],
                "changed_fields": ["slides", "target_page_count", "transitions"],
                "result_summary": f"Inserted {slide_id} at active position {position}.",
            }

        return self._apply(
            "insert",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
            limits=limits,
        )

    def exclude(
        self,
        slide_id: str,
        *,
        reason: str,
        idempotency_key: str | None = None,
        limits: PlanningLimits | None = None,
    ) -> OutlineChangeResult:
        """Logically remove one active slide while preserving its stable identity."""

        payload = {"slide_id": slide_id}

        def mutate(outline, graph, change_id, admitted_limits):
            del graph, admitted_limits
            slides = copy.deepcopy(outline["slides"])
            target = _slide_map(slides).get(slide_id)
            if target is None or target.get("status") == "excluded":
                raise OutlinePlanningError(f"Unknown active slide: {slide_id}")
            _assert_mutable(target, {"all", "position"})
            target["status"] = "excluded"
            target["operation_id"] = change_id
            target["revision_note"] = reason
            active_ids = [
                str(item["slide_id"])
                for item in slides
                if item.get("status") != "excluded"
            ]
            output = copy.deepcopy(outline)
            output["slides"] = slides
            return output, {
                "target_slide_ids": [slide_id],
                "created_slide_ids": [],
                "excluded_slide_ids": [slide_id],
                "preserved_slide_ids": active_ids,
                "mappings": [{"from_slide_ids": [slide_id], "to_slide_ids": []}],
                "changed_fields": [f"slides.{slide_id}.status", "target_page_count", "transitions"],
                "result_summary": f"Excluded {slide_id} while retaining its historical object.",
            }

        return self._apply(
            "exclude",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
            limits=limits,
        )

    def reorder(
        self,
        slide_id: str,
        *,
        position: int,
        reason: str,
        idempotency_key: str | None = None,
        limits: PlanningLimits | None = None,
    ) -> OutlineChangeResult:
        """Move one active slide to a new 1-indexed position without changing its ID."""

        payload = {"slide_id": slide_id, "position": position}

        def mutate(outline, graph, change_id, admitted_limits):
            del graph, admitted_limits
            active = _active(copy.deepcopy(outline["slides"]))
            if not 1 <= position <= len(active):
                raise OutlinePlanningError(
                    f"Reorder position must be between 1 and {len(active)}"
                )
            target = next((item for item in active if item["slide_id"] == slide_id), None)
            if target is None:
                raise OutlinePlanningError(f"Unknown active slide: {slide_id}")
            _assert_mutable(target, {"all", "position"})
            old_position = active.index(target) + 1
            if old_position == position:
                raise OutlinePlanningError(
                    f"Slide {slide_id} is already at position {position}"
                )
            active.remove(target)
            active.insert(position - 1, target)
            target["operation_id"] = change_id
            target["revision_note"] = reason
            output = copy.deepcopy(outline)
            output["slides"] = [*active, *_excluded(outline["slides"])]
            return output, {
                "target_slide_ids": [slide_id],
                "created_slide_ids": [],
                "excluded_slide_ids": [],
                "preserved_slide_ids": [str(item["slide_id"]) for item in active],
                "mappings": [{"from_slide_ids": [slide_id], "to_slide_ids": [slide_id]}],
                "changed_fields": [f"slides.{slide_id}.ordinal", "transitions"],
                "result_summary": f"Moved {slide_id} from position {old_position} to {position}.",
            }

        return self._apply(
            "reorder",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
            limits=limits,
        )

    def split(
        self,
        slide_id: str,
        parts: list[dict[str, Any]],
        *,
        reason: str,
        idempotency_key: str | None = None,
        limits: PlanningLimits | None = None,
    ) -> OutlineChangeResult:
        """Replace one active slide with two or more newly identified slide tasks."""

        payload = {"slide_id": slide_id, "parts": copy.deepcopy(parts)}

        def mutate(outline, graph, change_id, admitted_limits):
            if not 2 <= len(parts) <= admitted_limits.max_change_targets:
                raise OutlinePlanningError(
                    "Split requires 2..max_change_targets parts"
                )
            slides = copy.deepcopy(outline["slides"])
            historical = _excluded(slides)
            active = _active(slides)
            target = next((item for item in active if item["slide_id"] == slide_id), None)
            if target is None:
                raise OutlinePlanningError(f"Unknown active slide: {slide_id}")
            _assert_mutable(target, {"all"})
            if len(active) - 1 + len(parts) > admitted_limits.max_slides:
                raise OutlinePlanningError("Split would exceed max_slides")
            position = active.index(target)
            next_number = _next_slide_number(slides)
            created: list[dict[str, Any]] = []
            for index, raw in enumerate(parts):
                if next_number > 999:
                    raise OutlinePlanningError("Slide ID space is exhausted")
                new_id = f"S-{next_number:03d}"
                next_number += 1
                created.append(
                    self._new_slide(
                        raw,
                        slide_id=new_id,
                        ordinal=position + index + 1,
                        graph=graph,
                        change_id=change_id,
                        derived_from=[slide_id],
                        fallback=target,
                    )
                )
            target["status"] = "excluded"
            target["operation_id"] = change_id
            target["revision_note"] = reason
            active[position : position + 1] = created
            output = copy.deepcopy(outline)
            output["slides"] = [*active, target, *historical]
            created_ids = [str(item["slide_id"]) for item in created]
            return output, {
                "target_slide_ids": [slide_id],
                "created_slide_ids": created_ids,
                "excluded_slide_ids": [slide_id],
                "preserved_slide_ids": [
                    str(item["slide_id"])
                    for item in active
                    if item["slide_id"] not in set(created_ids)
                ],
                "mappings": [
                    {"from_slide_ids": [slide_id], "to_slide_ids": created_ids}
                ],
                "changed_fields": ["slides", "target_page_count", "transitions"],
                "result_summary": f"Split {slide_id} into {', '.join(created_ids)}.",
            }

        return self._apply(
            "split",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
            limits=limits,
        )

    def merge(
        self,
        slide_ids: list[str],
        merged_slide: dict[str, Any],
        *,
        reason: str,
        idempotency_key: str | None = None,
        limits: PlanningLimits | None = None,
    ) -> OutlineChangeResult:
        """Replace contiguous active slides with one newly identified slide task."""

        payload = {
            "slide_ids": list(slide_ids),
            "merged_slide": copy.deepcopy(merged_slide),
        }

        def mutate(outline, graph, change_id, admitted_limits):
            if not 2 <= len(slide_ids) <= admitted_limits.max_change_targets:
                raise OutlinePlanningError(
                    "Merge requires 2..max_change_targets slide IDs"
                )
            if len(slide_ids) != len(set(slide_ids)):
                raise OutlinePlanningError("Merge slide IDs must be unique")
            slides = copy.deepcopy(outline["slides"])
            historical = _excluded(slides)
            active = _active(slides)
            active_map = _slide_map(active)
            targets = [active_map.get(slide_id) for slide_id in slide_ids]
            if any(item is None for item in targets):
                raise OutlinePlanningError("Merge references unknown active slide")
            admitted_targets = [item for item in targets if item is not None]
            positions = sorted(active.index(item) for item in admitted_targets)
            if positions != list(range(min(positions), max(positions) + 1)):
                raise OutlinePlanningError("Merge targets must be contiguous active slides")
            for item in admitted_targets:
                _assert_mutable(item, {"all"})
            next_number = _next_slide_number(slides)
            if next_number > 999:
                raise OutlinePlanningError("Slide ID space is exhausted")
            new_id = f"S-{next_number:03d}"
            fallback = copy.deepcopy(admitted_targets[0])
            if "evidence_ids" not in merged_slide:
                fallback["evidence_ids"] = list(
                    dict.fromkeys(
                        evidence_id
                        for item in admitted_targets
                        for evidence_id in item.get("evidence_ids", [])
                    )
                )
                fallback["evidence_requirement"] = (
                    "required"
                    if fallback["evidence_ids"]
                    else "none"
                )
            merged = self._new_slide(
                merged_slide,
                slide_id=new_id,
                ordinal=min(positions) + 1,
                graph=graph,
                change_id=change_id,
                derived_from=list(slide_ids),
                fallback=fallback,
            )
            for item in admitted_targets:
                item["status"] = "excluded"
                item["operation_id"] = change_id
                item["revision_note"] = reason
            remaining = [item for item in active if item not in admitted_targets]
            remaining.insert(min(positions), merged)
            output = copy.deepcopy(outline)
            output["slides"] = [*remaining, *admitted_targets, *historical]
            return output, {
                "target_slide_ids": list(slide_ids),
                "created_slide_ids": [new_id],
                "excluded_slide_ids": list(slide_ids),
                "preserved_slide_ids": [
                    str(item["slide_id"])
                    for item in remaining
                    if item["slide_id"] != new_id
                ],
                "mappings": [
                    {"from_slide_ids": list(slide_ids), "to_slide_ids": [new_id]}
                ],
                "changed_fields": ["slides", "target_page_count", "transitions"],
                "result_summary": f"Merged {', '.join(slide_ids)} into {new_id}.",
            }

        return self._apply(
            "merge",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
            limits=limits,
        )

    def freeze(
        self,
        slide_id: str,
        *,
        fields: tuple[str, ...] = ("all",),
        reason: str,
        idempotency_key: str | None = None,
    ) -> OutlineChangeResult:
        """Freeze admitted slide fields against regeneration and other operations."""

        payload = {"slide_id": slide_id, "fields": list(fields)}
        admitted_fields = set(fields)
        if not admitted_fields or not admitted_fields.issubset(_ALLOWED_LOCK_FIELDS):
            raise OutlinePlanningError("Freeze contains unsupported locked fields")

        def mutate(outline, graph, change_id, admitted_limits):
            del graph, admitted_limits
            slides = copy.deepcopy(outline["slides"])
            target = _slide_map(slides).get(slide_id)
            if target is None or target.get("status") == "excluded":
                raise OutlinePlanningError(f"Unknown active slide: {slide_id}")
            current = set(str(item) for item in target.get("locked_fields", []))
            if admitted_fields.issubset(current) and target.get("status") == "frozen":
                raise OutlinePlanningError(f"Slide {slide_id} is already frozen for those fields")
            target["locked_fields"] = sorted(current | admitted_fields)
            target["status"] = "frozen"
            target["operation_id"] = change_id
            target["revision_note"] = reason
            output = copy.deepcopy(outline)
            output["slides"] = slides
            return output, {
                "target_slide_ids": [slide_id],
                "created_slide_ids": [],
                "excluded_slide_ids": [],
                "preserved_slide_ids": [
                    str(item["slide_id"])
                    for item in slides
                    if item.get("status") != "excluded"
                ],
                "mappings": [{"from_slide_ids": [slide_id], "to_slide_ids": [slide_id]}],
                "changed_fields": [f"slides.{slide_id}.locked_fields", f"slides.{slide_id}.status"],
                "result_summary": f"Froze {slide_id}: {', '.join(sorted(admitted_fields))}.",
            }

        return self._apply(
            "freeze",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
        )

    def unfreeze(
        self,
        slide_id: str,
        *,
        reason: str,
        idempotency_key: str | None = None,
    ) -> OutlineChangeResult:
        """Remove all field locks from one active slide."""

        payload = {"slide_id": slide_id}

        def mutate(outline, graph, change_id, admitted_limits):
            del graph, admitted_limits
            slides = copy.deepcopy(outline["slides"])
            target = _slide_map(slides).get(slide_id)
            if target is None or target.get("status") == "excluded":
                raise OutlinePlanningError(f"Unknown active slide: {slide_id}")
            if not target.get("locked_fields") and target.get("status") != "frozen":
                raise OutlinePlanningError(f"Slide {slide_id} is not frozen")
            target["locked_fields"] = []
            target["status"] = "approved"
            target["operation_id"] = change_id
            target["revision_note"] = reason
            output = copy.deepcopy(outline)
            output["slides"] = slides
            return output, {
                "target_slide_ids": [slide_id],
                "created_slide_ids": [],
                "excluded_slide_ids": [],
                "preserved_slide_ids": [
                    str(item["slide_id"])
                    for item in slides
                    if item.get("status") != "excluded"
                ],
                "mappings": [{"from_slide_ids": [slide_id], "to_slide_ids": [slide_id]}],
                "changed_fields": [f"slides.{slide_id}.locked_fields", f"slides.{slide_id}.status"],
                "result_summary": f"Unfroze all fields on {slide_id}.",
            }

        return self._apply(
            "unfreeze",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
        )

    def update(
        self,
        slide_id: str,
        changes: dict[str, Any],
        *,
        reason: str,
        idempotency_key: str | None = None,
        limits: PlanningLimits | None = None,
    ) -> OutlineChangeResult:
        """Update admitted semantic fields on one slide without changing its identity."""

        allowed = {
            "section_id",
            "narrative_section_ref",
            "slide_type",
            "headline",
            "takeaway",
            "purpose",
            "audience_question",
            "content_scope",
            "evidence_ids",
            "evidence_requirement",
            "evidence_qualification",
            "estimated_minutes",
            "notes",
        }
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise OutlinePlanningError(
                "Outline update contains unsupported fields: " + ", ".join(unknown)
            )
        payload = {"slide_id": slide_id, "changes": copy.deepcopy(changes)}

        def mutate(outline, graph, change_id, admitted_limits):
            del admitted_limits
            slides = copy.deepcopy(outline["slides"])
            target = _slide_map(slides).get(slide_id)
            if target is None or target.get("status") == "excluded":
                raise OutlinePlanningError(f"Unknown active slide: {slide_id}")
            lock_fields = {
                "section_id" if key == "narrative_section_ref" else key
                for key in changes
            }
            _assert_mutable(target, lock_fields | {"all"})
            replacement = copy.deepcopy(target)
            replacement.update(copy.deepcopy(changes))
            normalized = self._new_slide(
                replacement,
                slide_id=slide_id,
                ordinal=int(target["ordinal"]),
                graph=graph,
                change_id=change_id,
                derived_from=list(target.get("derived_from_slide_ids", [])),
            )
            normalized["status"] = str(target.get("status", "approved"))
            normalized["locked_fields"] = list(target.get("locked_fields", []))
            index = slides.index(target)
            slides[index] = normalized
            output = copy.deepcopy(outline)
            output["slides"] = slides
            return output, {
                "target_slide_ids": [slide_id],
                "created_slide_ids": [],
                "excluded_slide_ids": [],
                "preserved_slide_ids": [
                    str(item["slide_id"])
                    for item in slides
                    if item.get("status") != "excluded"
                ],
                "mappings": [{"from_slide_ids": [slide_id], "to_slide_ids": [slide_id]}],
                "changed_fields": [f"slides.{slide_id}.{key}" for key in sorted(changes)],
                "result_summary": f"Updated {slide_id}: {', '.join(sorted(changes))}.",
            }

        return self._apply(
            "update",
            payload,
            reason=reason,
            idempotency_key=idempotency_key,
            mutator=mutate,
            limits=limits,
        )
