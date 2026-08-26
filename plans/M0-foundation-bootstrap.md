# M0 Foundation Bootstrap Execution Plan

## 1. Objective

- 用户价值：交付一套可直接由本地 Codex 接手建设的 Slidethus 工程基础。
- 本轮边界：方法论、架构、Skill、Schema、确定性骨架、示例、测试、审计和打包。
- 明确不做：生产级模型/搜索/图片适配器、Final SVG、PPTX renderer、GUI。
- 退出条件：M0 自动审计、测试、Wheel 安装和 ZIP 完整性全部通过，残余边界明确。

## 2. Current state

- 包版本：0.1.0。
- 当前阶段：M0 Foundation Contract。
- 已存在能力：13 个 Schema、仓库级 Skill、Python CLI、Gate、Wireframe、示例项目。
- 已知缺口：M1–M6 均未实现。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 使用单一主编排器 | 强依赖事实和状态，减少代理交接损耗 | 中 |
| D-002 | Decision | 中间产物结构化持久化 | 支持恢复、审计和局部返工 | 低 |
| D-003 | Decision | 研究分方向性和逐页定向两次执行 | 来源同时要求提问前背景理解和大纲后逐页检索 | 中 |
| D-004 | Decision | 目标编辑等级与实测等级分离 | 防止 pending 输出冒充 E4 | 低 |
| D-005 | Decision | M0 只实现 Wireframe renderer | 先稳定合同，不伪装生产能力 | 高 |
| A-001 | Assumption | 本地 Codex 可读取仓库级 Skill 并执行 Python | 本包的目标宿主环境 | 高 |

## 4. Work breakdown

| Step | 产出 | 验证 | 状态 |
|---|---|---|---|
| 1 | 来源清洗、Prompt 保留、边界说明 | 来源哈希和镜像审计 | complete |
| 2 | 产品与架构文档 | Round 1/2 review | complete |
| 3 | 仓库级 Skill 与 Codex handoff | frontmatter、instruction budget | complete |
| 4 | 13 个 Artifact Schema | Draft 2020-12 校验和镜像测试 | complete |
| 5 | Python core、CLI、Gate、Wireframe | 单元和集成测试 | complete |
| 6 | 两阶段研究合同 | `research_cycles`、G2/G5A、返工测试 | complete |
| 7 | 编辑等级合同 | target/actual 字段和负向测试 | complete |
| 8 | 示例项目 | hash validation、G0–G6 | complete |
| 9 | 五轮审计 | 自动检查和人工记录 | complete |
| 10 | Wheel/ZIP | 安装 smoke、unzip test、SHA-256 | complete after final packaging |

## 5. Quality and risk controls

- 受影响 Schema：全部 13 个；重点为 Evidence、Render、Delivery、Project State。
- 受影响 Gate：G0–G9；M0 示例只应通过 G0–G6。
- 回归范围：所有测试、Schema mirror、示例哈希、相对链接、来源清单和 ZIP。
- 降级路径：缺少最终 renderer 时交付 Artifact 与 Wireframe，不声明 G7。
- 安全/来源：原始浏览器 HTML 不进入包；来源 Prompt 与生产 Prompt 隔离；路径穿越拒绝。

## 6. Verification

```bash
python -m pytest -q
python scripts/validate_all.py
python scripts/audit_package.py
python -m compileall -q src tests scripts
python -m pip wheel . --no-build-isolation --no-deps
```

Wheel 在独立目标目录安装后还需运行：

```bash
python -m slidethus doctor
python -m slidethus schemas
python -m slidethus init <temporary-workspace> --title "Wheel Runtime Smoke"
python -m slidethus validate <temporary-workspace> --check-hashes
```

## 7. Review

### 第一轮：开放问题发现

- Major：研究流程只在文档中描述，缺少机器可验证的“方向性/定向”周期和 outline 版本绑定。
- Major：pending Render/Delivery 把目标 E4 写成实际 E4，目标与结果混淆。
- Minor：来源审计中曾使用不准确的“five-stage”措辞。
- Minor：构建 Wheel 会产生 build/egg-info 污染，需要发布树卫生检查。

### 修复记录

- 增加 `research_cycles`，并接入 G2、G5A、状态验证和对抗测试。
- 增加 `target_editability_level` 与 `not_measured`，成功/ready 状态要求实测值。
- 修正来源审计措辞。
- 自动审计增加 release tree hygiene。
- 后续合同审计继续补齐：上游资产持续存在、布局块全覆盖、章节/异议证据引用、页数区间、研究来源和编辑等级承诺。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 4.7 | Schema、Gate、40 项测试、来源边界 | 未有生产 renderer 真实数据 |
| 架构一致性 | 4.8 | 分层、单编排器、Artifact contracts、ADR | M1 依赖失效尚未实现 |
| 可测试性 | 4.8 | 单元、集成、变异、Wheel smoke | 缺多 Python/OS CI 矩阵 |
| 可维护性 | 4.6 | provider-neutral、progressive disclosure、文档路由 | Schema migration 尚未实现 |
| 降级与恢复 | 4.2 | D0–D5、明确 blocker、负向 Gate | 原子事务/恢复属于 M1 |

M0 Gate：PASS；生产级发布 Gate：NOT APPLICABLE。

## 8. Final outcome

- 已完成：可运行的 Foundation/Bootstrap 包。
- 未完成：M1–M6。
- 后续任务：按 `CODEX_KICKOFF.md` 从 M1 Artifact Runtime 开始。
- 相关 ADR：ADR-0001 至 ADR-0005。
