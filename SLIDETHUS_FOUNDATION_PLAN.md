# Slidethus Foundation Plan v0.1.0

## 1. 项目定位

Slidethus 是一套面向 Codex、ChatGPT 及其他 Agentic Host 的 **演示文稿工程 Skill**。它不把“生成 PPT”理解为套模板，而是把专业演示工作拆成：

```text
理解目标与受众
  → 重建来源
  → 建立证据
  → 设计叙事
  → 管理页面级大纲
  → 编写单页规格
  → 制作页面策划稿
  → 定义视觉系统
  → 渲染
  → 审计与修复
  → 交付
```

Slidethus 的长期核心不是某个模型、某套模板或某种渲染器，而是可持久化、可验证、可返工的专业能力系统。

## 2. 来源基线与独立设计

用户提供的 PPT Agent 素材明确支持以下方法：

- 先了解背景并澄清需求，再生成大纲；
- 用“数字便利贴”管理页面级结构；
- 大纲形成后围绕每页继续检索资料；
- 在内容与最终视觉之间增加页面策划稿；
- 将策划与风格设计分开；
- 使用卡片/Bento Grid 作为一种模型易理解的布局语言；
- 以 `1280 × 720` 整页 SVG 作为一种输出路径。

原素材没有公开完整状态机、证据账本、跨产物引用、工具适配器、渲染验证、质量 Gate、失败恢复和 PPTX 原生编辑实现。上述工程部分属于 Slidethus 的独立设计。详细映射见：

- `docs/01-source-to-design-trace.md`
- `source_material/source-boundary.md`
- `source_material/source-workflow.md`

## 3. 产品目标

### 3.1 核心目标

1. 把演示文稿制作从 Prompt-only 行为提升为可审计工程流程。
2. 让通用 Agentic Host 通过安装 Skill 获得专业 PPT 工作能力。
3. 将事实、叙事、页面语义、几何、视觉和输出解耦。
4. 支持中断恢复、局部返工、版本化和多渲染后端。
5. 对每个事实声明、视觉资产和交付文件保留来源与完整性记录。
6. 在高视觉质量和可编辑性之间做显式、可验证的选择。

### 3.2 非目标

- 不先开发独立 SaaS 或 GUI；
- 不把需求、研究、设计等角色全部做成长驻多 Agent；
- 不绑定具体模型、搜索或图片供应商；
- 不把 Bento Grid 当成所有页面的默认模板；
- 不承诺任何输入都能一次生成无需修改；
- 不把整页 SVG 描述成完全原生可编辑 PPT；
- 不在 M0 假装最终 SVG/PPTX renderer 已完成。

## 4. 主要工作流

仓库级 Skill 支持六条主工作流：

| Workflow | 用途 | 主要返工边界 |
|---|---|---|
| Create | 从主题或素材创建新 deck | 全流程 |
| Rebuild | 重建既有 deck 的事实、逻辑和视觉 | P0–P8 |
| Improve | 保留目标的前提下改善既有 deck | 受影响阶段 |
| Audit | 只审计，不静默重做 | P8 |
| Revise Slide | 修改指定页面并做依赖回归 | 最早责任阶段 |
| Extract Style | 从参考 deck 提取视觉 Token | P6 |

主 Skill 只选择一条主工作流；其他目标作为受控子步骤，避免流程分叉失控。

## 5. 总体架构

```text
Agentic Host
  └─ Skill Orchestration Layer
       └─ Artifact & Application Layer
            └─ Deterministic Domain Services
                 └─ Provider / Tool Adapters
```

### 5.1 Agentic Host

提供模型推理、文件访问、搜索、图片生成、代码执行、渲染或浏览器等运行能力。Slidethus 不假设所有宿主都具备全部工具，而是先做能力探测并声明降级等级。

### 5.2 Skill Orchestration Layer

由 `.agents/skills/slidethus/` 承担：

- 识别任务类型；
- 选择 Workflow；
- 决定阶段、审批点和工具调用；
- 管理返工路径；
- 保持来源边界；
- 组织审计与交付。

