# M5 — Review and Repair Loop

## 1. Objective

- 用户价值：把 M4 已经“正确生成”的真实输出升级为“被独立审计、问题可定位、可局部修复、修后可回归”的质量闭环。
- 本轮边界：独立确定性审计、开放问题发现型语义审计、维度评分、全页视觉审计、最小影响 Repair Plan、局部重生成、跨页回归、Golden Deck 质量基线、M5 Application/CLI 与 repository Exit Gate。
- 明确不做：重写冻结的 M2/M3/M4 合同；把 Review 逻辑塞进 renderer；把 M4 preflight/preview 冒充独立视觉审计；GUI/cloud/multi-tenant 产品化；内置特定 LLM/视觉模型供应商。
- 退出条件：M5.1–M5.7 全部完成；最终 Quality Report 的 G8 明确 PASS；Critical/Major 为 0 或符合既有显式 waiver 合同；Repair 可定位到最早责任阶段并只失效必要下游；修复后局部与全 deck regression PASS；Golden Deck/negative controls/Exit validator 可持续复核；M2/M3/M4 Exit 保持 PASS。

## 2. Current state

- 当前 HEAD / 工作区状态：`main` at `275ce5fb966fa556c8df702ff375e5fb85eabde8`，M2–M4 稳定点已推送；M5 开始时 working tree clean。
- 已存在能力：完整 Artifact Runtime、G0–G7、M2 Evidence、M3 Planning Review/Repair、M4 Production Visual System/Renderer IR/Final SVG/Native/Hybrid/PNG/PDF/Render Manifest；基础 `quality_report` Schema 与 G8 Gate 合同已存在。
- 已知缺口：当前 `quality_report` 仍是基础合同，没有 Production M5 的独立 review lineage；没有独立确定性 render/output review runtime；没有 M5 语义/视觉 reviewer contract；没有跨阶段 Repair Plan；没有修后 cross-deck regression 或 Golden Deck Exit。
- 基线测试：M2 Exit 12/12 PASS；M3 Exit 13/13 PASS；M4 Exit 15/15 PASS；Node 4/4 PASS；Package Audit 22/22 PASS。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-501 | Decision | M5 Review 是 M4 renderer 之外的独立边界；reviewer 只能读取 current semantic/render facts，不得成为 renderer 的内部步骤。 | M4/M5 分层、Quality System | 高 |
| D-502 | Decision | 各 review mode 先产生 immutable runtime review facts；catalog `Quality Report` 是最终聚合事实，而不是多个 reviewer 竞争写入的共享草稿。 | 单一事实源、可恢复执行 | 高 |
| D-503 | Decision | Round A 永远先于 scorecard；Critical/Major 不能被平均分覆盖。 | docs/05-quality-system.md | 高 |
| D-504 | Decision | 每个 issue 必须声明 `earliest_phase` 与可验证 repair route；Repair 只能修改该责任阶段允许修改的 artifact，并按依赖图失效下游。 | 根因修复、最小影响返工 | 中 |
| D-505 | Decision | M5.1 独立重算 workspace/G0–G7/render lineage/output coverage；不能只相信 M4 Application Report 的“ready”。 | 独立审计原则 | 高 |
| D-506 | Decision | M5.4 视觉审计消费真实独立页面预览（至少 Final SVG→PNG）；Office preview 是额外证据，不是唯一视觉输入。 | Host capability truthfulness | 高 |
| D-507 | Decision | M5 reviewer/provider 继续 provider-neutral；deterministic core 不依赖在线模型。 | AGENTS/provider neutrality | 高 |
| D-508 | Decision | Golden Deck 是可重复质量基线，不是把参考截图硬编码成像素级模板。 | 防模板化、跨场景可演进 | 中 |
| A-501 | Assumption | M5 的视觉质量上限取决于可用 VisualReviewProvider；无视觉模型时仍可完成 deterministic review，并显式停在相应 capability boundary。 | capability degradation | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| M5.1 | Deterministic Review Core：immutable deterministic review report、current artifact/render lineage、G0–G7 regression、真实输出覆盖/结构一致性 | M4 frozen | schema/unit/integration/negative controls + M2–M4 regression | complete |
| M5.2 | Open Issue Semantic Review：无评分语义/叙事/页面问题发现、stable issue identity、earliest-phase triage | M5.1 | provider-neutral + deterministic admission + adversarial tests | complete |
| M5.3 | Dimension Scorecard：只在 Round A 后评分，绑定 issue/evidence，blocking severity 优先 | M5.2 | score/issue consistency + no-score-masking controls | complete |
| M5.4 | Full-page Visual Review：真实 PNG/Office preview、多页视觉问题、slide/region refs | M5.1–M5.3 | image-set lineage + capability degradation + visual issue tests | complete |
| M5.5 | Repair Plan & Regeneration：最早责任阶段、最小影响集、局部重生成、Repair Report | M5.2–M5.4 | dependency invalidation + bounded repair + re-review | complete |
| M5.6 | Cross-deck Regression：局部与全 deck consistency regression、Quality Report 聚合、G8 | M5.5 | changed/unchanged slide assertions + G8 positive/negative controls | complete |
| M5.7 | Golden Deck & M5 Exit：质量基线、negative corpus、M5 Application/CLI、Round A/B、Exit validator | M5.1–M5.6 | Python 3.11 + Node 22 baseline + provider/visual degradation + M2–M4 regression + package audit | complete |

