> 历史记录（2026-08-31 恢复）：正文保留撤回前提交 `2b005ecde6a80237d0f617a3d32da0b9379f0c8b` 的原文，供归因与审计追溯；其中 active/PASS/FAIL/pending 不代表当前状态。当前方案为 `plans/M6.6-final-optimization-and-rerelease.md`。本文件不授权恢复旧代码；正文引用的历史 ADR/文件按该提交解释。

# 跨案例视觉智能方案｜两轮独立通用抽象审计

Date: 2026-08-30

## 1. Audit object and independence protocol

审计对象：

```text
plans/cross-case-visual-intelligence-optimization.md
sha256:3f7fbefcf7cf22788449221e002c66b66c7edc5f86281b45cc6338bf1d38c635
```

两轮审计均为只读，在结论提交前互不读取对方结果，也没有修改被审计方案。

- Round A：架构、工件、阶段和控制边界审计。
- Round B：去主题、跨行业、跨工作流与 anti-gaming 压力测试。
- Synthesis：仅在两轮独立结论均冻结后执行。

共同判定标准：

1. 移除 FDE、珠宝、酒店香薰、技术展示、低奢等名词后，生产规则是否仍然成立；
2. 案例是否只作为 evidence/fixture，而没有进入 Schema、默认阈值、Gate、Provider 路由或 Renderer 行为；
3. 每项事实是否有唯一权威层，下游是引用/派生，而不是重复改写；
4. Artifact graph 是否无环，阶段责任是否符合最早责任阶段；
5. Gate 是否独立重算行为，而不是相信自报标签或字段存在；
6. Create/Rebuild/Improve/Audit/Revise/Extract Style 是否都有诚实路径；
7. 缺能力、旧 artifact 和已交付版本是否有明确 migration/degraded/stop 规则。

## 2. Overall decision

**两轮均判定：不通过。方案不能按现稿直接进入 Batch A。**

方向层通过：艺术指导前移、展示姿态与视觉风格分离、载体在策划阶段决策、Visual System 必须被 Renderer 消费、Taste 保持 provider 边界、Office 页面作为 PPTX release truth，均具备跨案例价值。

合同层未通过：现稿仍把“4 页样板扩展到全篇”“缺图片/图表”“对外展示”部分固化成了流程和字段；同时存在时间依赖环、Attempt/Review 边界冲突、重复事实源、Create-centric 路径和可刷 Gate。

审计结论不是“放弃整体方案”，而是先把方案从“案例经验抽象成字段”进一步收敛为“无环、正交、最小、可重算的通用合同”。

## 3. Round A — 架构与控制边界独立审计

### 3.1 Verdict

不通过。Critical 2，Major 9，Minor 3。

### 3.2 Critical findings

#### A-C1｜P5B 引用未来事实，Artifact graph 成环

位置：方案 §4.3–§4.5。

现稿要求 P5B 写入 `visual_lineage_id` 和 `component_family_id`，但具体 component variants 到 P6 才由 Packet/Visual System 定义，批准样板更要在校准渲染后才产生。

因此实现只能三选一：

- 在 P5B 写占位 ID；
- P6/P7 回写 frozen Layout Plan；
- 把最终组件和样板事实提前塞回 Seed。

三种都会破坏 artifact truth 和 P5B/P6 分工。

通用修订：

- P5B 只保存信息关系、representation requirement 和几何兑现；
- P6/Renderer IR 才分配具体 treatment/component rule IDs；
- 校准/reference 事实只能引用已完成的 Layout/Visual/Render，不能被上游反向引用；
- `topology_signature` 由 deterministic review 根据 regions/reading order 重算，不接受作者自报。

#### A-C2｜校准流程与 ADR-0026 的 Attempt/P8 边界冲突

位置：方案 §4.5–§4.6。

现稿在完整 P7 前调用 VisualReviewProvider 批准代表页，失败后回 P5A–P7 再生成。这把酒店样板迭代方式变成了 Production Attempt 中途 AI Review/Repair，而 ADR-0026 明确要求：Attempt 先终止，Stage AI Review 之后才运行，不在同一 Attempt 中边看边改。

通用修订二选一：

1. 校准本身是一个完整、已终止的 scoped Production Attempt；其 Review 结束后再开启 full-deck Attempt；或
2. 中途仅保留用户 checkpoint，VisualReviewProvider 不拥有批准权。

若要改变 ADR-0026，必须新 ADR 显式 supersede，不能在实现中绕过。

### 3.3 Major findings

#### A-M1｜`presentation_posture` 被放在错误阶段

external showcase、decision support、training、sales narrative 描述的是交付和说服事实，属于 P0，不应由 G4 后的 ArtDirectionProvider 创造第二份 Brief。