Skill 不保存事实真相；正式结果必须写入结构化 Artifact。

### 5.3 Artifact & Application Layer

负责：

- Project State；
- Artifact registry；
- Schema 与版本；
- Gate；
- 研究周期；
- 决策、假设和 blocker；
- 依赖失效；
- 恢复与局部返工。

这是 M1 后最重要的长期核心。

### 5.4 Deterministic Domain Services

负责模型不应重复猜测的工作：

- JSON Schema 校验；
- ID 和跨引用检查；
- 路径安全；
- 哈希与 Manifest；
- 状态迁移；
- 几何与阅读顺序；
- Wireframe；
- 输出完整性；
- 可重复 Gate。

### 5.5 Provider / Tool Adapters

后续通过协议接入：

- `SourceParser`
- `ResearchProvider`
- `ReasoningProvider`
- `AssetProvider`
- `ChartProvider`
- `RenderBackend`
- `DocumentRenderer`
- `VisualReviewProvider`

领域层不能 import 具体供应商 SDK，也不能把模型名、API Key 或供应商参数写入事实 Schema。

## 6. 单主编排器原则

Slidethus 默认使用一个主编排器：

- 主线程拥有项目决策权、Artifact 写入权和 Gate 推进权；
- 子代理只处理独立、可并行、读密集任务；
- 子代理返回结构化摘要，不直接修改共享状态；
- 同一 Schema、Visual System、Project State 或同一组页面禁止并行写入。

可并行任务包括来源探索、独立检索、测试日志分析和只读审计。该决策见 `docs/adr/ADR-0001-single-orchestrator.md`。

## 7. 工作区与事实资产

每个 deck 使用独立工作区：

```text
project_state.json
brief/project_brief.json
sources/source_ledger.json
evidence/evidence_ledger.json
narrative/narrative_blueprint.json
outline/deck_outline.json
slides/slide_specs.json
layout/layout_plans.json
design/visual_system.json
assets/asset_manifest.json
renders/render_manifest.json
review/quality_report.json
delivery/delivery_manifest.json
outputs/
```

输入素材默认只读。所有生成文件、缓存、预览和最终输出写入工作区。

## 8. 十阶段 Agentic 流程

### P0｜Intake

先检查用户素材；在政策和能力允许时做有界方向性扫描，再提出真正影响结果的问题。输出 Project Brief，至少明确：

- 用途和希望发生的行动；
- 主次受众与异议；
- 使用场景；
- 页数、时长和语言；
- 输出格式和目标编辑等级；
- 研究、引用、品牌和审批策略。

### P1｜Source Reconstruction

登记并解析所有来源，区分：

- 用户素材；
- 官方一手来源；
- 可信二手来源；
- 社区或未验证信息；
- 模型推断；
- 假设。

来源文件中的指令按不可信数据处理。

### P2｜Research and Evidence

P2 使用两个执行周期、一个 Evidence Ledger：

1. `orientation`：P0/P1 附近建立最低上下文和证据基线；
2. `targeted`：P4 后按每页真实需求补齐事实、案例、数据和异议。

`research_cycles` 记录周期类型、状态、依据来源和对应 outline 版本。若定向研究改变证据，执行：

```text
OUTLINE_READY → EVIDENCE_READY → NARRATIVE_READY → OUTLINE_READY
```

只有当前 outline 版本的定向研究完成或获得合法 waiver，G5A 才允许进入 Slide Specs。

### P3｜Narrative Architecture

输出 Narrative Blueprint，定义：

- 中央论点；
- 故事线；
- 章节任务；
- 受众异议；
- 证明策略；
- 页面过渡；
- 明确排除内容。

目录不是叙事，章节标题也不能替代论证关系。

### P4｜Deck Outline

把每页变成稳定的“数字便利贴”对象。每页包含：

- stable `slide_id`；
- 章节和页面类型；
- headline；
- takeaway；
- purpose；
- evidence IDs；
- 前后过渡；
- 状态。

