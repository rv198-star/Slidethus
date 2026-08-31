# Slidethus v0.8.1 — Evidence-backed Presentation Engineering

> 面向通用 Agentic Host 的 **Agentic Presentation Engineering Skill**：从本地文本依次产出策划稿、布局诊断、调试稿、设计稿和最终可编辑 PPTX。

## 这是什么

Slidethus 不是“输入标题后套模板”的 PPT 生成器，而是一套把专业演示文稿工作拆成可执行阶段、可验证中间产物和可回退质量门槛的 Agentic Skill 工程。

当前版本已经提供：

- 可被 Codex 自动发现的技能套件：`using-slidethus` 总入口、七个阶段子技能和兼容入口 `slidethus`；
- 根目录 `AGENTS.md`、Codex 启动指令、执行计划模板和分阶段任务清单；
- 需求、来源、证据、叙事、页面规格、布局、视觉系统、审计与交付的 JSON Schema；
- 一个可运行的 Python 核心与真实纵向 MVP；
- 随 Wheel 分发的 Schema 镜像，使确定性 CLI 可在仓库外独立运行；
- 初始化、校验、Gate 检查、状态查看和灰模 SVG 渲染 CLI；
- 统一 artifact registry 元数据、乐观锁、不可变版本历史和跨进程 workspace 锁；
- journaled 多文件事务、原子替换、故障恢复和显式 M0→M1 Schema 迁移；
- 独立、可版本化的 Gate 结果、决策日志和假设日志；
- `artifact list/show/validate/migrate/recover` CLI 与故障注入测试；
- `SourceParser` / `ReasoningProvider` / `RenderBackend` / `DocumentRenderer` 可替换接口；
- M2.1 Parser Registry、格式识别、稳定 Chunk/locator/hash、source risk 与资源限额；
- Markdown/TXT Production 摄取、create-if-absent 不可变快照、Source Ledger lineage、幂等复用与故障恢复；
- M2.2 HTML、PDF、DOCX、PPTX、CSV/TSV、XLSX 与常见图片元数据适配器；
- OOXML ZIP preflight、格式原生 locator、公式/链接隔离、EXIF 隐私风险和 `parsed/partial` 能力状态；
- M2.3 orientation/targeted Research Plan、provider/version lineage、可恢复 Research Run、不可变 query cache、TTL/generation invalidation 与 offline fail-closed；
- M2.4 deterministic Evidence Engine：Research Result → partial Web Source、stable Candidate/Evidence IDs、exact dedupe、Chunk/hash binding、conflict/freshness/authority/use policy 与 semantic cycle completion；
- M2.5 current-version Outline/Block Evidence binding、content-addressed Gap Report、targeted plan handoff 与正式 P2 rework；
- M2.6 单一 application orchestrator、显式 disclosure/degradation、高风险 Source 隔离、应用级 budgets、M2 Report 与 `m2` CLI；
- M2.7 repository-wide deterministic Exit validator、跨模块对抗审计、双 Python 基线与持久 Package Gate；
- M3.1 Project Brief 智能补全、最少提问、显式 assumptions/questions 和 `m3 answer` 恢复；
- M3.2–M3.5 provider-neutral Production Narrative、stable digital sticky-note Outline、Evidence-qualified Slide Specs、Layout Plans 与 immutable wireframes；
- designed Create 的 pre-layout `ArtDirectionSeed`（视觉载体、表面节奏、Taste-native 原型出处）与 P6 provider-neutral `ArtDirectionPacket`；内置固定版本 Taste 默认 provider、不可变 hash/lineage 与可替换 adapter；
- M3.6 Planning Review：密度、重复、节奏、过渡、容量、Bento 过度使用和 current-lineage 审计；
- M3.6 bounded local Repair、Planning Change/Review/Repair Reports、最小依赖传播和失败检查点；
- M3.7 单一 `M3ApplicationService`、`m3 run/list/show/gate`、repository Exit validator 与 M4 handoff；
- 用户来源限定的行号 evidence，以及规则式 Narrative/Outline/Slide Specs/Layout/Visual System MinimalImpl 回归链；
- 独立的策划灰模、布局诊断和带 Region/Block 映射的调试性 PPTX；
- 消费 Layout Plans 与 Visual System 的 Minimal DesignImpl 和设计预览；
- 基于 `python-pptx` 的最终原生文本/简单形状 PPTX，实测编辑等级 E3；
- 调试稿与最终稿分别经过 LibreOffice + Poppler 独立预览；
- `Render Manifest.pipeline_stages` 记录七个动作及其独立输出；
- `slidethus mvp` 从单个用户文件贯通 G0–G9，缺少任一步骤不能冒充完整 MVP；
- 一个完整的最小示例项目；
- 各里程碑两轮审计、repository-wide M2/M3 Exit 审计、自动审计脚本和 SHA-256 清单；
- 用户提供的 PPT Agent 素材、原始提示词和来源边界说明。

