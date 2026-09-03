# Issue #3｜Host Create Authoritative Rebuild

Status: engineering checkpoint complete; external integration acceptance pending; DO NOT RELEASE

## 1. Objective

- 用户价值：Host-led Create 在多轮 Host response、进程中断和阶段返工后仍能稳定继续，不要求重复初始长命令，不误复用过期工件，也不伪造候选或发布状态。
- 本轮边界：从干净 `origin/main@b1af33ccec224c0418f1d9d1f30f06952d16bf5f` 重建 Host Create 的持久化任务身份、Resume/Revision 事务、M2/Planning reuse、阶段终态事实和布局语义/几何合同。
- 明确不做：不合并两套旧半成品；不把 `@oai/artifact-tool` 换成另一后端制造通过；不发布；不关闭 Issue #3；不把工具预览冒充 PowerPoint 验收。
- 退出条件：OCI 工程回归通过；实现分支可独立拉取；Codex Artifact Tool + Microsoft PowerPoint 验收计划与报告模板完整；真实验收仍作为独立 Gate 保留。

## 2. Current state

- 基线：`b1af33ccec224c0418f1d9d1f30f06952d16bf5f`
- 实现分支：`fix/issue-3-authoritative-rebuild`
- 旧分支：`fix/issue-3-host-create-resume`、`fix/issue-3-root-cause-repair` 仅作为失败证据保留，未 merge、未 cherry-pick、未整文件复制。
- 已存在能力：Artifact Runtime、M2/M3 planning、Host proposal bridge、Artifact Tool adapter、render receipt 和既有 G0–G9 合同。
- 原始缺口：一次 Create 无 canonical identity；普通 Resume 与显式 Revision 语义混淆；Artifact 存在被误当成 current Gate；M2 report 可在上游变更后错误复用；layout family 字符串与真实几何节奏混淆；前后端失败缺统一 invocation terminal fact。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 两套旧半成品均冻结，只从干净 main 重建 | 旧实现修改面过大且互相竞争 | 高 |
| D-002 | Decision | Session 是跨调用唯一 canonical Create intent | CLI/对话参数不能承担持久化事实 | 中 |
| D-003 | Decision | Resume、Brief Revision、Source Revision、Stage Revision 为不同事务 | 防止续跑重解释 P0 或修订后重启完整 intake | 中 |
| D-004 | Decision | Reuse 同时要求 artifact、lineage、provider/policy、current Gate 与 current phase | 文件存在或 Schema 合法不等于阶段成立 | 低 |
| D-005 | Decision | Layout family 允许 provider-neutral semantic slug；节奏审计读取真实 Region geometry | 名称不能替代空间关系，也不能通过改名逃避审计 | 中 |
| D-006 | Decision | 每个 Create invocation 都有 started 与唯一 terminal fact | 失败和中断必须形成持久恢复事实 | 低 |
| D-007 | Decision | Artifact Tool 保留为本 Issue 的参考生产后端；真实集成在具备该 runtime 的 Codex 设备执行 | 私有 runtime 不应被 OCI 模拟为真实能力 | 高 |
| A-001 | Assumption | 验收设备能够合法获得并暴露 `@oai/artifact-tool`，且安装 Microsoft PowerPoint | 由验收预检决定；不满足则结论为 BLOCKED | 高 |

## 4. Work breakdown

| Step | 产出 | 验证 | 状态 |
|---|---|---|---|
| 1 | 干净分支和执行计划 | HEAD/branch/status | complete |
| 2 | Host Create Session/Operation Schema 与 runtime | Schema、identity、tamper、recovery tests | complete |
| 3 | 普通省略参数 Resume 与零修改冲突保护 | API/CLI integration tests | complete |
| 4 | Brief/Source/Stage Revision 事务 | 跨进程 revision、supersedes、rollback tests | complete |
| 5 | current M2/Planning reuse | stale targeted report、phase/Gate negative tests | complete |
| 6 | semantic layout family 与 geometry topology review | schema/service/review regression | complete |
| 7 | Host response 多问题聚合和 structured rework | malformed proposal/rework receipt tests | complete |
| 8 | fresh Create → controlled revision → synthetic candidate 组合闭环 | same IR、candidate/operation receipts | complete |
| 9 | 文档、ADR、Skill、双端验收协议 | link/package audit | complete |
| 10 | 真实 Artifact Tool + PowerPoint 验收 | `plans/issue-3-codex-powerpoint-acceptance.md` | pending external acceptance |

## 5. Quality and risk controls

