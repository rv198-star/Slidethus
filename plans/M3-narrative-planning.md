# M3 — Narrative and Planning Production Boundary

## 1. Objective

- 用户价值：把已经通过 M2 的 Brief、Source 与 Evidence 转换为可审阅、可操作、可局部返工的 Narrative、Deck Outline、Slide Specs、Layout Plans 与灰模；在进入最终视觉前完成“为什么讲、按什么顺序讲、每页讲什么、页面如何组织”的工程闭环。
- 本轮边界：Project Brief 智能补全/最少提问、provider-neutral Planning Proposal、Narrative Blueprint、数字便利贴 Outline 操作、Slide Specs、Layout Plans/灰模、确定性 planning quality audit、局部返工与依赖传播、M3 application/report/CLI、M3-wide Exit Gate。
- 明确不做：内置 LLM/搜索供应商、自动事实真伪判断、最终 Visual System、Production SVG/PPTX/Hybrid renderer、图片生成、视觉模型审计、M4–M5 自动修复。
- 退出条件：resolved Brief 可在不重复询问已知信息的情况下进入 G0；Production Narrative/Outline/Specs/Layout 均绑定当前上游 artifact 版本与哈希；Outline 支持增删、重排、拆分、合并、排除与冻结并保留稳定历史；事实性页面/Block 继续满足 M2 Evidence 约束；Layout 全覆盖、无 safe-area/碰撞/reading-order/映射错误；planning audit 无开放 Critical/Major；局部返工只改变最小受影响对象并正确失效下游；Python 3.11/3.12、workspace validation、M2 Exit、M3 Exit、Package Audit 与 diff check 全部 PASS。

## 2. Current state

