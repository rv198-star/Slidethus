# Issue #3 — Codex Artifact Tool / PowerPoint 集成验收

Status: prepared; execute only after the engineering branch is pushed

## 1. Purpose

本计划用于把 OCI 上完成的通用工程修复交给一台同时具备以下能力的本地设备做真实集成验收：

- Codex 宿主实际暴露 `@oai/artifact-tool`；
- Node 与该运行时架构匹配；
- Microsoft PowerPoint 可直接打开、播放和导出候选文件。

本计划不是第二套开发分支。OCI 保持框架代码单一写入权；本地设备只生成候选、执行验收并落盘证据。若发现问题，先完成整次 Production Attempt 和 Review Synthesis，再把抽象根因交回 OCI 修复，不在验收设备上增加场景补丁。

## 2. Collaboration contract

### OCI owner

- 维护 `fix/issue-3-authoritative-rebuild`；
- 完成 Python 3.11 全量测试、Schema/Package 审计、diff review；
- 提交并推送工程检查点；
- 根据本地验收证据决定是否继续修改通用框架。

### Codex / PowerPoint acceptance owner

- 从远端检查点创建独立验收分支或保持 detached HEAD；
- 不修改 `src/`、`schemas/`、Skill 或测试；
- 在 `dist/acceptance/issue-3/` 创建工作区和候选；
- 记录 Artifact Tool、Host Create、PowerPoint 和 PDF 的真实证据；
- 只提交小型审计报告、哈希和必要截图引用，不提交私有运行时、字体、用户敏感源文件或大型候选，除非另有明确授权。

若验收需要代码修复，停止在失败事实，不在本地形成竞争实现。由 OCI 更新同一工程分支后，本地拉取新提交并重新执行。

## 3. Admission checks

在仓库根目录执行：

```bash
git fetch --prune origin
git switch --detach origin/fix/issue-3-authoritative-rebuild
git status --short --branch
test -z "$(git status --porcelain)"
git rev-parse HEAD
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/ruff check src tests scripts
.venv/bin/python -m pytest -q \
  tests/test_host_create_records.py \
  tests/test_host_design.py \
  tests/test_m3_application.py \
  tests/test_layout_planning.py \
  tests/test_planning_review.py
.venv/bin/slidethus doctor
```

`doctor` 必须实际报告 Artifact Tool 的 Node、`node_modules` 和版本。仅安装 Codex CLI、仅存在 Presentations Skill、或仅有 Node 不算通过。记录 `doctor` 报告的准确路径；若运行时由 Codex 自动发现但当前 shell 尚未设置环境变量，则按报告值显式导出，确保命令行测试与正式渲染消费同一运行时：

```bash
export RUNTIME_NODE='<doctor-reported node path>'
export RUNTIME_NODE_MODULES='<doctor-reported node_modules path>'
```

如 Codex 宿主已经通过环境变量暴露运行时，先保留其原值并验证：

```bash
printf '%s\n' "$RUNTIME_NODE"
printf '%s\n' "$RUNTIME_NODE_MODULES"
test -x "$RUNTIME_NODE"
test -f "$RUNTIME_NODE_MODULES/@oai/artifact-tool/package.json"
```

禁止把该私有运行时复制进仓库、Wheel、Plugin ZIP 或验收报告。

## 4. Real backend smoke

先运行仓库内真实 Artifact Tool 适配器测试：

```bash
.venv/bin/python -m pytest -q \
  tests/test_host_design.py \
  -k real_artifact_sample_and_full_share_ir_and_embed_media
```

要求：

- 测试不得 skip；
- full/sample 消费同一 Renderer IR；
- PPTX 内嵌媒体、图表数据和字体序列化检查通过；
- Host candidate receipt 为 `candidate_office_review_pending`；
- 该结果仍不等于 PowerPoint 通过。

## 5. Fresh-case production attempt

选择一个未参与本轮生产规则编写的真实案例。不要使用本轮测试夹具、Issue #3 的精确原句、页码或一套专门为通过 Gate 设计的材料。

推荐工作区：

```text
dist/acceptance/issue-3/fresh-case/
```

第一次调用必须显式提供完整意图和来源：

```bash
.venv/bin/slidethus create \
  dist/acceptance/issue-3/fresh-case/workspace \
  --title '<deck title>' \
  --source '<absolute source path>' \
  --request '<purpose, audience, desired outcome, delivery context and page target>'
```

之后每次根据 `pending.request_path` 读取完整请求、写入对应 `response_path`，普通续跑只执行：

```bash
.venv/bin/slidethus create dist/acceptance/issue-3/fresh-case/workspace
```

不得重复第一条长命令。此处验证 Session 是唯一权威，而不是依赖聊天历史或命令重放。

Production Attempt 先完整运行到 `design_ready`、真实硬阻断或 `rework_required`。若命中 Planning Review：

- 保存 Review 路径、root phase 和全部 open issue IDs；
- 不在当次 Attempt 内直接修改框架；
- 使用现有 `--revise-stage` 完成经授权的阶段修订；
- 普通续跑继续同一 pending revision。

## 6. Mandatory controlled revision

第一次达到 `design_ready` 后，至少执行一次受控阶段修订。默认使用 `slide_specs`，除非真实问题明确归属于其他阶段：

```bash
.venv/bin/slidethus create \
  dist/acceptance/issue-3/fresh-case/workspace \
  --revise-stage slide_specs
```

修订请求必须绑定被替代工件的 version/content hash。提交新 response 后，只用普通续跑命令继续。

验收以下不变量：