修订：P0 记录行业无关的 communication constraints；Art Direction 只能解释并推导视觉后果。

#### A-M2｜Seed 与 Packet 没有 refinement/supersession 合同

二者重复拥有密度、节奏、页面角色和禁用规则，但没有定义哪些不可改、哪些可细化、冲突路由和失效范围。

修订：使用同一 Art Direction Decision 的 planning/final 两个不可变版本，或把 Seed 收缩为稀疏 planning policy，并规定 Packet 只能保守细化。

#### A-M3｜P5A/P5B 重复现有 Block/Region/density 事实

- `primary_carrier` 重复 content block/content type；
- `visual_weight` 重复 block priority；
- `density_role` 重复 density budget；
- asset/chart slots 重复 Block→Region 几何；
- page role 重复 Outline/Slide Specs slide type。

同时 `scene/material/object/portrait/texture` 混入了生活方式案例偏向。

修订：在 Block 上增加统一 representation intent/fulfillment contract；Layout 继续映射 Block→Region，只保存必要 fit/focal/fallback。

#### A-M4｜`VisualReferenceSet` 复制已有事实

- Office hashes 已属于 Render Manifest；
- approval 属于 Gate/Decision Log；
- allowed variants 属于 Packet/Visual System；
- earliest responsible phase 属于 Review Report。

修订：如保留，只做引用型 Calibration Run/Reference Contract，不复制正文事实。

#### A-M5｜Gate 可由 metadata 刷通过

carrier reason、component IDs、100% visual lineage 和 Renderer 自报 usage 都不能证明真实行为。

修订：独立重算 Block intent → Region → IR object → backend object/output；增加 metamorphic tests，改变规则时 IR/输出必须出现对应变化；只检查 applicable scope，并允许显式 deviation/degraded。

#### A-M6｜核心 Reviewer 泄漏案例组件词汇

把 panel/card/pill/score-dot 写入通用观察量，直接泄漏了酒店 dashboard 失败样本。

修订：核心审计只检查当前 deck 声明的 component rule IDs、容器碎片率、重复微标签和焦点竞争；具体名称留在当前 Packet。

#### A-M7｜图表缺少 Data lineage

Evidence ID 只能证明 claim 来源，不能证明 series、单位、时间范围、聚合、缺失值和变换。

修订：增加 provider-neutral DataBinding/ChartSpec；P5A 决定 representation，P7 只渲染。缺少 data lineage 时不得生成事实型图表。

#### A-M8｜ReasoningProvider 与 ArtDirectionProvider 边界含混

核心不应同时认识 Taste、ReasoningProvider 和 ArtDirectionProvider。

修订：领域核心只认识 `ArtDirectionProvider`；Taste+Reasoning 是 adapter 内部组合，Taste 只进入 lineage。

#### A-M9｜Migration/degraded/stop 只停留在原则

旧 artifacts 无法诚实迁移出 rationale/lineage；缺 Office 时必须阻断 PPTX release；required asset 无 fallback、chart data 无 lineage、critical deck 无 art-direction capability 的停止点都需表格化。

修订：增加逐字段 migration matrix 和 capability/stop matrix；不可推导字段迁为 `unknown/unplanned` 并路由重生成，禁止伪造理由。

### 3.4 Minor findings

- 实现前自评多个 5 分，不符合 Round A 先于评分；应标记 provisional/unverified。
- factual evidence、asset rights facts、render/review evidence 不应统称 Evidence Ledger evidence。
- `confidence` 需要 reason codes 和待确认项，不能是无解释数值。

### 3.5 Round A 通过项

- 明确拒绝行业模板、主题词规则和全局图片/图表配额；
- Taste 不进入 Renderer；
- 图片、图表和降级选择前移方向正确；
- Office 页面保持 release truth；
- 单主编排、最早阶段修复、交付冻结和跨案例 promotion policy 保持成立。

## 4. Round B — 去主题与跨工作流压力测试

### 4.1 Verdict

不通过。Critical 0，Major 8，Minor 3。

核心链路通用，但当前合同仍偏向“从零创建、对外展示、图片/图表驱动的新 deck”。

### 4.2 Cross-context stress test

