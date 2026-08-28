from __future__ import annotations

import copy
import re
from dataclasses import asdict
from typing import Any

from slidethus.io_utils import sha256_json
from slidethus.protocols import BriefCompletionHints

_PLACEHOLDERS = {"", "待补充", "tbd", "todo", "unknown", "未指定", "待确认"}
_GENERATED_QUESTION_IDS = {"Q-901", "Q-902", "Q-903", "Q-904"}
_GENERATED_ASSUMPTION_IDS = {"ASM-901", "ASM-902", "ASM-903", "ASM-904", "ASM-905"}


def normalize_text(value: Any, *, limit: int = 4000) -> str:
    """Return bounded single-space text for deterministic planning inputs."""

    text = " ".join(str(value or "").replace("\u00a0", " ").split()).strip()
    return text[:limit]


def is_unresolved(value: Any) -> bool:
    """Return whether a Brief scalar still carries an unresolved placeholder."""

    return normalize_text(value).casefold() in _PLACEHOLDERS


def brief_completion_input_payload(
    brief: dict[str, Any],
    hints: BriefCompletionHints,
    *,
    source_summary: dict[str, Any],
) -> dict[str, Any]:
    """Return the semantic input payload, excluding generated completion facts."""

    candidate = copy.deepcopy(brief)
    candidate.pop("completion", None)
    candidate["open_questions"] = [
        item
        for item in candidate.get("open_questions", [])
        if item.get("question_id") not in _GENERATED_QUESTION_IDS
    ]
    candidate["assumptions"] = [
        item
        for item in candidate.get("assumptions", [])
        if item.get("assumption_id") not in _GENERATED_ASSUMPTION_IDS
    ]
    return {
        "brief": candidate,
        "hints": asdict(hints),
        "source_summary": source_summary,
    }


def brief_completion_input_hash(
    brief: dict[str, Any],
    hints: BriefCompletionHints,
    *,
    source_summary: dict[str, Any],
) -> str:
    """Return the stable content hash used by Brief completion idempotency."""

    return "sha256:" + sha256_json(
        brief_completion_input_payload(brief, hints, source_summary=source_summary)
    )


def brief_completion_context_hash(
    hints: BriefCompletionHints,
    *,
    source_summary: dict[str, Any],
) -> str:
    """Return the stable external context hash for no-op detection."""

    return "sha256:" + sha256_json(
        {"hints": asdict(hints), "source_summary": source_summary}
    )


def brief_completion_result_hash(brief: dict[str, Any]) -> str:
    """Return the hash of a completed Brief excluding its self-referential completion fact."""

    candidate = copy.deepcopy(brief)
    candidate.pop("completion", None)
    return "sha256:" + sha256_json(candidate)


