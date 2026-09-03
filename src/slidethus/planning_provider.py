from __future__ import annotations

import re
from typing import Any

from slidethus.errors import PlanningError
from slidethus.protocols import PlanningLimits, PlanningProposal


def _text(value: Any, *, limit: int = 4000) -> str:
    normalized = " ".join(str(value or "").replace("\u00a0", " ").split()).strip()
    return normalized[:limit]


def _shorten(value: Any, limit: int) -> str:
    text = _text(value, limit=limit + 32)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip("，,。.;；:： ") + "…"


def _usable_claims(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in evidence.get("claims", [])
        if item.get("support_status") not in {"unsupported", "disputed"}
        and item.get("use_policy") != "do_not_use"
    ]


def _claim_qualification(claim: dict[str, Any]) -> str | None:
    support = str(claim.get("support_status", ""))
    freshness = str(claim.get("freshness_decision", {}).get("status", ""))
    policy = str(claim.get("use_policy", ""))
    reasons: list[str] = []
    if support == "provisional":
        reasons.append("该声明来自未独立抓取正文的间接或部分来源")
    elif support == "inference":
        reasons.append("该内容是基于来源的解释性推断")
    elif support == "assumption":
        reasons.append("该内容是待验证假设")
    if freshness == "stale":
        reasons.append("来源日期早于当前 freshness 要求")
    elif freshness == "unknown":
        reasons.append("确定性核心无法确认时效")
    if policy == "internal_only":
        reasons.append("仅限内部使用")
    if policy == "allowed_with_qualification" and not reasons:
        reasons.append("使用时需要显式限定来源能力或适用范围")
    return "；".join(reasons) if reasons else None


_THESIS_MARKERS = (
    "应该", "应当", "不应", "必须", "真正需要", "核心是", "关键是",
    " should ", " must ", " need ", " rather than ", " instead of ",
)
_PROBLEM_MARKERS = (
    "问题", "缺失", "不足", "阻碍", "风险", "无法", "不能", "不一致",
    " problem", " gap", " risk", " fail", " missing", " inconsistent",
)
_ACTION_MARKERS = (
    "建议", "批准", "立项", "决策请求", "下一步",
    " recommend", " approve", " decision", " next step", " pilot",
)


def _claim_clauses(value: Any) -> list[str]:
    text = _text(value, limit=4000)
    if not text:
        return []
    parts = re.split(r"[。！？!?；;]+|\s+(?=\d+[.、)]\s*)", text)
    return [part.strip(" ，,：:。；;!?！？") for part in parts if part.strip(" ，,：:。；;!?！？")]


def _numbered_labels(value: Any) -> list[str]:
    text = _text(value, limit=4000)
    return [
        _text(match, limit=24)
        for match in re.findall(r"(?:^|\s)\d+[.、)]\s*([^：:；;。]{1,24})[：:]", text)
        if _text(match, limit=24)
    ]


def _explicit_enumeration(value: Any) -> list[str]:
    text = _text(value, limit=4000)
    if text.count("、") < 3:
        return []
    clause = _claim_clauses(text)[0] if _claim_clauses(text) else text
    parts = [part.strip(" ，,。；;：:") for part in clause.split("、")]
    if len(parts) < 4 or any(not part for part in parts):
        return []
    tail = parts[-1]
    if "和" in tail and len(tail) <= 24:
        final = [item.strip() for item in tail.rsplit("和", 1) if item.strip()]
        if len(final) == 2:
            parts = [*parts[:-1], *final]
    return [_shorten(part, 72) for part in parts[:8]]


def _claim_role(value: Any) -> str:
    text = _text(value, limit=4000)
    folded = f" {text.casefold()} "
    if len(text) <= 18 and len(_claim_clauses(text)) <= 1:
        return "label"
    if any(marker in folded for marker in _ACTION_MARKERS):
        return "action"
    if re.search(r"(?:第一阶段|第二阶段|第三阶段|\bstage\s+\d|\bphase\s+\d)", folded):
        return "progression"
    if text.count("？") + text.count("?") >= 2:
        return "diagnostic"
    if _numbered_labels(text) or _explicit_enumeration(text):
        return "framework"
    clauses = _claim_clauses(text)
    if (
        re.search(r"(?:先.{1,120}(?:再|然后).{1,120}(?:最后|最终)|\bfirst\b.{1,120}\bthen\b.{1,120}\bfinally\b)", folded)
        or (
            len(clauses) >= 3
            and clauses[0].lstrip().startswith("先")
            and any(clause.lstrip().startswith(("最后", "最终")) for clause in clauses[1:])
        )
    ):
        return "process"
    if any(marker in folded for marker in _PROBLEM_MARKERS):
        return "problem"
    if any(marker in folded for marker in _THESIS_MARKERS):
        return "principle"
    return "evidence"


