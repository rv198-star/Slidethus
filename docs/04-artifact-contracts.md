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

M2 的生产摄取不会把全部正文复制进 Source Ledger。正文、稳定 Chunk IDs、格式原生 locator、内容哈希、`parsed/partial`、warning 和 source risks 写入 `source_snapshot.schema.json` 校验的运行时快照，再由 Ledger 的 `ingestion` 字段引用。快照 key 绑定 source ID、来源字节、parser、格式与全部解析限额；路径已存在时不得覆盖。

来源正文未变化时可以复用快照，但 title、ownership、confidentiality、authority 或 allowed-use 的变化仍必须创建新的 Source Ledger 版本。Parser 版本或解析限额变化会创建新快照。`source_id` 不允许重绑到另一文件，同一路径不允许创建第二个 source ID。

为兼容 M0/MVP 示例，旧记录可以没有 `ingestion`；由 M2 ProductionImpl 新建、`content_hash` 使用 `sha256:` 前缀且状态为 `parsed` 或 `partial` 的记录必须引用有效快照。`partial` 不是失败，而是严格的覆盖边界：后续 Evidence 只能使用快照中真实存在的文本/元数据，并携带 warning，不得把图片元数据冒充 OCR、把公式文本冒充计算结果或把未提取评论/媒体视为不存在。

M2.2 的解析限额覆盖来源字节、Chunk、risk、页、幻灯片、工作表、行、单元格、ZIP 条目、单个 ZIP 成员、总展开字节和图片总像素。这些限额进入 snapshot lineage；任一限额变化都会重新解析，而不是复用旧快照。

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

`unsupported` 或 `disputed` 声明不能作为确定事实进入页面。研究分为方向性与逐页定向两次执行，但最终仍写入同一个 Evidence Ledger。`research_cycles` 记录语义上的研究类型、状态、来源和对应 outline 版本。

M2.3 已增加独立的 Research Runtime：`research_run.schema.json` 持久化 plan/provider/task lineage，`research_cache_snapshot.schema.json` 持久化不可变 query results，并提供 TTL、generation invalidation 和 resume。两者都是运行时事实，不是 Evidence Ledger 的替代品。**Research Run complete 只表示查询执行完成，Research Result 也不等于已验证 Evidence。**

M2.4 Production Evidence claim 进一步记录：

- `claim_key`：保守 exact-normalized claim identity；
- `candidate_refs` 与 `candidate_bindings`：Candidate ID 及其 Source/Chunk/hash、Research、conflict 和 freshness lineage；
- `source_refs[].chunk_id/content_hash`：当前来源内容绑定，而不只是一段可漂移的 locator；
- `authority_decision`、`freshness_decision` 与 reason codes；
- `conflict_group/conflict_stances`；
- adjudication engine/version 与最终 `use_policy`。

Research Result 必须先物化为 `partial` Web Source；未抓取网页正文的 provider summary 只能形成 indirect/provisional Evidence。`unsupported`、`disputed`、metadata-only 或 do-not-use 来源必须得到 `do_not_use`。Source 更新后旧 Production Evidence 可保留历史 ID，但会降级或触发 G2 stale-lineage 阻断，不能静默保持可用。

`research_cycles.run_ids` 指向完成的 Research Runs；语义 cycle 只有在所有结果已物化并有非 `do_not_use` Evidence 后才 complete。完成操作聚合 query count 且必须幂等。详细决策见 ADR-0012。

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

M3 Production Narrative 还必须包含 approved status、story rationale、proof strategy、call to action、section thesis/slide budget/status，以及 `planning_lineage`。Lineage 绑定当前 Project Brief/Evidence 版本与 claims semantic hash；Evidence claims 变化会使 G3 stale，单纯 research-cycle 操作元数据变化不会强制重写故事。

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

M3 Outline 把页面建模为稳定数字便利贴：`S-*` 与 ordinal 分离，支持 active/excluded/frozen、locked fields、derived-from、audience question、content scope、Evidence requirement/qualification 和 estimated minutes。显式操作写入 `operations_applied` 并通过 content-addressed `planning_change_report.schema.json`（`PCH-*`）保存 payload、limits、idempotency、input/output Outline refs 与 mappings。

### 4.6 Slide Specs

回答：一页内部应该表达什么。

每页包括：