def request_inferences(text: str) -> dict[str, Any]:
    """Extract only conservative, explicit presentation hints from request text."""

    request = normalize_text(text)
    if not request:
        return {}
    lowered = request.casefold()
    output: dict[str, Any] = {"purpose": request}

    audience_patterns = (
        (r"(?:给|面向|向)(?:公司)?(?:老板|管理层|高管)", "企业管理层"),
        (r"(?:给|面向|向)(?:董事会|董事)", "董事会"),
        (r"(?:给|面向|向)(?:客户|甲方)", "客户决策者"),
        (r"(?:给|面向|向)(?:投资人|投资者)", "投资人"),
        (r"(?:给|面向|向)(?:学员|学生|参训人员)", "培训学员"),
        (r"(?:给|面向|向)(?:团队|员工|同事)", "内部团队"),
        (r"\bfor\s+(?:executives?|management)\b", "企业管理层"),
        (r"\bfor\s+(?:customers?|clients?)\b", "客户决策者"),
        (r"\bfor\s+investors?\b", "投资人"),
    )
    for pattern, role in audience_patterns:
        if re.search(pattern, lowered, re.IGNORECASE):
            output["audience_role"] = role
            break

    context_patterns = (
        (("培训", "课程", "教学", "workshop"), "培训授课"),
        (("路演", "pitch"), "现场路演"),
        (("董事会", "board"), "董事会决策会议"),
        (("汇报", "汇报会", "review"), "现场汇报"),
        (("宣讲", "发布会", "keynote"), "现场宣讲"),
        (("方案", "提案", "proposal"), "方案评审"),
        (("阅读版", "书面", "readout"), "独立阅读"),
    )
    for terms, context in context_patterns:
        if any(term in lowered for term in terms):
            output["delivery_context"] = context
            break

    if any(term in lowered for term in ("培训", "课程", "教学", "workshop")):
        output["desired_outcome"] = "让受众理解核心方法，并能够在实际任务中应用"
        output["presentation_mode"] = "live"
    elif any(term in lowered for term in ("批准", "决策", "立项", "选择方案", "board")):
        output["desired_outcome"] = "支持受众形成明确决策并批准下一步行动"
        output["call_to_action"] = "确认决策并授权下一步行动"
    elif any(term in lowered for term in ("销售", "购买", "签约", "成交", "pitch")):
        output["desired_outcome"] = "促使目标受众认可方案价值并进入下一步合作"
        output["call_to_action"] = "进入下一步合作或采购评估"
    elif any(term in lowered for term in ("复盘", "总结", "review")):
        output["desired_outcome"] = "形成共同认知，明确经验、问题和后续改进"
    else:
        output["desired_outcome"] = "让目标受众理解核心信息并形成明确判断"

    page_match = re.search(r"(?<!\d)(\d{1,3})\s*(?:页|pages?)\b", lowered)
    if page_match:
        output["page_target"] = int(page_match.group(1))
    duration_match = re.search(
        r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*(?:分钟|(?:min(?:ute)?s?)\b)",
        lowered,
    )
    if duration_match:
        output["duration_minutes"] = float(duration_match.group(1))
    formats: list[str] = []
    for marker, value in (("pptx", "pptx"), ("pdf", "pdf"), ("svg", "svg"), ("png", "png"), ("html", "html")):
        if marker in lowered:
            formats.append(value)
    if formats:
        output["output_formats"] = tuple(formats)
    return output


def field_value(data: dict[str, Any], path: str) -> Any:
    """Read one dotted Brief field path."""

    current: Any = data
    for part in path.split("."):
        if part.isdigit():
            current = current[int(part)]
        else:
            current = current[part]
    return current


def set_field_value(data: dict[str, Any], path: str, value: Any) -> None:
    """Set one admitted dotted Brief field path."""

    parts = path.split(".")
    current: Any = data
    for part in parts[:-1]:
        current = current[int(part)] if part.isdigit() else current[part]
    last = parts[-1]
    if last.isdigit():
        current[int(last)] = value
    else:
        current[last] = value


def generated_question(
    question_id: str,
    question: str,
    *,
    field_paths: tuple[str, ...],
    priority: str,
    reason: str,
    blocking: bool = True,
) -> dict[str, Any]:
    """Build one stable M3-generated Brief question."""

    return {
        "question_id": question_id,
        "question": question,
        "blocking": blocking,
        "status": "open",
        "answer": None,
        "field_paths": list(field_paths),
        "priority": priority,
        "reason": reason,
    }


def generated_assumption(
    assumption_id: str,
    statement: str,
    *,
    field_paths: tuple[str, ...],
    basis: str,
    risk: str,
) -> dict[str, Any]:
    """Build one stable M3-generated Project Brief assumption."""

    return {
        "assumption_id": assumption_id,
        "statement": statement,
        "status": "open",
        "field_paths": list(field_paths),
        "basis": basis,
        "risk": risk,
    }


def generated_question_ids() -> frozenset[str]:
    return frozenset(_GENERATED_QUESTION_IDS)


def generated_assumption_ids() -> frozenset[str]:
    return frozenset(_GENERATED_ASSUMPTION_IDS)
