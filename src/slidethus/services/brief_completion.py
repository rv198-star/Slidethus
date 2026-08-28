from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.brief_completion import (
    brief_completion_context_hash,
    brief_completion_input_hash,
    brief_completion_result_hash,
    field_value,
    generated_assumption,
    generated_assumption_ids,
    generated_question,
    generated_question_ids,
    is_unresolved,
    normalize_text,
    request_inferences,
    set_field_value,
)
from slidethus.errors import BriefCompletionError
from slidethus.planning_limits import validate_planning_limits
from slidethus.protocols import BriefCompletionHints, PlanningLimits

_ENGINE_NAME = "deterministic-brief-completion"
_ENGINE_VERSION = "1.0.0"
_ALLOWED_MODES = {"live", "read", "both"}
_ALLOWED_DECISION_POWER = {"none", "influencer", "decision_maker", "mixed"}
_ALLOWED_KNOWLEDGE = {"novice", "intermediate", "expert", "mixed"}
_ALLOWED_FORMATS = {"pptx", "pdf", "svg", "png", "html", "artifacts_only"}
_ALLOWED_EDITABILITY = {"E0", "E1", "E2", "E3", "E4"}
_ALLOWED_APPROVAL = {"auto", "checkpoint", "strict"}
_ALLOWED_QUALITY = {"draft", "standard", "critical"}


@dataclass(frozen=True)
class BriefCompletionResult:
    """One deterministic Project Brief completion result."""

    brief: dict[str, Any]
    changed: bool
    version: int
    status: str
    blocking_questions: tuple[dict[str, Any], ...]
    inferred_fields: tuple[str, ...]


def _material_fields() -> tuple[str, ...]:
    return (
        "intent.purpose",
        "intent.desired_outcome",
        "intent.delivery_context",
        "audiences.0.role",
    )


def _default_needs(role: str) -> list[str]:
    normalized = role.casefold()
    if any(term in normalized for term in ("管理", "董事", "老板", "decision", "executive")):
        return ["核心结论", "价值与投入", "风险", "明确行动"]
    if any(term in normalized for term in ("客户", "甲方", "customer", "client")):
        return ["业务价值", "可信证据", "实施路径", "下一步合作"]
    if any(term in normalized for term in ("投资", "investor")):
        return ["市场机会", "差异化", "增长证据", "风险与回报"]
    if any(term in normalized for term in ("学员", "学生", "培训", "learner")):
        return ["概念框架", "操作步骤", "案例", "可练习的方法"]
    return ["核心信息", "可信依据", "后续行动"]


def _field_resolved(brief: dict[str, Any], path: str) -> bool:
    try:
        value = field_value(brief, path)
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return not is_unresolved(value)