## 这不是什么

Slidethus v0.8.1 是 provider-neutral 的工程 Skill 与可验证 runtime/distribution boundary；它不是生产级端到端 PPT 产品（此处特指内置全部搜索、模型、图像和审阅供应商的一体化产品）。外部能力缺失时必须显式降级或阻断。当前 M6.6 已因真实 Office 视觉证据重开，尚未完成，不声明 v1.0 发布就绪。

当前包已经完成 M0–M5 与 M6.1–M6.5 的工程边界。**M6 Exit Gate：REOPENED。v1.0 Release Gate：DO NOT RELEASE（2026-08-31）。** v0.8.1 在 v0.8.0 宿主入口与模块化套件基础上，增加前置视觉 Seed、Taste 原生样板出处及页面视觉载体/表面节奏的传播校验，不等同于审美认证或 v1.0 验收通过。参见 [v0.8.1 发布说明](release/v0.8.1.md) 与 [发布执行记录](plans/v0.8.1-release.md)；历史 Round/RC 记录不作为本次发布依据。以下能力仍属于外部适配或显式 capability boundary：

- 内置搜索供应商、LLM/图片生成服务的真实适配；
- OCR、图片语义理解、音视频解释、公式计算和旧版 OLE/宏文件解析；
- 真实 LLM PlanningProvider、SemanticReviewProvider、VisualReviewProvider 适配及其独立模型评测；
- GUI、云端服务、多租户和商业化能力。

既有工程验收记录保持：M2 Exit Gate：PASS（2026-08-27）；M3 Exit Gate：PASS（2026-08-27）；M4 Exit Gate：PASS（2026-08-28）；M5 Exit Gate：PASS（2026-08-29）。这些子模块验收不替代当前 M6.6 的真实 PPTX 发布验收。

MVP1 的 MinimalImpl 仍只是跨里程碑回归切片。M2.2 的 `partial` 来源只提供已记录文本/元数据，Research Result 仍不是事实；M3 的确定性 PlanningProvider 是真实 Production contract baseline，但不声称具备通用 LLM 叙事智能。M4 已提供真实多后端渲染与输出完整性，M5 已提供独立 deterministic/semantic/visual review、severity-first scorecard、Repair Plan、cross-deck regression、Production Quality/G8 和 Golden baseline；没有注入语义/视觉 reviewer provider 时仍会显式停在 capability boundary，不伪造质量判断。

## 核心设计

```mermaid
flowchart LR
    U[用户目标与素材] --> B[Project Brief]
    B --> S[Source Ledger]
    S --> E[Evidence Ledger]
    E --> N[Narrative Blueprint]
    N --> O[Deck Outline<br/>数字便利贴]
    O --> P[Slide Specs]
    P --> L[Layout Plans<br/>页面策划稿]
    L --> V[Visual System]
    V --> R[Renderer Adapters]
    R --> Q[开放问题审计]
    Q --> C[维度评分与 Gate]
    C --> D[PPTX / PDF / SVG / 预览图]
```

最重要的边界是：

