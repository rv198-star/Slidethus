# M6 — Productization and Distribution

## 1. Objective

- 用户价值：把 M2–M5 已冻结的 Production 能力从“可被工程调用”提升为“多个用户工作流可稳定进入、可观测、可分发、可评测、可发布”的产品化边界。
- 本轮边界：Multi-workflow Runtime、运行可观测性/缓存/预算/并发控制、Plugin/sidecar 打包、示例/评测/兼容矩阵、许可证与第三方资产策略、v1.0 Release Gate。
- 明确不做：重写 M2–M5 的 Source/Evidence/Planning/Renderer/Review truth；把产品化状态塞进这些 frozen artifacts；捆绑未经许可的字体/素材；把特定在线模型供应商写死为核心依赖。
- 退出条件：M6.1–M6.6 全部完成；六个 Workflow 均有真实 runtime 行为或明确 capability block；运行控制可审计；Plugin/sidecar 可重复构建；许可/第三方策略可执行；示例/评测/兼容矩阵可复核；v1.0 Release Gate 无开放 Critical/Major；M2–M5 Exit 保持 PASS。

## 2. Current state

- 当前稳定点：`main` at `0a563c3859030f1bf9e1b7c4d67adc505f1efea2`，M5 已推送，working tree clean。
- 已存在能力：M2 Source/Research/Evidence、M3 Planning、M4 Rendering、M5 Review/Repair；Skill 已声明 Create/Rebuild/Improve/Audit/Revise/Extract Style 六类 Workflow，但当前尚无统一 Production Workflow Runtime/CLI 报告层。
- 已知产品化缺口：workflow dispatch 与运行事实、统一 capability/mutation policy、跨 workflow observability/预算/锁、Node sidecar 安装策略、Plugin 构建、许可证/第三方政策、兼容矩阵与最终 release gate。
- 验证基线：Python 3.11 + Node 22；M2 12/12、M3 13/13、M4 15/15、M5 16/16、Node 4/4、Package Audit 21/21。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-601 | Decision | M6 使用单一 Workflow Application boundary；六个 Workflow 不各建私有状态机。 | 单主编排器、降低产品漂移 | 高 |
| D-602 | Decision | Workflow runtime 只编排 M2–M5 services/artifacts；不产生 Evidence/Narrative/Layout/Render/Review 的第二真相源。 | frozen Production boundaries | 高 |
| D-603 | Decision | Audit 默认 read/review-only；允许写 immutable review/runtime facts，但禁止语义/渲染自动 repair。 | Audit no hidden edits | 高 |
| D-604 | Decision | Improve/Revise 的自动修改必须通过已有 Change/Repair admission；无法证明最小影响时明确 blocked/assisted。 | 根因修复、最小影响 | 高 |
| D-605 | Decision | Rebuild 保留原始输入只读，并在新 workspace 中重建；不覆盖原 deck。 | provenance、安全 | 高 |
| D-606 | Decision | Extract Style 输出 Visual System 候选与来源/权利事实；不自动复制未授权字体/品牌资产。 | rights/provenance | 高 |
| D-607 | Decision | M6 正式冻结基线使用 Python 3.11 + Node 22；不为每个子模块重复跑多个 Python minor。 | M5 收尾经验 | 高 |
| D-608 | Decision | Plugin/sidecar bootstrap 属于 M6 分发层；M4 renderer contract 继续保持独立。 | ADR-0019 | 高 |
| A-601 | Assumption | 通用自然语言 Improve/Revise/Style 智能可能依赖注入 provider；缺 provider 时必须返回真实 capability boundary，而不是伪造改动。 | provider neutrality | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| M6.1 | Multi-workflow Runtime：Create/Rebuild/Improve/Audit/Revise/Extract Style 统一 request/run/report、dispatcher、CLI、capability/mutation policy | M2–M5 frozen | six-workflow positive/blocked/negative controls | complete |
| M6.2 | Operational Controls：structured events、run metrics、cache policy、cost/resource budgets、workspace concurrency/lease/recovery | M6.1 | interruption/concurrency/budget/cache tests | complete |
| M6.3 | Plugin Packaging：installable Plugin bundle、schema/skill/workflow packaging、Node sidecar bootstrap/version verification | M6.1–M6.2 | clean install/build/supply-chain tests | complete |
| M6.4 | Examples & Evaluation：workflow examples、golden/eval corpus、compatibility matrix、release docs | M6.1–M6.3 | executable examples + regression corpus | complete |
| M6.5 | License & Third-party Policy：project license、dependency/asset/font/model policy、NOTICE/SBOM boundaries | M6.3–M6.4 | package/license audit | complete |
| M6.6 | v1.0 Preview Hardening & Release Gate：完整 Production Attempt 后的 retrospective Stage AI Review、whole-attempt Review Synthesis/归因、systemic repair promotion、Round A/B、release validator、artifact/package reproducibility、handoff | M6.1–M6.5 | same-case preview regression + abstract-repair audit + Python 3.11 + Node 22 + M2–M5 regression + package/release audit | in_progress |

