# 03｜Workflow and State Machine

## 1. 主流程

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> BRIEF_READY: G0
    BRIEF_READY --> SOURCES_READY: G1
    SOURCES_READY --> EVIDENCE_READY: G2
    EVIDENCE_READY --> NARRATIVE_READY: G3
    NARRATIVE_READY --> OUTLINE_READY: G4
    OUTLINE_READY --> EVIDENCE_READY: page-level evidence gap
    OUTLINE_READY --> SLIDE_SPECS_READY: targeted evidence complete / G5A
    SLIDE_SPECS_READY --> LAYOUT_READY: G5B
    LAYOUT_READY --> VISUAL_SYSTEM_READY: G6
    VISUAL_SYSTEM_READY --> DRAFT_RENDERED: G7
    DRAFT_RENDERED --> REVIEWED: G8
    REVIEWED --> DELIVERY_READY: G9
    DELIVERY_READY --> COMPLETED
```

项目状态由两个正交字段组成：

- `current_phase`：最近一个已成立的流程阶段；
- `status`：`active / blocked / failed / cancelled / completed / degraded`。

`blocked` 不是独立 Phase。项目被阻断时保留当前 `current_phase`，把 `status` 设为 `blocked`，并在 `blockers` 中记录原因；解除阻断后恢复 `active`，再从原阶段继续。阶段不是“模型说完成了”，而是 Gate 通过后的持久化结果。

## 2. 阶段合同

| Phase | 主要问题 | 输入 | 输出 | Gate |
|---|---|---|---|---|
| P0 Intake | 为什么做、给谁看、什么约束 | 用户请求、初始素材、允许时的方向性扫描 | Project Brief | G0 Brief |
| P1 Sources | 有哪些可用资料 | 文件/链接/既有 deck/方向性研究来源 | Source Ledger | G1 Sources |
| P2 Evidence | 哪些声明有依据 | Sources、方向性研究、逐页定向研究 | Evidence Ledger | G2 Evidence；P5A 前再次确认 |
| P3 Narrative | 整套演示如何说服 | Brief、Evidence | Narrative Blueprint | G3 Narrative |
| P4 Outline | 每一页承担什么任务 | Narrative | Deck Outline | G4 Outline |
| P5A Slide Specs | 每页讲什么 | Outline、Evidence | Slide Specs | G5A Specs |
| P5B Layout | 每页如何组织 | Slide Specs | Layout Plans、wireframes | G5B Layout |
| P6 Visual | 整套视觉规则是什么 | Brief、参考、Layout、Assets | immutable Art Direction Packet、Visual System | G6 Visual |
| P7 Render | 如何变成目标文件 | Specs、Layout、Visual | Render Manifest、draft | G7 Render |
| P8 Review | 具体哪里有问题 | draft、所有 artifacts | Quality Report、repair plan | G8 Review |
| P9 Delivery | 交付是否完整 | approved draft | Delivery Manifest | G9 Delivery |

### 2.1 MVP 动作完整性

在 MVP 路径中，P5B 的策划稿、P7 的调试性 PPTX、设计预览和最终 PPTX 是不同产出。把同一策划内容保存为 `.pptx` 不构成新的阶段完成。`Render Manifest.pipeline_stages` 与 `outputs[].role` 记录每个动作；G7 检查非审阅阶段，G8 检查调试稿和最终稿的独立预览。

## 2.2 双阶段研究回路

研究不是只在流程中单点执行：

1. **方向性扫描**发生在正式提问之前或 P0/P1 期间，用于理解领域、时效、受众关切和素材缺口；它只形成证据基线。
2. **逐页定向补全**发生在 P4 大纲之后，因为此时才能知道每页真正需要证明什么。
3. 若逐页补全新增、推翻或改变了关键证据，执行 `OUTLINE_READY → EVIDENCE_READY`，随后重新通过 P3/P4 的一致性检查。
4. 只有定向证据缺口被解决、明确限定或获得授权 waiver 后，才进入 P5A。

这是一条显式返工边，不是跳过状态机；Evidence Ledger 仍是唯一证据事实源。

## 2.3 M3 Production planning 回路

M3 的单一应用链为：

```text
Brief completion / G0
  → M2 orientation / G2
  → Narrative / G3
  → stable Outline / G4
  → Slide Specs
  → M2 targeted Evidence / G5A
  → Layout + immutable wireframes / G5B
  → Planning Review / bounded Repair
