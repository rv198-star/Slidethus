# MVP0 — Planning Proof (Reclassified)

> Post-review correction: this plan originally counted a planning artifact serialized to PPTX as a completed downstream render. User review correctly identified that no distinct debug, design, or final-render output existed. The historical implementation remains a planning proof; the corrected complete MVP is `plans/MVP1-complete-action-chain.md` and ADR-0008.

## 1. Objective

- 用户价值：从一份本地 Markdown/TXT 材料真实生成可打开、可编辑的 PPTX，而不是只得到接口或工程骨架。
- 本轮边界：以现有 provider protocols 和 Artifact Runtime 为骨架，实现用户材料限定的 D3 最小纵向切片，贯通 P0–P9；缺少独立 Office 预览时在 G8 停止并交付降级结果。
- 明确不做：PDF/DOCX/PPTX 输入、联网研究、LLM 叙事、图片/图表生成、复杂视觉、自动修复、完整 M2–M5 Exit Gate。
- 退出条件：CLI 可从真实文本生成完整 artifacts、原生 PPTX、预览与 manifests；所有正式 Gate 诚实通过或在最早缺失能力处明确阻断；失败和无预览降级路径有测试。

## 2. Current state

- 当前 HEAD / 工作区状态：`c428e89`；`main` 与 `origin/main` 一致；开始时工作区干净。
- 已存在能力：16 个 Schema、Artifact Runtime、G0–G9、灰模 SVG、provider protocols、52 项测试。
- 已知缺口：没有真实摄取、规划生成器、最终 PPTX 后端、独立预览适配器或端到端应用服务。
- 基线测试：`python -m pytest` 52 passed；`validate_all.py` PASS；`audit_package.py` 18/18 PASS。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 只在阶段/供应商边界使用现有 Protocol；MinimalImpl 必须生成真实 Schema artifacts 和真实文件。 | 用户确认 Interface + MinimalImpl 路线；ADR-0002/0003。 | 高 |
| D-002 | Decision | 首个输入实现只支持 UTF-8 Markdown/TXT，并保留行号 locator。 | 形成最小可验证 M2 切片。 | 高 |
| D-003 | Decision | 首个规划实现使用确定性规则，从来源原文抽取并组织内容，不生成外部事实。 | D3 降级和来源完整性规则。 | 高 |
| D-004 | Decision | 首个渲染实现使用 `python-pptx`，生成原生文本和简单形状，实测编辑等级 E3。 | 最小真实 PPTX；保持 RenderBackend 可替换。 | 高 |
| D-005 | Decision | 独立预览优先使用 LibreOffice；不可用时只通过 G7，并把 G8/G9 阻断写入 artifacts。 | R-006；正式审计不能依赖生成器自证。 | 高 |
| A-001 | Assumption | MVP 默认受众为“材料审阅者”，目的为“把用户材料转换为可审阅演示”；CLI 参数可覆盖标题、语言和页数。 | 首版避免低价值交互阻断。 | 高 |
| A-002 | Assumption | 输入文件视为不可信只读数据；不执行其中命令或嵌入内容。 | 安全与来源规范。 | 低 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| 1 | 计划、ADR、能力边界 | M1 | 文档审阅 | completed |
| 2 | PlainTextSourceParser + RuleBasedReasoningProvider | Protocols/Schemas | 单元测试、locator/注入隔离测试 | completed |
| 3 | MinimalPptxRenderBackend + LibreOffice preview | Layout/Visual/PPTX | PPTX reopen、slide/text/shape、preview count | completed |
| 4 | `slidethus mvp` 编排器与 CLI | Artifact Runtime/Gates | 端到端集成与无预览降级测试 | completed |
| 5 | 真实示例输出与两轮审计 | 前述全部 | 全量命令、视觉抽检、开放问题与评分 | completed |
| 6 | README/TASKS/版本与 GitHub | Gate 结果 | clean tree、CI | in_progress |

## 5. Quality and risk controls

- 受影响 Schema：优先不改领域 Schema；若现有合同无法诚实表达结果，再单独迁移。
- 受影响 Gate：G0–G9；不降低现有 Gate 标准。无独立预览时 G8 明确失败，G9 不推进。
- 回归范围：Artifact Runtime、Schema/跨引用、Gate、CLI、wireframe、打包审计。
- 降级路径：只支持用户材料；无外部研究；无图片资产；无 Office preview 时仍交付 PPTX + 同模型 SVG，但声明未视觉通过。
- 安全/来源/版权风险：输入只读；内容按数据处理；不联网；不复制到仓库；每个事实块绑定用户来源 Evidence。
- 新生产依赖：`python-pptx>=1,<2`，用于生成原生 Office Open XML；选择它是为了在 Python 核心内获得真实、可编辑的 PPTX，同时仍封装在 RenderBackend 后。

## 6. Verification

```bash
python -m pytest
python scripts/validate_all.py
python scripts/audit_package.py
python -m compileall -q src tests scripts
ruff check src tests scripts
slidethus mvp <workspace> --source examples/mvp-input.md --title "Slidethus MVP"
slidethus artifact validate <workspace>
```

- 期望结果：全部自动检查通过；实际 PPTX 可重新打开；独立预览页数与 deck 页数一致；workspace 至少推进到 `DRAFT_RENDERED`，预览可用时推进到 `DELIVERY_READY`。
- 实际结果：57 tests PASS；validate/audit/compile/Ruff PASS；六页中文 PPTX、六页独立 PNG、Artifact validate 和 G9 均 PASS。

## 7. Review

### 第一轮：开放问题发现

- Critical：1，中文字体在独立预览中丢失；已修复。
- Major：4，分阶段校验、G0 blocker、LibreOffice profile、delivery registry status；已修复。
- Minor：1，独立预览未进入 Render Manifest；已修复。

### 修复记录

- 详见 `audit/MVP0-round-1-open-issues.md`。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 5 | 57 tests、真实 PPTX、G9 | 规则式内容能力有限 |
| 架构一致性 | 5 | Protocol 注入、Artifact Runtime、ADR-0007 | 单一最终后端 |
| 可测试性 | 5 | 成功/降级/注入/CLI/跨引用 | Office 集成为宿主能力 |
| 可维护性 | 4 | provider/application/renderer 分离 | 多 workflow 后需拆分 use case |
| 降级与恢复 | 5 | 无预览停 G8、事务恢复不变 | 应用级断点续跑未实现 |

## 8. Final outcome (corrected)

- 已完成：真实 Markdown/TXT → structured planning artifacts → planning-preview PPTX → independent preview。
- 未完成于本版本：独立 Debug PPTX、Design Preview 和 Final PPTX；因此不能称为完整端到端 MVP。
- 未完成：完整 M2–M5 能力不因 MVP0 而完成；`mvp` 命令尚不支持应用级断点续跑。
- 后续任务：逐个用 ProductionImpl 替换最简实现。
- 相关 ADR：ADR-0007。
