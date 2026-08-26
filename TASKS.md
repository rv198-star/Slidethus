# Slidethus Build Roadmap

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

- [ ] PDF/DOCX/HTML/PPTX/图片/表格输入适配器
- [ ] source inventory、哈希与内容分块
- [ ] 方向性扫描 + outline-driven 定向研究的查询规划与 provider-neutral research port
- [ ] research cycle/query/task lineage、缓存、失效与恢复
- [ ] 证据去重、冲突、时效和可信等级
- [ ] 每个事实性内容块绑定 evidence IDs
- [ ] 来源注入防护与不可信指令隔离
- [ ] 无联网降级模式

**Exit Gate：** 任何进入 deck 的外部事实都可追溯；冲突和不支持声明不会静默进入后续阶段。

## M3 — Narrative and Planning

- [ ] Project Brief 智能补全与最少提问策略
- [ ] Narrative Blueprint 生成与审计
- [ ] Deck Outline 数字便利贴操作：增删、重排、拆分、合并
- [ ] Slide Specs 生成
- [ ] Layout Plans / 灰模生成
- [ ] 页面密度、重复、节奏和过渡检查
- [ ] 局部返工与依赖传播

**Exit Gate：** 内容可以在不做最终视觉的情况下完成结构、证据和页面策划审阅。

## M4 — Rendering Backends

- [ ] 最终 SVG renderer
- [ ] PptxGenJS native renderer
- [ ] Hybrid renderer
- [ ] 图片、图标、图表和表格资产合同
- [ ] 字体探测与替代
- [ ] overflow、collision、safe-area 检测
- [ ] PPTX/PDF/PNG 导出与 render manifest
- [ ] 编辑等级声明和验证

**Exit Gate：** 同一语义资产可由至少两个后端渲染；后端切换不修改领域 Schema。

## M5 — Review and Repair Loop

- [ ] 确定性审计
- [ ] 开放问题发现型语义审计
- [ ] 维度评分型审计
- [ ] 全页视觉审计
- [ ] 局部修复计划与重生成
- [ ] 跨页一致性回归
- [ ] 质量基线与 golden deck

**Exit Gate：** Critical/Major 问题为零，修复可定位到最小受影响阶段，并通过回归验证。

## M6 — Productization and Distribution

- [ ] 多工作流稳定化
- [ ] 可观测性、缓存、成本预算和并发控制
- [ ] Plugin 打包
- [ ] 示例库、评测集和发布文档
- [ ] 许可证与第三方素材策略
- [ ] v1.0 发布 Gate

## 实施纪律

- 每个里程碑单独建立执行计划和 ADR。
- Gate 未通过，不进入依赖该 Gate 的里程碑。
- 接口占位不等于任务完成。
- 先完成事实与合同，再扩展界面和视觉效果。