1. **原始素材不直接进入最终设计。**
2. **事实、叙事、页面语义、布局和视觉风格分层存储。**
3. **先发现具体问题，再评分；评分不能替代问题清单。**
4. **Bento Grid 只是布局家族之一，不是默认模板。**
5. **主 Skill 统一编排；子代理只用于可并行、读密集、低冲突任务。**
6. **确定性任务交给脚本，模型负责理解、判断和生成。**

## 本地启动

### 技能入口与分阶段使用

直接说“用 `$using-slidethus` 根据这些材料完成一份 PPT”，主 Agent 就会按需执行整条链路，不需要用户逐个调用技能。已有审批模式、用户指定的样页停点和能力限制仍然有效；一步到位不代表跳过证据、布局或真实 PowerPoint 验收。

| 技能 | 边界 |
|---|---|
| [using-slidethus](.agents/skills/using-slidethus/SKILL.md) | 总入口、六类工作流路由、端到端执行/续跑 |
| [slidethus-brief](.agents/skills/slidethus-brief/SKILL.md) | 需求、受众、场景、约束和假设 |
| [slidethus-research](.agents/skills/slidethus-research/SKILL.md) | 来源、两轮调研、证据与图表数据 |
| [slidethus-story](.agents/skills/slidethus-story/SKILL.md) | 叙事、论证与稳定页面大纲 |
| [slidethus-plan](.agents/skills/slidethus-plan/SKILL.md) | 内容块、图片/图表考虑、布局和线框 |
| [slidethus-design](.agents/skills/slidethus-design/SKILL.md) | Taste 默认设计路径、素材、全篇风格与节奏 |
| [slidethus-render](.agents/skills/slidethus-render/SKILL.md) | 同一链路生产样页/全篇候选及导出检查 |
| [slidethus-review](.agents/skills/slidethus-review/SKILL.md) | 审校、根因归属、授权修复复验与交付 |

例如“用 `$slidethus-plan` 只完成页面策划，不生成 PPT”，就停在 Specs/Layout/wireframe；“用 `$slidethus-review` 看看哪里不对”只审计，不擅自修改。

旧 `$slidethus` 保留兼容并转入总入口。子技能是同一 Agent 按需读取的工作模块，不是多 Agent 链。共用原有工件、脚本和 Taste，不改变已恢复的渲染器，也没有行业专用规则。

向其他工作区安装时使用 `slidethus plugin install-skill <host-root>`，会完整安装上述套件和兼容目录；不要只复制入口文件夹。已有目标文件不同会拒绝覆盖，请保留定制并选择干净目标或显式合并。Wheel 内使用 `share/slidethus/skills/<name>/` 同级布局，Plugin 同时包含全部技能及共享资源。详见 [技能模块化计划](plans/skill-suite-modularization.md)。

### 设计型生成链路

当前设计型 Create 入口为 `slidethus create <workspace> --source <file> --request "<需求>"`。
宿主逐阶段提交绑定当前上下文的规划/设计提案；明确的 Block 布局与逐页外观进入正式工件。
`--render --slide-id S-001` 与 `--render` 使用同一 IR/Artifact Tool 适配器，分别生成样板或全篇候选。
缺失设计、素材或宿主渲染能力会停止，不回填固定模板。旧 `workflow run create` 仅在显式
`--deterministic-baseline` 下运行。详见 [宿主入口](.agents/skills/slidethus/references/host-create.md)。

本轮仅落地职责边界和统一生成入口。完整生成包固化、新案例及真实 PowerPoint 美学验收由用户后续推进；候选文件不代表发布通过。执行记录见 [本轮收敛计划](plans/host-design-entry-stabilization.md)。

### 1. 解压并进入项目

```bash
cd Slidethus
```

### 2. 建立环境

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

只安装运行时多格式摄取能力时可使用：

```bash
python -m pip install -e '.[ingestion]'
```

