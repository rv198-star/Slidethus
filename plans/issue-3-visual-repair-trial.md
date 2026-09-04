# Issue 3 Visual Repair Trial

## 1. Objective

- 用户价值：验证 Slidethus 能否通过正式 Host Create、同一 admitted IR 与同一 Artifact Tool producer 恢复高质量视觉产出。
- 本轮边界：先修复 FDE 案例的 S-001、S-002、S-004、S-008；用户认可样稿后，再以同一 admitted IR 扩展 S-003、S-005、S-006、S-007。
- 明确不做：不修改原脏工作区；不修改只读验收 worktree；不扩展无关框架；不把候选稿误称为 release approved。
- 退出条件：八页均经真实 PowerPoint 检查；若存在明显碰撞、弱层级、语义错误或模板化重复，则回到最早责任阶段修复。

## 2. Current state

- 当前 HEAD / 工作区状态：独立分支 `codex/issue3-visual-repair-trial`，基于 `d0e1dde26b69210caafc6940bfb44a9bf2f3fc63`。
- 已存在能力：正式 Host Create、schema-backed Specs/Layout/Visual System、Artifact Tool 渲染、PowerPoint 实机检查。
- 已知缺口：现有 FDE 产物没有图像资产；S-002 数字层级弱；S-004 闭环语义被通用中心连线破坏；S-008 为三个等权盒子。
- 基线测试：现有八页工程验收通过、产品验收失败，0 Critical / 6 Major。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 先做四页正式样稿，再决定是否扩展全套 | 控制失败成本，并验证首轮质量 | 高 |
| D-002 | Decision | S-001 使用计划内生成图像；S-004 使用计划内精确闭环图资产 | 当前无图像且通用 diagram renderer 不具备正确路由 | 高 |
| D-003 | Decision | S-002 与 S-008 主要通过原生排版层级修复 | 保留可编辑性并验证布局能力 | 高 |
| A-001 | Assumption | 原 FDE 的事实与叙事内容保持有效，本轮只重做视觉表达 | 三轮审计未发现需要改写核心论点 | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| 1 | 独立可写 worktree 与试验 workspace | 已验收提交 | HEAD/tree 与工作区状态 | complete |
| 2 | 修订 Seed/Specs/Layout/Visual System 与资产清单 | 原正式 artifacts | schema 与 hash 校验 | complete |
| 3 | 四页 admitted IR 与 Artifact Tool PPTX | Step 2 | preflight 与渲染输出 | complete |
| 4 | 四页样稿真实 PowerPoint 视觉验收 | Step 3 | 四页逐页检查 | complete |
| 5 | 余下四页的 P5/P6 正式扩展 | 用户批准样稿 | 同一 admitted IR、页面角色差异 | complete |
| 6 | 完整八页 PowerPoint 视觉验收 | Step 5 | 八页逐页检查、Critical/Major=0 | complete |

## 5. Quality and risk controls

- 受影响 Schema：不修改 schema；所有修订 artifact 必须继续验证。
- 受影响 Gate：设计传播、资产解析、布局与目标渲染检查。
- 回归范围：FDE 完整八页候选、正式 Host Create 状态链与受影响仓库测试；不宣称 legacy G7/M5 release approval。
- 降级路径：四页样稿不达标即停止，不生成全套候选。
- 安全/来源/版权风险：封面图为本轮生成资产；闭环图为项目内原创矢量转栅格资产；不引入第三方受限素材。

## 6. Verification

```bash
PYTHONPATH=src python -m slidethus.cli validate <trial-workspace> --check-hashes
node .agents/skills/slidethus/scripts/render_artifact.mjs --input <ir> --output <pptx>
# 然后在 Microsoft PowerPoint 中逐页检查。
```

- 期望结果：S-001 有明确图像叙事；S-002 大数字形成第一视觉层级；S-004 闭环可读且回路不穿节点；S-008 不再是三等分盒子。
- 实际结果：四页样稿目标与余下四页的角色化构图均在 Artifact Tool 与 PowerPoint 实际导出中可见。完整候选为 `candidate-f811whkm`，PPTX SHA-256 为 `2f04c5930211f2763b31eb1edc7b23fb5e50b837ab03b7ed3f65127663ee6a8b`，PowerPoint PDF SHA-256 为 `f90a2993a4915f0fcda35fd1bed60dc80b4b50959e90a272c37b007a6a8e3cb4`，共 8 页。
- 仓库检查：Python 3.11.11；`compileall`、`ruff`、`validate_all.py`、`audit_package.py` 均通过；全量 `pytest` 为 430 passed、44 skipped。
- 环境说明：首次全量 `pytest` 因新 worktree 未安装 renderer 的锁定 Node 依赖而出现 M4/M5 两个连锁失败；执行 `npm ci` 后，原失败文件 12/12 通过且全量复跑 exit 0。安装过程报告 `image-size` 既有依赖的 2 个 high-severity 公告，本轮未越界升级生产依赖。

