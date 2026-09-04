# Designed Create 视觉质量前置主流程设计

Status: Implementation candidate complete for Batches 1–3 and the Batch 0 automated safety controls; engineering verification complete; Batch 4 real-Office proof pending; DO NOT RELEASE
Date: 2026-09-04
Baseline: `8ad3e49c8b3a6929d3d871da025282b7db2e2653` (`v0.9.2-rc.1`)
Architecture decision: `docs/adr/ADR-0034-quality-by-construction-designed-create.md`

## 1. Objective and guarantee boundary

把 Designed Create 从“工件齐全、Gate 未阻断、生成整套后再判断是否好看”改为“先完成全篇可执行设计，用同一完整 IR 的正式代表页取得当前视觉证据，再决定是否支付整套渲染与 Office 返工成本”。

本方案不承诺普遍意义上的“必然好看”。它能强制保证的是：

1. reviewed/critical 工作没有形成明确视觉判断、representation 和可执行几何时，不能进入正式渲染；
2. 未从同一份冻结的完整全篇 IR、同一 producer 和真实 Office 页面取得代表页审阅证据时，不能执行 full render；
3. renderer 不替上游猜测载体、信息主次、图形关系、图片职责或组件变体；
4. 同一页面 hash 上已经 admitted 的 Critical/Major 不能靠重报、遗漏或降级静默消失；
5. 未完成全篇 Office review、或仍有 open Critical/Major 时，不能取得 `quality_approved`；
6. 任一失败都有最早责任阶段、不可覆盖的历史事实和封闭返工路径。

这是一项 fail-closed 与 evidence-currentness 保证。它不能保证 reasoning provider 或 reviewer 永不漏判，不能消除合理审美差异，也不能在证据、资产或 producer 能力缺失时伪造高质量结果。真实能力仍需实现后的跨案例 Office 验收证明。

## 2. Current state and evidence-backed attribution

### 2.1 已经成立的能力

- 主流程已有 Project Brief、Narrative、Outline、Slide Specs、Layout Plans、ArtDirectionSeed、ArtDirectionPacket、Visual System、Renderer IR、Artifact Tool 和 PowerPoint 验收边界。
- `v0.9.2-rc.1` 已证明 Taste 原生 prototype 可以传播到正式 Seed、Specs、Layout、Visual System、同一完整 admitted IR 和同一 producer。
- YU7 证明 auto、早期真实资产、连续宿主设计判断、完整全篇视觉计划与正式 Host Create 可以共同产生用户认可的 PowerPoint；因此高风险所需证据不能简单等同于人工 Gate 数量。
- Issue #3 证明正式代表页先行能降低全篇渲染返工，但其直接代码根因是重复 Seed preparation 与旧 response replay 覆盖新 Seed；新增校准流程不能遗失这个精确回归。

### 2.2 就业案例真正暴露的问题

“2026 年应届大学生毕业就业情况”并非缺少载体数量：Slide Specs 已有五个 chart、三个 image、四个 table 和三个 diagram。主要缺陷是载体选择质量、视觉权重、语义图形实现、palette/typography 成熟度和跨页构图不足。

1. `taste-generated` provenance 证明 Taste 驱动过 native prototype，不证明 prototype 已被审美批准；
2. 结构灰模能检查 Block、Region、容量和粗拓扑，却可能把 chart/table/diagram 退化为等框或 raw JSON；
3. P5 representation 与 P6 executable grammar 不完整时，renderer 只能选择 generic fallback；
4. deterministic Planning Review 的 no-finding 不能证明焦点、构图、图像叙事和全篇节奏；
5. formal representative pages 尚不是不可绕过、可恢复、可失效的正式事务；
6. reference library 是可选资源，不是主题模板。若没有实际选择、采纳/拒绝和下游绑定，44 个方向的存在本身不会提高质量。

### 2.3 历史边界

- 能证明 v0.8.0 的 Art Direction 在 P5 之后，不能证明其被感知为较好的原因是“路径较小”或“案例调优”；案例、作者连续性与资产条件仅是待控制假设。
- 可审计的正向基线是 v0.8.1 YU7；v0.9.0 reference library 的发布没有完成自主选择与审美实测；v0.9.1 重放 YU7 时 11/12 页逐字节不变且表格改善，不能把一般 renderer 稳定性修改归为主因。
- 当前广义失效链是：design reasoning 质量不足 → P5 representation/geometry 不够可执行 → P6/IR fallback → 无正式 sample authorization → 全篇放大；Seed replay、self-review 和 generic diagram 是具体放大器。