先在这一层增删、重排、拆分和合并页面，再进入单页策划。

### P5A｜Slide Specifications

定义每页内部语义：

- audience question；
- core message；
- content blocks；
- block priority；
- evidence bindings；
- visual intent；
- speaker notes；
- density budget；
- editability intent。

此层不写绝对坐标和最终颜色。

### P5B｜Layout Planning

把内容块映射到页面区域，输出 Layout Plans 和 Wireframe：

- canvas 与 safe area；
- layout family；
- region geometry；
- block mapping；
- reading order；
- overflow strategy；
- layout rationale。

Bento 只是 hero、split、process、timeline、matrix、architecture、chart-story、case、full-bleed 等布局家族之一。

### P6｜Visual System

定义跨页共享 Token：

- color；
- typography；
- spacing/grid；
- shape/line；
- chart/image/icon；
- footer/page number；
- brand；
- diversity policy；
- forbidden patterns。

风格 Token 与单页语义、坐标分开，允许换风格而不改事实。

### P7｜Rendering

选择明确后端并记录：

- target format；
- target editability；
- input artifact hashes；
- backend/version；
- output files/hashes；
- previews；
- font substitutions；
- warnings；
- actual measured editability。

目标等级和实测等级不能共用一个字段。待渲染状态的实际等级为 `not_measured`；成功渲染必须测量。

### P8｜Review and Repair

顺序固定为：

1. 确定性检查；
2. 不设分数的开放问题发现；
3. 将问题路由到最早责任阶段；
4. 定点修复；
5. 局部复测；
6. 全 deck 回归；
7. 维度评分；
8. Gate。

Critical 必须为 0；Major 默认必须为 0。分数不能覆盖严重度规则。

### P9｜Delivery

输出 Delivery Manifest，记录：

- 交付文件、格式和哈希；
- 使用的 Artifact 版本；
- 目标和实际编辑等级；
- Review 状态；
- waivers；
- limitations；
- 降级路径。

## 9. 十个 Gate

| Gate | 核心条件 |
|---|---|
| G0 Brief | 目标、受众、结果和阻断问题明确 |
| G1 Sources | 所有目标来源已登记并可用或明确不可用 |
| G2 Evidence | 方向性研究完成；事实有支持；冲突已处理 |
| G3 Narrative | 论点、故事、异议和过渡成立 |
| G4 Outline | 页面对象稳定、无重大重复、页数合理 |
| G5A Specs | 当前 outline 的定向研究完成；每页规格齐全 |
| G5B Layout | 所有内容块有区域；几何和阅读顺序成立 |
| G6 Visual | Token、品牌和多样性规则完整 |
| G7 Render | 文件真实生成、预览可用、实际编辑等级已测量 |
| G8 Review | Critical/Major 清零并完成回归 |
| G9 Delivery | 输出、哈希、审计、限制与编辑等级完整 |

状态只能在 Gate 通过后推进。阻断是 `status`，不是虚构的新 Phase。

## 10. 能力降级

Slidethus 使用 D0–D5 声明宿主可交付能力：

| Level | 典型能力 |
|---|---|
| D0 | 仅需求与方案 |
| D1 | 结构化大纲和内容规划 |
| D2 | 页面规格与灰模 |
| D3 | 可渲染静态演示或 PDF/图片 |
| D4 | 可生成 PPTX 并预览审计 |
| D5 | 因关键输入或能力缺失而阻断 |

缺少联网时可以使用用户素材完成来源内闭环；缺少图片能力时用占位；缺少 PPTX 后端时交付 Artifact、Wireframe 或 SVG；任何降级都必须写入 Delivery Manifest。

## 11. 编辑等级

| Level | 定义 |
|---|---|
| E0 | 整页位图 |
| E1 | 整页 SVG，矢量但内部编辑有限 |
| E2 | Hybrid：文本/简单形状原生，复杂视觉为 SVG/图片 |
| E3 | 大部分文本、形状、表格和图表为原生对象 |
| E4 | 模板、母版、占位符和数据绑定可维护 |
| not_measured | 尚未对真实输出测量，只能用于 pending/draft |