def validate_brief_completion_hints(
    hints: BriefCompletionHints,
    limits: PlanningLimits,
) -> None:
    """Validate all explicit Brief hints before Source or Brief mutation."""

    validate_planning_limits(limits)
    if not isinstance(hints.request_text, str) or len(hints.request_text) > 20_000:
        raise BriefCompletionError("request_text must contain at most 20000 characters")
    scalar_limits = {
        "purpose": 4000,
        "desired_outcome": 4000,
        "call_to_action": 4000,
        "delivery_context": 1000,
        "audience_role": 1000,
    }
    for field, maximum in scalar_limits.items():
        value = getattr(hints, field)
        if value is not None and (
            not isinstance(value, str) or len(value) > maximum
        ):
            raise BriefCompletionError(
                f"{field} must be text with at most {maximum} characters"
            )

    def validate_text_tuple(values: object, field: str, maximum: int) -> None:
        if not isinstance(values, tuple):
            raise BriefCompletionError(f"{field} must be a tuple")
        if len(values) > limits.max_assumptions:
            raise BriefCompletionError(
                f"{field} exceeds max_assumptions={limits.max_assumptions}"
            )
        if len(values) != len(set(values)):
            raise BriefCompletionError(f"{field} must not contain duplicates")
        for item in values:
            if not isinstance(item, str) or not item.strip() or len(item) > maximum:
                raise BriefCompletionError(
                    f"{field} entries must contain 1..{maximum} characters"
                )

    validate_text_tuple(hints.audience_needs, "audience_needs", 1000)
    validate_text_tuple(hints.audience_objections, "audience_objections", 1000)
    if not isinstance(hints.output_formats, tuple):
        raise BriefCompletionError("output_formats must be a tuple")
    if len(hints.output_formats) != len(set(hints.output_formats)):
        raise BriefCompletionError("output_formats must not contain duplicates")
    if hints.presentation_mode is not None and hints.presentation_mode not in _ALLOWED_MODES:
        raise BriefCompletionError(f"Unsupported presentation_mode: {hints.presentation_mode}")
    if hints.decision_power is not None and hints.decision_power not in _ALLOWED_DECISION_POWER:
        raise BriefCompletionError(f"Unsupported decision_power: {hints.decision_power}")
    if hints.knowledge_level is not None and hints.knowledge_level not in _ALLOWED_KNOWLEDGE:
        raise BriefCompletionError(f"Unsupported knowledge_level: {hints.knowledge_level}")
    if hints.output_formats and not set(hints.output_formats).issubset(_ALLOWED_FORMATS):
        raise BriefCompletionError("Unsupported output format in Brief hints")
    if hints.editability_target is not None and hints.editability_target not in _ALLOWED_EDITABILITY:
        raise BriefCompletionError(f"Unsupported editability_target: {hints.editability_target}")
    if hints.approval_mode is not None and hints.approval_mode not in _ALLOWED_APPROVAL:
        raise BriefCompletionError(f"Unsupported approval_mode: {hints.approval_mode}")
    if hints.quality_profile is not None and hints.quality_profile not in _ALLOWED_QUALITY:
        raise BriefCompletionError(f"Unsupported quality_profile: {hints.quality_profile}")
    if hints.page_target is not None and not 1 <= hints.page_target <= limits.max_slides:
        raise BriefCompletionError(
            f"page_target must be between 1 and max_slides={limits.max_slides}"
        )
    if hints.duration_minutes is not None and (
        not isinstance(hints.duration_minutes, (int, float))
        or not math.isfinite(float(hints.duration_minutes))
        or not 0 <= float(hints.duration_minutes) <= 1440
    ):
        raise BriefCompletionError(
            "duration_minutes must be a finite value between 0 and 1440"
        )