## 3. Controller and ownership closure

采用 WAE ownership closure：agentic reasoning / 人工处理不确定视觉判断；workflow 处理顺序、事务、hash、失效与授权；renderer 只做由结构化输入唯一确定的机械实现。

| 对象 | 唯一权威 | 输出 | 不允许 |
|---|---|---|---|
| narrative page role | Deck Outline | stable `slide_type` / role ID | Layout/ReferenceSet 改名减少覆盖 |
| theme read、reference 取舍、prototype、carrier direction | Design Direction Provider + ArtDirectionSeed | native prototype、Seed、provenance | keyword-to-template |
| representation semantics | Slide Specs | discriminated `representation` | Layout/renderer 发明 nodes/data |
| placement/view geometry | Layout Plans | Regions、orientation、ports、routing、anchors | 重复拥有 semantic nodes/series |
| page family/component/style grammar | ArtDirectionPacket / Visual System | versioned supported IDs | ReferenceSet 成为第二设计系统 |
| planning preview evidence | Preview producer + review provider/human | content-addressed receipt + immutable findings | “已看过”或 raw JSON 代替证据 |
| sample/full render attempt | Host Candidate Receipt | scope、IR、producer、outputs、Office facts | 第二套 calibration run receipt |
| calibration review evidence | Reviewer | immutable findings | reviewer 直接写 pass/approved |
| calibration/full admission | Workflow policy | derived decision、dependency key、terminal fact | provider 自批或覆盖旧 finding |
| release visual evidence | P8 Office-first Review | current Office pages/findings/decision | SVG/object count/成功导出代替 |

机械边界：只有当语义、样式变体、slot、资产、geometry 与 producer capability 都已唯一确定时才进入 compiler/renderer。任何仍需回答“为什么用这个载体、谁主谁次、关系如何连接、图片承担什么”的问题都必须回到 Seed/P5/P6。

## 4. Authoritative mainline

不新增 Project State phase。校准是 P6 与 full P7 之间的 attempt-scoped supporting transaction。关键取舍是保守且唯一的：**校准前完成并冻结全篇 P5A/P5B/P6/page designs，编译一份完整全篇 IR；样板只从这份 IR 选择页面输出；批准后只允许同一 IR 的 full render。**

```text
P0 Brief
  → deterministic VisualAdmissionPolicy
  → P3 Narrative
  → P4 complete Outline / G4
  → Design Direction Prototype + direction evidence + frozen Seed
  → P5A full-deck Representation Specs / G5A
  → P5B full-deck Layout + semantic planning previews / G5B
  → P6 full-deck executable Visual Grammar + page designs / G6
  → compile and freeze one complete admitted IR
  → select representative slides deterministically
  → scope=sample render from that exact IR
  → real Office pages + immutable review evidence
  → workflow-derived CalibrationDecision + evidence-only ReferenceSet
  → scope=full render from the identical IR and producer identity
  → P8 whole-deck Office review
  → P9 delivery freeze
```

校准节省的是 full render、全篇 Office review 和整套设计返工成本；它不声称省掉全篇 P5/P6 设计成本。以后若要做真正渐进式 page fragments，必须单独 ADR 定义 append-only fragment authority，不能在本方案中暗建 partial/custom IR。

### 4.1 P0: VisualAdmissionPolicy separates risk from pause mode

Project Brief 继续唯一保存用户声明的 `approval_mode` 和 `quality_profile`。Workflow 从精确 Brief hash 与 versioned deterministic policy 派生 immutable `VisualAdmissionPolicy`，记录：

- `brief_ref/hash`；
- `policy_version`；
- `risk_class=controlled|reviewed|critical`；
- reason codes；
- required direction/planning/calibration/P8 evidence；
- `approval_authority_policy`；
- required reviewer independence/capabilities。

Risk 控制所需证据；approval mode 控制是否必须停下来等人：

- `auto` 不等于跳过 review。reviewed/critical auto 只有在 Session 已固定一个合格、独立、Office-image-capable 的 VisualReviewProvider 时才能继续；
- provider 只提交 evidence，workflow 机械派生 decision；author/provider identity 不满足独立策略时停止；
- checkpoint/strict 使用 schema-backed human request/response，provider findings 可作为输入但不能替人类响应；
- 缺少合格 reviewer 时终止为 `host_input_required`，不静默降 risk、不改 Brief、不把 lightweight 标成 degraded；
- provider/reviewer 或 policy version 变化是显式 session revision，并使相关 evidence 失效。

