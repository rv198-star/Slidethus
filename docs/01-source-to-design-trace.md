# 01｜Source-to-Design Trace

## 1. 来源边界

本项目方法论基线来自用户提供的保存网页《应该是目前最强的PPT Agent，附上完整思路分享》。原素材是产品思路与部分提示词分享，不是完整源码、完整 Agent 状态机或完整工程规范。

本文件把三类内容分开：

1. **Source-derived**：原素材明确表达的内容；
2. **Slidethus design**：为形成可复用 Skill 而新增的架构决策；
3. **Open gap**：原素材没有公开、仍需实现或验证的部分。

## 2. 方法映射

| 原素材表达 | Slidethus 保留方式 | 工程化扩展 | 状态 |
|---|---|---|---|
| 提问前先做背景调研 | P0 前置方向性扫描 | 有界检索、只用于理解上下文与缺口 | 合同已定义，适配器待 M2 |
| 需求调研后再做大纲 | Phase 0 Project Brief | 最少提问、阻断问题、审批模式 | 合同已定义 |
| 每页作为数字便利贴 | Deck Outline 的 slide objects | 稳定 ID、增删/重排/拆分/合并 | Schema 已定义 |
| 围绕大纲逐页检索 | P2 定向证据补全 | 查询计划、来源等级、冲突、时效与返工路由 | 合同已定义，适配器待 M2 |
| 内容和设计之间加入策划稿 | Slide Specs + Layout Plans | 语义/几何分离、灰模、Gate | 基础已实现 |
| 策划负责结构，设计负责风格 | Layout Plans 与 Visual System 分离 | 后端无关的 render contract | 合同已定义 |
| Bento Grid 组织信息 | Layout family: `bento` | 与 hero/process/timeline/matrix 等并列 | 规则已定义 |
| 输出 1280×720 SVG | 默认逻辑画布与 SVG backend | Native/Hybrid PPTX 后端 | 策划 SVG、设计 SVG、Debug/Final E3 PPTX 已分离，正式多后端待实现 |
| 大纲 JSON 输出 | Schema-backed artifacts | JSON Schema、跨引用与版本 | 基础已实现 |

## 3. 直接吸收的核心

### 3.1 先问清楚再生成

Slidethus 将用途、受众、决策目标、场景、页数、资料边界和交付格式固化为 `project_brief.json`。未解决的阻断问题不会被视觉生成掩盖。

### 3.2 研究是前后两次、同一证据账本

原素材同时包含“提问前先了解背景”和“根据大纲逐页检索”两种研究动作。Slidethus 将其定义为同一 P2 证据域的两次执行：

- **方向性研究**：在 P0/P1 附近进行，只建立当前语境、受众问题和资料缺口；
- **定向证据补全**：P4 大纲形成后，逐页检查事实、案例、数据和视觉证据需求。

若第二次研究改变了证据基础，状态从 `OUTLINE_READY` 返回 `EVIDENCE_READY`，更新证据后重新验证叙事和大纲，再进入 Slide Specs。Evidence Ledger 的 `research_cycles` 会把两次执行及其 outline 版本持久化。这样既保留原素材的工作流，也避免把一次粗搜索冒充完整事实链。

### 3.3 大纲是可操作对象

大纲不是一次性 Markdown。每页有稳定 `slide_id`、章节、页面类型、核心命题、证据引用和状态，因此支持局部重排和重生成。

### 3.4 页面策划稿是正式 Gate

Slidethus 把原素材的“策划稿”拆成：

- `slide_specs.json`：为什么讲、讲什么、内容块是什么；
- `layout_plans.json`：这些内容块怎样映射到页面区域；
- wireframe SVG：供人和模型检查结构的投影。

最终设计不能绕过这三层。

### 3.5 先结构后风格

Visual System 只在叙事、页面规格和布局计划足够稳定后生成。这样避免模型同时修改事实、叙事、几何和审美。

## 4. 不原样照搬的部分

### 4.1 不绑定 Grok 或任何搜索产品

原素材的 DIY 示例推荐特定搜索产品。Slidethus 只定义 `ResearchProvider` 协议和证据合同，供应商属于可替换适配器。

### 4.2 不把 Bento 当成万能设计

卡片式布局适合并列、摘要、模块和信息仪表盘，但不适合所有叙事。Slidethus 的布局家族至少包括：

- hero / statement
- split / comparison
- process / flow
- timeline
- matrix
- architecture
- chart story
- case study
- full-bleed image
- bento

### 4.3 不把整页 SVG 等同于完全可编辑 PPT

Slidethus 明确编辑等级：

| 等级 | 说明 |
|---|---|
| E0 | 整页位图，仅视觉可用 |
| E1 | 整页 SVG，可缩放但内部不便编辑 |
| E2 | Hybrid：文本/简单形状原生，复杂图形为 SVG/图片 |
| E3 | 大部分文本、形状、图表为原生 PPT 对象 |
| E4 | 模板、母版、占位符和数据绑定均可维护 |

MVP 推荐 E2，而不是承诺所有复杂视觉都达到 E4。

### 4.4 不只靠 Prompt 保证质量

Prompt 负责推理与生成，Schema、验证器、渲染预览、Gate 和回归测试负责确定性质量。

## 5. 原素材没有公开的关键层

- 需求调研状态机；
- 研究查询、引用、去重、冲突和事实校验；
- 页面策划稿完整 Schema；
- 多页视觉 Token；
- 图片、图标、图表与版权策略；
- SVG/PPTX 溢出、碰撞和字体校验；
- 自动修复和回归；
- 缓存、并发、成本和可观测性；
- 宿主工具不足时的降级策略。

这些缺口构成 Slidethus 的工程增量，不应被描述为原作者已经公开的能力。

## 6. 可追溯素材位置

- `source_material/cleaned-main-post.md`
- `source_material/source-workflow.md`
- `source_material/source-preserved/`
- `source_material/raw/README.md`（原始浏览器 HTML 因隐私与无关数据而不打包）
- `source_material/source-boundary.md`
