# 中国珠宝 2026 对外展示型样板实验

## 1. Objective

- 用户价值：验证“技术展示型 / 对外展示型”是一种演示姿态，而不是固定的科技风；同时验证数据图表与时尚编辑视觉可以共存。
- 本轮边界：制作 5 页《中国 2026 年珠宝市场调研报告》真实 PPTX 样板，使用截至 2026-08-30 的公开权威资料和原创生成视觉资产。
- 明确不做：不修改生产代码、Schema、默认模板或 Taste provider；不把珠宝风格固化为共性规则；不声称这是完整行业白皮书。
- 退出条件：PPTX 可打开、文本与图表保持可编辑、所有页面完成真实 Office 渲染检查、无可见溢出或碰撞，并形成共性能力结论。

## 2. Current state

- 当前 HEAD / 工作区状态：工作区已有用户进行中的大量变更；本实验只新增独立计划与 `dist/jewelry-china-2026-showcase/` 交付物。
- 已存在能力：Slidethus 分阶段语义规划；provider-neutral ArtDirectionPacket；Taste 默认美术方向；本地 Office 渲染与预览检查链路。
- 已知缺口：页面策划目前对图片占位、图表意图、数据绑定和主题语义之间的显式协同仍需验证。
- 基线测试：不运行全仓测试，因为本轮不改生产代码；对交付 PPTX 执行专项渲染和版面检查。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 将 presentation posture 与 visual idiom 分离：本轮 posture 为 external showcase，idiom 为 Chinese luxury editorial | 用户明确指出展示型不等于科技风 | 高 |
| D-002 | Decision | 至少使用一个原生可编辑数字图表，但只在支持比较/变化的证据页使用 | 用户补充图表是重要表达能力，不能滥用 | 高 |
| D-003 | Decision | 摄影类资产使用原创生成图，数据图表使用原生对象 | 降低版权风险并保持数据可编辑 | 高 |
| A-001 | Assumption | 5 页足以验证风格分离、图片占位和图表能力，不替代完整市场报告 | 本轮定位为验证样板 | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| 1 | 证据边界与 5 页叙事 | 中国黄金协会、国家统计局、世界黄金协会 | 每个定量结论可回溯；推断明确标注 | in progress |
| 2 | 三张原创珠宝时尚资产 | imagegen | 视觉检查；无品牌、无文字、无水印 | pending |
| 3 | 可编辑 PPTX | Artifact Tool | 导出成功；图表对象可检查 | pending |
| 4 | Office 渲染与专项 QA | Office 渲染链路、slides_test.py | 逐页检查、无溢出碰撞 | pending |

## 5. Quality and risk controls

- 受影响 Schema：无。
- 受影响 Gate：仅交付物专项视觉与可读性检查；不改变项目 Gate 实现。
- 回归范围：无生产代码变更。
- 降级路径：若某个定量结论来源口径不可比，则改为分源并列或方向性表达，不做伪精确合并。
- 安全/来源/版权风险：所有市场数字保留来源；生成图片仅作装饰性/语境性视觉，不承担事实证据；不使用品牌 Logo 或受版权保护产品图。

## 6. Verification

```bash
python /path/to/slides_test.py dist/jewelry-china-2026-showcase/中国珠宝2026市场调研样板.pptx
```

- 期望结果：PPTX 结构检查通过；5 页真实 Office 渲染均无可见异常。
- 实际结果：待完成。

## 7. Review

### 第一轮：开放问题发现

- Critical：待检查。
- Major：待检查。
- Minor：待检查。

### 修复记录

- 待第一轮审计后填写。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 |  |  |  |
| 架构一致性 |  |  |  |
| 可测试性 |  |  |  |
| 可维护性 |  |  |  |
| 降级与恢复 |  |  |  |

## 8. Final outcome

- 已完成：待完成。
- 未完成：待完成。
- 后续任务：根据实验结论决定是否把 `visual_evidence_mode`、`chart_intent`、`data_binding` 和 subject-derived visual idiom 抽象到 page planning / art direction contract。
- 相关 ADR：本轮不改架构；如后续落地共性 contract，再更新适用 ADR。