### 4.2 Design Direction Prototype before P5

G4 后、P5A 前执行常规 `Design Direction Prototype`；`Art-direction Lab` 保留给正式 deck 已完成但仍未达到审美条时的隔离恢复实验。

Prototype 流程：

1. 读取 Brief、Narrative、完整 Outline、evidence/asset inventory 和 Taste；
2. 根据需要检查少量 reference candidates，通常一至三个，或记录不采用；
3. 创建能覆盖 Outline 中高风险 role/representation 问题的 native prototype，而非 mood board/token list；
4. 记录 reference properties 的 adopted/rejected/transformed；
5. 产生 immutable direction review evidence；
6. 按 policy 取得 direction decision 并冻结 ArtDirectionSeed。

`taste-generated` 仍只表示 production provenance。Direction decision 是独立事实。Cover-only prototype 不能覆盖 diagram、data、dense 或 image-led body roles。

### 4.3 P5A: one discriminated Representation owner

Slide Specs 每页拥有一个 discriminated union：

```text
representation.kind = text | typographic | image | chart | table | diagram | mixed
```

共同字段：carrier reason、visual weight、density role、asset demand/fallback。Kind-specific semantic facts：

- chart: communication question、qualified data refs、series/categories、comparison semantics、chartability/fallback；
- table: decision task、schema、row/column hierarchy、emphasized dimension、source refs；
- diagram: normalized node IDs/roles、edge IDs/meaning/direction、cycle/flow/hierarchy topology；
- image: narrative role、subject/focal intent、source/generate/replan strategy；
- mixed: bounded child representations and their semantic priority。

G5A 阻断 decision 缺失和 contradiction，不设图片/图表数量 quota。例：`avoid equal cards` 与等权 siblings、required image 无 asset strategy、cycle 无 feedback edge、数字比较用 prose 却无理由，均回到 P5A/P2。

### 4.4 P5B: geometry only, plus content-addressed semantic previews

Layout 只引用 Outline role 和 Specs representation IDs，并拥有：

- Regions、first/second/third focal order 与 reading path；
- chart orientation/encoding placement/label geometry；
- diagram port assignment、routing geometry、edge label anchors；
- table header/label placement、emphasis geometry、overflow behavior；
- image slot、fit、crop/focal geometry 与 fallback Region；
- density/negative-space target 和 observable topology signature。

Layout 不重复保存 nodes/edges/series/table schema，也不拥有尚未产生的 approved lineage 或 Visual System component IDs。

现有 neutral wireframe 是 structural preview。新增 semantic planning preview 必须由 frozen Seed/Specs/Layout/target capability 确定生成，内容寻址并有 receipt/path/hash。它显示实际 chart orientation、table hierarchy、diagram topology、image crop/focal placeholder 与视觉权重，不能显示 raw JSON 或所有内容等框。

G5B 有两个独立结论：

- deterministic: bounds、capacity、minimum size、coverage、topology fingerprint、contradiction；
- qualitative: carrier fitness、focal hierarchy、page distinction、deck rhythm，绑定精确 semantic preview receipt 与 reviewer identity。

这是 planning admission review，不是 ADR-0026 的 retrospective Stage AI Review。实现批次必须同步更新 `docs/03-workflow-state-machine.md`、`docs/05-quality-system.md` 和 phase contract 以明确 supersession 范围。

### 4.5 P6: complete, closed and mutation-sensitive Visual Grammar

P6 在校准前完成全篇 Visual System 与每页 page design。Visual System 唯一拥有 page family/component variant/style IDs，并只使用 admitted producer 已实现的 versioned vocabulary。

必须具备：

- page-role treatments、typography、spatial rhythm；
- chart/table/diagram/image variants；
- component variants、contrast/density cadence；
- prohibited combinations、explicit degradation/capability conflicts；
- producer capability ID and version for every non-trivial behavior。

Reviewed/critical compiler 禁止 generic `_style_for` / decoration / diagram fallback。Unknown、unsupported 或 unconsumed decision 直接 fail/replan。Renderer IR 记录 source decision → Visual System variant → slot/asset → concrete element 的 consumption trace。

每个 executable decision 都需要 mutation-sensitive test：改变一个 material field 必须改变 IR 或明确触发 unsupported failure；仅序列化 metadata 而不改变输出不能通过 G6。