- core message；
- audience question；
- content blocks；
- block priority；
- evidence bindings；
- optional `evidence_requirement`（required/optional/none）；
- `evidence_qualification` for provisional/inference/assumption/stale support；
- visual intent；
- speaker notes；
- density budget；
- editability intent。

它不包含最终颜色、字体和绝对坐标。

M3 Production Slide Specs 还记录 `outline_slide_ref`/semantic hash、stable Block identity、`claim_mode`、Block content hash、frozen status 和 current `planning_lineage`。Factual Block 只能使用 Outline 已声明且 policy-usable 的 Evidence；qualified support 必须携带可见 qualification，Provider 不能通过正文扩写创造新事实。

Reviewed/critical Designed Create 使用 Slide Specs 0.2。每页必须拥有一个 closed、discriminated `representation`，kind 为 `text / typographic / image / chart / table / diagram / mixed`。Specs 是 carrier reason、visual weight、density role 以及 chart series/categories、table hierarchy、diagram nodes/edges、image narrative role 等语义事实的唯一 owner。它不得保存最终坐标、P6 style/component ID，renderer 也不得在缺字段时自行推断载体或拓扑。Legacy 0.1 Specs 仍可供明确 controlled path 读取，但不能通过新 G5A。

M2.5 在 G5A 前重新计算当前 Outline/Slide Specs 的 block-level Evidence gap：required factual block 必须绑定已知、可用 Evidence；required slide 的 Evidence 必须落实到具体 block；qualified Evidence 必须有显式 qualification。结果写入非 catalog 的 `evidence_gap_report.schema.json` 运行时事实，并可生成 targeted Research Plan 或走正式 `OUTLINE_READY/SLIDE_SPECS_READY → EVIDENCE_READY` 返工。

M2.6 另外发布非 catalog 的 `m2_application_report.schema.json` 运行时事实，回答“这次 M2 应用实际做了什么、缺什么能力、为什么降级或阻断、最后停在哪个 Gate”。它绑定 Project Brief、final Project State revision、Source/Evidence/Planning artifacts、requested Source fingerprints、完整 application config/limits、Gap Report、capability/security decisions 与 Gate evaluations。每个 Research Run 以 content-addressed 快照固化到 `.slidethus/m2/research-runs/`，并继续引用不可变 Research Cache；Application Report 位于 `.slidethus/m2/runs/`。

M3 新增三类非 catalog 审计事实：

- `planning_review_report.schema.json`（`PRV-*`）：绑定当前六类 planning inputs，记录具体 issues、最早责任阶段、repairability 和 dimension scores；
- `planning_repair_report.schema.json`（`PRP-*`）：绑定 source/result Reviews、selected issues、limits/provider、change/actions 和 remaining issues；
- `m3_application_report.schema.json`（`M3R-*`）：绑定 Brief hints、M2 reports、最终 planning artifact set、Review/Repair、wireframes、Project State 和 G0/G2/G3/G4/G5A/G5B。

这些运行时事实分别位于 `.slidethus/planning/reviews/`、`.slidethus/planning/repairs/` 和 `.slidethus/m3/runs/`。它们不是 Quality Report、Render Manifest 或 Delivery Manifest，不能被用来声称 M4/M5 完成。

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

M3 Production Layout 还绑定 current Slide Specs semantic hashes、stable `REG-*`、每个 Block 的一一映射、capacity/content units、minimum font floor、collision/safe-area/coverage diagnostics 和 `planning_lineage`。每页灰模以 content-addressed SVG 写入 `.slidethus/planning/wireframes/`；Layout artifact 只引用路径与 SHA-256，不把灰模冒充最终视觉。

Layout Plans 0.2 只引用 matching representation ID，并拥有 focal order、reading path、negative-space target 和载体 view geometry：chart orientation/labels/legend、table header/emphasis、diagram ports/routing/label anchors、image fit/crop/focal point。它不复制 series、nodes/edges 或 table schema。系统由 frozen Seed/Specs/Layout 生成 content-addressed semantic SVG 与 `SemanticPreviewReceipt`；预览必须把真实 chart orientation、table hierarchy、diagram topology、image crop/focal placeholder 和视觉权重画出来，raw JSON 或等权占位框不构成 reviewed/critical G5B 证据。

`PlanningReviewReport` 0.2 在原 deterministic planning facts 之外绑定精确 VisualAdmissionPolicy、SemanticPreviewReceipt、reviewer identity、immutable `VisualQualityReview` 和 workflow-derived `VisualQualityDecision`。Qualitative review 负责 carrier fitness、focal hierarchy、page distinction 与 deck rhythm；它是 P5 admission，不是 P8 Quality Report。

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

