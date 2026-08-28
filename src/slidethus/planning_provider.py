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


def _layout_family_for(slide_type: str, blocks: list[dict[str, Any]]) -> str:
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
    family = mapping.get(slide_type, "split")
    if len(blocks) >= 6 and family in {"split", "case"}:
        return "bento"
    return family


class DeterministicPlanningProvider:
    """Provider-neutral, no-network Production planning baseline."""

    name = "deterministic-planning-provider"
    version = "1.0.0"

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
        target = int(brief["constraints"]["page_count"]["target"])
        section_limit = max(2, min(limits.max_sections, max(2, target - 1)))
        templates = _section_templates(arc)[:section_limit]
        budgets = _allocate_slide_budgets(target, len(templates))
        claim_ids = [str(item["evidence_id"]) for item in claims]
        sections: list[dict[str, Any]] = []
        for index, ((title, purpose, question), budget) in enumerate(
            zip(templates, budgets, strict=True)
        ):
            if not claim_ids:
                assigned: list[str] = []
            elif index == 0:
                assigned = claim_ids[: min(2, len(claim_ids))]
            elif index == len(templates) - 1:
                assigned = claim_ids[-min(2, len(claim_ids)) :]
            else:
                assigned = claim_ids[index - 1 :: max(1, len(templates) - 2)][:budget]
            sections.append(
                {
                    "title": title,
                    "purpose": purpose,
                    "key_questions": [question],
                    "evidence_ids": list(dict.fromkeys(assigned)),
                    "transition": (
                        "在建立共同背景后进入核心问题。"
                        if index == 0
                        else (
                            "把论证收敛为明确行动。"
                            if index == len(templates) - 2
                            else "沿着前一结论继续推进论证。"
                        )
                    ),
                    "thesis": purpose,
                    "audience_shift": question,
                    "proof_strategy": (
                        "使用当前 Evidence Ledger 中可用声明；无证据的组织语句不作为外部事实。"
                    ),
                    "slide_budget": budget,
                }
            )
        purpose = _text(brief["intent"]["purpose"])
        outcome = _text(brief["intent"]["desired_outcome"])
        thesis = _shorten(f"围绕“{purpose}”，本演示将引导受众{outcome}", 240)
        audience = brief.get("audiences", [{}])[0]
        journey = [
            f"从受众“{_text(audience.get('role'))}”当前关心的问题出发",
            "建立可追溯的共同事实和判断框架",
            outcome,
        ]
        objections = []
        raw_objections = list(audience.get("objections", []))
        if not raw_objections and audience.get("decision_power") in {"decision_maker", "mixed"}:
            raw_objections = ["价值是否足以覆盖投入？", "主要风险和边界是什么？"]
        for objection in raw_objections:
            objections.append(
                {
                    "objection": _text(objection),
                    "response_strategy": "使用直接相关 Evidence 回应；证据不足时明确限定或保留问题。",
                    "evidence_ids": claim_ids[:2],
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
            int(brief["constraints"]["page_count"]["target"]),
            limits.max_slides,
        )
        target = max(3, target)
        slides: list[dict[str, Any]] = [
            {
                "section_index": 0,
                "slide_type": "cover",
                "headline": _shorten(brief["title"], 80),
                "takeaway": _shorten(narrative["central_thesis"], 180),
                "purpose": "建立主题、核心主张和受众预期。",
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
            for local_index in range(budget):
                evidence_slot = local_index - section_prefix
                assigned = (
                    [evidence_ids[evidence_slot]]
                    if 0 <= evidence_slot < len(evidence_ids)
                    else []
                )
                if assigned:
                    used_evidence_ids.update(assigned)
                claim = claims_by_id.get(assigned[0]) if assigned else None
                question = questions[min(local_index, len(questions) - 1)]
                if local_index == 0 and budget > 1:
                    slide_type = "section"
                    headline = _shorten(section["title"], 80)
                    takeaway = _shorten(
                        f"进入“{section['title']}”：本节将回答“{question}”",
                        180,
                    )
                    assigned = []
                elif claim is not None:
                    claim_text = _text(claim.get("claim"))
                    numeric = bool(re.search(r"\d", claim_text))
                    slide_type = "chart" if numeric and len(assigned) == 1 else "evidence"
                    headline = _shorten(claim_text, 88)
                    takeaway = _shorten(claim_text, 180)
                else:
                    slide_type = (
                        "process"
                        if "如何" in question or "how" in question.casefold()
                        else "statement"
                    )
                    headline = _shorten(f"{section['title']}：{question}", 88)
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
            ["页面数量优先满足 Brief target，并以 section slide_budget 分配。"],
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
                blocks.append(
                    {
                        "semantic_role": "evidence",
                        "content_type": "text",
                        "priority": "secondary",
                        "content": _text(claim["claim"]),
                        "evidence_ids": [evidence_id],
                        "evidence_requirement": "required",
                        "claim_mode": "fact",
                        "evidence_qualification": _claim_qualification(claim),
                    }
                )
            if len(blocks) == 1:
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
                blocks.append(
                    {
                        "semantic_role": "body",
                        "content_type": "list",
                        "priority": "secondary",
                        "content": [
                            _text(outline_slide["takeaway"]),
                            "明确责任人、时间点和下一次检查。",
                        ],
                        "evidence_ids": [],
                        "evidence_requirement": "none",
                        "claim_mode": "instruction",
                        "evidence_qualification": None,
                    }
                )
            blocks = blocks[: limits.max_blocks_per_slide]
            slide_type = str(outline_slide["slide_type"])
            family = _layout_family_for(slide_type, blocks)
            slides.append(
                {
                    "slide_id": slide_id,
                    "audience_question": _text(
                        outline_slide.get("audience_question") or outline_slide["purpose"]
                    ),
                    "core_message": _text(outline_slide["takeaway"]),
                    "content_blocks": blocks,
                    "visual_intent": {
                        "relationship": {
                            "cover": "single thesis",
                            "section": "section transition",
                            "comparison": "contrast",
                            "process": "sequence",
                            "timeline": "time",
                            "matrix": "two-dimensional classification",
                            "architecture": "system relationships",
                            "chart": "quantitative evidence",
                            "evidence": "claim and proof",
                            "action": "ordered action",
                        }.get(slide_type, "hierarchy"),
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
        outline_by_id = {
            str(item["slide_id"]): item for item in context["deck_outline"].get("slides", [])
        }
        for slide in context["slide_specs"].get("slides", []):
            outline_slide = outline_by_id[str(slide["slide_id"])]
            plans.append(
                {
                    "slide_id": slide["slide_id"],
                    "layout_family": _layout_family_for(
                        str(outline_slide["slide_type"]),
                        list(slide.get("content_blocks", [])),
                    ),
                }
            )
        return {"plans": plans}, [], []