### 4.6 Freeze one complete IR and calculate calibration coverage

G6 后 compile 一份覆盖完整 active slide set 的 admitted IR。Workflow 使用 frozen Outline roles、Specs representation kinds 与 risk policy 确定性计算 high-risk coverage 和最小代表页集合；Host/Provider 不能自由改名、拆分或少报 role 来减少样板。

Typical high-risk coverage dimensions include statement/cover, quantitative evidence, image-led story, dense decision/framework and material diagram/process. Count is derived, not fixed。

`calibration_dependency_key` conservatively binds:

- complete Brief/VisualAdmissionPolicy/Narrative/Outline、direction review evidence/decision/adjudication、Seed、Specs/Layout/preview review、Packet/Visual System/page designs hashes；
- selection policy/version and selected slide IDs；
- complete IR hash/schema and compiler name/version/code hash；
- backend、adapter hash、Artifact Tool version and capability contract；
- asset and font resolution receipts；
- Office application/build/profile/export parameters。

初版任何一项变化都产生不同 dependency key，并使 sample receipt、review evidence、decision 和 ReferenceSet 全部失效。Seed 即使没有直接引用 direction decision，full admission 也必须解析并校验 current direction evidence/decision/adjudication refs；不能只依赖一次外部 invalidation event。局部 per-family 复用不在本轮范围内。

### 4.7 Calibration transaction reuses Host Candidate Receipt

不新增 `VisualCalibrationRun`。现有 Host Candidate Receipt 是唯一 render-attempt authority，扩展其 `scope=sample` 身份与 dependency/producer/Office refs。Receipt 只能由 workflow 从真实 render attempt 生成，Host/Reviewer 不能自报路径。

Session 持有一个 `pending_calibration` subrecord：

```text
requested → render_started → sample_candidate_ready
  → office_pending → review_pending
  → approved | rework | blocked | failed
```

- Project State 在 sample 期间保持 `VISUAL_SYSTEM_READY`；sample receipt 不满足 G7；
- 每步绑定前一步 hash；resume 只继续首个缺失步骤；
- orphaned start 按 ADR-0033 关闭后再恢复；
- Decision 与 ReferenceSet 同一 journal transaction 提交，或 ReferenceSet 是 approved Decision 的幂等、内容寻址推导；
- terminal operation 列出 exact open finding IDs、earliest owner 和 allowed next actions。

所有正式 full-render 入口共同调用 `RenderAdmissionPolicy`。对 reviewed/critical work，没有 current approved calibration refs 时一律 fail closed，不能只在 HostCreate 编排器中检查。

### 4.8 Immutable review evidence and derived decision

Reviewer 接收的实际 image paths 必须是 scope=sample 的真实 Office-rendered pages；Final SVG/PNG 仅作诊断。

Review evidence immutable。Finding ID 由 candidate/page hash、dimension、location 和 normalized issue semantics 计算，不包含 severity。Workflow 根据以下事实派生 CalibrationDecision，reviewer 不提交 `approved`：

- current dependency key and receipt；
- complete role coverage；
- reviewer identity/capability/independence；
- immutable findings and adjudications；
- zero open Critical/Major。

同一 page hash 的 admitted Critical/Major 不能因重跑、换 reviewer、遗漏或降 severity 消失。修复应产生新 page hash。若 finding 是事实误判，授权主体可以写 immutable `ReviewAdjudication`，保留原 finding、理由和身份；waiver 只记录用户选择，不能产生 reviewed/critical `quality_approved`。

Failure earliest owner 可为 P4、Design Direction Prototype/Seed、P5A、P5B、P6 或 P7。用户接受 direction 不覆盖 sample Major；若方向本身失败，显式 Seed revision 并使旧 direction evidence 与全部 calibration facts 失效；producer 无法实现用户坚持的方向时停止为 capability conflict。

Approved `VisualReferenceSet` 只保存 accepted Office page refs、role/representation coverage、receipt/decision/dependency hashes。它不拥有 allowed styles、geometry 或 renderer behavior，不是第二个 Visual System。

### 4.9 Full render is the identical IR, not post-approval expansion

批准后只允许：用精确相同 complete IR hash、compiler/backend/adapter/producer/capability/asset/font identity 执行 `scope=full` render。任何页面、新 role、component、asset 或 P6 决定变化都会改变 dependency key，旧 authorization 失效并回到 planning/calibration。

