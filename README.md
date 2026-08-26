# Slidethus v0.4.0 — Complete Action-Chain MVP

> 面向通用 Agentic Host 的 **Agentic Presentation Engineering Skill**：从本地文本依次产出策划稿、布局诊断、调试稿、设计稿和最终可编辑 PPTX。

## 这是什么

Slidethus 不是“输入标题后套模板”的 PPT 生成器，而是一套把专业演示文稿工作拆成可执行阶段、可验证中间产物和可回退质量门槛的 Agentic Skill 工程。

当前版本已经提供：

- 可被 Codex 自动发现的仓库级 Skill：`.agents/skills/slidethus/`；
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
- 用户来源限定的行号 evidence，以及规则式 Narrative/Outline/Slide Specs/Layout/Visual System MinimalImpl；
- 独立的策划灰模、布局诊断和带 Region/Block 映射的调试性 PPTX；
- 消费 Layout Plans 与 Visual System 的 Minimal DesignImpl 和设计预览；
- 基于 `python-pptx` 的最终原生文本/简单形状 PPTX，实测编辑等级 E3；
- 调试稿与最终稿分别经过 LibreOffice + Poppler 独立预览；
- `Render Manifest.pipeline_stages` 记录七个动作及其独立输出；
- `slidethus mvp` 从单个用户文件贯通 G0–G9，缺少任一步骤不能冒充完整 MVP；
- 一个完整的最小示例项目；
- 五轮独立审计记录、自动审计脚本和 SHA-256 清单；
- 用户提供的 PPT Agent 素材、原始提示词和来源边界说明。

## 这不是什么

当前包已经完成 **M0 Foundation Contract**、**M1 Artifact Runtime**、**MVP0 Planning Proof**、跨 M2–M5 的 **MVP1 完整动作链**，以及 M2 的首个子模块 **M2.1 Ingestion Core**，但不是生产级端到端 PPT 产品。以下能力仍未完成：

- LLM/搜索/图片生成服务的真实适配；
- PDF/DOCX/PPTX/图片/表格等多格式摄取；
- LLM 驱动的受众化叙事与页面策划；
- 最终视觉 SVG 生成和复杂视觉资产；
- PptxGenJS 原生/混合 PPTX 渲染；
- 视觉模型驱动的自动审计与局部修复；
- GUI、云端服务、多租户和商业化能力。

MVP1 的规则式 MinimalImpl 只使用用户提供的 Markdown/TXT，并明确声明 D3、E3 和所有限制。它证明每个基本动作都有独立产物与验收，不代表 M2–M5 的完整 Exit Gate 或生产级设计质量已完成。

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

### 3. 验证基础包

```bash
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

当前 admitted adapter 仅支持 Markdown/TXT。CSV、HTML、PDF、DOCX、PPTX、XLSX 和图片会在 M2.2 适配器完成前显式返回 unsupported。

### 6. 从 Markdown/TXT 生成真实 PPTX

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
.agents/skills/slidethus/   Codex/ChatGPT 可发现的 Skill
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

- 包版本：`0.4.0`
- 成熟度：MVP1 Complete Action Chain + M2.1 Ingestion Core（M2.2–M2.7 与 M3–M5 仍未完整）
- 默认语言：中文
- 逻辑画布：`1280 × 720`
- 推荐最终渲染：Hybrid（原生文本/形状 + SVG/图片复杂视觉）
- 项目许可证：尚未决定；第三方素材不自动纳入未来项目许可证

## 下一步

下一步是 **M2.2 Multi-format Adapters**：在同一 Parser Registry、快照和失败语义下实现 HTML、PDF、DOCX、PPTX、CSV/XLSX 与图片元数据适配器。后续能力继续逐个用 ProductionImpl 替换当前 MinimalImpl，不改变 Artifact Runtime、语义 Schema 或 Gate 标准。
