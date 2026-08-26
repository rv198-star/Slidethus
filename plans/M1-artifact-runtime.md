# M1 Artifact Runtime Execution Plan

## 1. Objective

- 用户价值：让 Slidethus 的结构化产物可以安全创建、版本化、迁移、校验、恢复并通过 CLI 审计。
- 本轮边界：完成 `TASKS.md` 的 M1 Artifact Runtime；补齐运行时、Schema、CLI、文档、示例和测试，并建立公开 GitHub 仓库。
- 明确不做：M2 外部研究适配器、M3 智能叙事生成、M4 最终 PPTX/视觉渲染、M5 模型审计。
- 退出条件：M1 清单和 Exit Gate 全部有真实实现与故障路径测试；规定的五项检查全部通过；两轮 review 完成；公开仓库推送成功。

## 2. Current state

- 当前 HEAD / 工作区状态：目录尚未初始化 Git；现有文件为 M0 foundation 包。
- 已存在能力：Schema catalog、基础 workspace 初始化、跨引用校验、阶段状态机、Gate 评估、wireframe 与 CLI 骨架。
- 已知缺口：没有统一 artifact runtime/registry 服务、迁移、乐观锁、版本历史、事务恢复、独立 Gate 历史、决策/假设日志及 M1 artifact CLI；`docs/13-codex-compatibility.md` 缺失。
- 基线测试：`python -m pytest`、`scripts/validate_all.py`、`scripts/audit_package.py` 均因 `src` 包导入路径未配置而在导入阶段失败。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 使用一个 `ArtifactRuntime` 统一管理 registry、版本写入、迁移、Gate 和恢复 | ADR-0001/0002；避免状态写入分散 | 中 |
| D-002 | Decision | 版本快照和事务恢复信息保存在 workspace 内部 `.slidethus/`，正式 artifact 路径保持不变 | 兼容现有 artifact map，同时允许恢复 | 高 |
| D-003 | Decision | 采用 expected-version 乐观锁；每次正式写入产生不可变历史快照 | M1 合同与中断恢复要求 | 中 |
| D-004 | Decision | Gate 结果使用独立 schema-backed artifact，同时在 project state 保存最新摘要引用 | 状态机文档要求独立、可版本化 Gate 历史 | 中 |
| A-001 | Assumption | 用户所说“完成项目构建”以 kickoff 锁定的 M1 为本轮完成边界，而非声称 M2–M6 已完成 | 用户附带 kickoff 明确限定本轮目标 | 高 |
| A-002 | Assumption | GitHub 仓库名使用 `Slidethus`，公开可见，默认分支 `main` | 项目名与用户请求 | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| 1 | 完整现状与契约审计、M1 ADR | 核心文档/ADRs | 文档一致性 review | completed |
| 2 | 统一元数据、registry、日志和 Gate schemas | Step 1 | Draft 2020-12 schema checks | completed |
| 3 | 原子事务、版本快照、乐观锁、恢复与迁移 runtime | Step 2 | 单元 + 故障注入 | completed |
| 4 | 全量跨产物引用与 Gate 持久化/推进约束 | Step 3 | 集成测试 | completed |
| 5 | `artifact list/show/validate/migrate` 与日志/Gate CLI | Step 3-4 | CLI tests | completed |
| 6 | 示例、README、兼容性文档、TASKS/计划同步 | Step 2-5 | package audit | completed |
| 7 | 完整门禁、两轮 review、修复与评分 | Step 1-6 | required checks | completed |
| 8 | 初始化 Git、创建 `rv198-star/Slidethus` 公开仓库并推送 | Step 7 | GitHub repo visibility + remote/HEAD | in_progress |

## 5. Quality and risk controls

- 受影响 Schema：`project_state`、新增 artifact/gate/log runtime schemas、catalog 及打包镜像。
- 受影响 Gate：G0–G9 的输入版本、持久化、Critical/Major waiver 规则和阶段推进。
- 回归范围：workspace init、全部 schema 示例、跨引用、状态机、Gate、CLI、wireframe、package audit。
- 降级路径：迁移或事务失败时保留当前正式文件，写入恢复记录并允许显式 `recover`；不静默覆盖人工修改。
- 安全/来源/版权风险：不修改 `source_material/source-preserved/`；不引入网络型生产依赖；GitHub 仅发布现有项目材料和本轮实现。

## 6. Verification

```bash
python -m pytest
python scripts/validate_all.py
python scripts/audit_package.py
python -m compileall -q src tests scripts
ruff check src tests scripts
```

- 期望结果：全部命令退出码 0；故障注入证明半写入不会成为正式状态，恢复与冲突有显式结果。
- 实际结果：52 tests passed；16 schemas/example/G0–G6/G7 negative control passed；18/18 package checks passed；compileall exit 0；Ruff 0.16.4 passed。

## 7. Review

### 第一轮：开放问题发现

- Critical：0。
- Major：5 个，均已修复；见 `audit/M1-round-1-open-issues.md`。
- Minor：1 个，已修复。

### 修复记录

- 修复 journal 归档顺序、上游依赖失效、waiver 绑定、失败 Gate 持久化、读锁范围和 CI hygiene 误报，并增加回归测试。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 5 | 52 tests + 16 schemas + Gate negative control | 无已知阻断问题 |
| 架构一致性 | 5 | ADR-0006、单写入 runtime、provider-neutral | 无 |
| 可测试性 | 5 | 故障注入、迁移、CLI、Gate、跨引用 | Windows 锁分支待 CI 覆盖 |
| 可维护性 | 4 | 显式 migration/gate contracts/type hints | M2 扩张时可拆分 runtime 模块 |
| 降级与恢复 | 5 | partial/final valid/final invalid 三类恢复测试 | 磁盘耗尽属于环境残余风险 |

## 8. Final outcome

- 已完成：M1 全清单、Exit Gate、两轮 review、文档和发布前验证。
- 未完成：GitHub 公开仓库创建与推送正在执行。
- 后续任务：M2 Ingestion, Research, Evidence。
- 相关 ADR：ADR-0001、ADR-0002、ADR-0006。