不存在 reviewed/critical “新高风险 role 例外”。Controlled work只可在其自己的 lightweight policy 下处理已覆盖的低风险变体；一旦该页进入 reviewed/critical contract，必须重校准。

Sample page bytes 可在 full candidate 中复用其局部 page-correctness observation，但不能继承 full-candidate approval，也不能跳过 adjacent-page cadence、whole-deck currentness、font/asset/Office environment 和 G8。

### 4.10 P8 whole-deck Office review

真实 Microsoft PowerPoint pages 是主要视觉 evidence：

1. page correctness: overflow、collision、font substitution、orphan text/punctuation、crop/label；
2. plan fulfillment: representation、asset、chart/table/diagram slots and declared degradation；
3. grammar fulfillment: variant consumption、visual weights、contrast/density cadence；
4. reference propagation: sample language 在 body roles 中同源而不机械重复；
5. whole-deck quality: hierarchy、composition diversity、adjacent transitions and narrative rhythm。

P8 可以因全篇上下文撤销 calibration decision，即使 sample page bytes 未变；“protected”只表示不得静默改写，不表示免于新 finding。Delivery 需要 current whole-deck decision 且 zero open Critical/Major。

## 5. Artifact and schema design

| Fact/artifact | Authority/change | Target contract | Compatibility |
|---|---|---|---|
| Project Brief | unchanged authority | existing | no editable risk field |
| `VisualAdmissionPolicy` | new deterministic supporting fact | 0.1.0 | derived from exact Brief hash |
| direction review/decision | new immutable supporting facts | 0.1.0 | required by policy |
| ArtDirectionSeed | preserve current authority/provenance | next compatible revision only if role-coverage refs required | no fake defaults |
| Slide Specs | discriminated representation semantics | 0.2.0 | explicit replan for reviewed/critical legacy |
| Layout Plans | representation-referencing geometry | 0.2.0 | explicit replan; no semantic backfill |
| semantic preview receipt | new content-addressed fact | 0.1.0 | absent only on admitted legacy/controlled path |
| Planning Review | deterministic + qualitative refs | 0.2.0 | old report cannot approve new path |
| ArtDirectionPacket/Visual System | closed capability-bound grammar | 0.2.0 | old grammar limited to legacy/controlled |
| Renderer IR | consumption trace and exact producer inputs | 0.2.0 | no mixed IR versions |
| Host Candidate Receipt | extend single sample/full attempt authority | existing 0.2.0 → additive 0.3.0 | historical 0.2.0 remains readable but cannot authorize the new reviewed/critical path |
| Host Create Session/Operation | reviewer config, pending calibration, terminal refs | 0.2.0 | explicit session migration/new workspace |
| CalibrationDecision/ReferenceSet/Adjudication | new immutable supporting facts | 0.1.0 | no cross-workspace approval reuse |
| P8 Visual Review | Office-primary, current dependency refs | 0.2.0 | prior review is historical evidence only |

Rules:

- semantic-breaking contracts use a new major artifact generation; implementation must not squeeze them into permissive `0.1.x` defaults；
- Host Candidate Receipt 0.3.0 adds dependency/producer/Office refs without changing 0.2.0 history; if implementation changes any existing field meaning or makes the new fields globally mandatory, it must use a breaking generation instead of 0.3.0；
- `schemas/` and `src/slidethus/_schemas/` update atomically；
- fields that cannot be derived without design judgment remain missing and trigger replan；
- mixed-version reviewed/critical planning is rejected；
- old controlled workspaces may retain their declared legacy path and are not automatically `degraded`；only missing promised capability/deliverable earns that label；
- old reviewed/critical workspace must explicitly replan/migrate; file existence never grants new approval。

## 6. Transaction and invalidation matrix

| Change/event | Effect |
|---|---|
| Brief/policy/Narrative/Outline change | invalidate direction through P8; recompute coverage |
| Seed/prototype/direction decision change | invalidate P5–P8 and all calibration facts |
| any Specs/Layout/preview review change | invalidate P6/IR and all calibration facts |
| Packet/Visual/page design/IR change | invalidate sample receipt onward |
| selected IDs/policy change | invalidate sample receipt onward |
| asset/font resolution change | invalidate IR/receipt/reviews |
| compiler/backend/adapter/tool/capability change | invalidate IR/receipt/reviews |
| Office build/profile/export change | invalidate Office evidence/decisions |
| reviewer/provider/policy identity change | explicit session revision; invalidate affected review/decision |
| admitted finding on same page hash | remains open unless immutable adjudication; cannot be overwritten |
| new role/page after approval | full design hash changes; full render admission revoked |
| P8 whole-deck issue | may revoke calibration and route to earliest owner |

