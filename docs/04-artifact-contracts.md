# 04｜Artifact Contracts

## 1. 为什么使用结构化产物

Slidethus 的各阶段需要在长任务、中断恢复、局部返工和不同工具之间保持一致。仅依赖对话历史会导致：

- 事实和假设混淆；
- 页面顺序变化后引用失效；
- 设计 Agent 看不到来源边界；
- 局部修改无法计算影响范围；
- 审计只剩主观评价。

因此，正式阶段输出必须写入 schema-backed artifacts。

## 2. 通用元数据

每个 artifact 后续应统一包含：

```json
{
  "schema_version": "0.1.0",
  "artifact_id": "ART-...",
  "artifact_type": "deck_outline",
  "project_id": "...",
  "version": 1,
  "status": "draft",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "created_by": "human|agent|service",
  "supersedes": null,
  "content_hash": "sha256:..."
}
```

M1 将这些字段保存在 `project_state.artifacts[]` 的统一 registry metadata 中。artifact 正文继续只保存各领域 Schema 的事实字段，避免把运行时元数据复制到每个领域合同。`project_state` 自身以 `revision` 版本化，避免自引用哈希。

## 3. ID 规范

| 对象 | 前缀 | 示例 |
|---|---|---|
| Source | `SRC-` | `SRC-001` |
| Evidence | `EVD-` | `EVD-014` |
| Section | `SEC-` | `SEC-02` |
| Slide | `S-` | `S-005` |
| Content Block | `BLK-` | `BLK-S005-03` |
| Layout Region | `REG-` | `REG-S005-02` |
| Asset | `AST-` | `AST-022` |
| Render | `RND-` | `RND-S005-v3` |
| Issue | `ISS-` | `ISS-104` |
| Decision | `DEC-` | `DEC-008` |

ID 一经发布不能因标题或顺序变化而改变。

## 4. Artifact catalog

### 4.1 Project Brief

回答：为什么做、给谁看、希望发生什么、有哪些约束。

关键字段：

- purpose / desired outcome；
- audience；
- presentation mode；
- page/time constraints；
- output/editability；
- source/research policy；
- approval mode；
- assumptions/open questions。

### 4.2 Source Ledger

回答：可用资料是什么、来自哪里、是否可用。

关键字段：

- `source_id`；
- 类型、路径或 URL；
- 所有权与许可；
- 时间、权威和可信等级；
- 内容哈希、媒体类型和字节数；
- 解析状态；
- parser 名称/版本与识别格式；
- 不可变解析快照的工作区相对路径和文件哈希；
- Chunk、warning、risk 数量与解析限额；
- allowed-use 与保密策略。

M2.1 的生产摄取不会把全部正文复制进 Source Ledger。正文、稳定 Chunk IDs、locator、内容哈希、warning 和 source risks 写入 `source_snapshot.schema.json` 校验的运行时快照，再由 Ledger 的 `ingestion` 字段引用。快照 key 绑定 source ID、来源字节、parser、格式与限额；路径已存在时不得覆盖。

来源正文未变化时可以复用快照，但 title、ownership、confidentiality、authority 或 allowed-use 的变化仍必须创建新的 Source Ledger 版本。Parser 版本或解析限额变化会创建新快照。`source_id` 不允许重绑到另一文件，同一路径不允许创建第二个 source ID。

为兼容 M0/MVP 示例，旧记录可以没有 `ingestion`；由 M2 ProductionImpl 新建、`content_hash` 使用 `sha256:` 前缀且状态为 `parsed` 的记录必须引用有效快照。

### 4.3 Evidence Ledger

回答：哪些声明被哪些来源支持。

关键字段：

- claim；
- support status；
- source refs + locator；
- freshness；
- conflict notes；
- allowed use；
- confidence reason，而不是只给一个无解释分数。

`unsupported` 或 `disputed` 声明不能作为确定事实进入页面。研究分为方向性与逐页定向两次执行，但写入同一个 Evidence Ledger。`research_cycles` 记录类型、状态、来源和对应 outline 版本；M2 再增加 query/task lineage、缓存和失效机制，而不是复制两套证据。

### 4.4 Narrative Blueprint

回答：整套演示的论点、故事线和说服路径。

包括：

- central thesis；
- story arc；
- section purpose；
- audience objections；
- proof strategy；
- transitions；
- excluded content。

### 4.5 Deck Outline

回答：每页承担什么叙事职责。

每页至少包含：

- stable slide ID；
- section；
- page type；
- headline；
- takeaway；
- purpose；
- evidence IDs；
- transition relationship。

### 4.6 Slide Specs

