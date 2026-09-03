# Issue #3｜Codex Artifact Tool + PowerPoint 验收记录

> 本文件由正式验收设备填写。验收设备只执行已推送的实现提交并记录证据，不在该设备临时修改生产代码。

## 1. 不可变输入

- 实现分支：`origin/fix/issue-3-authoritative-rebuild`
- 实现 commit：
- 实现 tree：
- 验收日期：
- 操作者：
- 操作系统 / 架构：
- Python：
- Node：
- Microsoft PowerPoint 版本：
- `@oai/artifact-tool` 版本：
- `RUNTIME_NODE`：已验证 / 未验证
- `RUNTIME_NODE_MODULES`：已验证 / 未验证

开始验收前必须确认：

```bash
git fetch --prune origin
git switch --detach origin/fix/issue-3-authoritative-rebuild
git status --short
git rev-parse HEAD
git rev-parse HEAD^{tree}
```

要求：工作区为空，HEAD 与本记录一致。

## 2. 工程与运行时预检

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m compileall -q src tests scripts
ruff check src tests scripts
python -m pytest -q \
  tests/test_host_create_records.py \
  tests/test_host_design.py \
  tests/test_m3_application.py \
  tests/test_layout_planning.py \
  tests/test_planning_review.py
slidethus doctor
```

- 预检结果：PASS / FAIL
- Artifact Tool package 路径：
- `package.json` SHA-256：
- 失败日志或限制：

真实后端测试必须实际执行且不能被 skip：

```bash
python -m pytest -q tests/test_host_design.py \
  -k real_artifact_sample_and_full_share_ir_and_embed_media
```

- 结果：PASS / FAIL / SKIPPED（SKIPPED 不能通过验收）

## 3. 新案例 Production Attempt

- 新案例名称：
- Source 文件及 SHA-256：
- 初始命令：
- Workspace：仅记录相对或脱敏标识，不提交私有绝对路径
- Host Create Session ID：
- 初始 Session config hash：

逐轮记录：

| Round | 动作 | Pending stage / terminal status | Request hash | Operation ID | 结果 |
|---:|---|---|---|---|---|
| 1 | start |  |  |  |  |
| 2 | resume |  |  |  |  |
| 3 | resume |  |  |  |  |

必须验证：

- 初始调用后，后续普通续跑仅使用 `slidethus create <workspace>`；
- request/source/limits 冲突在生产工件修改前被拒绝；
- 每次调用均有一个 `started.json` 和唯一 `terminal.json`；
- Session `pending_request` 与本轮实际 request hash 一致；
- 任何 Planning Review 阻断均给出最早责任阶段、Review 路径和 `PRI-*` issue IDs。

## 4. 受控阶段修订

必须至少执行一次：

```bash
slidethus create <workspace> --revise-stage slide_specs
```

提交修订 response 后，使用普通命令继续：

```bash
slidethus create <workspace>
```

记录：

- 被替代 Slide Specs version/hash：
- 修订 request hash：
- 修订 Operation ID：
- 新 Slide Specs version/hash：
- Outline 在修订前后是否保持一致：是 / 否
- 旧 targeted M2 report 是否被拒绝或重新验证：
- 下游 Layout / Visual 是否重新生成：
- 修订终态 `resulting_config_hash` 是否等于当前 Session config hash：

## 5. Sample / Full 同源生成

```bash
slidethus create <workspace> --render --slide-id S-001 --slide-id S-003
slidethus create <workspace> --render
```

- Sample receipt：
- Full receipt：
- 两者 Renderer IR path/hash：
- 两者 adapter identity/hash：
- Sample 页是否与 Full 对应页逐字节一致：
- PPTX SHA-256：
- 工具预览页数：
- 所有 render attempt 是否有唯一终态 receipt：

工具自身 PNG 只作为生成事实，不作为 PowerPoint 视觉验收。

## 6. Microsoft PowerPoint 真实验收

必须使用原始候选 PPTX，不得先经 LibreOffice、Keynote 或其他工具重存。

### 6.1 技术完整性

- 打开时是否出现修复提示：否 / 是
- 实际页数：
- 字体替代或缺字：无 / 有
- 图片缺失：无 / 有
- 图表数据/标签异常：无 / 有
- 表格溢出或裁切：无 / 有
- 可编辑对象符合声明：是 / 否
- PowerPoint 导出 PDF：PASS / FAIL
- PDF SHA-256：

### 6.2 全篇视觉审阅

| 维度 | PASS/FAIL | 证据与页码 |
|---|---|---|
| 核心命题与层级 |  |  |
| 字号与可读性 |  |  |
| 构图与留白 |  |  |
| 信息关系表达 |  |  |
| 跨页一致性 |  |  |
| 布局与节奏多样性 |  |  |
| 图片/图表/表格质量 |  |  |
| 无溢出、碰撞、裁切 |  |  |

逐页 Critical/Major：

| Slide ID | Severity | 观察 | 最早责任阶段 | 验证方式 |
|---|---|---|---|---|
|  |  |  |  |  |

## 7. 结论

只允许以下结论之一：

- `PASS`：真实 Artifact Tool 与 PowerPoint 技术验收均通过，且全篇 Critical/Major 为 0；
- `ENGINEERING PASS / PRODUCT FAIL`：控制链正确，但真实视觉仍有 Critical/Major；
- `BLOCKED`：运行时、PowerPoint、字体或资产能力不足，不能形成有效结论；
- `FAIL`：控制链、候选完整性或 PowerPoint 技术完整性失败。

最终结论：

- Issue #3 是否可关闭：是 / 否
- M6 是否仍为 Reopened：是 / 否
- v1.0 是否仍为 `DO NOT RELEASE`：是 / 否
- 未解决问题：

## 8. 回传边界

只提交本记录及必要的小型、脱敏验收证据。不得提交：

- 用户 Source；
- 工作区完整副本；
- 私有 `@oai/artifact-tool` 包或 `node_modules`；
- 字体文件；
- 含敏感绝对路径、令牌或账号信息的日志；
- 未经授权的候选 PPTX/PDF/截图。

建议验收分支：`accept/issue-3-codex-powerpoint`。验收提交只包含报告与授权证据，由 OCI 工程分支以 report-only cherry-pick 回收。