- 当前 HEAD / 工作区状态：`main` at `077ec3b`，`origin/main` 同步；M2.2–M2.7 与当前 M3 工作将继续存在于尚未提交工作区，不能虚报 Git 稳定点。
- 已存在能力：M2 Exit Gate PASS；M3 Production Brief/Narrative/Outline/Specs/Layout、stable sticky-note operations、Planning Review/Repair、M3 Application/CLI 和 repository Exit validator 已落地。
- 已知缺口：M4 Production render backends 与 M5 independent visual review/repair 不属于本轮；真实 LLM PlanningProvider adapter 尚未接入。
- 基线测试：进入 M3 时 Python 3.11 `190 passed`；M3 聚焦实现/审计回归为 `58 passed`。最终双 Python/Package 结果见本计划 Verification 和 `audit/M3-BUILD_REPORT.md`。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-301 | Decision | M3 保持单一 `M3ApplicationService`；Brief、Narrative、Outline、Specs、Layout、Audit 与 Change services 是受控子服务，不创建角色扮演多 Agent 链。 | AGENTS / 单一主编排器 | 高 |
| D-302 | Decision | 新增 `PlanningProvider` protocol，provider 只提出结构化 proposal；确定性 services 负责输入 lineage、ID、Evidence policy、Schema、Gate、资源限额和持久化。默认 `DeterministicPlanningProvider` 提供可运行基线；外部模型适配器以后通过相同 protocol 接入。 | provider-neutral / 能力诚实 | 中 |
| D-303 | Decision | Production planning artifacts 增加 `planning_lineage`，绑定 engine/provider 与上游 artifact type/version/content hash；legacy Minimal artifacts继续可验证，但不能被 M3 Exit 当作 ProductionImpl。 | 可追溯/当前版本 Gate | 中 |
| D-304 | Decision | Brief completion 不做不可解释的模型猜测：从现有 Brief、Source/Evidence inventory 与显式 hints 补全安全默认值；每个 unresolved field 形成稳定 question/assumption，并按 materiality 排序；最多返回 3 个 blocking questions。 | 最少提问 | 中 |
| D-305 | Decision | Outline 将 slide 视为稳定数字便利贴。exclude/reorder 保持 ID；split/merge 不重用被改变语义的原 ID，而是保留原 slide 为 excluded 并分配新 ID；Change Report 保存映射与原因。 | 历史可解释 | 中 |
| D-306 | Decision | Slide Specs 只使用当前 Outline 与 policy-usable Evidence；provisional/inference/assumption/stale/unknown support 必须写 `evidence_qualification`；不从 headline 文本猜造外部事实。 | M2 事实安全 | 中 |
| D-307 | Decision | Layout family 由内容关系和 Block 角色确定；Bento 不是默认。每个 Block 一一映射到 Region，所有 Region 必须在 safe area 内、reading order 完整、同层不碰撞、文本容量有 floor。 | 页面策划合同 | 中 |
| D-308 | Decision | 新增非 catalog `planning_review_report`、`planning_change_report`、`planning_repair_report`、`m3_application_report` 运行时事实，分别记录质量、局部变更、局部修复和应用级 lineage；它们不是 G8 Quality Report 或 Delivery Manifest。 | Gate 分层 | 中 |
| D-309 | Decision | Planning audit 先开放问题发现，再维度评分；M3 Submodule/Exit Gate 不复用 M5 最终视觉质量结论。 | 审计分层 | 高 |
| D-310 | Decision | M3 可以生成/更新 Narrative、Outline、Specs、Layout；不得生成 Visual System 或 Render outputs。任何上游变化通过 Artifact Runtime 自动失效后续 artifacts，局部修复保留未受影响对象字节语义。 | 里程碑边界 | 高 |
| A-301 | Assumption | 默认 deterministic provider 的目标是高质量可审阅策划基线，不声称取代外部 LLM 对复杂商业叙事的语义能力；provider mode 和限制必须写入 M3 Report。 | 能力诚实 | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| M3.1 | Planning contracts、Brief completion、question/assumption policy、lineage Schema | M2 frozen boundary | resolved/unresolved/idempotency/concurrency tests | complete |
| M3.2 | Narrative Engine + Narrative audit + G3 strengthening | M3.1 / current Evidence | thesis/arc/section/evidence/objection/lineage tests | complete |
| M3.3 | Outline Engine + digital-sticky operations + Change Report | M3.2 | insert/exclude/reorder/split/merge/freeze/history tests | complete |
| M3.4 | Slide Specs Engine + evidence qualification + targeted gap integration | M3.3 / M2.5 | block coverage/policy/current-lineage tests | complete |
| M3.5 | Layout Engine + geometry/reading-order/capacity + wireframes + G5B | M3.4 | family/diversity/collision/safe-area/golden tests | complete |
| M3.6 | Planning Review Engine + local repair/dependency propagation | M3.2–M3.5 | density/duplicate/rhythm/transition/rework/regression tests | complete |
| M3.7 | M3 Application/CLI/report、docs/ADR、Round A/root fixes/Round B、M3 Exit validator | 全部 | dual Python/full package/negative controls | complete |

## 5. Quality and risk controls

- 受影响 Schema：Project Brief、Narrative Blueprint、Deck Outline、Slide Specs、Layout Plans；新增 planning proposal/review/change/application runtime Schemas，并保持 packaged mirrors 字节一致。
- 受影响 Gate：G0、G3、G4、G5A、G5B；不降低 G1/G2，不把 M3 Exit 混入 deck G0–G9。
- 回归范围：M0/M1、MVP1、M2 全链、Artifact Runtime、Schema examples、CLI、workspace validation、wireframe/PPTX diagnostics、Package Audit。
- 降级路径：无外部 PlanningProvider 时使用明确的 deterministic provider；Brief 仍有 blocking questions 时停在 G0；Evidence gap 回 P2；无法形成合格 Layout 时停在 G5B；不以“生成了 JSON/SVG”替代 Gate。
- 安全/来源/版权风险：provider proposal 视为不可信结构化输入；禁止 provider 修改 ID/lineage/Gate；所有 factual content 继续走 Evidence；Source instructions 不进入 planning commands；不生成未经许可资产。