def _headline_from_claim(value: Any, limit: int = 56) -> str:
    text = _text(value, limit=4000)
    role = _claim_role(text)
    labels = _numbered_labels(text)
    enumeration = _explicit_enumeration(text)
    if role == "framework" and len(labels) >= 3:
        prefix = "核心构成：" if re.search(r"[\u3400-\u9fff]", text) else "Key elements: "
        return _shorten(prefix + "、".join(labels[:6]), limit)
    if role == "framework" and len(enumeration) >= 4:
        return _shorten("结构要素：" + "、".join(enumeration[:4]), limit)
    clauses = _claim_clauses(text)
    if not clauses:
        return _shorten(text, limit)
    if role == "principle":
        def score(clause: str) -> tuple[int, int]:
            folded = f" {clause.casefold()} "
            points = sum(marker in folded for marker in _THESIS_MARKERS)
            points += 2 * sum(marker in folded for marker in ("真正", "rather than", "instead of"))
            return points, min(len(clause), limit)
        candidate = max(clauses, key=score)
    else:
        candidate = clauses[0]
    return _shorten(candidate, limit)


def _is_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _trim_proposition_part(value: Any, limit: int = 28) -> str:
    text = _text(value, limit=240).strip(" ，,。；;：:!?！？\"'“”‘’")
    text = re.sub(
        r"^(?:第一|第二|第三|第四|第五)(?:阶段|步|，|,)?(?:可以|应当|应该|再)?",
        "",
        text,
    )
    text = re.sub(
        r"^(?:first|second|third|fourth|fifth)(?:\s+stage|\s+step)?\s*[:,.-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text if len(text) <= limit else ""


def _contrast_proposition(value: Any, limit: int) -> str | None:
    text = _text(value, limit=4000)
    chinese = re.search(
        r"(?:不应(?:该)?|不要|并非|不是)\s*(.{2,100}?)(?:[，,。；;]|而是|而应).*?"
        r"(?:真正需要|而是|而应|更应(?:该)?|应该)\s*(.{2,120}?)(?:[。；;]|$)",
        text,
    )
    if chinese:
        before = _trim_proposition_part(chinese.group(1), 22)
        after = _trim_proposition_part(chinese.group(2), 26)
        if before and after:
            proposition = f"重点应从{before}转向{after}"
            return proposition if len(proposition) <= limit else None
    english = re.search(
        r"\b(?:should\s+not|not)\s+(.{2,100}?)\s+"
        r"(?:but|rather\s+than|instead\s+of)\s+(.{2,120}?)(?:[.;]|$)",
        text,
        flags=re.IGNORECASE,
    )
    if english:
        before = _trim_proposition_part(english.group(1), 28)
        after = _trim_proposition_part(english.group(2), 32)
        if before and after:
            proposition = f"Shift the focus from {before} to {after}"
            return proposition if len(proposition) <= limit else None
    return None


def _responsibility_proposition(value: Any, limit: int) -> str | None:
    text = _text(value, limit=4000)
    pairs = [
        (_trim_proposition_part(subject, 16), _trim_proposition_part(responsibility, 24))
        for subject, responsibility in re.findall(
            r"(?:^|[。；;，,])\s*([^。；;，,]{1,24}?)负责([^。；;，,]{2,80})",
            text,
        )
    ]
    pairs = [(subject, responsibility) for subject, responsibility in pairs if subject and responsibility]
    if len(pairs) >= 2:
        left, right = pairs[-2:]
        proposition = f"{left[0]}与{right[0]}应按职责边界分工"
        return proposition if len(proposition) <= limit else None
    english_pairs = [
        (_trim_proposition_part(subject, 24), _trim_proposition_part(responsibility, 30))
        for subject, responsibility in re.findall(
            r"(?:^|[.;])\s*([^.;,]{1,36}?)\s+(?:owns|is responsible for)\s+([^.;]{2,90})",
            text,
            flags=re.IGNORECASE,
        )
    ]
    english_pairs = [item for item in english_pairs if all(item)]
    if len(english_pairs) >= 2:
        left, right = english_pairs[-2:]
        proposition = f"{left[0]} and {right[0]} need distinct responsibilities"
        return proposition if len(proposition) <= limit else None
    return None


def _sequence_proposition(value: Any, limit: int) -> str | None:
    text = _text(value, limit=4000)
    clauses = [
        item.strip(" ，,：:。；;!?！？")
        for item in re.split(
            r"[。！？!?；;]+|(?<!\d)\.(?!\d)|\s+(?=\d+[.、)]\s*)",
            text,
        )
        if item.strip(" ，,：:。；;!?！？")
    ]
    ordered = [
        clause
        for clause in clauses
        if re.match(
            r"^(?:第一|第二|第三|第四|第五)(?:阶段|步|，|,)|"
            r"^(?:first|second|third|fourth|fifth)(?:\s+stage|\s+step)?\b",
            clause,
            flags=re.IGNORECASE,
        )
    ]
    if len(ordered) < 2:
        return None
    labels = [_trim_proposition_part(item, 14 if _is_cjk(text) else 12) for item in ordered[:4]]
    labels = [item for item in labels if item]
    if len(labels) < 2:
        return (
            f"{len(ordered)}个阶段构成递进路径"
            if _is_cjk(text)
            else f"{len(ordered)} stages form a progressive path"
        )
    if _is_cjk(text):
        proposition = f"从{labels[0]}到{labels[-1]}形成递进路径"
    else:
        proposition = f"From {labels[0]} to {labels[-1]}: staged path"
    return proposition if len(proposition) <= limit else None


def _diagnostic_proposition(value: Any, limit: int) -> str | None:
    text = _text(value, limit=4000)
    question_count = text.count("？") + text.count("?")
    labels = _numbered_labels(text)
    count = max(question_count, len(labels))
    if count < 2:
        return None
    if _is_cjk(text):
        return _shorten(f"{count}项可验证条件共同决定方案能否稳定运行", limit)
    return _shorten(f"{count} verifiable conditions determine operational readiness", limit)


def _page_proposition(
    section: dict[str, Any],
    question: str,
    claims: list[dict[str, Any]],
    *,
    limit: int = 56,
) -> str:
    """Synthesize a page-job proposition from full assigned semantics."""

    texts = [_text(item.get("claim"), limit=4000) for item in claims]
    combined = "。".join(item for item in texts if item)
    roles = {_claim_role(item) for item in texts}
    for builder in (
        _contrast_proposition,
        _responsibility_proposition,
        _diagnostic_proposition if "diagnostic" in roles else lambda value, size: None,
        _sequence_proposition,
    ):
        proposition = builder(combined, limit)
        if proposition:
            return proposition
    title = _text(section.get("title"), limit=32)
    is_cjk = _is_cjk(combined + question)
    if "framework" in roles:
        count = max(
            (len(_support_fragments(text, max_fragments=12)) for text in texts),
            default=0,
        )
        if count >= 3:
            return (
                f"{count}项关键要素共同构成{title}"
                if is_cjk
                else f"{count} key elements jointly define {title}"
            )
    if any(marker in combined for marker in ("不应", "不是", "而是")) or re.search(
        r"\b(?:should\s+not|rather\s+than|instead\s+of)\b",
        combined,
        flags=re.IGNORECASE,
    ):
        return (
            f"{title}需要完成从旧重点到新重点的转移"
            if is_cjk
            else f"{title} requires a clear shift in focus"
        )
    if "process" in roles or "action" in roles:
        return (
            f"{title}需要分阶段推进并设置验证点"
            if is_cjk
            else f"{title} needs staged execution and verification checkpoints"
        )
    subjects = [
        _trim_proposition_part(clause.split("，", 1)[0].split(",", 1)[0], 18)
        for text in texts
        for clause in _claim_clauses(text)[:1]
    ]
    subjects = list(dict.fromkeys(item for item in subjects if item))
    if len(subjects) >= 2:
        if is_cjk:
            return f"多项证据共同支撑{title}的核心判断"
        return f"Multiple evidence points jointly shape {title}"
    if subjects:
        if is_cjk:
            proposition = f"{title}的关键在于{subjects[0]}"
        else:
            proposition = f"{subjects[0]} is central to {title}"
        if len(proposition) <= limit:
            return proposition
    return f"{title}需要形成可执行的核心判断" if is_cjk else f"{title} requires an actionable core judgment"


def _semantic_key(value: Any) -> str:
    text = _text(value, limit=1000).casefold()
    text = re.sub(
        r"^(?:决策请求|行动请求|decision request|request|decision)\s*[:：-]?\s*",
        "",
        text,
    )
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text)


