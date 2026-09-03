# Issue #3｜OCI → Codex / PowerPoint 工程交接

## 1. 交接目标

本交接用于让两类环境协同收敛同一个版本：

- **OCI 工程环境**负责 Host Create 的通用机制、Schema、状态恢复、自动化测试、Package Audit 和远端工程分支；
- **Codex + Microsoft PowerPoint 验收设备**负责真实 `@oai/artifact-tool` 候选生成、原始 PPTX 打开、PowerPoint 导出 PDF 和逐页视觉验收。

两端不是并行开发者。生产代码只有 OCI 一处写入权；验收设备发现问题后只记录失败事实和最早责任阶段，不在本地形成第二套补丁。

## 2. 权威代码位置

```text
remote: origin
branch: fix/issue-3-authoritative-rebuild
base: b1af33ccec224c0418f1d9d1f30f06952d16bf5f
```

验收开始前，以远端分支当前 HEAD 为唯一权威，并记录：

```bash
git fetch --prune origin
git rev-parse origin/fix/issue-3-authoritative-rebuild
git rev-parse origin/fix/issue-3-authoritative-rebuild^{tree}
```

不要从以下旧半成品分支复制、合并或 cherry-pick：

- `fix/issue-3-host-create-resume`
- `fix/issue-3-root-cause-repair`

## 3. 本轮工程变化

本轮从干净 `origin/main` 重建，不继承两套旧实现。核心边界为：

1. `.slidethus/host-create/session.json` 持久化一次 Create 的完整初始意图、Source fingerprints、limits、provider identity、pending request/revision 和已验证的 M2/M3 引用；
2. 初始调用后，普通 `slidethus create <workspace>` 表示 Resume；显式不同输入必须在生产工件 mutation 前拒绝；
3. `--revise-brief`、`--revise-sources`、`--revise-stage` 是不同事务；阶段修订绑定被替代工件的 version/content hash，并可跨进程继续；
4. Planning/M2 复用要求 current Phase、accepted current Gate、registry version/hash、provider/policy 和当前 upstream lineage 同时成立；
5. 每次 Create invocation 都有 immutable `started.json` 和唯一 `terminal.json`；Intent revision 的 terminal 同时记录调用前和结果 Session config hash；
6. Slide Specs 与 Layout Plans 使用同一 provider-neutral semantic family；Review 根据可观察 Region geometry 判断拓扑重复，不能靠改名逃避；
7. Host response 在当前边界一次聚合可确定的 Envelope、required field、coverage、family、density 和基础 geometry findings；
8. `rework_required` 返回最早责任阶段、Planning Review 路径、开放 `PRI-*` issue IDs 和合法下一动作。

架构决定见：

```text
docs/adr/ADR-0033-host-create-authoritative-session-and-resume.md
```

## 4. OCI 完成条件

OCI 工程检查点只有在以下项目均通过后才能推送：

```bash
python3 -m pytest -q
python3 scripts/validate_all.py
python3 scripts/audit_package.py
python3 -m compileall -q src tests scripts
ruff check src tests scripts
git diff --check
```

Python 基线为 3.11，Node 基线为 22。真实 `@oai/artifact-tool` 与 PowerPoint 不属于 OCI 可伪造的通过项。

## 5. 验收设备工作边界

验收设备应在**新的干净 worktree**中检出远端分支，不能切换或覆盖已有脏工作区：

```bash
git fetch --prune origin
git worktree add ../Slidethus-issue3-accept \
  origin/fix/issue-3-authoritative-rebuild
cd ../Slidethus-issue3-accept
git status --short --branch
git rev-parse HEAD
git rev-parse HEAD^{tree}
```

随后按以下文件执行：

1. `plans/issue-3-codex-powerpoint-acceptance.md`
2. `audit/issue-3-codex-powerpoint-acceptance-template.md`
3. `.agents/skills/slidethus/references/host-create.md`

验收设备不得提交：

- 私有 `@oai/artifact-tool`、`node_modules` 或 Codex Runtime；
- 字体文件；
- 用户敏感 Source；
- 未经授权的大型 PPTX/PDF/完整工作区；
- 为单个案例增加的生产代码补丁。

## 6. 必须完成的真实验收

1. `slidethus doctor` 实际识别 Node、`RUNTIME_NODE_MODULES` 和 `@oai/artifact-tool` 版本；
2. 真实 Artifact Tool 集成测试不得 skip；
3. 使用一个未参与规则编写的全新真实案例，从空工作区开始完成多轮 Host response；
4. 初始调用后只用短命令 Resume；
5. 至少执行一次受控 `slide_specs` 修订，并验证 Session/Intent/上游工件不变量；
6. Sample 和 Full candidate 消费同一正式 Renderer IR；
7. 直接用 Microsoft PowerPoint 打开原始 Full PPTX，无修复对话框；
8. 检查页数、字体、媒体、图表、表格、可编辑性、裁切、碰撞、层级和跨页节奏；
9. 由 PowerPoint 原生导出 PDF，核对页数和内容；
10. 填写验收模板并给出分层结论。

## 7. 结果回传

验收结果使用独立分支：

```text
accept/issue-3-codex-powerpoint
```

只提交填写后的审计报告和必要、脱敏、获准的小型证据。报告必须分别给出：

- Engineering control chain：PASS / FAIL
- Artifact Tool production：PASS / FAIL
- PowerPoint technical acceptance：PASS / FAIL
- Visual acceptance：PASS / FAIL
- Issue #3：KEEP OPEN / CLOSE
- M6 / v1.0：DO NOT RELEASE / eligible for next gate

如出现 Critical/Major，先完成整次 Production Attempt 和 Review Synthesis，再把问题归因到 P0/P2/P3/P4/P5A/P5B/P6/P7。OCI 仅接受抽象机制修复，不接受案例、页码、行业或原句特判。

## 8. 当前发布边界

在真实 Artifact Tool 与 PowerPoint 验收完成前：

```text
Issue #3: Open
M6 Exit: Reopened
v1.0: DO NOT RELEASE
```

结构、Schema、模拟候选或 Artifact Tool 自身 PNG 均不能替代原始 PPTX 的 Microsoft PowerPoint 全篇验收。