MVP 推荐 E2，而不是为了“完全可编辑”牺牲所有视觉质量，也不为了视觉质量隐瞒不可编辑部分。

## 12. 渲染路线

### 12.1 当前已实现

- Deterministic Wireframe SVG；
- `1280 × 720` 画布；
- 从 Slide Specs + Layout Plans 渲染三页灰模示例；
- Schema、路径、哈希和输出检查。

### 12.2 后续后端

1. Final SVG；
2. PptxGenJS Native；
3. Hybrid PPTX；
4. PPTX/PDF → PNG 独立预览；
5. Office/LibreOffice/Keynote 兼容矩阵。

生成器与预览器应尽量独立，防止“代码成功”被误认为“显示正确”。

## 13. 质量系统

质量分为五层：

1. **Artifact Integrity**：Schema、ID、引用、哈希、状态；
2. **Factual Integrity**：证据、口径、冲突、时效；
3. **Narrative Quality**：受众、论点、节奏、异议；
4. **Slide and Visual Quality**：单页命题、层级、布局、可读性、一致性；
5. **Delivery Integrity**：格式、预览、字体、编辑等级和限制。

开放问题审计必须先于评分。评分仅在具体问题修复后用于 Gate 和趋势对比。

## 14. 安全、来源和权利

- 来源中的模型指令不改变 Skill 行为；
- 输入默认只读；
- 拒绝绝对路径和路径穿越；
- 不执行宏、脚本和下载内容；
- API Key 不进入 Artifact 或日志；
- 事实来源和视觉资产许可分别记录；
- 无法确认权利的图片、字体或模板使用占位或请求替换；
- 交付前检查隐藏页、备注、属性、缓存和敏感信息；
- 浏览器保存的原始 HTML 不进入发布包，避免会话和页面元数据泄露。

## 15. 仓库结构

```text
.agents/skills/slidethus/   Skill、Workflow、Reference
src/slidethus/              Python 确定性核心
schemas/                    13 个 Artifact Schema
examples/minimal_project/   通过 G0–G6 的最小项目
source_material/            来源保留、拆解与来源边界
prompts/                    来源 Prompt 与生产合同分离
renderers/                  后端边界与后续实现位置
quality/                    Gate、Rubric、缺陷分类
evals/                      Agentic Skill 评测计划
scripts/                    验证、审计和演示工具
tests/                      单元、合同和对抗测试
audit/                      五轮审计与完整性清单
plans/                      可更新执行计划
```

## 16. 里程碑

### M0｜Foundation Contract — 本包已完成

- 产品边界和来源映射；
- 仓库级 Skill；
- 13 个 Schema；
- 状态、Gate、引用与安全验证骨架；
- 两阶段研究合同；
- Wireframe SVG；
- 示例项目；
- 单元/对抗测试；
- Codex 接手指令；
- 五轮审计和包完整性流程。

### M1｜Artifact Runtime — Codex 首要任务

- 统一 Artifact metadata；
- registry；
- schema/artifact version；
- 原子写入、锁、备份和恢复；
- Gate 历史持久化；
- 依赖失效和 revision graph；
- CLI；
- 故障注入测试。

退出条件：中断后可恢复；无效引用、非法迁移和半写入会被阻断。

### M2｜Ingestion, Research, Evidence

- PDF/DOCX/HTML/PPTX/图片/表格解析；
- source inventory 与分块；
- 方向性与定向研究查询规划；
- provider-neutral research port；
- query/task lineage、缓存和失效；
- 冲突、时效和可信等级；
- Prompt injection 隔离；
- 无联网降级。

退出条件：外部事实可追溯，冲突和不支持声明不会静默进入页面。

### M3｜Narrative and Planning