def _action_support_items(primary_cta: str) -> list[str]:
    candidates = (
        [
            "责任：明确一位对结果负责的执行负责人",
            "时间：确认启动窗口和完成时限",
            "检查点：约定下一次复盘以及继续、调整或停止的条件",
        ]
        if _is_cjk(primary_cta)
        else [
            "Owner: name one accountable execution owner",
            "Timing: confirm the start window and completion deadline",
            "Checkpoint: agree when to review and the conditions to continue, adjust, or stop",
        ]
    )
    primary_key = _semantic_key(primary_cta)
    return [
        item
        for item in candidates
        if _semantic_key(item) != primary_key
        and _semantic_key(item) not in primary_key
        and primary_key not in _semantic_key(item)
    ]


def _cover_takeaway(brief: dict[str, Any], narrative: dict[str, Any]) -> str:
    thesis = _text(narrative.get("central_thesis"), limit=180)
    outcome = _text(brief.get("intent", {}).get("desired_outcome"), limit=120)
    if not outcome or _semantic_key(outcome) in _semantic_key(thesis):
        return _shorten(thesis, 180)
    if _is_cjk(thesis + outcome):
        return _shorten(f"{thesis}；决策目标：{outcome}", 180)
    return _shorten(f"{thesis}; decision outcome: {outcome}", 180)


def _support_fragments(value: Any, *, max_fragments: int = 8) -> list[str]:
    text = _text(value, limit=4000)
    enumeration = _explicit_enumeration(text)
    if enumeration:
        return enumeration[:max_fragments]
    parts = _claim_clauses(text)
    if len(parts) <= 1:
        return [_shorten(text, 180)] if text else []
    normalized = [_shorten(part, 180) for part in parts if len(part.strip()) >= 4]
    if len(normalized) <= max_fragments:
        return normalized
    return [
        *normalized[: max_fragments - 1],
        _shorten("；".join(normalized[max_fragments - 1 :]), 240),
    ]