Artifact commit and supporting-fact invalidation occur in one journaled graph transaction, or the runtime must prove recovery closes any stale-current window before resume/render。

## 7. Quality economics

The process deliberately pays full semantic/design planning cost before sample:

```text
full-deck design reasoning + complete IR
  + small representative render/Office/revision loop
  << weak full-deck render + whole-deck Office inspection + all-page redesign
```

Gate remains a transaction controller and safety net. First-pass quality comes from complete reasoning, semantic previews, bounded producer vocabulary, independent evidence and early representative Office observation—not from adding a score or raising media counts。

## 8. Failure and degradation policy

| Failure | Required behavior | Forbidden shortcut |
|---|---|---|
| no qualified design reasoning | stop reviewed/critical; controlled follows declared legacy/lightweight policy | claim Taste-generated from bundled files |
| no independent reviewer for auto high-risk | `host_input_required` for human review/config revision | author self-approval |
| no viable image asset | replan or approved generation path | decorative surface counted as image fulfillment |
| unqualified chart data | table/metric/prose with reason | invented data |
| unsupported diagram topology | replan or admitted planned asset | guessed equal nodes/edges |
| semantic preview missing | block G5B on reviewed/critical | raw JSON/boxes as visual proof |
| sample Office unavailable | remain `office_pending` | SVG/PNG substitution |
| sample Critical/Major | new artifact/page hash or adjudication; rerun exact transaction | severity downgrade/omission |
| full identity drift | invalidate authorization and recalibrate | compare only page bytes |
| P8 drift | earliest-owner rework, possibly revoke calibration | keep attractive cover and waive body |

## 9. Work breakdown

### Batch 0 — Lock evidence, negative controls and migration plan

Historical matrix:

1. YU7 auto/asset-rich/formal-path positive；
2. hotel initial custom-render bypass negative；
3. hotel accepted low-luxury whole-deck propagation positive；
4. FDE formal-sample positive and remaining-page drift negative；
5. employment cold-start negative；
6. one post-freeze holdout not used to write rules。

Negative controls include critical/reviewed auto without independent reviewer, cover-only prototype, equal-card contradiction, undefined loop, raw-JSON preview, hand-scripted sample, producer mismatch, severity omission/downgrade, new role after approval, direct non-Host full-render bypass, mixed schema versions and Office unavailability。

Exact Seed regression:

```text
Seed revision → Specs → Layout → P6 → calibration stop/resume → full render
```

Every phase preserves the intended Seed hash; duplicate prepare and stale response injection cannot overwrite it; a real Seed change invalidates calibration/reference facts。

Exit: every historical bypass has an automated negative test or explicit Office audit case; schema/migration matrix approved。

### Batch 1 — Admission, representation and semantic planning

- implement VisualAdmissionPolicy and reviewer config；
- implement Specs/Layout 0.2 ownership split；
- produce content-addressed semantic previews；
- split deterministic/qualitative planning admission；
- update workflow/quality/phase docs。

Exit: reviewed/critical cannot reach G5B with boxes/raw JSON, incomplete semantics, self-review or policy drift。

### Batch 2 — Closed grammar, complete IR and render admission

- define the smallest Artifact Tool-supported grammar/capability vocabulary；
- add mutation-sensitive consumption tests and IR trace；
- freeze complete full-deck IR before sample；
- extend Host Candidate Receipt and shared RenderAdmissionPolicy。

Exit: unknown/unconsumed decisions fail; all full-render entries reject missing/stale calibration。

### Batch 3 — Calibration lifecycle and Office evidence

- implement pending lifecycle, resume/orphan recovery and terminal facts；
- make Office pages the actual reviewer inputs；
- implement immutable finding/adjudication/derived decision/ReferenceSet；
- prove exact same IR and producer identity sample→full。

Exit: a failing sample blocks full render; same-page re-review cannot clear a blocker; approved transaction resumes without replaying intent。

### Batch 4 — Whole-deck and cross-case proof

- run the locked historical matrix；
- run one genuine holdout after implementation freeze；
- if holdout changes implementation, replace it with a new holdout；
- measure representative first-pass acceptance, P5/P6 revisions, full-deck Major findings, cost and earliest-owner distribution；
- decide RC/stable only after real PowerPoint review。