- 受影响 Schema：`host_create_session`、`host_create_operation`、`slide_specs`、`layout_plans`；root/package mirrors 保持一致。
- 受影响 Gate：G0/G2/G3/G4/G5A/G5B/G6 currentness；不修改 G7/G8/G9 的发布含义。
- 回归范围：Host Create、M2/M3、Narrative、Outline、Specs、Layout、Planning Review、Artifact Runtime、CLI、package validation。
- 降级路径：缺 `@oai/artifact-tool` 时明确阻断真实 reference-backend candidate；synthetic runtime 只验证控制链，不能成为产品证据。
- 安全/来源/版权风险：不提交私有 runtime、Node modules、字体、用户素材或未授权候选；验收日志必须脱敏。
- 单写者纪律：OCI 工程分支是唯一代码写入点；验收设备只提交报告与授权证据。

## 6. Verification

```bash
python -m pytest -q
python scripts/validate_all.py
python scripts/audit_package.py
python -m compileall -q src tests scripts
ruff check src tests scripts
git diff --check
```

专项验证覆盖：

- Session config omission/reuse、explicit conflict、source fingerprint drift；
- operation started/terminal、orphan recovery、live/recovered duration、before/resulting config hashes；
- CLI plain resume；
- Brief/Source/Stage revision；
- revision rejection后继续同一 pending request；
- pending revision不能 render；
- current M2 reuse 与 stale targeted M2 rejection；
- phase rollback不能用结构仍合法的旧 Layout 记录 G6；
- provider-neutral layout family 与 geometry-based rhythm；
- Host response envelope/Narrative/Outline/Specs/Layout 多 finding 聚合；
- structured Planning Review rework；
- fresh cold start、六阶段 response、受控 Specs revision、synthetic candidate 和双层 terminal receipts。

实际结果：工程专项回归、完整 Python 3.11 测试、compileall、Ruff、`validate_all.py`、`audit_package.py` 和 diff integrity 均作为提交前硬条件执行。真实 Artifact Tool 与 PowerPoint 结果不在 OCI 中声明。

## 7. Review

### 第一轮：开放问题发现

- Critical：0。
- Major：0。审计发现的“意图修订只保留修订前 config hash”已根修：terminal 同时绑定 invocation-base `config_hash` 与 `resulting_config_hash`，最新 terminal 可与当前 Session 对照。
- Minor：Host Create orchestration 与 proposal pre-admission 代码仍较大；本轮不为了行数拆分已闭合事务，后续可在 Issue #3 真实验收后做行为不变的模块化。
- External blocker：当前 OCI 未获得合法 `@oai/artifact-tool` runtime，且没有 Microsoft PowerPoint；这不阻断工程提交，但阻断真实 reference-backend/Office Gate。

### 修复记录

- 用 canonical Session 替换“每次调用重新解释输入”。
- 用显式 Revision transaction 替换 `--request` 多义行为。
- 用 Gate/phase/lineage currentness 替换“文件存在即复用”。
- 用 immutable per-invocation facts 替换只靠返回文本判断终态。
- 用 semantic slug + observable geometry 替换固定 taxonomy 与字符串节奏代理。
- 用聚合 pre-admission findings 替换一次只返回一个字段错误。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 4 | 正负向专项、完整回归、fresh+revision integration | 待真实私有 backend/Office 证实 |
| 架构一致性 | 4 | ADR-0033、单 Session、既有 Artifact Runtime/Gate owner | 无阻断 |
| 可测试性 | 5 | public contract、failure、recovery、tamper、integration tests | 私有 runtime 只能在验收机测试 |
| 可维护性 | 3 | 分离 records/orchestration/provider admission，完整类型与 Schema | 两个 orchestration 文件仍偏大 |
| 降级与恢复 | 4 | conflict-before-production、orphan recovery、structured terminal | 真实跨 OS/进程崩溃待验收机补证 |

## 8. Final outcome

- 已完成：Issue #3 工程根因修复、全套控制链、抽象布局合同、工程回归、双端验收计划和证据模板。
- 未完成：真实 `@oai/artifact-tool` candidate、原始 PPTX 的 Microsoft PowerPoint 打开/PDF 导出/逐页视觉验收。
- 发布状态：Issue #3 保持 Open；M6 保持 Reopened；v1.0 保持 `DO NOT RELEASE`。
- 验收入口：`plans/issue-3-codex-powerpoint-acceptance.md`。
- 验收记录模板：`audit/issue-3-codex-powerpoint-acceptance-template.md`。
- 相关 ADR：`docs/adr/ADR-0033-host-create-authoritative-session-and-resume.md`。