基础安装仍只包含确定性核心、JSON Schema 与 `python-pptx`；PDF、DOCX、XLSX 和图片适配器缺少可选依赖时会返回明确的 `SourceCapabilityError`，不会伪装成解析成功。

### 3. 验证基础包

```bash
slidethus doctor
python -m pytest
python scripts/validate_all.py
python scripts/audit_package.py
```

或：

```bash
make verify
```

### 4. 查看最小示例

```bash
slidethus validate examples/minimal_project
slidethus status examples/minimal_project
slidethus artifact list examples/minimal_project
slidethus artifact show examples/minimal_project project_brief
slidethus artifact validate examples/minimal_project
slidethus artifact migrate examples/minimal_project --dry-run
slidethus artifact recover examples/minimal_project
slidethus render-wireframe examples/minimal_project
```

灰模会输出到：

```text
examples/minimal_project/outputs/wireframes/
```

### 5. 独立摄取并检查来源快照

```bash
slidethus init /tmp/slidethus-source --title "来源摄取"
slidethus source ingest /tmp/slidethus-source examples/mvp-input.md \
  --source-id SRC-001 \
  --allowed-use internal_only
slidethus source show /tmp/slidethus-source SRC-001
slidethus validate /tmp/slidethus-source --check-hashes
```

生产摄取会把解析正文写入 `.slidethus/cache/ingestion/` 的不可变快照，并在 Source Ledger 中记录 parser、格式、限额、快照哈希与风险计数。重复执行不会增加 artifact 版本；修改来源权限策略会版本化 Ledger；修改来源字节、parser 版本或解析限额会生成新快照。

当前 Production adapters：

| 格式 | 主要 locator / 结果 | 能力边界 |
|---|---|---|
| Markdown/TXT | 标题、段落、行号/字符范围 | 完整文本解析 |
| HTML | title、语义元素、表格行、图片 alt | script/style/template 不执行；链接只保留不打开 |
| CSV/TSV | 逻辑行与物理行范围 | 公式样式文本只记录风险，不计算 |
| PDF | 页码 | 只提取文本；无文本页、表单/批注触发 `partial`，不 OCR |
| DOCX | 段落、表格、页眉页脚、文本框、图片 alt | 图片、评论、脚注/尾注、公式等遗漏触发 `partial` |
| PPTX | 幻灯片、形状、表格、图表、备注、图片元数据 | 图片/SmartArt/音视频等不解释并触发 `partial` |
| XLSX | 工作表、行、单元格坐标 | 不计算公式；评论、图表、媒体触发 `partial` |
| PNG/JPEG/GIF/WebP/BMP/TIFF/ICO | 尺寸、格式、帧、有限 EXIF 文本 | 始终为元数据级 `partial`，不 OCR/视觉理解 |

宏启用 OOXML、加密 PDF、旧版 OLE Office、SVG 和其他没有 admitted adapter 的格式继续 fail closed。OOXML 在库打开前验证 ZIP 条目、单成员/总展开大小、重名、路径穿越、symlink、加密、VBA、外部关系和嵌入对象。

### 5.1 规划和检查 Research Runtime

```bash
slidethus research plan <workspace> orientation
slidethus research plan <workspace> targeted --slide-id S-003
slidethus research list <workspace>
slidethus research show <workspace> RRN-XXXXXXXXXXXXXXXX
slidethus research invalidate <workspace> RRN-XXXXXXXXXXXXXXXX \
  --query-id RQ-001 --reason "source or freshness changed"
```

这些命令负责 deterministic plan 和运行时 lineage 检查/失效，不内置具体 Web 搜索供应商。Research Result 只有在来源物化和 Evidence 裁决后才可进入事实链。

### 5.2 物化并裁决 Production Evidence