## 7. Review

### 第一轮：开放问题发现

- Critical：0。
- Major：2。PowerPoint 首次实际导出发现 S-001 标题末字“岗”孤行，S-008 第 30 天正文句号孤行；Artifact Tool 预览不足以替代该检查。
- Minor：S-008 仍属高信息密度行动页，后续扩展时可继续压缩非决策性文字，但不构成本次四页试验阻断。

### 修复记录

- 正式回到 P5/P6：扩大 S-001 标题区域并将标题字号从 60pt 调整为 54pt；保持页面语义与图像构图不变。
- 正式回到 P6：将 S-008 第 30 天正文从 24pt 调整为 22pt；保持 30/60/90 非对称几何不变。
- 重新生成同一 admitted IR / Artifact Tool 候选，并再次用 Microsoft PowerPoint 导出四页 PDF。两项 Major 均消失，无新增碰撞、溢出、孤字或孤标点。
- 修复 Seed 修订跨进程恢复缺陷：同一规划尝试复用已准备的修订 Seed，后续恢复优先使用现有 Slide Specs 引用且 lineage 有效的冻结 Seed，避免旧 Host response 回放覆盖 Taste-generated 方向。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 4 | 四页事实内容未改；闭环顺序与回流语义正确；PowerPoint 逐页检查 | 仅代表四页样本，不代表全套八页 |
| 架构一致性 | 5 | 全部变更经正式 Seed/Specs/Layout/Visual System、同一 IR 与 producer | 无 |
| 可测试性 | 4 | 新增 Seed 修订跨进程回归测试；workspace validate 通过 | Office 视觉仍需人工检查 |
| 可维护性 | 4 | 修复集中在 Seed 选择根因，无补偿性分支链 | 可进一步抽出 Seed 选择策略测试矩阵 |
| 降级与恢复 | 4 | 样本先行，失败即停止扩展；首次 Office 缺陷回到 P5/P6 | 尚未自动化 Office 行宽预测 |

### 完整八页扩展复核

- Artifact Tool 初次余页预检暴露一项 Major：S-006 的四条关系标签被中心节点遮挡。未用缩字或换色绕过，而是回到 P5，将关系动词并入四个外层节点、清空悬浮边标签，保留原生可编辑节点与连线。
- S-003 以深色递进场和 Demo 后断层线表达责任失速；S-005/S-007 使用明暗反向的原生表格；S-006 使用中心放大的约束系统。四页共享视觉语法但不共享同一模板。
- 修订后完整八页在 Microsoft PowerPoint 导出的 8 页、960×540pt PDF 中逐页通过；未发现碰撞、溢出、孤字、孤标点、遮挡或连续页面构图重复。

## 8. Final outcome

- 已完成：完整八页正式候选、生成封面图、原创闭环图、S-003/S-006 原生可编辑图、S-005/S-007 原生可编辑表格、Taste-generated Seed 实质传播、Seed 恢复根因修复、Artifact Tool 与 PowerPoint 双重验收。
- 未完成：没有把 Host candidate receipt 改写为 release approval；其 `office_review` 仍为 `pending`、`release_approved` 仍为 `false`，需要后续正式发布流程另行处置。
- 后续任务：框架侧优先增加 representative-page preflight、Office-aware 文本适配与 diagram-label collision 检查，继续降低人工 P5/P6 往返。
- 相关 ADR：本轮不改变架构，无新增 ADR。

## 9. Approved full-deck expansion

- 用户已认可四页样品并授权扩展剩余页面。
- 受保护元素：八页事实、叙事顺序、稳定 Slide/Block 语义、已批准 S-001/S-002/S-004/S-008 的视觉表达。
- 扩展页面：S-003、S-005、S-006、S-007。
- 基线审计：S-003 的五个节点等权，违反其 `avoid: five equal cards`；S-005/S-007 仍是标准表格直接落版；S-006 的中心生产采用缺少足够层级。
- 最早修复阶段：S-003/S-006 回到 P5A 调整语义图几何；四页回到 P5B/P6 建立与样品一致但不重复的构图节奏。
- 验收边界：生成完整八页候选并逐页检查真实 PowerPoint 页面；Critical/Major 必须为 0，且不把 Host candidate receipt 误称为 legacy G7/M5 release approval。