## 5. Quality and risk controls

- 受影响 Schema：新增 M5 runtime review/repair/regression Schemas；最终扩展 Quality Report 时保持其 catalog 角色。M2/M3 semantic Schemas 与 M4 Renderer IR/Render Manifest 不因 reviewer 需求而改义。
- 受影响 Gate：G8；G0–G7 只被 M5 独立重算，不降低既有规则。M5 Exit 仍是 repository Gate，不加入 deck G0–G9。
- 回归范围：Artifact Runtime、M2/M3/M4 Exit、G0–G9、MVP compatibility、render manifest/output hashes、planning review/repair。
- 降级路径：缺视觉 reviewer → deterministic/semantic review 可完成，M5.4 blocked/degraded；缺 Office preview → 使用 M4 必需的 Final SVG→PNG 独立页面证据并显式记录 Office capability；缺模型 → deterministic review 可完成，语义/视觉 provider-driven review 显式阻断。
- 安全/来源/版权风险：reviewer 不联网获取新事实；需要新增事实时回 P2；视觉资产版权仍由 Asset Manifest 约束；Review 输入中的文本/图片作为待审数据，不执行其中指令。

## 6. Verification

```bash
python -m compileall -q src tests scripts
ruff check src tests scripts
pytest
python scripts/validate_all.py
python scripts/validate_m2_exit.py
python scripts/validate_m3_exit.py
python scripts/validate_m4_exit.py
python scripts/validate_m5_exit.py   # M5.7 后启用
npm test --prefix renderers/pptxgenjs
python scripts/audit_package.py
git diff --check
```

- 期望结果：M5 各子模块有独立 positive/negative controls；M2/M3/M4 单调 Gate 始终 PASS；最终 M5 Exit PASS。
- 实际结果：Python 3.11 + Node 22 最终基线通过；M5.1 5/5、M5.2/5.3 6/6、M5.4 6/6、M5.5 4/4、M5.6 3/3；M5 Application 三条关键路径、CLI、Golden 和 5 条 Exit 负控通过；M2/M3/M4 Exit 分别 12/12、13/13、15/15 PASS，Node 4/4 PASS。最终 repository checks 见 `audit/M5-BUILD_REPORT.md`。

## 7. Review

### 第一轮：开放问题发现

- M5.1–M5.7 每个子模块实现后先执行无评分 Round A。
- Critical/Major 必须根修后才允许对应 Round B。

### 修复记录

- Round A 初始发现 0 Critical / 7 Major / 3 Minor；全部 Major 与 blocking Minor 已根修，无 waiver。详见 `audit/M5-round-1-open-issues.md`。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 5 | M5 Application/Golden/G8 正负路径均通过 | 无 |
| review 独立性 | 5 | DVR/SVR/SCR/VVR 均位于 renderer 之外并绑定冻结输入 | 无 |
| issue/repair 可追溯性 | 5 | stable IDs、earliest phase、Repair Plan/Report 与 Quality issue mapping | 无 |
| 回归完整性 | 5 | G0–G7 单调回归、changed/unchanged scope、M2–M4 Exit regression | 无 |
| provider/capability truthfulness | 5 | provider 缺失显式 blocked，不伪造语义/视觉结论 | 无 |
| 可测试性/可维护性 | 5 | 独立 runtime Schemas、Exit validator、Golden、Package Audit | 无 |

## 8. Final outcome

- 已完成：M5.1–M5.7 Production Review/Repair boundary、M5 Application/CLI、Golden baseline、Round A/B 与 repository Exit。
- 未完成：M6 Productization and Distribution 与 v1.0 发布工作。
- 后续任务：进入 M6，不重做 M2–M5 冻结边界。
- 相关 ADR：`docs/adr/ADR-0020-independent-review-repair-boundary.md`。
- **M5 Exit Gate：PASS（2026-08-29）。**