| 场景/工作流 | 现稿适配性 | 主要失败反例 |
|---|---|---|
| 培训课件 | 部分 | 固定 cover/chart/image/dense 样板不覆盖练习、步骤、知识检查；有意重复可能被判单调 |
| 财报/董事会 | 部分 | 内部材料也可能高风险；图表、精确表格和审计脚注可能同时为主 |
| 科研汇报 | 不充分 | 单一 primary carrier 不覆盖公式、代码、地图、实验图、统计不确定性 |
| 公益传播 | 部分 | 媒介类型、沟通功能、证据地位、肖像权和无障碍被混在 media role |
| 教育/无障碍 | 不充分 | 校准应受观看距离、打印、色觉、识字水平和学习任务影响，而非品牌/外部标签 |
| 消费品牌 | 部分 | brand guide、母版和 Taste 冲突时没有 authority/strength/scope 规则 |
| 无图内部备忘 | 容易误判 | 正确的文字/表格一致性可能被 carrier cadence/topology diversity 处罚 |
| Extract Style | 不成立 | 没有 Narrative/Outline；参考页是输入而不是生成后批准 |
| Rebuild | 部分 | 缺 preserve/replace/adapt 以及源视觉 reference authority |
| Improve | 不充分 | 小范围修复可能被迫全篇重新推导 Seed/Packet/样板 |
| Revise Slide | 不成立 | 单页修订不应重置全篇 reference/lineage |
| Audit | 不成立 | Audit 不应创建 Seed/ReferenceSet，只能检查现有事实并报告缺口 |

### 4.3 Major findings

#### B-M1｜目标流程 Create-centric

修订：增加六工作流 invocation matrix，规定 create/reuse/forbid、reference 来源、protected facts、失效范围、calibration scope 和 mutation authority。

#### B-M2｜`presentation_posture` 仍是隐性类别模板

它声称连续，却使用 external showcase/decision support/training 等类别名，下游还直接用类别触发 Gate。

修订：类别只作人类摘要；控制事实改为正交 `communication_constraints`，覆盖观看/分发、时间/距离/设备、受众任务、决策后果、品牌忠实度、无障碍、编辑复用和可用媒介能力。

`visual_idiom` 应变成带 `source_ref/authority/scope/strength/rationale` 的 design-policy items，禁止作模板 lookup key。

#### B-M3｜多层重复同一策略，没有唯一权威

修订为四层：

1. planning policy；
2. P5A block-level representation decision；
3. P5B region binding；
4. P6 executable grammar。

下游保存引用、解析结果和 fulfillment，不重复编辑上游政策。

#### B-M4｜载体与 slot 抽象过窄

修订为每个 Block 的 `representation_decisions[]`：communicative function、carrier kind、source/data binding、salience、rights/accessibility/editability、availability 和 fallback。

Layout 使用统一 `representation_slots[]`；chart 只是带附加 DataBinding 的 carrier kind，不单设并列 slot 体系。

#### B-M5｜校准触发存在外部/品牌偏置

修订为 `CalibrationDecision`：依据方向不确定性、reference fidelity、返工成本、新规则/组件数量、renderer/font/chart/media 脆弱性、变更范围、可访问性/精确呈现风险和用户要求。

样板选择对实际风险特征做最小 set-cover，数量 1..N，不固定 3–4 页或四个角色。

#### B-M6｜ReferenceSet 不是通用 Reference 抽象

修订为可选 `VisualReferenceContract`，允许 existing slide、master/template、brand guide、screenshot、manual spec 和 approved generated sample；每项有 authority、strength、scope、properties to preserve、allowed variation。

#### B-M7｜单一 `visual_lineage_id` 可刷分

修订为多对多 provenance：applied policy refs、reference item refs、component rule refs、representation decision refs，以及 deviations+rationale/approval。

#### B-M8｜Corpus/指标可被三案例适配或机械刷分

修订：指标默认产生诊断，不直接形成美学 PASS；组件从当前 grammar 动态读取；增加“满足指标但语义错误”的 adversarial fixtures，并覆盖六工作流。

### 4.4 Minor findings

- `contrast_mode` 混合 surface tone 与 image-led background behavior，应拆分正交字段。
- `negative_space_ratio` 只能是观察事实，不能是质量目标。
- 方案自评分应改为 provisional/unverified。

### 4.5 Round B 仍然成立的规则

- 艺术指导必须在 P5A/P5B 前提供必要规划约束，但不提前冻结最终坐标/组件；
- 展示方式与设计语言分离；
- 所有 representation 在 planning 阶段显式选择，不在 Renderer 末端补洞；
- 不使用图片/图表全局数量配额；
- 定量关系必须显式决定如何表达并绑定真实数据；
- required representation 缺失时 fail 或使用预声明降级；
- Visual System 必须被 Renderer 实际消费并留下可重算 trace；
- Taste 保持 provider 角色；
- PPTX release 必须使用真实 Office 页面；
- 校准是条件式；accepted version frozen；case 只作 fixture。

## 5. Cross-round synthesis

### 5.1 两轮共同确认的根因

