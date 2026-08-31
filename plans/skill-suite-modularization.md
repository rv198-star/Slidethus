# Skill Suite Modularization

## 1. Objective

- 用户价值：`using-slidethus` 接受一句话任务并负责到底；用户也可只调用某一阶段。
- 本轮边界：技能指令、共享合同、兼容入口、完整分发和安装验证。
- 明确不做：改 PPT 生成器、语义工件 Schema、Provider、视觉模板、现有案例或发布状态；不新增行业案例，不提交或推送。
- 退出条件：入口与七个子技能可发现，阶段输入/输出/停点清楚，Repo/Plugin/Wheel 安装引用闭合，冲突安装不覆盖用户文件，相关测试通过。

## 2. Current state

- HEAD：`e34b62a`；工作区已有宿主 Create 链路修复、案例及文档改动，全部保留。
- 已有单一 `slidethus` Skill、六种工作流、P0–P9 工件合同和宿主设计入口。
- 分发只安装一个 Skill 目录；直接拆文件会产生缺失的跨技能引用。
- 基线：本轮先检查现有实现；不把此前测试或实际 PPT 认可当作本轮技能行为验证。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 一个入口 + brief/research/story/plan/design/render/review 七个阶段技能 | 复用 P0–P9，不按行业或版式拆分 | 可 |
| D-002 | Decision | 旧 slidethus 为兼容入口；共享资源仍由该目录维护 | 保持 Taste、脚本及调用路径 | 可 |
| D-003 | Decision | 单一主 Agent 按需读技能；不新增 Agent 链或状态机 | ADR-0001/0021 | 可 |
| D-004 | Decision | Wheel 使用 skills/<name> 同级目录；兼容读取旧 share/skill | 保证相对引用与安装结构一致 | 可 |
| A-001 | Assumption | 未指定停点的新建任务按 auto 执行；已有批准模式及用户停点优先 | 一步到位不等于跳 Gate 或扩张授权 | 可 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| 1 | 阶段划分、执行计划、ADR-0030 | 既有合同 | 边界阅读 | completed |
| 2 | 入口、七个子技能、共享合同、兼容入口 | 1 | Skill frontmatter / 引用闭合 | completed |
| 3 | allowlist 完整打包/安装、Wheel 数据、测试 | 2 | 完整安装、缺失/冲突、无仓库运行 | completed |
| 4 | 回归、文档与结果记录 | 3 | required checks、人工路由走查 | completed |

## 5. Quality and risk controls

- 不新增生产依赖；不修改语义工件 Schema 或 Gate 语义。仅 Plugin Manifest 分发路径 allowlist 扩展为完整技能套件，并同步包内镜像。
- 单阶段任务缺少上游时只报告前置条件，不能擅自变成整套生产。
- Audit 不修复；原件/已认可文件只读；修复回到最早责任阶段。
- Taste 原文、MIT License、Provenance 字节不变。
- 不以同色替代风格，不设图片/图表配额；样页不能替代全篇节奏检查。
- 候选预览、实际 Office 视觉验收与集成发布 Gate 分开；缺能力必须报告。
- 安装前检查全部已有目标，任一冲突拒绝；不自动迁移或覆盖旧用户技能。

## 6. Verification

```bash
.venv/bin/python -m pytest tests/test_skill_layout.py tests/test_distribution.py
.venv/bin/python -m pytest
.venv/bin/python scripts/validate_all.py
.venv/bin/python scripts/audit_package.py
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/ruff check src tests scripts
```