```bash
# 把一个已摄取 Source 的 Chunks 转为保守 Evidence Candidates 并裁决
slidethus evidence source <workspace> SRC-001 \
  --freshness-cutoff 2026-08-01

# 修复 Source 更新后失效的 Production Evidence，不添加新 Candidate
slidethus evidence reconcile <workspace> \
  --freshness-cutoff 2026-08-01

# 把 complete Research Run 先物化为 partial Web Sources，再裁决并完成 semantic cycle
slidethus evidence research <workspace> RRN-XXXXXXXXXXXXXXXX \
  --freshness-cutoff 2026-08-01

slidethus evidence show <workspace>
slidethus evidence show <workspace> EVD-001
slidethus gate <workspace> G2
```

Production Evidence 绑定 `source_id + locator + chunk_id + content_hash`，并记录 Candidate/Research/conflict/freshness/authority lineage。Provider summary 未抓取远程正文时只能得到 provisional/qualified Evidence；本地 Source 与 Research summary 都执行 Source-risk 扫描。high-risk promotion 需要 `--allow-high-risk-source-evidence`，即使显式允许也保持 qualified。Source 更新会使旧 Evidence draft 并阻断 G2，直到 reconcile 或重新裁决。

### 5.3 检查页面/Block Evidence gap 并返工

```bash
slidethus evidence gaps <workspace>
slidethus evidence targeted-plan <workspace>
slidethus evidence complete-user-targeted <workspace>
slidethus evidence rework <workspace> --reason "required block proof is missing"
slidethus gate <workspace> G5A
```

Gap Report 绑定当前 Brief、Source、Evidence、Outline 和 Slide Specs 版本；required factual block 必须使用已知、可用 Evidence，qualified support 必须有显式 qualification。外部研究关闭且用户材料已覆盖全部缺口时，可用 `complete-user-targeted` 完成 query_count=0 的 targeted review；Web/Research Run lineage 仍必须走 M2.4 Evidence Engine。

### 5.4 使用集成 M2 Application 边界

```bash
# 本地用户材料：从 resolved Brief + Sources 推进到 G2，并重验证已有 planning artifacts
slidethus m2 run <workspace> --source <file> [--source <file> ...]

# Brief 要求外部研究但当前 CLI 无 provider 时，只有显式接受且无 freshness 要求才允许 D3
slidethus m2 run <workspace> --source <file> --allow-research-degraded

slidethus m2 list <workspace>
slidethus m2 show <workspace> M2R-XXXXXXXXXXXXXXXX
slidethus m2 gate <workspace>
```

CLI 故意不内置在线 ResearchProvider。Python 调用方可注入 provider，但实际执行还需要独立 external-disclosure approval。high-severity Source 默认只进入 inventory，不自动提升为 Evidence；应用同时检查 requested/current/final Source 与 Research budgets。每次运行生成 `.slidethus/m2/runs/` 下的不可变 M2 Application Report，并在 `.slidethus/m2/research-runs/` 固化所引用的 Research Run/cache lineage；这些都是工作区操作事实，不是 Delivery Manifest，也不能单独作为 M4/M5 完成证据。

### 5.5 使用集成 M3 Planning 边界

```bash
# 从一句话需求和本地 Sources 推进到经审计的 P5B Layout/wireframes
slidethus m3 run <workspace> \
  --source <file> \
  --request "给管理层做一份 10 页方案汇报，推动立项决策"

# Brief 返回 needs_input 时，回答材料性问题并恢复
slidethus m3 answer <workspace> Q-903 "企业管理层"

slidethus m3 list <workspace>
slidethus m3 show <workspace> M3R-XXXXXXXXXXXXXXXX
slidethus m3 gate <workspace>
```

M3 CLI 使用内置 DeterministicPlanningProvider，提供离线、provider-neutral 的 Production contract baseline；它不内置 LLM SDK，也不声称等价于通用模型的受众洞察。运行链会生成 current Narrative、stable `S-*` Outline、Evidence-qualified `BLK-*` Slide Specs、stable `REG-*` Layout、content-addressed wireframes、`PRV-*` Planning Review，并在准入时生成 `PCH-*` Change / `PRP-*` Repair facts。`M3 Application Report` 记录最终 P0/P2/P3/P4/P5A/P5B 层级，不能把部分失败或灰模冒充最终设计。