class BriefCompletionService:
    """Complete a Project Brief conservatively and emit only material questions."""

    def __init__(self, workspace, *, runtime: ArtifactRuntime | None = None) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)

    def _source_summary(self, graph: dict[str, dict[str, Any]]) -> dict[str, Any]:
        sources = graph["source_ledger"]["data"].get("sources", [])
        return {
            "source_count": len(sources),
            "source_ids": [str(item.get("source_id")) for item in sources],
            "source_kinds": sorted({str(item.get("kind", "unknown")) for item in sources}),
            "source_titles": [normalize_text(item.get("title"), limit=240) for item in sources[:12]],
        }

    @staticmethod
    def _apply_answered_questions(brief: dict[str, Any]) -> list[str]:
        applied: list[str] = []
        for question in brief.get("open_questions", []):
            if question.get("status") != "answered":
                continue
            answer = normalize_text(question.get("answer"))
            paths = list(question.get("field_paths", []))
            if not answer or len(paths) != 1:
                continue
            path = str(paths[0])
            try:
                set_field_value(brief, path, answer)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            applied.append(path)
        return applied

    @staticmethod
    def _apply_value(
        brief: dict[str, Any],
        path: str,
        value: Any,
        *,
        explicit: bool,
        inferred_fields: set[str],
        resolved_fields: set[str],
    ) -> None:
        if value is None:
            return
        if isinstance(value, str):
            value = normalize_text(value)
            if not value:
                return
        set_field_value(brief, path, value)
        resolved_fields.add(path)
        if not explicit:
            inferred_fields.add(path)

    def complete(
        self,
        hints: BriefCompletionHints | None = None,
        *,
        limits: PlanningLimits | None = None,
        created_by: str = "brief-completion-service",
    ) -> BriefCompletionResult:
        """Complete current Brief fields, replacing broad prompts with bounded questions."""

        admitted_hints = hints or BriefCompletionHints()
        admitted_limits = limits or PlanningLimits()
        validate_brief_completion_hints(admitted_hints, admitted_limits)
        graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "source_ledger")
        )
        original = graph["project_brief"]["data"]
        expected_version = int(graph["project_brief"]["version"])
        brief = copy.deepcopy(original)
        source_summary = self._source_summary(graph)
        input_hash = brief_completion_input_hash(
            original,
            admitted_hints,
            source_summary=source_summary,
        )
        context_hash = brief_completion_context_hash(
            admitted_hints,
            source_summary=source_summary,
        )
        existing_completion = dict(original.get("completion", {}))
        if (
            existing_completion.get("context_hash") == context_hash
            and existing_completion.get("result_hash")
            == brief_completion_result_hash(original)
        ):
            blocking = tuple(
                copy.deepcopy(item)
                for item in original.get("open_questions", [])
                if item.get("blocking") and item.get("status") == "open"
            )
            return BriefCompletionResult(
                brief=copy.deepcopy(original),
                changed=False,
                version=expected_version,
                status=str(existing_completion.get("status", "needs_input")),
                blocking_questions=blocking,
                inferred_fields=tuple(existing_completion.get("inferred_fields", [])),
            )
        completed_at = (
            str(existing_completion["completed_at"])
            if existing_completion.get("context_hash") == context_hash
            else utc_now()
        )

        inferred = request_inferences(admitted_hints.request_text)
        explicit_values = {
            "purpose": admitted_hints.purpose,
            "desired_outcome": admitted_hints.desired_outcome,
            "call_to_action": admitted_hints.call_to_action,
            "delivery_context": admitted_hints.delivery_context,
            "presentation_mode": admitted_hints.presentation_mode,
            "audience_role": admitted_hints.audience_role,
            "audience_needs": list(admitted_hints.audience_needs) or None,
            "audience_objections": list(admitted_hints.audience_objections) or None,
            "decision_power": admitted_hints.decision_power,
            "knowledge_level": admitted_hints.knowledge_level,
            "page_target": admitted_hints.page_target,
            "duration_minutes": admitted_hints.duration_minutes,
            "output_formats": admitted_hints.output_formats or None,
            "editability_target": admitted_hints.editability_target,
            "approval_mode": admitted_hints.approval_mode,
            "quality_profile": admitted_hints.quality_profile,
        }
        for name, value in explicit_values.items():
            if value is not None:
                inferred[name] = value

        resolved_fields: set[str] = set(self._apply_answered_questions(brief))
        inferred_fields: set[str] = set()
        explicit_names = {name for name, value in explicit_values.items() if value is not None}

        mapping = {
            "purpose": "intent.purpose",
            "desired_outcome": "intent.desired_outcome",
            "call_to_action": "intent.call_to_action",
            "delivery_context": "intent.delivery_context",
            "presentation_mode": "intent.presentation_mode",
            "audience_role": "audiences.0.role",
            "audience_needs": "audiences.0.needs",
            "audience_objections": "audiences.0.objections",
            "decision_power": "audiences.0.decision_power",
            "knowledge_level": "audiences.0.knowledge_level",
            "duration_minutes": "constraints.duration_minutes",
            "editability_target": "constraints.editability_target",
            "approval_mode": "approval_mode",
            "quality_profile": "quality_profile",
        }
        for key, path in mapping.items():
            value = inferred.get(key)
            if value is None:
                continue
            self._apply_value(
                brief,
                path,
                value,
                explicit=key in explicit_names or bool(admitted_hints.request_text),
                inferred_fields=inferred_fields,
                resolved_fields=resolved_fields,
            )

        if inferred.get("page_target") is not None:
            target = int(inferred["page_target"])
            brief["constraints"]["page_count"] = {
                "min": min(int(brief["constraints"]["page_count"]["min"]), target),
                "target": target,
                "max": max(int(brief["constraints"]["page_count"]["max"]), target),
            }
            resolved_fields.add("constraints.page_count.target")
            if "page_target" not in explicit_names and not admitted_hints.request_text:
                inferred_fields.add("constraints.page_count.target")
        if inferred.get("output_formats"):
            formats = list(dict.fromkeys(str(item) for item in inferred["output_formats"]))
            brief["constraints"]["output_formats"] = formats
            resolved_fields.add("constraints.output_formats")

        assumptions: list[dict[str, Any]] = [
            copy.deepcopy(item)
            for item in brief.get("assumptions", [])
            if item.get("assumption_id") not in generated_assumption_ids()
        ]

        if is_unresolved(brief["intent"]["purpose"]):
            if source_summary["source_count"]:
                brief["intent"]["purpose"] = (
                    f"基于已入库的 {source_summary['source_count']} 份材料制作《{brief['title']}》演示"
                )
                purpose_assumption = "演示用途暂按“整理并呈现当前已入库材料”处理。"
                purpose_basis = "Project title and current Source inventory"
            else:
                brief["intent"]["purpose"] = f"制作关于《{brief['title']}》的结构化演示"
                purpose_assumption = "演示用途暂按项目标题所表达的主题进行结构化说明。"
                purpose_basis = "Project title"
            inferred_fields.add("intent.purpose")
            assumptions.append(
                generated_assumption(
                    "ASM-901",
                    purpose_assumption,
                    field_paths=("intent.purpose",),
                    basis=purpose_basis,
                    risk="medium",
                )
            )
        if is_unresolved(brief["intent"]["desired_outcome"]) and not is_unresolved(
            brief["intent"]["purpose"]
        ):
            brief["intent"]["desired_outcome"] = "让目标受众理解核心信息并形成明确判断"
            inferred_fields.add("intent.desired_outcome")
            assumptions.append(
                generated_assumption(
                    "ASM-902",
                    "在用户未指定行动目标时，默认目标是形成清晰理解和判断。",
                    field_paths=("intent.desired_outcome",),
                    basis="Safe presentation-planning default",
                    risk="medium",
                )
            )
        if is_unresolved(brief["intent"]["delivery_context"]):
            mode = str(brief["intent"].get("presentation_mode", "both"))
            default_context = {
                "live": "现场演示",
                "read": "独立阅读",
                "both": "现场演示与会后阅读",
            }.get(mode, "现场演示与会后阅读")
            brief["intent"]["delivery_context"] = default_context
            inferred_fields.add("intent.delivery_context")
            assumptions.append(
                generated_assumption(
                    "ASM-903",
                    f"交付场景暂按“{default_context}”处理。",
                    field_paths=("intent.delivery_context",),
                    basis="presentation_mode",
                    risk="low",
                )
            )
        role = normalize_text(brief["audiences"][0].get("role"))
        if role and not is_unresolved(role) and not brief["audiences"][0].get("needs"):
            brief["audiences"][0]["needs"] = _default_needs(role)
            inferred_fields.add("audiences.0.needs")
            assumptions.append(
                generated_assumption(
                    "ASM-904",
                    f"受众关注点根据角色“{role}”采用通用规划基线。",
                    field_paths=("audiences.0.needs",),
                    basis="Audience role heuristic",
                    risk="low",
                )
            )
        if brief["constraints"]["output_formats"] == ["artifacts_only"]:
            assumptions.append(
                generated_assumption(
                    "ASM-905",
                    "当前只要求规划 artifacts；最终输出格式可在 M4 前确认。",
                    field_paths=("constraints.output_formats",),
                    basis="Existing Project Brief default",
                    risk="low",
                )
            )

        questions: list[dict[str, Any]] = [
            copy.deepcopy(item)
            for item in brief.get("open_questions", [])
            if (
                item.get("question_id") not in generated_question_ids()
                or item.get("status") in {"answered", "waived"}
            )
            and not (
                item.get("question_id") == "Q-001"
                and normalize_text(item.get("question")).startswith("请补充用途、核心受众")
            )
        ]
        generated: list[dict[str, Any]] = []
        if is_unresolved(brief["intent"]["purpose"]):
            generated.append(
                generated_question(
                    "Q-901",
                    "这份演示要解决什么问题或完成什么沟通任务？",
                    field_paths=("intent.purpose",),
                    priority="critical",
                    reason="Purpose changes the narrative architecture and page selection.",
                )
            )
        if is_unresolved(brief["intent"]["desired_outcome"]):
            generated.append(
                generated_question(
                    "Q-902",
                    "看完这份演示后，希望受众形成什么判断或采取什么行动？",
                    field_paths=("intent.desired_outcome",),
                    priority="critical",
                    reason="Desired outcome determines the thesis, proof strategy, and ending.",
                )
            )
        if is_unresolved(brief["audiences"][0]["role"]):
            generated.append(
                generated_question(
                    "Q-903",
                    "核心受众是谁？请给出最主要的角色，例如管理层、客户、投资人或学员。",
                    field_paths=("audiences.0.role",),
                    priority="critical",
                    reason="Audience role materially changes terminology, depth, objections, and action.",
                )
            )
        if is_unresolved(brief["intent"]["delivery_context"]):
            generated.append(
                generated_question(
                    "Q-904",
                    "这份演示将用于什么场景，例如现场汇报、培训、路演或独立阅读？",
                    field_paths=("intent.delivery_context",),
                    priority="high",
                    reason="Delivery context changes pacing, density, and speaker-note strategy.",
                )
            )
        generated = generated[: admitted_limits.max_blocking_questions]
        questions.extend(generated)
        questions.sort(key=lambda item: int(str(item["question_id"]).split("-")[-1]))
        assumptions = assumptions[: admitted_limits.max_assumptions]
        assumptions.sort(key=lambda item: int(str(item["assumption_id"]).split("-")[-1]))
        brief["open_questions"] = questions
        brief["assumptions"] = assumptions

        for path in _material_fields():
            if _field_resolved(brief, path):
                resolved_fields.add(path)
        blocking = tuple(
            copy.deepcopy(item)
            for item in questions
            if item.get("blocking") and item.get("status") == "open"
        )
        status = "needs_input" if blocking else "resolved"
        brief["completion"] = {
            "status": status,
            "engine": _ENGINE_NAME,
            "engine_version": _ENGINE_VERSION,
            "completed_at": completed_at,
            "input_hash": input_hash,
            "context_hash": context_hash,
            "result_hash": "",
            "resolved_fields": sorted(resolved_fields),
            "inferred_fields": sorted(inferred_fields),
            "question_ids": [str(item["question_id"]) for item in questions],
            "assumption_ids": [str(item["assumption_id"]) for item in assumptions],
        }
        brief["completion"]["result_hash"] = brief_completion_result_hash(brief)

        changed = brief != original
        version = expected_version
        if changed:
            entry = self.runtime.write_artifact(
                "project_brief",
                brief,
                expected_version=expected_version,
                status="approved" if status == "resolved" else "draft",
                created_by=created_by,
            )
            version = int(entry["version"])
            brief = self.runtime.show_artifact("project_brief")
        return BriefCompletionResult(
            brief=copy.deepcopy(brief),
            changed=changed,
            version=version,
            status=status,
            blocking_questions=blocking,
            inferred_fields=tuple(sorted(inferred_fields)),
        )

    def answer(
        self,
        question_id: str,
        answer: str,
        *,
        limits: PlanningLimits | None = None,
        created_by: str = "brief-completion-service",
    ) -> BriefCompletionResult:
        """Answer one single-field Brief question and recompute material questions."""

        normalized_answer = normalize_text(answer)
        if not normalized_answer:
            raise BriefCompletionError("Brief question answer must not be blank")
        brief, version = self.runtime.read_artifact_snapshot("project_brief")
        question = next(
            (
                item
                for item in brief.get("open_questions", [])
                if item.get("question_id") == question_id
            ),
            None,
        )
        if question is None:
            raise BriefCompletionError(f"Unknown Brief question: {question_id}")
        paths = list(question.get("field_paths", []))
        if len(paths) != 1:
            raise BriefCompletionError(
                f"Question {question_id} does not map to exactly one Brief field"
            )
        set_field_value(brief, str(paths[0]), normalized_answer)
        question["status"] = "answered"
        question["answer"] = normalized_answer
        brief.pop("completion", None)
        self.runtime.write_artifact(
            "project_brief",
            brief,
            expected_version=version,
            status="draft",
            created_by=created_by,
        )
        return self.complete(limits=limits, created_by=created_by)