def _takeaway_from_claims(
    claims: list[dict[str, Any]],
    headline: str,
) -> str:
    if not claims:
        return ""
    support: list[str] = []
    headline_folded = _text(headline).casefold()
    for claim_index, claim in enumerate(claims):
        fragments = _support_fragments(claim.get("claim"), max_fragments=4)
        if claim_index == 0:
            fragments = [
                fragment
                for fragment in fragments
                if _text(fragment).casefold() != headline_folded
                and headline_folded not in _text(fragment).casefold()
            ]
        if not fragments and claim_index > 0:
            fragments = [_headline_from_claim(claim.get("claim"), 80)]
        support.extend(fragment for fragment in fragments if fragment)
    if support:
        return _shorten("；".join(support[:4]), 240)
    if len(claims) > 1:
        return _shorten(
            "；".join(_headline_from_claim(item.get("claim"), 80) for item in claims[1:]),
            240,
        )
    return _shorten(_text(claims[0].get("claim")), 240)


def _claim_score_for_thesis(claim: dict[str, Any]) -> tuple[int, int]:
    text = _text(claim.get("claim"), limit=4000)
    role = _claim_role(text)
    score = {
        "principle": 8,
        "framework": 5,
        "problem": 5,
        "process": 4,
        "progression": 4,
        "action": 3,
        "diagnostic": 3,
        "evidence": 2,
        "label": -3,
    }[role]
    if 24 <= len(text) <= 260:
        score += 2
    return score, min(len(text), 260)


def _effective_page_target(
    brief: dict[str, Any],
    claims: list[dict[str, Any]],
) -> int:
    contract = brief.get("constraints", {}).get("page_count", {})
    requested = max(3, int(contract.get("target", 3) or 3))
    minimum = max(3, int(contract.get("min", 1) or 1))
    maximum = max(minimum, int(contract.get("max", requested) or requested))
    semantic_capacity = max(3, len(claims) + 2)
    return max(minimum, min(requested, maximum, semantic_capacity))


def _section_index_for_role(arc: str, role: str, count: int) -> int:
    if count <= 1:
        return 0
    normalized = {
        "problem-solution-proof-action": {
            "label": 0,
            "progression": 0,
            "problem": 1,
            "diagnostic": 1,
            "principle": 2,
            "framework": 2,
            "evidence": 3,
            "process": 4,
            "action": 4,
        },
        "teaching": {
            "label": 0,
            "problem": 0,
            "principle": 1,
            "framework": 1,
            "diagnostic": 2,
            "evidence": 2,
            "progression": 2,
            "process": 2,
            "action": 3,
        },
    }.get(arc, {
        "label": 0,
        "problem": 0,
        "diagnostic": 0,
        "principle": 1,
        "framework": 1,
        "evidence": 2,
        "progression": 2,
        "process": 2,
        "action": 3,
    })
    return min(count - 1, int(normalized.get(role, count - 1)))


def _relationship_for_claims(slide_type: str, claims: list[dict[str, Any]]) -> str:
    if slide_type == "cover":
        return "single thesis"
    if slide_type == "section":
        return "section transition"
    if slide_type == "action":
        return "ordered action"
    roles = {_claim_role(item.get("claim")) for item in claims}
    if "progression" in roles:
        return "time"
    if roles.intersection({"process", "action"}):
        return "sequence"
    if roles.intersection({"framework", "diagnostic"}):
        return "classification"
    if "problem" in roles and "principle" in roles:
        return "contrast"
    if slide_type == "comparison":
        return "contrast"
    return "claim and proof" if claims else "hierarchy"


def _story_arc(brief: dict[str, Any]) -> str:
    purpose = _text(brief.get("intent", {}).get("purpose")).casefold()
    outcome = _text(brief.get("intent", {}).get("desired_outcome")).casefold()
    action = _text(brief.get("intent", {}).get("call_to_action")).casefold()
    audience = brief.get("audiences", [{}])[0]
    role = _text(audience.get("role")).casefold()
    if any(term in purpose for term in ("培训", "课程", "教学", "workshop", "teach")):
        return "teaching"
    if any(term in purpose for term in ("时间线", "历程", "历史", "演进", "chronolog")):
        return "chronological"
    if any(term in purpose for term in ("问答", "答疑", "faq", "question")):
        return "question-answer"
    if action or any(term in outcome + role for term in ("决策", "批准", "立项", "董事", "管理", "decision")):
        return "problem-solution-proof-action"
    if any(term in purpose for term in ("方案", "策略", "转型", "改造", "proposal", "strategy")):
        return "situation-complication-resolution"
    return "why-what-how"