## 5. M6.1 contract

统一 Workflow Runtime 的职责：

```text
WorkflowRequest
  → WorkflowAdmission
  → WorkflowApplicationService
      → frozen M2/M3/M4/M5 services
  → immutable Workflow Application Report
```

六类 Workflow：

- **Create**：新 workspace + sources/brief → M3 → M4 → M5；缺 review provider 时停在明确 capability boundary。
- **Rebuild**：既有 PPTX/PDF/图片作为只读 Source，在新 workspace 重新建立语义/规划/视觉输出；原文件永不覆盖。
- **Audit**：对已有 DRAFT_RENDERED+ workspace 执行 M5，`auto_repair=False`；允许新增 review facts，不改变 semantic/render artifacts。
- **Improve**：先 Audit，再仅执行 M5/Change contract 已准入的修复；其余问题返回 Repair Plan/assisted route。
- **Revise Slide**：结构化 target slide patch → existing Outline Change / dependent regeneration / M5 regression；stable IDs 和 history 保留。
- **Extract Style**：从支持的 reference deck/Visual System 建立 style candidate；schema、font、rights admission 后才能写入目标 workspace。

## 6. Quality and risk controls

- Workflow report 必须绑定 workflow type、request hash、workspace/project state、input refs、mutation policy、capabilities、actions、outputs、final Gate/status。
- `audit` 运行前后 semantic/render artifact versions/hashes 必须保持一致。
- `rebuild` 输出目录不得与原始输入同路径；原文件 hash 前后必须一致。
- `revise` 只允许显式 target slides；任何传播变化必须在 report 中列出。
- `extract_style` 不复制 font bytes 或第三方 asset bytes；只记录可验证 token/fallback/source refs。
- 所有 workflow runtime path 约束在 `.slidethus/workflows/`。

## 7. Verification

```bash
python -m compileall -q src tests scripts
ruff check src tests scripts
pytest tests/test_workflow_application.py
python scripts/validate_m2_exit.py
python scripts/validate_m3_exit.py
python scripts/validate_m4_exit.py
python scripts/validate_m5_exit.py
npm test --prefix renderers/pptxgenjs
python scripts/audit_package.py
git diff --check
```

- M6 子模块按单一 Python 3.11 + Node 22 正式环境冻结；必要时只增加发布级兼容矩阵，不做每层重复双 Python。

## 8. Review

### Round A

- M6.1–M6.6 每段先执行无评分 Open Issue Mining。
- Critical/Major 根修前不进入对应 Round B。

### Round B

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| workflow correctness |  |  |  |
| frozen-boundary integrity |  |  |  |
| operational reliability |  |  |  |
| distribution reproducibility |  |  |  |
| rights/supply-chain truthfulness |  |  |  |
| maintainability |  |  |  |

## 9. Final outcome

- 已完成：M6.1 Multi-workflow Runtime、M6.2 Operational Controls、M6.3 Plugin Packaging、M6.4 Examples & Evaluation、M6.5 License & Third-party Policy 均已通过 Round A/B Submodule Gate。
- M6.6：Round 4 的五个 systemic candidates 与 Round 5 新归因的 headline closure / planning text-capacity candidates 均完成抽象根修和 unrelated regression；未修改冻结 Source/Brief 或 case-local title。
- Round 6：`WFR-928E28C10F896F5C` 到达 `DRAFT_RENDERED`，生成 8 页 SVG/PNG/PDF/Native PPTX/Hybrid PPTX；仅在缺少外部 `SemanticReviewProvider` 的声明边界停止。
- Retrospective：九阶段 SAR 与 `SYN-E17A689D3096E148` 无 Critical/Major systemic candidate；仅保留 case-local Major title identity 与 non-promotable Minor mixed-script wrap。
- M6 Exit Gate：REOPENED（2026-08-30）。v1.0 Release Gate：DO NOT RELEASE；Round 7 已生成真实 Office 评审候选，等待用户视觉评审。
- 相关 ADR：增加 `docs/adr/ADR-0027-office-visual-quality-release-gate.md`。
- 相关 ADR：`docs/adr/ADR-0021-workflow-productization-boundary.md`、`docs/adr/ADR-0022-workflow-operational-controls.md`、`docs/adr/ADR-0023-plugin-and-renderer-distribution.md`、`docs/adr/ADR-0024-evaluation-and-compatibility-corpus.md`、`docs/adr/ADR-0025-license-rights-and-sbom-boundary.md`。