#### 4.8.1 Art Direction Packet

`ArtDirectionPacket` 是 P6 中位于 provider proposal 与 Visual System 之间的不可变运行事实，不是 renderer 输入替代品。它必须记录：

- `ADP-*` stable identity、provider name/version/mode；
- design read 与 variance/motion/density dials；
- palette、typography、composition、image direction 与 forbidden patterns；
- Brief、Outline、Slide Specs、Layout Plans、Asset Manifest 的完整 version/content-hash lineage；
- bundled Skill 的 path/hash/upstream commit/license（若 provider 使用随包资源）；
- warnings、assumptions 与 deterministic timestamp。

若 designed Host Create 使用原生视觉样板，P5A 前还会冻结 supporting runtime fact `ArtDirectionSeed`：`.slidethus/art-direction/seeds/<sha256>.json`。它绑定 Brief/Outline，逐页声明 `image`、`chart`、`diagram`、`table`、`typographic` 或 `textual` 载体及 `plain`、`tonal`、`field`、`image-led` 表面节奏。它不拥有内容、Evidence、资产或 Region。`taste-generated` 必须带 workspace 内原生样板的相对路径、媒介和 SHA-256；资源随包或固定 token 只能标为 `resource-only` / `taste-informed`。Slide Specs 与最终 Packet 只保存同一 immutable Seed reference。

Packet 写入 `.slidethus/art-direction/packets/<sha256>.json` 后不可覆盖。Visual System 只引用 Packet ID/path/hash、provider identity 和（若有）Seed reference，并把已准入方向编译为正式 tokens/page designs。Taste 是默认 provider，但 Packet schema 不出现供应商专属字段。

Reviewed/critical 使用 ArtDirectionPacket/Visual System 0.2 的 closed grammar。Packet 唯一拥有 page family、component variant 与 style IDs；Visual System 将相同 style ID 映射到相同 concrete style，并绑定 producer capability ID/hash。`semantic-fallback`、family/variant 不匹配、未绑定 style、隐式 image fit、隐式 chart/table view 或 diagram routing 均是阻断。Renderer IR 0.2 必须逐页记录 family/variant/representation/view 和 source decision → style/slot/asset → concrete region 的 consumption trace；generic `_style_for`、decorations 或 diagram fallback 不能用于该路径。

方向评审使用同一组不可变 supporting facts：`VisualQualityReview` 保存 reviewer evidence/findings，`VisualQualityDecision` 由 workflow 机械派生，`ReviewAdjudication` 保存授权主体对事实误判的不可覆盖处理。Reviewer 不提交 pass。`VisualReferenceSet` 只保存批准的真实 Office page refs、coverage、receipt/decision/dependency hashes，不拥有 style、geometry 或 renderer behavior。

#### 4.8.2 Host Create Session 与 Operation

Designed Create 使用两类非 catalog supporting facts：

- `.slidethus/host-create/session.json`：一次用户意图的 canonical config，包含 Source fingerprints、Brief hints、Planning/M2 limits、policy flags、provider identities、固定 visual reviewer identity/capabilities、pending revision/request、已冻结但尚未被 Specs 引用的 exact ArtDirectionSeed ref、calibration lifecycle、可复用 M2 refs、最近 M3 report 与最近终态；
- `.slidethus/host-create/operations/HCO-*/started.json|terminal.json`：每次 invocation 的 config/invocation hash、动作、状态前后、耗时、pending request、结果引用和恢复动作。

Session 可版本化更新但不能改变 `session_id` 或 `created_at`；`intent_revision` 只在显式 Brief/Source revision 时递增。普通参数省略复用 Session，显式冲突不能修改 Project State、Brief、Source、Evidence 或 planning artifacts。Stage revision 在 owning artifact 提交后立即更新 Session、清除 pending revision/request，再继续 dependents；pending revision 不能与 Render 合并。Operation started/terminal 使用 immutable create-if-absent 文件；每个 attempt 只能有一个终态，后续持锁调用会把中断的 started fact 关闭为 failed。