def _section_templates(arc: str) -> list[tuple[str, str, str]]:
    templates = {
        "teaching": [
            ("建立共同起点", "说明学习目标、范围和关键问题", "受众为什么需要先建立这套认知？"),
            ("核心框架", "解释概念、原则和关键关系", "这套方法的核心结构是什么？"),
            ("方法与证据", "用步骤、案例和证据说明如何应用", "如何把框架落实到真实任务？"),
            ("应用与行动", "总结迁移方式和下一步练习", "受众离开后应该如何开始？"),
        ],
        "problem-solution-proof-action": [
            ("决策背景", "建立当前情境、目标和决策窗口", "为什么现在需要做出判断？"),
            ("关键问题", "明确现状与目标之间的主要缺口", "真正阻碍结果的核心问题是什么？"),
            ("方案与机制", "说明推荐方向以及它如何解决问题", "建议采取什么方案，机制是什么？"),
            ("证据、风险与取舍", "展示支持依据、限制和主要风险", "为什么相信它，代价与风险是什么？"),
            ("决策与行动", "收敛为明确选择、责任和下一步", "现在需要决定什么并如何推进？"),
        ],
        "situation-complication-resolution": [
            ("现状与目标", "建立共同事实和目标状态", "我们现在在哪里，要去哪里？"),
            ("矛盾与约束", "解释为什么当前方式不足", "什么矛盾使现状不可持续？"),
            ("解决路径", "提出解决框架和实施顺序", "怎样以可控方式解决？"),
            ("证据与边界", "验证路径并披露风险和适用条件", "方案在哪些条件下成立？"),
            ("下一步", "明确近期行动和检查点", "如何从今天开始？"),
        ],
        "chronological": [
            ("起点", "说明背景和初始条件", "故事从哪里开始？"),
            ("关键演进", "呈现影响结果的转折与变化", "哪些变化真正改变了轨迹？"),
            ("当前状态", "解释今天的事实、能力和问题", "我们现在处于什么位置？"),
            ("下一阶段", "给出未来方向和行动", "下一步应该走向哪里？"),
        ],
        "question-answer": [
            ("核心问题", "定义受众真正关心的问题", "我们到底要回答什么？"),
            ("关键答案", "逐层给出明确回答", "最重要的答案是什么？"),
            ("证据与异议", "证明答案并回应反对意见", "哪些证据支持，哪些边界需要说明？"),
            ("结论与行动", "把答案转为可执行选择", "基于答案应该如何行动？"),
        ],
        "why-what-how": [
            ("为什么", "说明主题的重要性、目标和受众影响", "为什么值得关注？"),
            ("是什么", "定义核心概念、范围和关键结构", "需要建立什么共同理解？"),
            ("怎么做", "给出步骤、机制和证据", "如何落实并验证？"),
            ("下一步", "总结行动和检查点", "现在应该开始做什么？"),
        ],
    }
    return list(templates.get(arc, templates["why-what-how"]))


def _allocate_slide_budgets(target: int, count: int) -> list[int]:
    available = max(count, target - 2)
    base, remainder = divmod(available, count)
    return [max(1, base + (1 if index < remainder else 0)) for index in range(count)]


def _layout_family_for(
    slide_type: str,
    blocks: list[dict[str, Any]],
    relationship: str | None = None,
) -> str:
    relation = _text(relationship, limit=160).casefold()
    relation_mapping = {
        "single thesis": "hero",
        "section transition": "hero",
        "ordered action": "process",
        "sequence": "process",
        "time": "timeline",
        "contrast": "split",
        "classification": "matrix",
        "two-dimensional classification": "matrix",
        "system relationships": "architecture",
        "quantitative evidence": "chart-story",
        "claim and proof": "case",
    }
    if relation in relation_mapping:
        family = relation_mapping[relation]
    else:
        family = ""
    mapping = {
        "cover": "hero",
        "agenda": "split",
        "section": "hero",
        "statement": "hero",
        "evidence": "case",
        "process": "process",
        "comparison": "split",
        "timeline": "timeline",
        "matrix": "matrix",
        "architecture": "architecture",
        "chart": "chart-story",
        "case": "case",
        "quote": "hero",
        "summary": "split",
        "action": "process",
        "appendix": "split",
    }
    family = family or mapping.get(slide_type, "split")
    if len(blocks) >= 6 and family in {"split", "case"}:
        return "bento"
    return family