## 6. Verification

```bash
docker run --rm -v "$PWD":/work -w /work python:3.11-slim \
  sh -lc 'python -m pip install --disable-pip-version-check --no-cache-dir -q -e ".[dev]" && \
  python -m compileall -q src tests scripts && ruff check --no-cache src tests scripts && \
  pytest -o addopts="" && python scripts/validate_all.py && \
  python scripts/validate_m2_exit.py && python scripts/validate_m3_exit.py'

docker run --rm -v "$PWD":/work -w /work python:3.12-slim \
  sh -lc 'python -m pip install --disable-pip-version-check --no-cache-dir -q -e ".[dev]" && \
  python -m compileall -q src tests scripts && ruff check --no-cache src tests scripts && \
  pytest -o addopts="" && python scripts/validate_all.py && \
  python scripts/validate_m2_exit.py && python scripts/validate_m3_exit.py'

python scripts/audit_package.py
git diff --check
```

- 期望结果：全部检查 PASS；M2 Exit 持续 PASS；M3 只声明 Planning Production boundary。
- 实际结果：Python 3.11 / 3.12 均以完整非重叠测试分组覆盖 `255/255 PASS`；`validate_all.py` PASS，M2 Exit `12/12 PASS`，M3 Exit `13/13 PASS`，Package Audit `21/21 PASS`、332 files hashed，`git diff --check` PASS。

## 7. Review

### 第一轮：开放问题发现

- Critical：0。
- Major：14；覆盖 Schema mirror、统一 limits/preflight、完整 provider proposal budget、Change/Repair policy identity、Report forgery/finality、failure checkpoint 等；全部根修。
- Minor：5；覆盖 internal change-provider admission、blocked budget report、计划/文档/持久验证同步等；全部修复。
- 证据：`audit/M3-round-1-open-issues.md`。

### 修复记录

- 所有 Major 在最早责任层直接修复，无 waiver；详细根修与负向测试见 Round A 报告。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 5 | 双 Python 255/255；G0/G3/G4/G5A/G5B 与 Application/Repair 测试 | 无 |
| 叙事与页面策划质量 | 5 | thesis/arc/objection/section budget、sticky-note、density/rhythm/transition review | deterministic provider 语义能力保持保守 |
| Evidence 与 lineage | 5 | M2 Evidence policy、planning lineage、current-version Gate | 无 |
| 数字便利贴操作/局部返工 | 5 | insert/exclude/reorder/split/merge/freeze/update、PCH/PRP 与 optimistic conflict | assisted editorial rewrite 仍需 provider/人工 |
| Layout 几何与容量 | 5 | Region/Block 一一映射、safe area、collision、capacity、wireframe | 最终视觉属于 M4 |
| 架构一致性 | 5 | 单一 M3ApplicationService、provider-neutral、Artifact Runtime 单写入口 | 无 |
| 可测试性 | 5 | 正向/降级/needs-input/tamper/forgery/repair/Exit negative controls | 无 |
| 可维护性 | 4 | limits/lineage/rules/change/review/repair/report 分层 | Application 编排规模需在 M4 继续控制 |
| 降级与恢复 | 5 | P0 needs-input、P2 block、bounded repair、formal rework、history validation | 无 |

## 8. Final outcome

- 已完成：M3.1–M3.7 Production planning boundary 与 repository-wide audit。
- 未完成：M4 Rendering Backends、M5 independent visual review/repair。
- 后续任务：进入 M4 Rendering Backends；不重做 M2/M3，不把 renderer 变成 planning source of truth。
- 相关 ADR：ADR-0003、ADR-0005、ADR-0007、ADR-0008、ADR-0013、ADR-0014、ADR-0015、ADR-0016、ADR-0017、ADR-0018。
- **M3 Exit Gate：PASS（2026-08-27）。**