- Session ID 不变；
- `intent_revision` 不因 phase revision 改变；
- Brief、Source 和 Evidence 不被无故重写；
- 旧 targeted M2 fact 若不再绑定当前 Specs，必须重跑而不能复用；
- 下游 Layout、Visual 和候选按依赖重新生成；
- 每次 `create` 都有一个 started fact 和唯一 terminal fact；
- `pending_revision` 在成功完成后清空。

## 7. Sample and full candidate

先从同一正式 Renderer IR 生成具有代表性的样板页，再生成全篇：

```bash
.venv/bin/slidethus create \
  dist/acceptance/issue-3/fresh-case/workspace \
  --render --slide-id S-001 --slide-id '<difficult slide id>'

.venv/bin/slidethus create \
  dist/acceptance/issue-3/fresh-case/workspace \
  --render
```

样板应包含至少一页高密度、表格、图表、图片或复杂关系页，不能只选择封面。

生成后执行：

```bash
.venv/bin/slidethus validate \
  dist/acceptance/issue-3/fresh-case/workspace --check-hashes
.venv/bin/slidethus status \
  dist/acceptance/issue-3/fresh-case/workspace
```

记录：

- commit SHA；
- OS/CPU；
- Node 版本；
- Artifact Tool 版本；
- Session ID、intent revision、session revision；
- sample/full candidate receipt 路径和 SHA-256；
- Renderer IR、PPTX、全部 preview/layout 文件的 SHA-256；
- operation started/terminal 数量与状态；
- Planning Review、M2 orientation/targeted report refs；
- 生成耗时和任何 capability warning。

## 8. Microsoft PowerPoint acceptance

必须直接打开原始 full candidate PPTX，不能先用 LibreOffice、修复脚本或 PowerPoint“打开并修复”后的副本替代。

### Technical checks

- 无文件修复、损坏或兼容性对话框；
- 页数与 receipt/Renderer IR 一致；
- 所有文本、图片、图表、表格、图解和页码存在；
- 字体替代与回执一致，无缺字；
- 无裁切、越界、重叠、负尺寸或不可见核心对象；
- 图表数据和标签正确；
- 关键对象达到声明的编辑等级；
- PowerPoint 原生导出 PDF 成功，PDF 页数一致。

### Visual checks

逐页并跨页检查：

- 第一眼层级是否明确；
- 单页核心命题是否可识别；
- 构图是否表达该页的信息关系；
- 字号、行长、对比度和投影可读性；
- 图片裁切与主体位置；
- 表格和图表的阅读顺序；
- 配色、字体和图形语言一致；
- 页面节奏是否变化但不失统一；
- 不同 family 名称是否真实对应不同几何关系；
- 不存在连续页面机械重复同一拓扑。

PowerPoint 导出的 PDF 仅用于复核和留证，不能替代首次原始 PPTX 打开检查。

## 9. Accepted-baseline regression

Fresh case 用于证明 Issue #3 的一般冷启动、续跑和修订链路。进入发布判断前，还需要对一份既有用户认可的正式 Host Create 案例做隔离重放，优先使用 YU7 基线：

- 从保存的 Source 与原始 intent 在新的 ignored acceptance workspace 重新启动 Host Create；不要把缺少新 Session 的旧工作区静默接管；
- 保留原认可候选只作逐页对照，不覆盖原文件；使用同一 commit 和真实 Artifact Tool 重新生成；
- 对原认可候选与新候选记录逐页程序预览差异；
- 在 PowerPoint 中检查无修复弹窗、媒体/字体/图表/表格和全篇视觉无 Critical/Major 回归；
- 任何差异都说明具体页、对象、预期原因和是否需要框架归因，不能只写“基本一致”。

Fresh case 通过可以支持 Issue #3 控制链关闭；既有认可基线无回归通过后，才可进入下一步 M6/发布判断。二者不得互相替代。

## 10. Evidence report

在验收设备创建：

```text
audit/issue-3-codex-powerpoint-acceptance.md
```

至少包含：

```markdown
# Issue #3 Codex / PowerPoint Acceptance

- Commit:
- OS / CPU:
- Python / Node:
- Artifact Tool:
- PowerPoint:
- Case and source hashes:
- Session ID / intent revision:
- Controlled revision:
- Sample receipt / SHA-256:
- Full receipt / SHA-256:
- PPTX / PDF SHA-256:

## Deterministic result
- Host Create session/operation validation:
- M2/M3 currentness:
- Candidate integrity:

## PowerPoint technical result
- Opened without repair:
- Slide count:
- Fonts/media/charts/tables/editability:
- PDF export:

## Visual review
| Severity | Slide | Earliest phase | Finding | Evidence | Verification after repair |
|---|---|---|---|---|---|

## Conclusion
- Engineering control chain: PASS/FAIL
- Artifact Tool production: PASS/FAIL
- PowerPoint technical acceptance: PASS/FAIL
- Visual acceptance: PASS/FAIL
- Issue #3 closure recommendation: KEEP OPEN/CLOSE
- M6 / v1.0 decision: DO NOT RELEASE/eligible for next gate
```

截图或大型文件存放在 ignored acceptance directory，并在报告中记录相对路径和 SHA-256。不要提交字体文件或 Codex runtime 文件。

## 11. Exit and return to OCI

只有以下四层分别明确通过，才建议关闭 Issue #3；进入新的发布 Gate 还必须追加既有认可基线无回归：

1. Session/Resume/Revision/Operation 工程控制链；
2. 真实 Artifact Tool sample/full production；
3. 原始 PPTX 的 PowerPoint 技术验收；
4. 新案例全篇视觉验收，无 Critical/Major。

任一层失败时，报告应保留最早责任阶段和具体证据。OCI 先做整次归因和抽象修复；本地设备在新提交上复跑。旧候选、旧 PowerPoint 结论和 synthetic runtime 测试不能自动批准新 commit。