- 补充：Skill Creator quick_validate；实际 Wheel 构建/无仓库安装；自然语言路由人工走查。
- 自动化只证明指令/包装结构与分发行为，不冒充模型端到端执行质量或 Office 美学验收。
- 专项测试：25 passed。含真实 BriefCompletionService 写入 auto 且不生成 Outline 的行为验证。
- 九个 Skill Creator quick_validate 全部通过。项目环境缺 PyYAML，使用已有离线 uv 工具环境验证，未添加项目依赖。
- `validate_all`：PASS；`audit_package`：21/21 PASS；compileall、ruff、diff whitespace checks：PASS。
- `validate_m6_3_distribution`：7/7 PASS；完整 suite 共 38 个分发文件。
- 实际 Wheel：`uv build --wheel --offline` 使用符合 pyproject 要求的隔离构建环境成功；旧 `.venv` 的 setuptools 不满足构建要求，未修改许可证配置来兼容旧构建器。
- 仓库外 Python 3.13 环境安装 Wheel 后，`plugin status` 解析全部九个技能，`install-skill` 完整物化，`plugin build` 连续两次字节一致（102 文件，SHA-256 `4fec9091e4e7935f145458e680b099d1e7bc6fe8a1d7be50a1d968835f072b92`）。安装环境是临时测试目标，未覆盖用户全局技能。
- 全量 pytest：365 passed, 43 skipped，681.53s。第一次运行加载了迁移前的验收脚本，M2/M3 路径检查失败；迁移修复后重启进程，以上是最终全量结果，不把旧进程结果计为通过。额外的历史验收负向测试：17 passed, 4 deselected。

## 7. Review

### 开放问题与修复记录

1. Plugin Manifest 原先只接受 `slidethus/` 路径：更新为九个明确模块的 allowlist，并同步 Schema 镜像，没有放开任意兄弟技能。
2. 旧安装代码逐树处理会在后面的模块发生冲突前写入其他模块：改为全套冲突预检；测试证明用户修改保留、未出现半套冲突安装。
3. M2–M5 静态验收仍读取兼容入口正文：迁移到入口和子技能必读的共享合同，保留原能力边界断言；未撤掉验收检查。
4. SBOM 的 Taste 路径只认旧 Wheel 位置：支持新同级套件目录并保留旧位置兼容；仓库外二次打包实测成功。
5. 新初始化 Brief 的 checkpoint 默认值可能让自动入口停顿：用现有 BriefCompletionService 持久化新任务的 auto 选择；不改生成器、CLI 参数或用户已有审批模式。

### 路由与授权人工走查（不是模型执行评测）

| 请求 | 指令推导的路径和停点 | 检查 |
|---|---|---|
| 根据材料直接完成 PPT | using → Brief → Research → Story → targeted Research → Plan → Design → Render → Review；按真实能力交付/报告阻断 | 不止于路由建议；不漏 targeted/P5 |
| 只做页面策划，不生成 | plan，缺少上游则指出必要输入，完成 Specs/Layout 后停 | 不擅自产出 PPTX |
| 看看哪里丑，先别改 | review/Audit 只读分析；建议根阶段动作 | 不启动修复 |
| 先给四页样板，确认后继续 | 同一完整规划/IR 中选择覆盖角色与难页的样页；按用户停点暂停 | 不把样页另起炉灶或当全篇通过 |
| 只改明确页面 | Revise 解析 S-ID、根阶段变更、依赖回归 | 不无声扩大修改范围 |
| 无 PowerPoint 检查能力 | 保留候选与真实检查结果，记录 Office pending | 不用 PNG/修复后删内容文件冒充完成 |
| 展示型但不是科技风 | Brief 定义传播目的；Plan/Design 根据内容选择表达 | 无行业配色、图片/图表配额 |

### 复查结论

- 通用抽象：按既有工件职责分层，不按行业、样例、配色或模型拆分。
- 架构：仍一个主 Agent；无新状态机、生产 Provider、渲染模板或语义工件。
- 可验证性：安装、引用、真实服务调用及失败路径有测试；自然语言理解、实际整篇美学尚未通过本轮新案例评测，不能从格式测试外推。
- 范围：本轮未更改现有 PPT、接受过的视觉样板和渲染生产脚本；未提交、推送或发布。

## 8. Final outcome

- 已完成：一个 using 入口、七个阶段技能、旧入口兼容、共享合同、完整 Repo/Plugin/Wheel 分发与相关验证。
- 新增能力边界：模块化指令与分发，不是新生产后端；完整请求继续执行，单阶段请求明确停点。
- 未在本轮执行：新主题 PPT 端到端模型评测、实际 Office 美学验收、发布。43 个跳过的既有测试不计为通过能力。
- 保持后续边界：由用户的新任务验证实际产出；不为收敛额外扩展行业或场景。本轮没有新增已知 Critical/Major 分发缺陷，项目已有 M6 Release Gate 仍为 DO NOT RELEASE。
- 相关决策：[ADR-0030](../docs/adr/ADR-0030-modular-skill-suite.md)。