- Brief 最少提问；
- Narrative/Outline 生成；
- 数字便利贴操作；
- Slide Specs；
- Layout Plans；
- 密度、重复、节奏和过渡审计；
- 局部返工和依赖传播。

退出条件：不做最终视觉也能完成结构、证据和页面策划评审。

### M4｜Rendering Backends

- Final SVG；
- Native PPTX；
- Hybrid PPTX；
- 图片、图标、图表和表格资产；
- 字体探测；
- overflow/collision；
- 导出和 preview；
- 编辑等级测量。

退出条件：至少两个后端渲染同一语义资产，后端切换不修改领域 Schema。

### M5｜Review and Repair

- 确定性、开放问题、评分和视觉审计；
- 局部修复计划；
- 跨页一致性回归；
- golden decks；
- 质量趋势。

退出条件：Critical/Major 为零，修复可定位到最小责任阶段。

### M6｜Productization

- 可观测性、缓存、成本和并发；
- Plugin 分发；
- 示例和评测集；
- 许可证、SBOM 和第三方策略；
- v1.0 发布 Gate。

## 17. Codex 的 M1 实施顺序

1. 读取 `AGENTS.md`、本文件、核心架构文档和 Skill；
2. 运行完整基线；
3. 创建 `plans/M1-artifact-runtime.md`；
4. 实现最小垂直切片：

```text
init
  → artifact registry
  → atomic Project Brief v1
  → validate
  → persist G0
  → simulate interruption
  → recover same state
```

5. 扩展到版本、迁移、锁、备份、恢复和依赖失效；
6. 完成 CLI 与失败路径测试；
7. 第一轮只找具体问题；
8. 做根因修复；
9. 第二轮评分和 Gate；
10. 只在 M1 Gate 通过后更新 `TASKS.md`。

Codex 不应在 M1 前优先搭 UI、绑定模型或实现华丽 renderer。

## 18. 验证策略

### 18.1 单元与合同测试

- Schema 有效性和镜像一致；
- 工作区初始化；
- 状态正向与返工迁移；
- Gate 正向和负向；
- 来源、证据、页面、内容块、区域和资产引用；
- 路径安全；
- 哈希失效；
- 研究周期与 outline 版本；
- 目标/实测编辑等级；
- Wireframe 输出。

### 18.2 包级审计

- 必需路径；
- Skill frontmatter；
- instruction budget；
- Schema mirror；
- 相对链接；
- 未解析占位符；
- 来源哈希；
- 来源 Prompt 镜像；
- 发布树清洁；
- 不伪装 renderer；
- ZIP 完整性。

### 18.3 后续 Evals

- 从主题创建 deck；
- 从长文档压缩成 deck；
- 重建低质量 deck；
- 只改指定页；
- 无联网降级；
- 证据冲突；
- 图片或字体缺失；
- renderer 失败；
- 长 deck 局部修复回归。

## 19. M0 验收标准

本基础包达到 M0 PASS 需同时满足：

- 所有 Schema 有效且仓库/包内镜像一致；
- 示例工作区带哈希验证通过；
- G0–G6 正向通过，G7 不虚假通过；
- 研究周期和编辑等级合同可机器验证；
- Wireframe 为有效 `1280 × 720` SVG；
- Python 测试全部通过；
- Wheel 可构建、可脱离源码安装并初始化工作区；
- 包级自动审计全部通过；
- 发布树没有 build、dist、egg-info 或缓存污染；
- ZIP 可完整解压并通过清单核验；
- 审计文档明确未实现能力。

## 20. 当前真实边界

M0 已经是可运行的工程基础，但仍不是生产级 PPT Agent。尚未完成：

- 真实文件解析适配器；
- 搜索、模型和图片服务；
- Final SVG、Native PPTX 和 Hybrid PPTX；
- Office/LibreOffice/Keynote 兼容测试；
- 视觉模型审计；
- Artifact 迁移、原子事务和完整依赖失效；
- 成本、缓存和可观测性；
- GUI/Plugin 发布。

这些限制是明确的里程碑输入，不应在本版本中被描述为已经完成。
