# Slidethus Build Roadmap

## v0.8.0 能力发布

发布当前宿主设计链路与模块化技能套件，保持 provider-neutral、单一主编排器和既有阶段合同。只用 Python 3.11 做本轮验证，不做多版本审计，不新增行业案例或重开优化。

执行与结果见 `plans/v0.8.0-release.md`，用户说明见 `release/v0.8.0.md`。这是 0.x 能力发布，不改变下文 M6.6 / v1.0 的未完成状态。

## 当前基线

本包已经完成 **M0 — Foundation Contract** 与 **M1 — Artifact Runtime**：

- [x] 产品边界、架构与非目标
- [x] 仓库级 Skill 与 Codex 指令
- [x] 核心 JSON Schema
- [x] 最小示例项目
- [x] 初始化、校验、状态、Gate 和灰模渲染 CLI 骨架
- [x] 基线测试、自动审计与完整性清单
- [x] 来源素材与 Slidethus 设计决策分离

M0 只代表基础合同成立，不代表端到端 PPT 生成完成。

## M1 — Artifact Runtime

目标：让所有中间产物成为可创建、可版本化、可校验、可恢复的工程事实。

- [x] Artifact registry 与统一元数据
- [x] Schema 版本迁移机制
- [x] Artifact 乐观锁/版本号
- [x] 原子写入、失败恢复与备份
- [x] 全量跨引用校验
- [x] Gate 结果持久化
- [x] 决策日志与假设日志
- [x] CLI：`artifact list/show/validate/migrate`
- [x] 单元、集成与故障注入测试

**Exit Gate：PASS（2026-08-26）。** 示例项目和新建项目均可在中断后恢复；无效引用、非法状态迁移、过期 Gate 或半写入会被检测并阻止推进。验收证据见 `audit/M1-round-2-scorecard.md`。

## MVP0 — Planning Proof

目标：用可替换 MinimalImpl 证明输入、证据、策划 artifacts 和 PPTX 文件写入可以连接。该版本后来被确认只完成最简策划稿，PPTX 是策划内容的直出预览，不能算独立调试或设计阶段。

- [x] Markdown/TXT 输入与 line-located chunks
- [x] 用户材料限定的 Evidence、双阶段 research cycle 与事实块绑定
- [x] 规则式 Narrative、Outline、Slide Specs、Layout Plans、Visual System
- [x] 策划稿的原生 PPTX 预览（E3 文本与简单形状）
- [x] Wireframe 和 LibreOffice/Poppler 可行性验证
- [x] 中文字体临时装载；字体不打包进入交付
- [x] G0–G9 端到端 CLI：`slidethus mvp`
- [x] 无独立预览时停在 G8 并交付 degraded 结果
- [x] provider 替换、来源指令隔离和失败路径测试

**Planning Gate：PASS（2026-08-26）。** 该版本只证明最简策划稿与文件生成，不再称为完整端到端 MVP。

## MVP1 — Complete Action and Output Chain

目标：每个声称完成的动作都有不同产出物和独立验收，不能用格式转换代替缺失阶段。

- [x] Planning wireframes：一页一个灰模 SVG
- [x] Layout diagnostics：safe area、边界、碰撞、文本容量和字号检查
- [x] Debug PPTX：网格、safe area、Region/Block ID 与映射
- [x] Debug Office previews：独立渲染调试稿
- [x] Design previews：消费 Visual System 和布局家族
- [x] Final PPTX：独立于调试稿的 E3 最简设计实现
- [x] Final Office previews：独立渲染最终稿
- [x] Render Manifest 七段动作记录和 output roles
- [x] G7 检查非审阅阶段，G8 检查调试/最终两条预览链，G9 检查交付

**MVP Gate：PASS（2026-08-26）。** 六页真实验收生成 27 个分阶段输出，Artifact Validation 与 G7/G8/G9 均通过。设计仍为 MinimalImpl，不代表生产级视觉能力或完整 M2–M5 Exit Gate。

## M2 — Ingestion, Research, Evidence

- [x] PDF/DOCX/HTML/PPTX/图片/表格输入适配器
- [x] source inventory、哈希与内容分块
- [x] 方向性扫描 + outline-driven 定向研究的查询规划与 provider-neutral research port
- [x] research cycle/query/task lineage、缓存、失效与恢复
- [x] 证据去重、冲突、时效和可信等级
- [x] 每个事实性内容块绑定 evidence IDs
- [x] 来源注入防护与不可信指令隔离
- [x] 无联网降级模式

**Exit Gate：PASS（2026-08-27）。** M2.1–M2.6 Submodule Gates 与 M2.7 repository-wide Gate 均通过，无 waiver。外部事实必须经过 Source/Research/Evidence lineage；冲突、不支持、失效或未限定声明不能静默进入页面。验收证据见 `audit/M2.7-round-2-scorecard.md` 与 `audit/M2-BUILD_REPORT.md`。

## M3 — Narrative and Planning

- [x] Project Brief 智能补全与最少提问策略
- [x] Narrative Blueprint 生成与审计
- [x] Deck Outline 数字便利贴操作：增删、重排、拆分、合并
- [x] Slide Specs 生成
- [x] Layout Plans / 灰模生成
- [x] 页面密度、重复、节奏和过渡检查
- [x] 局部返工与依赖传播