```

- Production Narrative、Outline、Specs、Layout 都携带 `planning_lineage`，绑定当前上游 artifact version/content hash、provider、proposal 与 policy；
- `S-*` 是稳定页面身份，ordinal 只是顺序；insert/exclude/reorder/split/merge/freeze/update 产生 `PCH-*`，并只失效依赖该 Outline 的下游；
- Planning Review 产生 `PRV-*`，把具体问题定位到 P0/P2/P3/P4/P5A/P5B 中最早责任阶段；
- 自动 Repair 只处理已显式准入的 deterministic 问题，产生 `PRP-*`，并重跑 G2/G3/G4/G5A/G5B 与全套 Planning Review；
- assisted/manual 问题不自动改写语义，而是正式路由到最早责任阶段；
- `M3 Application Report` 的 planning level P0/P2/P3/P4/P5A/P5B 必须与最终 Project State 一致，部分失败不能冒充 P5B。

M3 Exit 是仓库级 Gate，不加入 deck G0–G9。它只证明不做最终视觉时，结构、证据、页面语义、几何和灰模已可审阅。

## 3. Gate 语义

### M1 当前记录

`gates/gate_results.json` 是独立、可版本化的 Gate 历史事实源，保存：

- Gate record ID、Gate ID 与状态；
- 输入 artifact type/path/version/hash；
- check results、severity 和 issue refs；
- 审批者、时间戳、waiver reason 和 notes。

`project_state.completed_gates[]` 只保存每个 Gate 的最新阶段控制摘要，并通过 `gate_record_id` 指回完整记录。Gate 输入版本落后于当前 registry 时，阶段校验报告 `stale_phase_gate`，不能继续推进。

Critical 规则不能被 waiver。Major waiver 只允许显式审批者、原因和 issue refs，并必须在 Delivery Manifest 中披露。

阶段推进还必须校验 Gate 与专属审计产物的一致性。尤其是 `REVIEWED` 及其后续阶段，`Quality Report.gate_result` 必须明确记录通过的 `G8`；P6 产生的 G6 规划审计不能复用为最终视觉审计。`DRAFT_RENDERED` 及其后续阶段必须对应成功 Render Manifest，`DELIVERY_READY` 及其后续阶段必须对应 ready/delivered Delivery Manifest。

## 4. 审批模式

### Auto

适合低风险草稿。阶段自动推进，但仍写入全部 artifacts 和 Gate 结果。

### Checkpoint

默认模式。在以下节点等待用户或主代理确认：

- Project Brief；
- Deck Outline；
- Layout wireframes；
- 最终视觉草稿。

### Strict

适合高价值、法律、财务、医疗、董事会和外部发布材料。每个 Gate 都需要显式批准，研究与来源要求更高。

## 5. 返工路由

问题应回到最早产生它的阶段：

| 问题 | 返回阶段 |
|---|---|
| 目标或受众错误 | P0 |
| 缺少关键文件 | P1 |
| 事实无支持/冲突 | P2 |
| 故事线不成立 | P3 |
| 页数、节奏或重复 | P4 |
| 单页命题/内容块错误 | P5A |
| 元素关系、密度、构图错误 | P5B |
| 字体、颜色、风格错误 | P6 |
| 溢出、碰撞、导出错误 | P7 |
| 审计遗漏或修复回归 | P8 |

禁止在 P7 用缩小所有文字的方式掩盖 P5 的内容过载。

M2.5 将 Evidence gap 返工实现为正式 Runtime 事务：

- Gap Report 绑定当前 Brief/Source/Evidence/Outline/Specs 版本；
- 只允许从 `OUTLINE_READY` 或 `SLIDE_SPECS_READY` 回到 `EVIDENCE_READY`；
- 保留 G0–G2，移除后续 Gate 摘要；
- Narrative、Outline、Slide Specs 与后续 staged artifacts 标为 draft；
- 返工原因写入 Decision Log；
- 输入版本在事务锁内再次核对，过期报告不能路由状态。

M3 将策划返工拆成两类：

- **显式数字便利贴操作**：Outline 与 Change Report 在同一事务提交；stable Slide IDs 和 mappings 保留页面历史；
- **Planning Review/Repair**：Review 绑定当前六类规划事实，Repair 绑定选中 issues、limits、provider 和 result Review；中断后保留最后一个有效阶段，M3 Application 发布 failed/rework report。

改变 Outline 会使 Specs/Layout/Visual/Render/Review/Delivery draft，但不会无故重写 Narrative 或 Evidence；事实缺口仍回 P2，故事线问题回 P3，页面职责问题回 P4，内容块问题回 P5A，几何容量问题回 P5B。

## 6. 局部重生成

每个 slide 和 block 都有稳定 ID。局部修改流程：

1. 锁定变更对象和反馈；
2. 找到其上游 evidence、slide spec、layout 与 visual token；
3. 判断最早受影响阶段；
4. 只失效依赖该对象的下游 artifacts；
5. 重生成并渲染；
6. 对该页做局部审计；
7. 对全 deck 做跨页一致性回归。

## 7. 并发模型

可以并行：

- 不同来源解析；
- 不同查询的研究；
- 已冻结 outline 后的独立 slide spec 草拟；
- 不同审计维度的只读检查；
- 不同页的渲染。

必须串行或统一合并：

- Project Brief 决策；
- Narrative Blueprint；
- Deck Outline 顺序；
- Visual System；
- Gate 状态和 artifact registry；
- 跨页修复决策。

## 8. 失败状态

- **blocked**：缺少用户输入、工具或权利；可恢复。
- **failed**：执行错误或 artifact 不一致；必须修复后重试。
- **cancelled**：用户停止；保留已完成 artifacts。
- **degraded**：按能力矩阵输出部分结果；必须声明缺失交付。

失败不能把项目状态推进到后续阶段。

## 9. 可恢复执行

Artifact Runtime 保证：

- artifact 写入原子化；
- 状态迁移和 artifact 版本在同一事务语义内；
- 中断后可从最后一个通过的 Gate 恢复；
- 临时文件不被识别为正式 artifact；
- 重试不会静默覆盖人工修改；
- 每次修复保留可比较版本。

事务 journal、历史快照与锁文件保存在 workspace 的 `.slidethus/` 中；正式 artifact 路径不变。`artifact recover` 会确认完整且有效的提交，或回滚不完整/无效的提交。
