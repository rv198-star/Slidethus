# FDE Scenario Variation Experiment

## 1. Objective

- 用户价值：验证同一证据与核心文案在不同演示场景下，是否能产生合理且可辨识的规划与视觉差异。
- 本轮边界：只创建独立实验样板与评审记录，不修改现有 FDE 成稿、Schemas、Provider、Renderer 或生产代码。
- 明确不做：不把图片比例、信息密度、Bento 或暗色科技风固化为全局规则；不新增事实或市场数据。
- 退出条件：三个场景样板完成真实 PPTX 渲染与逐页检查，并形成“场景选择 / Provider 执行 / 共性能力缺口”的归因结论。

## 2. Current state

- 当前 HEAD / 工作区状态：`af88bed`；工作区已有大量用户修改，本实验不触碰这些文件。
- 已存在能力：Artifact Tool PPTX 生成、Office 预览、Slide Specs 的 visual intent / density budget、Layout Plans、Asset Manifest、ArtDirectionPacket。
- 已知缺口：尚未用同一事实与代表页做跨场景受控比较。
- 基线测试：`dist/fde-china-2026/FDE中国2026现状调研报告.pptx` 及其 Office 渲染页。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 固定 S7、S8、S12 三张代表页 | 分别覆盖证据型、概念型、执行型页面 | 高 |
| D-002 | Decision | 生成现场汇报、独立阅读、技术展示三个 3 页样板 | 隔离场景变量，避免完整重写带来的叙事干扰 | 高 |
| D-003 | Decision | 保持事实、标题、结论和来源一致 | 确保差异主要来自场景与视觉策略 | 高 |
| A-001 | Assumption | 当前 13 页成稿代表“现场汇报型、编辑克制型”基线 | 现有 Art Direction 的 visual density=5 与页面表现一致 | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| 1 | 基线与代表页清单 | 现有成稿、研究笔记 | 内容与来源核对 | completed |
| 2 | 三个场景策略包 | 固定页面与事实 | 变量边界审阅 | completed |
| 3 | 三个独立 PPTX 样板 | Artifact Tool | PPTX 可打开、对象可编辑 | completed |
| 4 | 逐页渲染与横向评审 | 样板 PPTX | Office 页图、溢出/重叠检查 | completed |
| 5 | 归因结论 | 三组渲染证据 | 区分选择、执行与能力缺口 | completed |

## 5. Quality and risk controls

- 受影响 Schema：无。
- 受影响 Gate：无生产 Gate；实验沿用真实渲染、可读性、来源与视觉检查。
- 回归范围：只检查实验 PPTX 与现有基线的视觉差异；不运行代码回归。
- 降级路径：若外部图片不可用，技术展示场景使用现有已获许可的封面资产或明确的原生示意图，不伪造事实图像。
- 安全/来源/版权风险：所有事实复用现有研究笔记与 Speaker Notes；不引入未经记录的第三方资产。

## 6. Verification

```bash
<bundled-python> <presentations-skill>/container_tools/render_slides.py <sample.pptx>
<bundled-python> <presentations-skill>/container_tools/slides_test.py <sample.pptx>
PYTHONPATH=src .venv/bin/python dist/fde-china-2026/scenario-experiment/work/probe-default-art-direction.py
.venv/bin/python -m pytest tests/test_brief_completion.py tests/test_slide_spec_planning.py tests/test_render_compile.py -q
```

- 期望结果：三份 3 页样板均可渲染，无可见溢出、碰撞或断裂；相同事实在三种场景下形成可解释差异。
- 实际结果：三份样板均通过 Office 渲染与 `slides_test.py`；相关 Brief、Slide Spec、Art Direction 测试通过。默认 Taste Provider 的三组 direction hash 完全一致，只根据 `presentation_mode` 把 visual density 调为 4 / 7 / 6。

## 7. Review

### 第一轮：开放问题发现

- Critical：无。
- Major：默认 Taste Provider 虽绑定完整 Brief / Specs / Layout / Asset lineage，但当前 proposal 只把 `presentation_mode` 映射到 visual density；`delivery_context`、Slide Specs 与 Asset Manifest 没有改变 direction。
- Minor：技术展示样板为了验证资产优先而使用较强图片占比，不应成为默认风格或全局 QA 配额。

### 修复记录

- 本轮不修生产代码；按用户约定先报告实验结论并讨论共性抽象。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 场景符合度 | 4.7 | 三套样板在密度、资产与叙事依赖上差异明确 | 尚未通过生产 Provider 自动生成整套成稿 |
| 事实一致性 | 5.0 | 标题、核心判断与 Speaker Notes 来源保持一致 | 无 |
| 视觉载体适配 | 4.7 | 现场版无图、阅读版证据展开、展示版每页一项原创资产 | 展示版资产由本轮显式规划，不是默认 Provider 自动选择 |
| 真实渲染质量 | 5.0 | 9 页均逐页 Office 检查，三份 `slides_test.py` 全部 PASS | 无 |
| 可编辑性 | 4.5 | 文字、形状与简单图式为原生对象；展示版图片为嵌入资产 | 生成图片本身不可拆分编辑 |

## 8. Final outcome

- 已完成：三套受控样板、Office 对比图、结构指标、默认 Provider 探针和相关测试。
- 未完成：尚未改变生产 Provider、Schema 或 Gate。
- 后续任务：讨论是否以连续的 provider-neutral presentation posture 扩展现有场景表达；用户确认后再做 ADR / Schema / Provider / Gate 变更。
- 相关 ADR：无；本轮不做架构变更。