| 共识 | Round A | Round B | 综合判断 |
|---|---|---|---|
| 场景控制事实不应由 Art Direction 创造 | posture 放错阶段 | posture 是隐性类别模板 | P0 使用正交通信约束；posture 仅是派生摘要 |
| Seed/Specs/Layout/Packet/Visual 重复事实 | Seed/Packet 无 refinement | 多层无唯一权威 | 收缩成 policy→decision→binding→grammar 单向链 |
| 图片/图表字段过拟合当前反馈 | 字段重复且 media enum 偏生活方式 | carrier/slot 过窄 | 使用 block-level 通用 representation contract |
| 样板机制过拟合酒店过程 | 固定四类且复制事实 | 对外/品牌触发偏置 | 使用风险驱动 CalibrationDecision + set-cover；reference 泛化 |
| lineage/coverage 可刷 | metadata 不证明行为 | 单 ID 无法表达多源继承 | 多对多 trace + 独立重算 + deviation |
| 评测语料不足 | Gate 需 metamorphic proof | 三案例和指标可适配 | 六工作流 + adversarial + cross-domain corpus |

### 5.2 一轮独有但成立的阻断

- Round A 独有：P5B→P6/reference 的未来引用环；必须在任何 Schema 草案前移除。
- Round A 独有：校准与 ADR-0026 冲突；必须选择 scoped Attempt 或纯人工 checkpoint。
- Round A 独有：事实型图表需要 DataBinding/ChartSpec lineage。
- Round B 独有：VisualReference 必须覆盖 template/source deck/brand guide 等输入引用，而不只是 generated samples。
- Round B 独有：Audit/Extract Style/Improve/Revise 的 mutation 和复用边界必须进入主方案。

### 5.3 不是过拟合的内容

以下内容可以保留，不应因审计而退回纯 token 系统：

- 上游艺术指导约束；
- planning 阶段 representation 决策；
- Renderer 对 executable grammar 的真实消费；
- Office-first Review；
- 条件式校准；
- provider-neutral/Taste default 边界；
- 案例 fixture 和真实 deck 回归。

问题不在“这些能力不通用”，而在它们当前的字段命名、权威边界、触发条件和验证方式仍然受三组案例塑形。

## 6. Required revision before implementation

建议先增加一个 plan revision，不进入 Schema/代码：

1. **恢复无环 artifact graph**：P5B 不引用 P6 或校准后事实。
2. **增加六工作流 invocation matrix**：逐工作流定义 create/reuse/forbid、mutation、preserve、invalidation 和 calibration scope。
3. **把控制事实归还 P0**：以正交 communication constraints 取代类别触发；posture 只作摘要。
4. **建立唯一权威链**：`DesignPlanningPolicy → RepresentationDecision → RegionBinding → ExecutableGrammar → independently recomputed fulfillment`。
5. **统一 representation 抽象**：图、表、公式、代码、地图、截图、图片等共用 block-level contract；专属字段作为 typed extension。
6. **泛化 reference/calibration**：`VisualReferenceContract` 支持外部参考和生成样板；`CalibrationDecision` 风险驱动，样板 set-cover，校准为 scoped Attempt 或人工 checkpoint。
7. **用 trace 取代 lineage 标签**：多源 policy/reference/rule/decision refs + deviation；Gate 独立重算输出行为。
8. **补齐 DataBinding、migration、degraded、stop matrix**。
9. **扩展 regression corpus**：六工作流、跨领域、无图、accessibility、局部修订与 adversarial anti-gaming fixtures。
10. **删除提前高分**：修订方案只记录 open findings 和 provisional status。

只有上述修订完成并经过一次短审后，才适合进入原计划 Batch A。

## 7. Gate decision

```text
Generalization Review: FAIL
Critical: 2
Major: 17 raw findings; 10 consolidated themes
Waivers: 0
Plan mutation during audit: none
Production code mutation during audit: none
Recommended route: revise plan before Batch A
```

说明：两轮 Major 存在重叠，不能把 9+8 视为 17 个独立根因。综合后为 10 个修订主题；Critical 仅来自 Round A 的阶段依赖环和 Attempt/Review 冲突。

## 8. Verification performed

- 读取并核对 AGENTS.md、产品章程、架构、状态机、工件合同、质量系统；
- 核对 ADR-0026、ADR-0027、ADR-0028；
- 核对 Project Brief、Slide Specs、Layout Plans、Asset Manifest、ArtDirectionPacket、Visual System、Renderer IR 现有合同；
- 核对 Create/Rebuild/Improve/Audit/Revise/Extract Style 工作流边界；
- 对方案执行行业词、场景词和新字段确定性扫描；
- 两轮审计互相隔离，均为 read-only；
- 本报告写入后执行 `git diff --check`。