Exit: all negative controls remain blocked; positives and holdout have current Office evidence and zero open Critical/Major。Otherwise DO NOT RELEASE。

## 10. Verification

```bash
PYTHONPATH=$PWD/src python -m pytest
PYTHONPATH=$PWD/src python scripts/validate_all.py
PYTHONPATH=$PWD/src python scripts/audit_package.py
python -m compileall -q src tests scripts
ruff check src tests scripts
git diff --check
```

Behavioral acceptance:

1. auto high-risk never skips evidence and cannot self-review；
2. sample and full bind one identical complete IR and producer identity tuple；
3. every material design mutation changes IR/output or fails unsupported；
4. all formal full-render entries share admission policy；
5. immutable Critical/Major cannot disappear on same page hash；
6. any new role or artifact/provider/Office drift invalidates authorization；
7. sample failure can return through Seed/P4, not only P6；
8. P8 can revoke a sample decision based on whole-deck context；
9. no reference, asset or media quota is required merely to satisfy metadata；
10. Office pages are the actual review input and release evidence。

## 11. Three independent audits and required closure

The first audit candidate was frozen by hashes and independently reviewed:

- Round 1 artifact/contract: `audit/designed-create-quality-round-1-artifact-contract.md` — REWORK；
- Round 2 adversarial workflow: `audit/designed-create-quality-round-2-adversarial-workflow.md` — REWORK；
- Round 3 historical/regression: `audit/designed-create-quality-round-3-historical-regression.md` — REWORK。

All three independently found the complete-IR/post-sample-expansion contradiction. The revision chose one complete IR before sample and resolved the common Critical. The synthesis maps every Critical/Major to an explicit disposition; all three reviewers completed closure verification with no open Critical/Major. Architecture is accepted for implementation, which still does not prove production capability。

## 12. Implementation status

The accepted architecture is now implemented on the isolated `codex/issue3-visual-repair-trial` branch without changing the original dirty workspace. The implementation preserves the audited authority boundaries rather than introducing a second renderer or a parallel design path:

- `VisualAdmissionPolicy`, qualified reviewer configuration and fail-closed reviewed/critical admission are implemented;
- Slide Specs/Layout 0.2 separate representation semantics from placement/view geometry and bind content-addressed semantic previews plus qualitative review;
- ArtDirectionPacket/Visual System/Renderer IR 0.2 use a closed, capability-bound visual grammar with explicit consumption trace and no reviewed/critical generic fallback;
- Host Candidate Receipt 0.3 is the sole sample/full attempt authority and records exact producer, dependency and Microsoft PowerPoint evidence facts;
- the Host Create Session owns one resumable calibration lifecycle, selects samples from one complete frozen IR, and authorizes only an identical-IR/producer full render;
- immutable findings, adjudications, workflow-derived decisions, evidence-only `VisualReferenceSet` and whole-deck Office review are implemented;
- the prepared ArtDirectionSeed reference is persisted in Session 0.2 so a pause/resume cannot replay preparation and overwrite the authoritative Seed;
- direct M4 and other formal full-render entry points share the same `RenderAdmissionPolicy` instead of relying on Host-only checks.

Automated regression coverage includes policy/legacy rejection, independent-review requirements, immutable blocker history, append-only Office evidence, Session migration, material-decision mutation, and a complete reviewed Host Create lifecycle through sample Office review, identical full render and whole-deck approval.

Still intentionally open: the locked YU7/hotel/FDE/employment historical matrix, a genuine post-freeze holdout and current real Microsoft PowerPoint visual evidence. These are Batch 4 production-proof obligations; they are not replaced by unit tests, Artifact Tool previews or schema validation.

## 13. Final outcome

Three independent reviewers initially returned REWORK, the plan was revised, and all three then returned `ACCEPT FOR IMPLEMENTATION` on the same substantive hashes. The synthesis is recorded in `audit/designed-create-quality-three-round-synthesis.md`; no Critical/Major design finding remains open。

The design acceptance has been translated into production code, schemas, Gates, workflow state, renderer contracts, Skills and regression tests. It is an implementation candidate, not a release approval: until Batch 4 completes with current real PowerPoint evidence and zero open Critical/Major findings, production visual-quality improvement remains unproven and the release decision remains `DO NOT RELEASE`。
