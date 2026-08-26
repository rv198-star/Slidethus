# 10｜Codex Build Plan

## 1. 仓库接手方式

从仓库根目录启动 Codex。根目录 `AGENTS.md` 负责持久规则，`.agents/skills/slidethus/SKILL.md` 负责产品工作流。不要把全部设计文档塞进 AGENTS.md；按当前任务渐进读取。

## 2. 首次会话

1. 运行基线；
2. 输出当前架构理解；
3. 验证已完成的 M1 Gate，创建新的 M2 执行计划；
4. 定位 M2 ingestion/evidence 最小垂直切片；
5. 实现并通过测试；
6. 做开放问题审计；
7. 修复后做评分审计；
8. 只在 Gate 通过后更新任务状态。

M1 已完成的垂直切片：

```text
init project
  → create artifact registry
  → atomically write project brief v1
  → validate
  → persist G0 result
  → simulate interruption
  → recover and read same state
```

M2.1 已完成该切片的来源侧：用户文件进入版本化 Source Ledger，并持久化可校验、可中断恢复的 locator/Chunk 快照。后续 M2.2–M2.5 继续补齐多格式适配、带 locator 的 Evidence、research lineage 与 Evidence Gate；在生产 Evidence Gate 完成前，MVP 的 Minimal Evidence 不能被描述为完整 M2。

## 3. 工作拆分

### 主线程

- 理解需求和架构；
- 维护执行计划；
- 作出领域决策；
- 写核心状态/registry；
- 合并结果；
- 运行 Gate。

### 可选子代理

- 一个只读探索现有 Schema 与跨引用；
- 一个分析测试缺口；
- 一个做独立代码审计。

不要让多个子代理同时修改 state machine、artifact registry 或同一 Schema。

## 4. 推荐提交节奏

1. baseline and plan；
2. domain types and persistence interface；
3. atomic storage and recovery；
4. registry and migrations；
5. CLI；
6. tests and failure injection；
7. docs/ADR；
8. review fixes。

每个提交保持可运行，不把“大量未完成 TODO”作为一整个提交。

## 5. 代码变更路由

| 变更 | 优先阅读 |
|---|---|
| Skill 行为 | `.agents/skills/slidethus/SKILL.md`、workflows/references |
| 状态/Gate | `docs/03-*`、`src/slidethus/state_machine.py`、`gates.py` |
| Schema | `docs/04-*`、`schemas/`、example、tests |
| 渲染 | `docs/06-*`、`renderers/`、layout/visual schemas |
| 审计 | `docs/05-*`、`quality/`、quality schema |
| 来源 | `docs/01-*`、`source_material/` |

## 6. 需要避免的 Codex 误区

- 看到“PPT Agent”就先搭 UI；
- 用一段超级 Prompt 替代阶段合同；
- 把所有角色建成独立 Agent；
- 在 semantic schema 中加入供应商 API 字段；
- 只做 happy path；
- 用分数掩盖具体缺陷；
- 生成文件但不独立渲染验证；
- 修改 frozen artifact 而不创建版本；
- 为了过测试降低 Gate 标准。

## 7. 每轮汇报格式

- 本轮目标；
- 已读取事实；
- 变更文件；
- 决策与 ADR；
- 测试结果；
- 第一轮问题；
- 修复；
- 第二轮评分/Gate；
- 已知风险；
- 下一最小步骤。

## 8. Definition of Done

Codex 不能只说“已完成”。必须附：

- 具体命令与结果；
- artifact/schema 示例；
- 失败路径测试；
- 受影响 Gate；
- 未完成能力；
- diff review 结论。