回答：一页内部应该表达什么。

每页包括：

- core message；
- audience question；
- content blocks；
- block priority；
- evidence bindings；
- visual intent；
- speaker notes；
- density budget；
- editability intent。

它不包含最终颜色、字体和绝对坐标。

### 4.7 Layout Plans

回答：内容块放在哪里、如何形成视觉关系。

包括：

- logical canvas；
- layout family；
- safe area；
- region geometry；
- block mapping；
- alignment；
- overflow strategy；
- reading order；
- layout rationale。

### 4.8 Visual System

回答：跨页共享的视觉规则。

包括：

- tone；
- color tokens；
- typography tokens；
- spacing/grid；
- shape and line rules；
- chart/image/icon rules；
- footer/page number；
- layout diversity policy；
- forbidden patterns；
- brand asset refs。

### 4.9 Asset Manifest

回答：图片、图标、字体、图表和模板资产从哪里来、能否使用。

### 4.10 Render Manifest

回答：哪一个 artifact 版本被哪个后端渲染成什么文件。

必须记录：

- backend/version；
- input hashes；
- output paths/hashes；
- font substitutions；
- warnings；
- target editability level；
- actual measured editability level；
- render duration；
- preview refs。

`target_editability_level` 表示计划目标；`editability_level` 表示对真实输出的测量结果。`pending`/`draft` 阶段必须允许 `not_measured`，成功渲染和可交付状态则不能继续使用该值。

完整 MVP 还使用 `pipeline_stages` 记录 planning、diagnostics、debug render/preview、design compile、final render/preview 动作，并用 `outputs[].role` 区分每个产出。输出文件扩展名不能替代阶段语义；Debug PPTX 和 Final PPTX 必须是不同文件。

### 4.11 Quality Report

回答：具体问题、严重度、修复路径和 Gate 结论。

支持三种 review mode：

- deterministic；
- open issue mining；
- dimension scorecard。

### 4.12 Delivery Manifest

回答：最终交付包含什么、基于哪些版本、有哪些已知限制。它必须把目标编辑等级与实际交付编辑等级分开；草稿阶段实际等级可为 `not_measured`，`ready/delivered` 时必须由真实输出验证。

## 5. 语义与几何分离

错误做法：

```json
{"text": "三大问题", "x": 50, "y": 80, "font": "...", "color": "..."}
```

单个对象同时绑定语义、几何和样式，导致任何视觉调整都可能改写内容事实。

正确分层：

```text
Slide Spec:    BLK-01 = “三大问题”，priority=primary
Layout Plan:   REG-01 → BLK-01, x/y/w/h
Visual System: title.primary font/color/weight
Renderer:      合并三者并输出目标格式
```

## 6. 来源引用规则

- 用户素材和外部研究使用不同 source type；
- 每个来源有稳定 `source_id`；
- 每个事实块引用 evidence IDs，不直接粘贴 URL；
- locator 尽量使用页码、表格名、章节、行范围；同一长行被切分时必须增加字符范围，不能产生无法区分的重复 locator；
- 研究时记录 retrieved_at；
- 来源字节、parser 版本或解析限额变化后，所有相关 evidence 和 slide 必须失效回归；只修改来源权限策略时复用快照但版本化 Source Ledger；
- 视觉资产同样记录来源与许可。

## 7. Schema 演进

- Schema 采用语义化版本；
- 向后兼容增加字段：minor；
- 删除/改义/重构：major；
- 每个迁移必须可测试、可回滚；
- 不允许在运行中静默改变旧 artifact 含义；
- `schema_version` 与 artifact `version` 是两个概念。

当前 `MigrationRegistry` 使用显式的 `(artifact_type, from_version) → to_version` 步骤。M0 `project_state 0.1.0` 可迁移到 M1 `0.2.0`；迁移前状态保存在 `.slidethus/history/project_state/`。

## 8. Artifact 状态

建议状态：

```text
draft → reviewed → approved → frozen → superseded
```

- `frozen` 表示下游可以依赖；
- 修改 frozen artifact 必须创建新版本；
- `superseded` 不删除历史；
- 临时草稿不得被 Gate 当作正式输入。

## 9. 跨引用校验

最低要求：

- evidence source refs 均存在；
- outline evidence IDs 均存在且可用；
- slide IDs 在 outline/spec/layout 中覆盖一致；
- layout region 的 block ID 存在；
- asset refs 存在且许可可用；
- render manifest 输入版本与当前项目状态一致；
- quality issues 的 slide/block/region refs 存在；
- delivery 只引用通过 Gate 的版本。
