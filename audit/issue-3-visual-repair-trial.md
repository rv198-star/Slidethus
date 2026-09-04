# Issue 3 Visual Repair Trial Audit

## Verdict

完整八页候选通过本轮 PowerPoint 视觉验收，但不等于 v0.8.0 release 已获批准。最终 PowerPoint 实际导出中，S-001 至 S-008 均无碰撞、溢出、孤字、孤标点或图形遮挡；Taste 方向已经从原生视觉原型传播到正式 page plans、visual system、planned assets 与 rendered pages。

## Scope and provenance

- 基线提交：`d0e1dde26b69210caafc6940bfb44a9bf2f3fc63`。
- 独立分支：`codex/issue3-visual-repair-trial`。
- 原脏工作区与只读验收 worktree 均未修改。
- 正式范围：先验收 S-001、S-002、S-004、S-008 样稿，再按用户授权扩展并验收完整 S-001 至 S-008。
- renderer：Artifact Tool `2.8.59`；PPTX 和 PNG 来自同一 admitted IR / producer。
- 最终候选：`candidate-f811whkm/candidate.pptx`，SHA-256 `2f04c5930211f2763b31eb1edc7b23fb5e50b837ab03b7ed3f65127663ee6a8b`。
- PowerPoint 导出：`candidate-f811whkm/candidate-office.pdf`，SHA-256 `f90a2993a4915f0fcda35fd1bed60dc80b4b50959e90a272c37b007a6a8e3cb4`，8 页，960×540pt。
- PowerPoint contact sheet：`candidate-f811whkm/office-contact-sheet.png`，SHA-256 `1f075447f326580c979017a222b6fb7f0dc0cd23998bd512225de431daab4d05`。
- 正式 artifacts：Slide Specs v10、Layout Plans v11、Visual System v12；workspace hash validation PASS。

## Material visual propagation

| 页面 | 传播结果 | PowerPoint 证据 |
|---|---|---|
| S-001 | Taste-driven 暗色工业封面；生成背景图；左文右图、不对称留白 | 标题不再孤字；图像构成主叙事载体 |
| S-002 | “5”建立第一视觉层级，“3”为次级；证据与限制分区 | 数字强弱和研究边界清晰，未退回等权卡片 |
| S-004 | 原创五阶段闭环图；回流线不穿节点；产品化学习被强调 | 顺序、回流方向和成功标准同时可读 |
| S-008 | 30 天主块与 60/90 天次块形成非对称节奏 | 第 30 天句号孤行已消失，行动与停止条件可读 |
| S-003 | 深色责任进阶场；节点尺寸逐步增长；锈红断层线标记 Demo 后失速 | 五阶段连续关系可读，不再是五个等权卡片 |
| S-005 | 冷灰证据场上的深色原生责任表 | 与样稿同一语言，责任列保持主导且可编辑 |
| S-006 | 中心放大的原生约束系统；四层关系动词并入外围节点 | 关系标签无遮挡、连线不穿文字、中心焦点明确 |
| S-007 | 深色决策场上的浅色原生门槛表 | 与 S-005 明暗反向，停止信号和页面节奏可辨 |

## Root cause confirmed during repair

`HostPlanningProvider.prepare_art_direction_seed()` 在一次 Slide Specs 生成中可能被调用两次。第一次已接收修订 Seed，第二次却再次查询 Host provider；跨进程恢复时又可能回放原 Seed response，导致新 Taste-generated Seed 被旧冻结方向覆盖。该缺陷能直接解释“记录上调用了 Taste，但正式下游未持续使用”的现象。

修复后：同一 attempt 缓存并验证已准备 Seed；没有显式 Seed revision 时，优先复用现有 Slide Specs 所引用、且对当前 Brief/Outline lineage 有效的冻结 Seed。回归测试覆盖 Seed 修订响应、Slide Specs 请求和下一进程 Layout Plans 恢复。

