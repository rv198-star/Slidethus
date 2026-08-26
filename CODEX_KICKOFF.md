# Codex Kickoff Prompt

将下面整段复制给在本仓库根目录启动的 Codex：

---

你现在接手 Slidethus。它是一套 Agentic Presentation Engineering Skill，不是简单 PPT 模板生成器。

先执行以下动作，不要直接开始扩展渲染功能：

1. 读取根目录 `AGENTS.md`，并按其中顺序读取核心文档、`TASKS.md`、适用 ADR 和 `.agents/skills/slidethus/SKILL.md`。
2. 运行当前基线检查：
   - `python -m pytest`
   - `python scripts/validate_all.py`
   - `python scripts/audit_package.py`
3. 先验证 M1 Artifact Runtime 的 Gate 和 `audit/M1-round-2-scorecard.md`，然后用新的执行计划文件规划 `TASKS.md` 的 M2；不要重做已经通过的 M1。
4. M2 目标是完成可靠的 Ingestion, Research, Evidence：
   - provider-neutral 输入解析与 source inventory；
   - 方向性扫描和 outline-driven 定向研究；
   - query/task lineage、缓存、失效和恢复；
   - 证据去重、冲突、时效和可信等级；
   - 不可信来源指令隔离与无联网降级；
   - CLI、适配器合同和测试。
5. 保持单一主编排器。除独立的只读审计、测试分析或代码探索外，不要使用多代理并行写代码。
6. 不要把模型、搜索、图片生成或 PptxGenJS 写死进领域层；适配器通过协议接入。
7. 不要从内容直接跳到最终设计；`slide_specs` 与 `layout_plans` 是正式事实资产。
8. 发现架构问题时做根因修复，并更新 ADR；不要用补丁堆叠绕过现有合同。
9. 每完成一个子阶段，运行相关测试；M2 全部完成后，再运行完整基线检查并做两轮独立 review：
   - 第一轮只找具体问题，不评分；
   - 修复后第二轮按维度评分与 Gate 验收。
10. 只在 M2 Gate 通过后更新 `TASKS.md`。不要提前实现最终 PPT 视觉生成，除非它是验证 evidence contract 所必需的最小测试夹具。

最终汇报：变更清单、关键设计决策、测试结果、仍存风险、下一里程碑建议，并引用具体文件路径。

---
