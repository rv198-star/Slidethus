> 历史记录（2026-08-31 恢复）：正文保留撤回前提交 `2b005ecde6a80237d0f617a3d32da0b9379f0c8b` 的原文，供归因与审计追溯；其中 active/PASS/FAIL/pending 不代表当前状态。当前方案为 `plans/M6.6-final-optimization-and-rerelease.md`。本文件不授权恢复旧代码；正文引用的历史 ADR/文件按该提交解释。

# Visual Intelligence Follow-up Issues

Status: Backlog / non-blocking for `M6.6-visual-decision-propagation-convergence.md`

## Boundary

本文件记录两轮独立审计中成立、但按用户决策不进入当前收敛轮的事项。它们不得被用于宣称当前轮失败，也不得因未实现而阻断当前三案 same-case regression。

每个 issue 只有在当前 Create 纵向闭环稳定后，按独立计划和验收重新开启。

## VI-FU-001｜扩展跨行业与跨场景 Golden Corpus

- 来源：Round B 反事实压力测试。
- 推迟原因：当前继续扩展培训、财报、科研、公益、教育、无图内部材料会显著扩大验证面，阻碍本轮收敛。
- 建议样本：培训课件、董事会/财报、科研、公益/无障碍、消费品牌、纯文字内部材料。
- 重启条件：当前三案 Create 路径通过 Office 回归并冻结核心 contracts。
- 验收：每个新增样本先定义其正确的不变项和允许差异；不得用“更多页面看起来不错”代替 failure fixture。

## VI-FU-002｜六工作流 Visual Intelligence 接入矩阵

- 来源：Round B 的 Create-centric finding。
- 范围：Rebuild、Improve、Audit、Revise Slide、Extract Style，以及 Create 的复用行为。
- 需要定义：create/reuse/forbid、mutation authority、protected visual facts、invalidation scope、calibration scope。
- 关键边界：Audit 只读；Revise/Improve 局部失效；Extract Style 不要求 Narrative/Outline；Rebuild 支持 preserve/replace/adapt。
- 重启条件：Create path 的 Planning Policy/representation/grammar/trace 稳定。

## VI-FU-003｜通用 VisualReferenceContract

- 来源：Round B 的 ReferenceSet 非通用 finding。
- 范围：brand guide、PPT master/template、source deck、existing slide、screenshot、manual spec、approved generated sample。
- 需要字段：authority、strength、scope、properties_to_preserve、allowed_variation、rights/provenance。
- 当前轮替代：只实现 generated-sample `CalibrationRun` 引用索引，不宣称覆盖外部 reference。
- 重启条件：Extract Style/Rebuild 接入前。

## VI-FU-004｜完整 DataBinding / ChartSpec

- 来源：Round A 的 chart lineage finding。
- 范围：series、单位、时间范围、分母、聚合、缺失值、变换、排序、统计不确定性、展示命题。
- 当前轮替代：chart 至少要求 chart_data Asset + Evidence；缺失时 replan/阻断，不声称完成通用数据图表引擎。
- 重启条件：需要生产级数据驱动图表或新增财报/科研 corpus 时。

## VI-FU-005｜可访问性与观看环境合同

- 来源：Round B 教育/无障碍反例。
- 范围：观看距离、投影/屏幕/打印、色觉、字号、字幕/alt text、屏幕阅读、识字水平和学习任务。
- 当前轮边界：沿用现有可读性、字号、对比与 Office 检查，不声称覆盖完整 accessibility。
- 重启条件：新增教育、公益、公共发布或 accessibility-first 场景。

## VI-FU-006｜自动 Calibration Risk Policy

- 来源：Round B 对 external/brand-sensitive 隐性触发的反对。
- 范围：方向不确定性、reference fidelity、返工成本、新规则/组件数量、renderer/font/media 脆弱性、精确呈现和可访问性风险。
- 当前轮替代：Workflow Request/approval mode 显式选择 `off|checkpoint`，不自动按行业/场景分类。
- 重启条件：当前 scoped Calibration Attempt 稳定且有足够跨案失败数据。

## VI-FU-007｜扩展 Anti-gaming / Metamorphic Visual Evaluation

- 来源：两轮审计关于 lineage、coverage、diversity 指标可刷分的 finding。
- 范围：随机轮换组件、伪造 trace、缩小内容制造留白、轻微坐标变化伪装 family diversity、满足统计但语义错误。
- 当前轮包含：伪 trace、rule 改变但 IR 不变、未来引用、Office/SVG 不一致等核心结构负例。
- 重启条件：当前 trace reviewer 稳定后扩展 corpus。

## VI-FU-008｜多语言、长篇和特殊表示载体

- 来源：Round B 科研/教学反例与 Golden Corpus 缺口。
- 范围：公式、代码、地图、科学影像、文档节选、界面截图、RTL、多语言、30/80 页节奏。
- 当前轮边界：只复用现有 content types 与三案语言/规模，不新增 carrier-specific schema。
- 重启条件：出现真实用户任务或扩展 corpus 计划。

## VI-FU-009｜Legacy Visual Intelligence Migration Across Workflows

- 来源：Round A migration finding。
- 范围：旧 Create/Rebuild/Improve/Revise workspaces 在新 Policy/representation/trace 合同下的版本迁移和局部失效。
- 当前轮包含：当前 Create path 的旧 Block 无法推导 rationale 时迁为 `unplanned` 并重跑 P5A。
- 重启条件：六工作流接入前；不得通过迁移伪造 provider judgment。

## Issue governance

- 本 backlog 不自动承诺实施顺序或里程碑。
- 新 issue 进入实现前需要独立 Objective、边界、ADR 影响和 acceptance fixtures。
- 单一新案例的偏好不得直接升级为生产规则；至少先说明它修复的是哪项现有 contract 缺口。
- 如果后续证据推翻本文件中的假设，允许关闭、合并或重写 issue，不要求机械完成全部条目。