### 6. 从已支持来源格式生成真实 PPTX

```bash
slidethus mvp /tmp/slidethus-demo \
  --source examples/mvp-input.md \
  --title "Slidethus 纵向 MVP" \
  --max-slides 6 \
  --require-preview
```

主要输出：

```text
/tmp/slidethus-demo/outputs/planning-wireframes/*.svg
/tmp/slidethus-demo/outputs/debug/layout-diagnostics.json
/tmp/slidethus-demo/outputs/debug/*-debug.pptx
/tmp/slidethus-demo/outputs/debug-office-previews/*.png
/tmp/slidethus-demo/outputs/final/design-previews/*.svg
/tmp/slidethus-demo/outputs/final/*-final.pptx
/tmp/slidethus-demo/outputs/final-office-previews/*.png
```

`--require-preview` 会在调试稿或最终稿缺少 LibreOffice/Poppler 独立预览时阻止 G8/G9；不加时仍保留已经生成的制品，但状态为 degraded，绝不冒充完整验收通过。

MVP0 命令当前要求目标 workspace 为空；Artifact Runtime 的事务恢复仍然生效，但应用级断点续跑属于后续 ProductionImpl。

### 7. 用 Codex 接手

从仓库根目录启动 Codex，然后粘贴 `CODEX_KICKOFF.md` 中的指令。Codex 会自动读取根目录 `AGENTS.md`，并能发现 `.agents/skills/slidethus/SKILL.md`。

## 推荐阅读顺序

1. `SLIDETHUS_FOUNDATION_PLAN.md`
2. `AGENTS.md`
3. `CODEX_KICKOFF.md`
4. `docs/00-product-charter.md`
5. `docs/01-source-to-design-trace.md`
6. `docs/02-architecture.md`
7. `docs/03-workflow-state-machine.md`
8. `docs/04-artifact-contracts.md`
9. `docs/05-quality-system.md`
10. `TASKS.md`
11. `audit/final-audit-summary.md`

## 项目目录

```text
SLIDETHUS_FOUNDATION_PLAN.md  总体详细方案
.agents/skills/using-slidethus/ 总入口
.agents/skills/slidethus-*/  七个阶段子技能
.agents/skills/slidethus/    兼容入口与共享工作流、参考、Taste、脚本
src/slidethus/              确定性核心与 CLI
schemas/                    结构化中间产物合同
examples/minimal_project/   可验证的最小项目
workflows/                  开发者视角的工作流说明
prompts/                    来源保留与生产提示词合同
source_material/            原素材、拆解和来源边界
renderers/                  后续 SVG/PPTX 后端边界
quality/                    Gate、审计维度和缺陷分类
scripts/                    校验、审计和演示脚本
tests/                      单元与合同测试
evals/                      Agentic Skill 评测场景
audit/                      本包审计记录与完整性清单
```

## 版本定位

- 包版本：`0.8.1`
- 成熟度：0.x 能力发布；M6.6 / v1.0 验收仍未完成
- 本轮验证：单一 Python 3.11；不做多 Python 版本审计，不把历史兼容矩阵当作本轮验证结果
- 默认语言：中文
- 逻辑画布：`1280 × 720`
- 设计型 Create 候选渲染：宿主提供的 Artifact Tool；Legacy Hybrid 保留为显式工程基线，不自动替代已确认设计
- 项目许可证：Apache-2.0；`source_material/`、用户输入、第三方依赖/素材/字体/模型输出不因项目主许可证自动获得再许可，详见 `NOTICE.md`、`THIRD_PARTY_NOTICES.md` 与 `release/rights-policy.json`

## 下一步

用后续真实任务继续检验样板到全篇的风格贯穿、图表与图片策划；扩大行业/场景验证仍列后续待办，不作为 v0.8.1 的追加范围。v1.0 按 [最后优化与重新发布计划](plans/M6.6-final-optimization-and-rerelease.md) 单独验收，其 Release Gate 继续保持 `DO NOT RELEASE`。