class DeterministicPlanningProvider:
    """Provider-neutral, no-network Production planning baseline."""

    name = "deterministic-planning-provider"
    version = "1.3.0"

    def propose(
        self,
        artifact_type: str,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> PlanningProposal:
        builders = {
            "narrative_blueprint": self._narrative,
            "deck_outline": self._outline,
            "slide_specs": self._slide_specs,
            "layout_plans": self._layout_preferences,
        }
        try:
            builder = builders[artifact_type]
        except KeyError as exc:
            raise PlanningError(f"Planning provider cannot propose {artifact_type}") from exc
        content, warnings, assumptions = builder(context, limits)
        return PlanningProposal(
            artifact_type=artifact_type,
            content=content,
            warnings=tuple(warnings),
            assumptions=tuple(assumptions),
        )

    def _narrative(
        self,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        brief = context["project_brief"]
        evidence = context["evidence_ledger"]
        claims = _usable_claims(evidence)
        arc = _story_arc(brief)
        target = _effective_page_target(brief, claims)
        section_limit = max(2, min(limits.max_sections, max(2, target - 2)))
        templates = _section_templates(arc)[:section_limit]
        budgets = _allocate_slide_budgets(target, len(templates))
        claim_ids = [str(item["evidence_id"]) for item in claims]
        claims_by_id = {str(item["evidence_id"]): item for item in claims}
        section_claim_ids: list[list[str]] = [[] for _ in templates]
        unclassified_claim_ids: list[str] = []
        for claim in claims:
            role = _claim_role(claim.get("claim"))
            if role == "evidence":
                unclassified_claim_ids.append(str(claim["evidence_id"]))
                continue
            target_index = _section_index_for_role(arc, role, len(templates))
            section_claim_ids[target_index].append(str(claim["evidence_id"]))
        for evidence_id in unclassified_claim_ids:
            target_index = min(
                range(len(section_claim_ids)),
                key=lambda index: (len(section_claim_ids[index]), index),
            )
            section_claim_ids[target_index].append(evidence_id)
        sections: list[dict[str, Any]] = []
        for index, ((title, purpose, question), budget) in enumerate(
            zip(templates, budgets, strict=True)
        ):
            assigned = list(dict.fromkeys(section_claim_ids[index]))
            section_thesis = (
                _headline_from_claim(claims_by_id[assigned[0]].get("claim"), 120)
                if assigned
                else purpose
            )
            sections.append(
                {
                    "title": title,
                    "purpose": purpose,
                    "key_questions": [question],
                    "evidence_ids": assigned,
                    "transition": (
                        "在建立共同背景后进入核心问题。"
                        if index == 0
                        else (
                            "把论证收敛为明确行动。"
                            if index == len(templates) - 2
                            else "沿着前一结论继续推进论证。"
                        )
                    ),
                    "thesis": section_thesis,
                    "audience_shift": question,
                    "proof_strategy": (
                        "使用当前 Evidence Ledger 中可用声明；无证据的组织语句不作为外部事实。"
                    ),
                    "slide_budget": budget,
                }
            )
        purpose = _text(brief["intent"]["purpose"])
        outcome = _text(brief["intent"]["desired_outcome"])
        thesis_claim = max(claims, key=_claim_score_for_thesis) if claims else None
        thesis = (
            _headline_from_claim(thesis_claim.get("claim"), 120)
            if thesis_claim is not None
            else _shorten(f"围绕“{purpose}”，本演示将引导受众{outcome}", 240)
        )
        audience = brief.get("audiences", [{}])[0]
        journey = [
            f"从受众“{_text(audience.get('role'))}”当前关心的问题出发",
            "建立可追溯的共同事实和判断框架",
            outcome,
        ]
        objections = []
        raw_objections = list(audience.get("objections", []))
        inferred_objections = False
        if not raw_objections and audience.get("decision_power") in {"decision_maker", "mixed"}:
            raw_objections = ["价值是否足以覆盖投入？", "主要风险和边界是什么？"]
            inferred_objections = True
        for objection in raw_objections:
            objections.append(
                {
                    "objection": _text(objection),
                    "response_strategy": (
                        "当前来源未提供直接回答该异议的证据；作为决策检查项显式保留。"
                        if inferred_objections
                        else "使用直接相关 Evidence 回应；证据不足时明确限定或保留问题。"
                    ),
                    "evidence_ids": [] if inferred_objections else claim_ids[:2],
                    "severity": "high",
                }
            )
        excluded = list(brief.get("constraints", {}).get("forbidden_content", []))
        blocked_ids = [
            str(item["evidence_id"])
            for item in evidence.get("claims", [])
            if item.get("use_policy") == "do_not_use"
        ]
        if blocked_ids:
            excluded.append("不把以下 do-not-use Evidence 作为页面事实：" + ", ".join(blocked_ids))
        warnings = []
        if not claims:
            warnings.append("当前没有 policy-usable Evidence；Narrative 只能形成结构，不能形成事实论证。")
        assumptions = [
            "Deterministic provider 只使用 Brief 和当前 Evidence，不进行外部语义扩写。"
        ]
        return (
            {
                "central_thesis": thesis,
                "story_arc": arc,
                "story_rationale": f"根据目的、期望结果、受众角色和行动要求选择 {arc}。",
                "proof_strategy": "事实性命题只使用当前 policy-usable Evidence；限定性内容保留 qualification。",
                "call_to_action": _text(brief["intent"].get("call_to_action")) or outcome,
                "audience_journey": journey,
                "sections": sections,
                "objections": objections,
                "excluded_content": list(dict.fromkeys(_text(item) for item in excluded if _text(item))),
                "notes": [],
            },
            warnings,
            assumptions,
        )

    def _outline(
        self,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        brief = context["project_brief"]
        narrative = context["narrative_blueprint"]
        evidence = context["evidence_ledger"]
        claims_by_id = {
            str(item["evidence_id"]): item for item in _usable_claims(evidence)
        }
        target = min(
            _effective_page_target(brief, list(claims_by_id.values())),
            limits.max_slides,
        )
        target = max(3, target)
        slides: list[dict[str, Any]] = [
            {
                "section_index": 0,
                "slide_type": "cover",
                "headline": _shorten(brief["title"], 80),
                "takeaway": _cover_takeaway(brief, narrative),
                "purpose": "建立主题、核心主张和受众预期。",
                "audience_question": "这份演示要帮助我们形成什么判断？",
                "evidence_ids": [],
                "evidence_requirement": "none",
            }
        ]
        remaining = target - 2
        sections = list(narrative.get("sections", []))
        total_budget = sum(max(1, int(item.get("slide_budget", 1))) for item in sections)
        used_evidence_ids: set[str] = set()
        for section_index, section in enumerate(sections):
            if remaining <= 0:
                break
            raw_budget = max(1, int(section.get("slide_budget", 1)))
            budget = max(1, round(remaining * raw_budget / max(1, total_budget)))
            if section_index == len(sections) - 1:
                budget = remaining
            budget = min(budget, remaining)
            evidence_ids = [
                str(item)
                for item in section.get("evidence_ids", [])
                if str(item) in claims_by_id and str(item) not in used_evidence_ids
            ]
            questions = [
                _text(item)
                for item in section.get("key_questions", [])
                if _text(item)
            ] or [_text(section["purpose"])]
            section_prefix = 1 if budget > 1 else 0
            content_slots = max(1, budget - section_prefix)
            evidence_groups: list[list[str]] = [[] for _ in range(content_slots)]
            for position, evidence_id in enumerate(evidence_ids):
                bucket = min(
                    content_slots - 1,
                    position * content_slots // max(1, len(evidence_ids)),
                )
                evidence_groups[bucket].append(evidence_id)
            for local_index in range(budget):
                evidence_slot = local_index - section_prefix
                assigned = (
                    evidence_groups[evidence_slot]
                    if 0 <= evidence_slot < len(evidence_groups)
                    else []
                )
                if assigned:
                    used_evidence_ids.update(assigned)
                assigned_claims = [claims_by_id[item] for item in assigned if item in claims_by_id]
                question = questions[min(local_index, len(questions) - 1)]
                if local_index == 0 and budget > 1:
                    slide_type = "section"
                    headline = _shorten(section["title"], 80)
                    takeaway = headline
                    assigned = []
                elif assigned_claims:
                    roles = {_claim_role(item.get("claim")) for item in assigned_claims}
                    if "framework" in roles or "diagnostic" in roles:
                        slide_type = "matrix"
                    elif "progression" in roles:
                        slide_type = "timeline"
                    elif roles.intersection({"process", "action"}):
                        slide_type = "process"
                    elif "problem" in roles and "principle" in roles:
                        slide_type = "comparison"
                    else:
                        claim_text = _text(assigned_claims[0].get("claim"))
                        numeric = bool(re.search(r"\d", claim_text))
                        slide_type = "chart" if numeric and len(assigned_claims) == 1 else "evidence"
                    headline = _page_proposition(
                        section,
                        question,
                        assigned_claims,
                        limit=56,
                    )
                    takeaway = _takeaway_from_claims(assigned_claims, headline)
                else:
                    slide_type = (
                        "process"
                        if "如何" in question or "how" in question.casefold()
                        else "statement"
                    )
                    headline = _shorten(f"{section['title']}：{question}", 72)
                    takeaway = _shorten(
                        f"{section['purpose']}；本页聚焦回答“{question}”",
                        180,
                    )
                slides.append(
                    {
                        "section_index": section_index,
                        "slide_type": slide_type,
                        "headline": headline,
                        "takeaway": takeaway,
                        "purpose": _shorten(section["purpose"], 240),
                        "evidence_ids": assigned,
                        "evidence_requirement": "required" if assigned else "none",
                        "audience_question": _shorten(
                            (section.get("key_questions") or [section["purpose"]])[0],
                            180,
                        ),
                    }
                )
                remaining -= 1
                if remaining <= 0:
                    break
        slides.append(
            {
                "section_index": max(0, len(sections) - 1),
                "slide_type": "action",
                "headline": "结论与下一步",
                "takeaway": _shorten(
                    "决策请求："
                    + (
                        _text(narrative.get("call_to_action"))
                        or _text(brief["intent"]["desired_outcome"])
                    ),
                    180,
                ),
                "purpose": "把整套论证收敛为明确行动、责任和检查点。",
                "evidence_ids": [],
                "evidence_requirement": "none",
                "audience_question": "基于以上判断，现在应该做什么？",
            }
        )
        slides = slides[: limits.max_slides]
        while len(slides) < target:
            section_index = max(0, len(sections) - 1)
            slides.insert(
                -1,
                {
                    "section_index": section_index,
                    "slide_type": "summary",
                    "headline": f"关键结论 {len(slides)}",
                    "takeaway": _shorten(
                        f"{narrative['central_thesis']}；补充检查点 {len(slides)}",
                        180,
                    ),
                    "purpose": "补足 Brief 目标页数，并承担一个独立的结论复核任务。",
                    "evidence_ids": [],
                    "evidence_requirement": "none",
                    "audience_question": "这一部分最需要记住什么？",
                },
            )
        return (
            {
                "target_page_count": len(slides),
                "slides": slides,
                "appendix_policy": "只有在 Brief 明确需要或正文证据过载时才生成附录。",
            },
            [],
            ["页面数量在 Brief min/max 内按可用语义容量生成；target 不通过空洞页面强行补齐。"],
        )

    def _slide_specs(
        self,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        outline = context["deck_outline"]
        evidence = context["evidence_ledger"]
        claims = {str(item["evidence_id"]): item for item in evidence.get("claims", [])}
        slides: list[dict[str, Any]] = []
        for outline_slide in outline.get("slides", []):
            if outline_slide.get("status") == "excluded":
                continue
            slide_id = str(outline_slide["slide_id"])
            evidence_ids = list(outline_slide.get("evidence_ids", []))
            assigned_claims = [
                claims[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in claims
            ]
            slide_type = str(outline_slide["slide_type"])
            relationship = _relationship_for_claims(slide_type, assigned_claims)
            has_ordered_structure = relationship in {"sequence", "time", "ordered action"} and any(
                _claim_role(claim.get("claim")) in {"process", "progression"}
                for claim in assigned_claims
            )
            blocks: list[dict[str, Any]] = [
                {
                    "semantic_role": "headline",
                    "content_type": "text",
                    "priority": "primary",
                    "content": _text(outline_slide["headline"]),
                    "evidence_ids": [],
                    "evidence_requirement": "none",
                    "claim_mode": "label",
                    "evidence_qualification": None,
                }
            ]
            for evidence_id in evidence_ids:
                claim = claims.get(evidence_id)
                if claim is None:
                    continue
                claim_role = _claim_role(claim.get("claim"))
                fragments = _support_fragments(claim["claim"])
                headline_text = _text(outline_slide["headline"]).casefold()
                if len(fragments) > 1:
                    non_duplicate = [
                        fragment
                        for fragment in fragments
                        if _text(fragment).casefold() != headline_text
                    ]
                    if non_duplicate:
                        fragments = non_duplicate
                semantic_role = "evidence"
                if has_ordered_structure:
                    semantic_role = (
                        "body" if claim_role in {"process", "progression"} else "subhead"
                    )
                group_as_list = len(fragments) > 1 and (
                    (
                        len(evidence_ids) > 1
                        and claim_role in {"framework", "problem"}
                    )
                    or (
                        claim_role in {"process", "action"}
                        and slide_type != "timeline"
                    )
                )
                if group_as_list:
                    blocks.append(
                        {
                            "semantic_role": semantic_role,
                            "content_type": "list",
                            "priority": "secondary",
                            "content": fragments,
                            "evidence_ids": [evidence_id],
                            "evidence_requirement": "required",
                            "claim_mode": "fact",
                            "evidence_qualification": _claim_qualification(claim),
                        }
                    )
                    continue
                for fragment in fragments:
                    blocks.append(
                        {
                            "semantic_role": semantic_role,
                            "content_type": "text",
                            "priority": "secondary",
                            "content": fragment,
                            "evidence_ids": [evidence_id],
                            "evidence_requirement": "required",
                            "claim_mode": "fact",
                            "evidence_qualification": _claim_qualification(claim),
                        }
                    )
            if len(blocks) == 1 and slide_type != "section":
                blocks.append(
                    {
                        "semantic_role": "body",
                        "content_type": "text",
                        "priority": "secondary",
                        "content": _text(outline_slide["takeaway"]),
                        "evidence_ids": [],
                        "evidence_requirement": "none",
                        "claim_mode": "interpretation",
                        "evidence_qualification": None,
                    }
                )
            if outline_slide["slide_type"] == "action":
                primary_cta = _text(outline_slide["takeaway"])
                blocks.append(
                    {
                        "semantic_role": "body",
                        "content_type": "list",
                        "priority": "secondary",
                        "content": _action_support_items(primary_cta),
                        "evidence_ids": [],
                        "evidence_requirement": "none",
                        "claim_mode": "instruction",
                        "evidence_qualification": None,
                    }
                )
            blocks = blocks[: limits.max_blocks_per_slide]
            family = _layout_family_for(slide_type, blocks, relationship)
            slides.append(
                {
                    "slide_id": slide_id,
                    "audience_question": _text(
                        outline_slide.get("audience_question") or outline_slide["purpose"]
                    ),
                    "core_message": _text(outline_slide["takeaway"]),
                    "content_blocks": blocks,
                    "visual_intent": {
                        "relationship": relationship,
                        "suggested_layout_families": [family],
                        "avoid": [
                            "用装饰替代信息层级",
                            "通过缩小文字掩盖内容过载",
                            "把无 Evidence 的解释写成外部事实",
                        ],
                    },
                    "speaker_notes": _text(outline_slide.get("purpose")),
                    "density_budget": {
                        "max_blocks": max(len(blocks), min(limits.max_blocks_per_slide, len(blocks) + 1)),
                        "max_words": min(limits.max_words_per_slide, 40 + 45 * len(blocks)),
                        "min_body_pt": 18,
                    },
                    "editability_intent": context["project_brief"]["constraints"]["editability_target"],
                }
            )
        return {"slides": slides}, [], []

    def _layout_preferences(
        self,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        del limits
        plans = []
        for slide in context["slide_specs"].get("slides", []):
            suggested = list(
                slide.get("visual_intent", {}).get("suggested_layout_families", [])
            )
            plans.append(
                {
                    "slide_id": slide["slide_id"],
                    "layout_family": str(suggested[0]) if suggested else "custom",
                }
            )
        return {"plans": plans}, [], []