Session/Operation 0.2 的 calibration state 为 `idle / sample_rendered / sample_office_available / approved / rework / full_rendered / full_office_available / whole_deck_approved / whole_deck_rework`。每个状态引用前一步 immutable fact；Brief/Source/Seed/Specs/Layout/P6 revision 将其复位。Direction review 已完成而 Slide Specs request 尚待回答时，Session 保存并校验 exact Seed ref，使跨进程 resume 不会再次 prepare Seed 或重放旧 response。0.1 Session 不被静默补默认值，必须显式迁移或新建 workspace。

这些事实不进入 Artifact Runtime catalog，不满足 G0–G9，也不替代 M2/M3 Application Report、Planning Review、Render Manifest 或 Host Candidate Receipt。`rework_required` 的 terminal fact 必须引用真实 Planning Review，并携带 earliest phase 与具体 `PRI-*` issue IDs。详细决策见 ADR-0033。

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

Designed Host Create 另有非 catalog 的 `host_candidate_receipt.schema.json`。每次真正启动的 Artifact Tool attempt 先写 `render_started`，再闭合为 `render_failed`、`render_timed_out` 或 `candidate_office_review_pending`。0.3 receipt 增加 `scope=sample|full`、conservative dependency key、完整 producer identity/capability、calibration authorization 和 Office evidence。回执绑定 current artifact refs、同一完整 Renderer IR、Preflight、input/output hashes、adapter identity、stage/duration/exit/timeout 和截断脱敏后的 stdout/stderr；失败回执也必须通过 Schema。

Artifact Tool preview 只能诊断。`record_office_evidence` 要求 application 为 Microsoft PowerPoint、精确 slide order、build/profile/export parameters 和每页独立 raster hash；它拒绝把 attempt output path 重新登记为 Office 页面，并写入新的 content-addressed `receipt-office-<hash>.json`，不覆盖 terminal receipt。Sample receipt 不满足 G7；full receipt 只有通过共享 `RenderAdmissionPolicy`，且与 sample 使用精确相同的 complete IR/producer/dependency authorization，才可启动。Receipt 0.2 历史可读，但不能授权新 reviewed/critical 路径。

`render_preflight_report.schema.json` 的容量 finding 使用结构化 `details`：required/available height、minimum height increase、width、preferred/floor/fitted font、line-height、line count、qualification reserve、实际 renderer horizontal/vertical padding 与 stable failure reason。Adapter-specific finding 可绑定 `asset_id`，同一次报告聚合全 deck 的 capacity、collision、asset、caption、carrier 与 runtime 条件。

Artifact Tool 表格在既定 Region 内按内容需求分配列宽、按换行需求分配行高，并使用显式单元格边距；Preflight 与 sidecar 共享同一目标计算。总需求超过 Region 时必须回到 P5A/P5B，不能依赖 PowerPoint 裁切或等分单元格继续交付。

完整 MVP 还使用 `pipeline_stages` 记录 planning、diagnostics、debug render/preview、design compile、final render/preview 动作，并用 `outputs[].role` 区分每个产出。输出文件扩展名不能替代阶段语义；Debug PPTX 和 Final PPTX 必须是不同文件。

### 4.11 Quality Report

回答：具体问题、严重度、修复路径和 Gate 结论。

支持三种 review mode：

- deterministic；
- open issue mining；
- dimension scorecard。

M5 Production Review 不让各 reviewer 直接竞争写 `quality_report.json`。各模式先形成 immutable runtime facts，最终再聚合为 catalog Quality Report。M5.1 新增 `deterministic_review_report.schema.json`（`DVR-*`），位于 `.slidethus/review/deterministic/`，记录 current M2–M4 artifact refs、G0–G7 regression、render/output checks、summary 和最早责任阶段。

每个 M5.1 input ref 同时保留：

- `content_hash`：Artifact Runtime registry 在 review 开始时的期望 hash；
- `observed_content_hash`：reviewer 实际读取到的 artifact body hash。

因此 deterministic review 可以把“artifact 已漂移/被篡改”作为有效 finding 持久化；报告自身仍能验证其实际观察内容，而不是要求失败输入假装与 registry 一致。所有 runtime input/output 路径必须先通过 workspace admission。

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
- locator 使用格式原生位置：HTML 语义元素、PDF 页码、DOCX 段落/表格/页眉页脚、PPTX 幻灯片/形状/备注、CSV 逻辑行与物理行、XLSX 工作表/行/单元格、图片/EXIF 元数据；同一块被切分时必须增加字符范围，不能产生无法区分的重复 locator；
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