**Exit Gate：PASS（2026-08-27）。** Production Brief、Narrative、stable Outline、Evidence-qualified Slide Specs、Layout Plans、immutable wireframes、Planning Review/Repair 与 M3 Application 已形成 current-version、可恢复、provider-neutral 的策划边界；Round A Critical/Major 全部根修，无 waiver。证据见 `audit/M3-round-2-scorecard.md` 与 `audit/M3-BUILD_REPORT.md`。

## M4 — Rendering Backends

- [x] 最终 SVG renderer
- [x] PptxGenJS native renderer
- [x] Hybrid renderer
- [x] 图片、图标、图表和表格资产合同
- [x] 字体探测与替代
- [x] overflow、collision、safe-area 检测
- [x] PPTX/PDF/PNG 导出与 render manifest
- [x] 编辑等级声明和验证

**Exit Gate：PASS（2026-08-28）。** 同一 current Renderer IR 已由 Final SVG、PptxGenJS Native 与 Hybrid 三个 Production backend 渲染；真实 PPTX/SVG/PNG/PDF 输出、资产/字体/几何 preflight、实际 editability、Production Render Manifest、M4 Application/CLI 和 G6/G7 均已形成可验证边界。后端切换不修改 M2/M3 领域 Schema。证据见 `audit/M4-round-2-scorecard.md` 与 `audit/M4-BUILD_REPORT.md`。

## M5 — Review and Repair Loop

- [x] **M5.1 Deterministic Review Core**：独立重算 workspace/G0–G7/render lineage、真实输出覆盖与跨后端结构一致性
- [x] **M5.2 Open Issue Semantic Review**：无评分问题发现、stable issue identity、最早责任阶段定位
- [x] **M5.3 Dimension Scorecard**：Round A 后评分，评分绑定问题证据且不能覆盖 Critical/Major
- [x] **M5.4 Full-page Visual Review**：消费真实页面预览，执行跨页视觉审计与 capability-aware degradation
- [x] **M5.5 Repair Plan & Regeneration**：生成最小影响 Repair Plan，回到正确责任阶段局部重生成
- [x] **M5.6 Cross-deck Regression**：修复后局部/全 deck 回归、Quality Report 聚合与 G8
- [x] **M5.7 Golden Deck & M5 Exit**：质量基线、negative corpus、M5 Application/CLI、Round A/B 与 repository Exit validator

执行计划：`plans/M5-review-repair-loop.md`。架构边界：`docs/adr/ADR-0020-independent-review-repair-boundary.md`。

**Exit Gate：PASS（2026-08-29）。** Critical/Major open issues 为零，无 waiver；Review/Repair 可定位到最小责任阶段，局部修复通过 cross-deck regression，Production Quality Report 驱动 G8；M2/M3/M4 Exit 保持单调 PASS。验收证据见 `audit/M5-round-2-scorecard.md` 与 `audit/M5-BUILD_REPORT.md`。

## M6 — Productization and Distribution

- [x] **M6.1 Multi-workflow Runtime**：Create/Rebuild/Improve/Audit/Revise/Extract Style 统一 request/run/report、dispatcher、CLI 与 capability/mutation policy
- [x] **M6.2 Operational Controls**：structured events、缓存策略、成本/资源预算、并发/lease/恢复
- [x] **M6.3 Plugin Packaging**：Plugin bundle、Schema/Skill/workflow 打包、Node sidecar bootstrap/version verification
- [x] **M6.4 Examples & Evaluation**：六 workflow 示例、评测集、兼容矩阵与发布文档
- [x] **M6.5 License & Third-party Policy**：项目许可证、依赖/素材/字体/模型分发策略、NOTICE/SBOM 边界
- [ ] **M6.6 v1.0 Preview Hardening & Release Gate**：已恢复酒店低奢统一版对应代码检查点 `e34b62a`；正在复核视觉判断、正式生产路径与发布证据，尚未重新验证发布候选。

执行计划：`plans/M6-productization-distribution.md`。架构边界：`docs/adr/ADR-0021-workflow-productization-boundary.md`。

**M6 Exit Gate：REOPENED（2026-08-31）。v1.0 Release Gate：DO NOT RELEASE。** 当前范围与历史依据见 `plans/M6.6-final-optimization-and-rerelease.md`。旧跨案例/收敛计划和审计仅为历史记录，不自动恢复撤回实现；更多行业/场景验证仍为后续待办。

## 实施纪律

本轮技能模块化已完成：`plans/skill-suite-modularization.md`（`using-slidethus` 入口、七个阶段子技能及完整分发验证；全量测试 365 passed / 43 skipped）。未改生产渲染链路、未扩大行业案例、未改变 Release Gate。

当前限定执行项：`plans/host-design-entry-stabilization.md`（用户指定的第 1、2 项：职责与真实宿主生成入口）。第 3 项完整生成包固化、第 4 项新案例/Office 视觉验收明确延期，不影响本轮工程收敛，也不被计为完成。

- 每个里程碑单独建立执行计划和 ADR。
- Gate 未通过，不进入依赖该 Gate 的里程碑。
- 接口占位不等于任务完成。
- 先完成事实与合同，再扩展界面和视觉效果。