扩展过程中另确认一个执行环境风险：仓库采用 `src/` 布局，若误用 `PYTHONPATH=$PWD`，Python 会静默导入另一 worktree 中已安装的旧 Slidethus，从而表现为“新 Seed 已生成但运行时仍使用旧逻辑”。验收命令统一改为 `PYTHONPATH=$PWD/src`，并将该规则写入 `AGENTS.md`。

## First-pass control finding

首次正式候选在 Artifact Tool 侧看似可用，但 PowerPoint 实际导出暴露两项 Major：封面标题末字“岗”孤行、行动页句号孤行。本轮只做了一次最小 P5/P6 修订，两项缺陷均消失。由此得出的结论不是“Gate 没阻断所以通过”，而是：

1. representative pages 必须先证明图像、层级、语义几何和构图，再扩整套；
2. 目标渲染必须进入首轮质量控制，结构 Gate 只能作安全网；
3. 冷启动一次通过仍需 Office-aware 文本适配，不能把人工 P6 往返常态化。

## Decision

- 允许：在用户确认样本方向后，受控扩展到余下四页。
- 不允许：仅凭本四页把整套八页标记为 `release_approved`。
- 下一优先级：把 representative-page sample gate 与 Office-aware 行宽/标点适配放入正式流程，再扩大更多案例。

## Verification record

- Python 3.11.11。
- `python -m compileall -q src tests scripts`：PASS。
- `ruff check src tests scripts`：PASS。
- `python scripts/validate_all.py`：PASS，16 schemas、example workspace、G0–G6、G7 negative control、3 wireframes。
- `python scripts/audit_package.py`：PASS，21/21 checks。
- 全量 `PYTHONPATH=$PWD/src python -m pytest`：430 passed、44 skipped，exit 0。
- 首次全量测试曾因新 worktree 缺少锁定的 renderer Node dependencies 导致 M4/M5 两个环境性失败；`npm ci` 后原失败文件 12/12 通过，随后全量复跑通过。`npm ci` 同时报告 `image-size` 依赖的 2 个 high-severity 公告；未在本次视觉修复范围内擅自升级。

## Remaining-page baseline audit

用户批准四页样品后，使用同一 admitted full-deck IR 渲染 S-003/S-005/S-006/S-007 基线候选 `candidate-ee6ltmo7`。发现：

- S-003：五个完全等权节点，与 Slide Spec 自身禁止的 `five equal cards` 冲突，无法表达 Demo 后的责任断层。
- S-005：内容正确，但标准白表格缺乏“责任列主导”的视觉证据，和样品的设计成熟度不一致。
- S-006：四层约束关系正确，中心“生产采用”与外围节点尺寸过近，决策焦点不足。
- S-007：决策矩阵可读，但与 S-005 使用同一通用表格语言，导致全套节奏重复且停止信号不够强。

结论：不能只做 P6 换色；S-003/S-006 应回到 P5A 调整图形几何，四页均需新的 P5B/P6 处理。

## Full-deck expansion result

- S-003：P5 将五节点改为不等宽、不等高的连续采用阶梯，P6 使用石墨背景和锈红断层线，直接表达 Demo 后的责任失速。
- S-005/S-007：保留原生可编辑表格，但分别采用“冷灰底＋深表”和“深底＋浅表”，消除连续页面的同模重复。
- S-006：首次扩展预览发现关系标签被中心节点遮挡，判定 Major。回到 P5 将“部署可行 / 流程可接 / 结果可审计 / 采用可持续”并入外围节点，并清空悬浮边标签；重渲染后遮挡消失，中心节点仍保持视觉主导。
- 完整八页候选来自同一 admitted IR / Artifact Tool producer。Artifact Tool 八页预检与 Microsoft PowerPoint 八页逐页复核均未发现 Critical/Major。

## Final decision

- 本轮结论：完整八页候选达到用户批准方向下的视觉验收标准，可作为后续正式发布验收输入。
- 边界：candidate receipt 仍明确记录 `office_review: pending` 与 `release_approved: false`；本审计不伪造或替代正式发布批准。
- 可编辑性：S-003/S-006 为原生可编辑图，S-005/S-007 为原生可编辑表；S-001 封面图与 S-004 闭环图按 E2 目标使用计划内栅格载体。
