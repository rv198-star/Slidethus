> 历史记录（2026-08-31 恢复）：正文保留撤回前提交 `2b005ecde6a80237d0f617a3d32da0b9379f0c8b` 的原文，供归因与审计追溯；其中 active/PASS/FAIL/pending 不代表当前状态。当前方案为 `plans/M6.6-final-optimization-and-rerelease.md`。本文件不授权恢复旧代码；正文引用的历史 ADR/文件按该提交解释。

# 跨案例视觉智能与风格贯穿整体优化方案

Status: Superseded for execution by `plans/M6.6-visual-decision-propagation-convergence.md`.

本文件保留为三案例归因后的第一版探索方案及双轮审计对象，不再作为当前执行计划。未纳入当前收敛轮的扩展验证见 `plans/visual-intelligence-follow-up-issues.md`。

## 1. Objective

- 用户价值：让 Slidethus 在技术展示、时尚品牌、低奢行业研究、内部决策与独立阅读等不同场景中，稳定地产生“场景合适、视觉有主张、图片与图表有职责、全篇风格能贯穿”的真实 PPTX，而不是只保证内容、结构和导出成立。
- 本轮边界：基于 FDE、中国珠宝、酒店香薰三组真实案例，定义跨场景的控制模型、阶段契约、运行事实、Review/Gate、实施批次和回归语料；本计划本身不修改生产代码，也不为单一主题添加模板。
- 明确不做：不把“技术展示型”等同于科技风；不建立酒店、珠宝或 FDE 专用模板；不设置全局图片/图表配额；不让 Taste 直接控制 renderer；不在交付后静默持续修改已获用户接受的 deck。
- 退出条件：方案能够解释三组案例的主要反馈；每项改动都有最早责任阶段、控制者、可观察输出和失败路径；实施批次可以独立验证；最终回归必须使用真实 Office 页面和跨案例语料。

## 2. Executive decision

当前最主要的问题不是“缺少更多样式”，而是视觉决策没有形成一条可执行、可回归的传播链：

```text
场景与受众
  → 展示姿态与主题视觉语法
  → 每页视觉载体选择
  → 图片/图表/留白席位
  → 页面家族与组件语法
  → Renderer 实际消费
  → 代表页校准
  → 全篇 Office 视觉回归
```

现有流程对 artifact 存在性、证据、几何和导出控制较强，但对“视觉判断如何从上游传播到真实页面”控制不足。WAE 控制边界应调整为：

| 工作对象 | 主控制者 | 原因 |
|---|---|---|
| 阶段顺序、Schema、lineage、hash、几何、容量、文件完整性 | deterministic workflow | 路径确定、可机械验证 |
| 展示姿态、主题视觉语法、视觉载体、图片职责、图表机会、页面节奏 | agentic reasoning provider | 依赖主题、受众、语境与审美判断，不能由固定映射冻结 |
| 数字图表、来源、资产许可、Office 页面 | evidence | 必须连接到可观察事实 |
| 品牌敏感或对外高质量 deck 的代表页取舍 | checkpoint approval | 审美存在合理偏好差异，样板确认比事后整套返工成本更低 |

核心方向是“两段式艺术指导 + 视觉载体规划 + 可执行视觉语法 + 代表页校准 + Office-first 回归”。

## 3. Current state and case evidence

### 3.1 当前仓库状态

- 当前 HEAD：`af88bed`。
- 工作区已有 M6.6、Taste provider、真实案例与用户评审相关的未提交修改；实施时必须保留并按小批次处理，不能覆盖或重置。
- 已存在能力：Project Brief、Narrative、Outline、Slide Specs、Layout Plans、ArtDirectionPacket、Visual System、多后端渲染、Office preview、M5 Review/Repair。
- 已知结构缺口：Art Direction 进入布局较晚；Taste 默认实现偏固定；图片/图表职责未成为规划一等事实；Visual System 高层语义未稳定驱动 renderer；样板到全篇的视觉 lineage 和 Office 回归尚未建立。

### 3.2 三组案例的共同证据

| 案例 | 已验证的局部真相 | 暴露的共性缺口 | 不应推出的错误结论 |
|---|---|---|---|
| FDE 2026 | 内容与结构先达到可用，Taste-informed 样板显著提高视觉完成度；现场、阅读、展示三种姿态需要不同密度与载体 | `presentation_mode` 只改变少量 dial，场景没有深入影响 visual idiom、资产策略和页面拓扑 | 所有对外技术展示都应使用暗色科技风 |
| 中国珠宝 2026 | 对外展示可以采用时尚编辑与低奢视觉，同时使用原生数据图表 | 展示姿态与主题视觉语法必须分离；图表机会和图片席位要在策划阶段决定 | 展示型只能牺牲信息密度，或时尚主题不适合数字图表 |
| 酒店香薰 2026 | 封面方向正确但正文漂移为内部 dashboard；4 页样板确认后可把低奢语法迁移到 16 页 | 封面 token 不会自动产生全篇组件语法；初稿绕过正式工件链；缺少样板 lineage、组件约束、明暗/图片/图表节奏回归 | 需要酒店行业模板，或所有页面都必须低密度大图 |

### 3.3 统一失效链

1. Brief 只表达 `live/read/both` 和自由文本 delivery context，无法明确区分展示姿态与主题视觉语法。
2. ArtDirectionPacket 在 G5B 后生成，无法自然影响 P5A 的视觉载体选择和 P5B 的图片、图表、留白席位。
3. 默认 Taste adapter 主要用固定代码映射通用 editorial 方向；确定性代码承担了本应由语境判断控制的审美推导。
4. Slide Specs 虽支持 image/chart block，但没有回答“为什么需要、承担什么、数据是否成熟、没有资产怎样降级”。
5. Layout Plans 记录 Region 几何，却不记录页面角色、资产席位、裁切焦点、视觉 lineage 或组件家族约束。
6. Visual System 保存 `page_role_treatments`、`component_variants`、`deck_rhythm` 等语义，但 renderer 仍大量按 block role/layout family 使用硬编码表面与装饰。
7. Review 能检测粗粒度布局重复，却不能证明整套页面遵循已批准样板、图片/图表计划和组件语法；Office preview 也没有成为 VisualReviewProvider 的优先图像输入。

## 4. Target workflow

不新增新的 Project State phase，但增加两个内容寻址的运行事实和一个条件式校准子流程。

```text
P0 Brief
  → P3 Narrative
  → P4 Outline / G4
  → ArtDirectionSeed
  → P5A Slide Specs + Visual Carrier Plan / G5A
  → P5B Layout Plans + Asset Slots / G5B
  → final ArtDirectionPacket
  → executable Visual System / G6
  → representative calibration render
  → VisualReferenceSet approval (conditional)
  → full P7 Render
  → Office-first P8 Visual Review
  → Delivery freeze
```

### 4.1 `ArtDirectionSeed`：在布局前约束，不提前冻结最终样式

在 G4 后、P5A 前生成 provider-neutral、immutable runtime fact，建议路径：

```text
.slidethus/art-direction/seeds/<sha256>.json
```

Seed 绑定 Project Brief、Narrative Blueprint、Deck Outline、用户参考图/品牌要求和可用资产概况。它只表达方向性约束，不包含最终字体坐标或页面几何：

- `presentation_posture`：live/read/both 之外的交付姿态，例如 external showcase、decision support、training、sales narrative；这是连续判断，不做狭窄固定模板枚举。
- `visual_idiom`：主题适合的视觉母语、材质感、文化语境和情绪描述；与 posture 分离。
- `density_strategy`：全篇密度区间、允许的高密度页角色和呼吸页角色。
- `media_strategy`：摄影、对象图、人物、空间、插画、示意图、纹理分别承担什么职责。
- `chart_strategy`：哪些叙事问题适合数字图表，哪些只能用定性关系图；不设置图表数量指标。
- `page_role_profile`：封面、statement、evidence、media story、framework、action 等角色的期望焦点。
- `rhythm_intent`：明暗、密疏、图文、证据/情绪页面的节奏原则。
- `forbidden_defaults`：针对本 deck 的默认禁用组件或表现，不是全局禁令。
- `confidence/warnings/assumptions`：方向推导不充分时显式降级。

Seed 由 ArtDirectionProvider 提议，确定性服务只负责输入 admission、Schema、大小限制、lineage 和冻结。Taste 是默认指导资源；主题/场景推导由 reasoning provider 完成，不再由固定 dial 映射假装完成。

无 reasoning provider 时允许 `deterministic-fallback`，但必须：

- 标记为 generic/degraded art direction；
- 不声称已完成主题级审美推导；
- 对 external showcase、brand-sensitive 或 `quality_profile=critical` 的 deck 强制进入代表页校准，不能直接自动放行。

### 4.2 P5A：把视觉载体与图表机会变成正式选择

Slide Specs 需要新增结构化 `visual_strategy`，最少回答：

- `primary_carrier`：text / image / chart / diagram / table / mixed；
- `carrier_reason`：为什么该载体最适合本页 core message；
- `visual_weight`：hero / support / ambient / none；
- `media_role`：scene / evidence / material / object / portrait / texture / illustration / none；
- `chart_intent`：要回答的问题、比较维度、数据绑定、成熟状态和不使用图表的理由；
- `asset_demand`：required / preferred / optional / none，以及 source/generate/degrade 策略；
- `density_role`：breathing / balanced / dense，并受 Seed 的全篇节奏约束。

数字图表规则：

1. 只要页面包含可比较的定量 evidence，P5A 必须显式选择 chart / metric / table / prose 之一并写明理由。
2. `chart_intent` 必须绑定 Evidence/Data refs；无可靠数据时不能为了视觉效果制造图表。
3. “没有图表”可以是正确选择，Gate 检查的是是否做过判断，而不是数量配额。
4. 生成图片只承担已声明的 scene/material/illustrative 等角色，不可替代事实证据。

### 4.3 P5B：让图片、图表、留白和页面 lineage 进入几何合同

Layout Plans 增加或等价表达：

- `page_role_id`：本页在 Seed/Packet 中的视觉角色；
- `visual_lineage_id`：本页应遵循的样板/页面家族 lineage；
- `component_family_id`：本页允许的组件语法，而不仅是 layout family 标签；
- `asset_slots[]`：角色、requiredness、目标占比、geometry、fit、focal point、crop intent、fallback；
- `chart_slots[]`：绑定 chart intent/data refs、图表主结论和可编辑性；
- `contrast_mode`：light/dark/image-led 等有限、可执行模式；
- `density_target` 与计算出的 `negative_space_ratio`；
- `topology_signature`：用于证明 architecture/timeline/matrix/full-bleed 等家族在主几何和阅读路径上确实不同。

G5B 不要求每页有图，而要求：规划中声明的视觉载体拥有真实席位；required asset 缺失时 fail 或走已声明 degradation；family label 与可观察拓扑一致。

### 4.4 P6：把 Art Direction 编译为可执行视觉语法

最终 `ArtDirectionPacket` 继续保持 provider-neutral 和内容寻址，但输入 lineage 增加 Seed，并把自由文本方向编译为结构化规则：

- `page_role_treatments` 从字符串 map 升级为结构对象：背景模式、标题处理、焦点载体、表面策略、允许组件、图片处理、图表处理。
- `component_variants` 从名称数组升级为有稳定 ID 的允许列表：适用 semantic role、fill/stroke/radius/padding/label treatment、允许条件与禁用组合。
- `deck_rhythm` 拆为可验证的序列/预算：连续同 contrast、同 component family、同 density role 的上限由本 deck 自身方向决定。
- `forbidden_patterns` 采用稳定 rule ID + scope + severity + rationale，供 Preflight 和 Review 消费。
- `image_rules/chart_rules` 明确不同 page role 的裁切、标注、图例、数据标签和降级方式。

Visual System 是 Packet 的确定性编译结果。Renderer 不读取 Taste 或 provider，但必须读取并执行上述结构化语法；不能再把 body/evidence/chart 默认统一绘制为同一 surface card。

Renderer IR 需要记录每张页面实际采用的：

- `art_direction_seed_ref`；
- `art_direction_packet_ref`；
- `visual_lineage_id`；
- `page_role_id`；
- `component_variant_ids`；
- `asset_slot_fulfillment`；
- `chart_intent_fulfillment`。

这样 Review 才能验证“语义存在并且真实执行”，而不只是检查字段已被序列化。

### 4.5 `VisualReferenceSet`：条件式代表页校准

对于 external showcase、brand-sensitive、critical quality profile，或用户显式要求样板时，在完整 P7 前先渲染 3–4 张代表页：

1. cover/statement；
2. evidence/chart；
3. image/media story；
4. dense/action/framework。

选择基于页面角色覆盖，不固定页码。校准产物必须来自真实目标 backend，并在 PPTX 目标下生成 Office previews。批准后冻结：

```text
.slidethus/art-direction/reference-sets/<sha256>.json
```

`VisualReferenceSet` 记录样板 slide IDs、Visual System/Packet lineage、Office page hashes、批准状态、允许变体和需要返工的最早责任阶段。它不是一个主题模板，也不进入 renderer 供应商依赖。

Checkpoint/Strict 模式由用户或授权 reviewer 确认；Auto 模式可由 VisualReviewProvider 确认，但 external/critical 的 generic fallback 不能自动越过。

样板失败时只回到 P5A/P5B/P6/P7 中最早责任阶段，修复后重新生成样板；不在同一 Production Attempt 中边看边改。

### 4.6 P8：Office-first 视觉回归与明确停止条件

当 Office preview 可用时，VisualReviewProvider 的主输入必须是 Office-rendered pages；Final SVG/PNG 只作为差异对照。Review 分四层：

1. **page correctness**：overflow、collision、字体、图表标签、图片裁切；
2. **plan fulfillment**：asset/chart slot 是否兑现，required degradation 是否披露；
3. **visual grammar**：组件、页面角色、contrast/density rhythm 是否遵循 Packet；
4. **reference propagation**：全篇是否与 `VisualReferenceSet` 同源，是否出现封面正确、正文漂移。

Review 指标不使用全局美学配额，而读取本 deck 的 Seed/Packet 预算。推荐观察量：

- visual lineage coverage；
- component family 连续页数与覆盖率；
- panel/card/pill/score-dot 等组件占比；
- light/dark/image-led cadence；
- breathing/balanced/dense cadence；
- image/chart/table/diagram/text carrier 分布；
- required asset/chart fulfillment；
- family topology diversity；
- sample-to-full visual consistency。

停止条件：

- Production Attempt 完成后才运行 retrospective review/synthesis；
- 用户接受并交付后，当前版本 frozen，不继续静默优化；
- 后续发现的共性缺陷进入新的版本/Attempt，并通过跨案例 promotion policy 决定是否修改框架；
- 单一审美偏好、Suggestion 或一次性页面反馈不自动晋升为生产规则。

## 5. Artifact and contract changes

| 对象 | 变更 | 状态模型 | 主要消费者 |
|---|---|---|---|
| Project Brief | 保持 live/read/both；品牌、场景、受众继续作为 Seed 输入，不在 Brief 中塞入主题模板枚举 | catalog artifact | Seed provider |
| `ArtDirectionSeed` | 新增 provider-neutral runtime fact | immutable/content-addressed | P5A、P5B、final Packet、Review |
| Slide Specs | 新增 `visual_strategy`、`chart_intent`、`asset_demand` | catalog schema minor/major 依兼容设计决定 | Layout Planning、Asset/Chart provider、Review |
| Layout Plans | 新增视觉 lineage、page/component family、asset/chart slots、contrast/density/topology | catalog schema migration | Visual System、Renderer、Review |
| ArtDirectionPacket | lineage 增加 Seed；自由文本组件语义升级为结构化规则 | supporting runtime schema migration | Visual System/G6 |
| Visual System | 编译为 executable page/component/rhythm grammar | catalog schema migration | Renderer/G6/G7 |
| Renderer IR | 记录实际使用的视觉规则与 slot fulfillment | runtime/renderer contract | Backends、Preflight、M5 |
| `VisualReferenceSet` | 新增条件式样板批准事实 | immutable/content-addressed | full render、M5 regression、Delivery |
| Visual Review Report | Office-first 输入、reference propagation 与 plan fulfillment findings | supporting runtime schema migration | Quality Report/G8 |

所有 canonical schema 与 `src/slidethus/_schemas/` packaged mirror 必须同步；不允许用 loose `additionalProperties` 绕过核心视觉合同。

## 6. Gate changes

| Gate/Review | 新增检查 | 失败路由 |
|---|---|---|
| G4 后置 Seed admission | Seed schema、provider identity、Brief/Narrative/Outline lineage、confidence/degraded disclosure | P0/P3/P4 或 capability block |
| G5A | 每页 primary carrier 有理由；定量 evidence 已作 chart/metric/table/prose 决策；required asset demand 有策略 | P5A/P2 |
| G5B | 视觉载体有席位；asset/chart slots 完整；family label 与 topology 一致；Seed rhythm 可实现 | P5B/P5A |
| G6 | Packet 绑定 Seed/Layout/Assets；Visual System 为结构化 executable grammar；provider/resource lineage 完整 | P6/P5B |
| calibration checkpoint | 代表页覆盖关键角色；真实 backend/Office pages；VisualReferenceSet frozen | P5A/P5B/P6/P7 |
| G7 | Renderer 真实消费 component/page-role grammar；forbidden rule、slot fulfillment、Office parity | P7 或最早上游阶段 |
| G8 | Office-first 全页检查；sample-to-full propagation；跨页组件/密度/载体节奏；Critical=0、Major=0 | P5A–P8 earliest owner |
| G9 | Delivery 引用 approved reference set（若 required），披露 degraded assets/charts 和实际 Office review | P8/P9 |

## 7. Provider strategy and Taste boundary

Taste 继续作为随库开箱即用的默认艺术指导资源，但不是核心 renderer 依赖，也不是唯一质量来源。

推荐 provider 模式：

1. `taste-reasoned`：ReasoningProvider 读取固定版本 Taste 原则和当前 artifacts，提出 Seed/Packet；这是高质量默认路径。
2. `enterprise/manual`：企业设计系统、模板提取、人工方向或其他 provider 输出同一合同。
3. `taste-deterministic-fallback`：无 reasoning capability 时给出保守通用方向，明确 degraded；不得冒充已完成主题级审美判断。

Taste 负责提供 anti-slop 原则和设计判断框架；Slidethus 负责阶段、Schema、lineage、渲染、Office 证据与 Gate。更换 Taste 不应修改 Slide Specs、Layout Plans、Visual System 或 renderer 的领域合同。

## 8. Implementation batches

### Batch A — 契约与回归夹具（先证明失败）

产出：

- 新 ADR：两段式 art direction、VisualReferenceSet 与 Office-first visual regression；
- `ArtDirectionSeed` / `VisualReferenceSet` supporting schemas 草案；
- Slide Specs、Layout Plans、Packet、Visual System、Renderer IR 的 schema migration 设计；
- FDE、珠宝、酒店香薰跨案例 fixtures 和当前失败断言。

验证：

- FDE live/read/showcase 在 posture、carrier、density、asset strategy 上必须可辨；
- 珠宝 external showcase 不能被判成科技蓝/暗色科技风；
- 酒店香薰的非封面页能检测 UI-card drift 和 visual lineage 缺失；
- 所有 fixtures 不匹配主题词、原句和固定 slide ID。

### Batch B — 上游判断与页面规划

产出：

- Seed provider/admission/runtime；
- Taste reasoning path + explicit deterministic fallback；
- Slide visual strategy/chart intent/asset demand；
- Layout asset/chart slots、topology 与 lineage；
- Planning Review/G5A/G5B 对应检查。

验收：

- 同一事实在 FDE 三种场景下产生不同且合理的 planning artifacts；
- 珠宝图表只出现在有数据问题的页面，图片席位在 layout 前已被声明；
- 无图片生成 capability 时走预先声明的降级布局，不留下空洞占位。

### Batch C — P6 到 Renderer 的执行闭环

产出：

- structured page-role/component/rhythm grammar；
- Visual System compiler；
- Renderer IR lineage/usage facts；
- Native、Hybrid、Final SVG 对同一规则的消费；
- forbidden rules 与 component coverage preflight。

验收：

- 不同 page role 在主几何、焦点、表面策略和阅读路径上可观察地区分；
- Renderer 删除“所有正文默认 surface card”的隐式全局行为；
- Visual System 字段被实际执行的 tests 取代单纯 metadata-presence tests；
- 三后端在 page/component lineage 上一致。

### Batch D — 代表页校准与 Office-first Review

产出：

- representative slide selector；
- calibration render pipeline；
- VisualReferenceSet approval/freeze；
- VisualReviewProvider Office-first input；
- sample-to-full propagation、slot fulfillment、deck rhythm review；
- Delivery freeze/版本停止规则。

验收：

- 酒店香薰先确认 4 页后，全 16 页能够证明同源而不必同构；
- Office 与 SVG 不一致时以 Office finding 为 release truth；
- 用户接受并交付后不会继续在当前版本上自动修改。

### Batch E — 跨案例发布回归

至少包含：

1. FDE external technical showcase；
2. FDE independent read；
3. 珠宝 external showcase / luxury editorial；
4. 酒店香薰 external showcase / low-luxury business research；
5. 内部 decision-support、数据密集、轻渲染样本；
6. 无网络/无图片生成/无 reasoning provider 的 degraded 样本。

每个 case 保存 artifacts、Seed、Packet、ReferenceSet（如 required）、PPTX、Office pages、Quality Report、预期 Gate 与容差。不用单一总分决定 release；Critical/Major 与场景符合度分别判断。

## 9. Acceptance matrix

| 能力 | 必须证明的事实 | 反例 |
|---|---|---|
| posture/idiom 分离 | 同为 external showcase，FDE 与珠宝呈现不同 visual idiom | 把 showcase 直接映射成科技蓝、霓虹、暗色 |
| 场景影响规划 | live/read/showcase 改变密度、载体、备注和节奏，而非只改变一个 dial | 三组 Art Direction hash/内容基本相同 |
| 图片规划 | required 图片在 P5A/P5B 已有角色、席位和降级 | 渲染末端发现空白才临时塞图 |
| 图表规划 | 定量 evidence 有明确 chart/table/metric/prose 决策和数据绑定 | 为好看伪造图表，或所有数字只写正文 |
| 页面家族 | family 在主几何、焦点、阅读路径上可区分 | 只换 label、角标或连接线 |
| 组件语法 | Packet/Visual System 的允许组件被 renderer 真实消费 | 字段存在但 renderer 仍硬编码卡片 |
| 风格贯穿 | 全篇 100% 页面有 visual lineage；变体在批准范围内 | 封面正确、正文逐页漂移为 dashboard |
| Office truth | PPTX release 使用真实 Office-rendered pages | SVG/IR/导出成功代替 Office 评审 |
| provider neutrality | 替换 Taste/人工/企业 provider 不改变核心 artifacts/backend 协议 | renderer 直接读取 Taste Skill |
| 停止条件 | accepted deck frozen；系统性修复走新 Attempt/版本 | 交付后继续无边界地修改当前文件 |

## 10. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-VI-001 | Decision | 采用两段式 Art Direction：G4 后 Seed，G5B 后 final Packet | 图片/图表/留白必须在 Layout 前受到方向约束，同时保留最终 Packet 的审计性 | 中 |
| D-VI-002 | Decision | 展示姿态与主题视觉语法分离 | 珠宝案例证明 external showcase 不等于科技风 | 高 |
| D-VI-003 | Decision | 图片与图表使用“必须做出选择”的合同，不使用全局数量配额 | 用户要求策划阶段考虑图表，但不能滥用 | 高 |
| D-VI-004 | Decision | Visual System 升级为 renderer 可执行语法，并记录 usage lineage | 当前最大共性缺口是语义已存在但未执行 | 中 |
| D-VI-005 | Decision | 代表页校准是条件式，不是所有 deck 的强制人工 Gate | 对外品牌 deck 收益高，内部阅读 deck 不应被过度渲染或拖慢 | 高 |
| D-VI-006 | Decision | Office 页面是 PPTX release 的最终视觉事实源 | ADR-0027 与真实溢出/风格漂移证据 | 低 |
| D-VI-007 | Decision | Taste 是默认指导资源，reasoning provider 控制主题级推导，deterministic core 控制 admission | 避免固定代码映射冻结审美判断 | 中 |
| A-VI-001 | Assumption | 现有 M6.6 仍保持 DO NOT RELEASE，直到本方案实施后的跨案例 Office 回归和用户评审完成 | TASKS 与当前 release audit | 高 |

## 11. Quality and risk controls

- 受影响 Schema：`project_brief` 原则上不改；新增 Seed/ReferenceSet supporting schemas；修改 `slide_specs`、`layout_plans`、`art_direction_packet`、`visual_system`、Renderer IR、Visual Review Report。
- 受影响 Gate：G5A、G5B、G6、G7、G8、G9；Project State phase 枚举不变。
- 回归范围：M3 planning、M4 compile/backends/preflight、M5 visual review/regression、M6 distribution/package、canonical/packaged schemas。
- 兼容策略：旧 artifacts 必须经显式 migration；legacy generic Visual System 可以读取，但 external/critical deck 不能以 legacy 路径通过新的视觉 release gate。
- 降级路径：缺 reasoning provider、图片 provider、chart provider、Office renderer 时分别记录 capability；不生成空白占位、不伪造数据、不宣称完成视觉校准。
- 过拟合控制：所有生产规则通过“移除主题、原句、页码后是否仍成立”的 anti-overfit test；具体案例只作为 fixture。
- 审美边界：确定性指标证明执行与一致性，不宣称完全证明“好看”；场景符合度和高阶审美仍由 visual reasoning + 条件式 checkpoint 共同确认。

## 12. Verification

实施阶段每个 batch 至少执行：

```bash
python -m compileall -q src tests scripts
ruff check src tests scripts
python -m pytest
python scripts/validate_all.py
python scripts/audit_package.py
npm test --prefix renderers/pptxgenjs
git diff --check
```

视觉验收还必须执行：

- 每个 golden case 生成真实 PPTX；
- 使用目标 Office renderer 导出逐页 PNG/PDF；
- 逐页开放问题审查，再做维度评审；
- reference-required deck 执行 sample-to-full regression；
- Native/Hybrid/Final SVG 对 visual lineage、page role、component usage 一致；
- Critical=0、Major=0；无隐藏在总分后的风格贯穿缺陷。

## 13. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| 1 | 三案例归因与统一控制模型 | 真实 PPTX/反馈/归因报告 | 可解释全部主要反馈 | completed |
| 2 | 本整体方案与 acceptance matrix | 架构/工件/Gate/ADR | 与现有产品原则一致 | completed |
| 3 | Batch A：ADR、Schema 草案、失败 fixtures | 用户确认方案 | schema + negative tests | pending |
| 4 | Batch B：Seed 与 planning contracts | Batch A | FDE/珠宝 planning regression | pending |
| 5 | Batch C：executable grammar 与 renderer | Batch B | backend usage lineage tests | pending |
| 6 | Batch D：ReferenceSet 与 Office-first review | Batch C | 酒店 4→16 页 propagation | pending |
| 7 | Batch E：跨案例 release regression | A–D | golden corpus + user Office review | pending |

## 14. Review

### 第一轮：开放问题发现

- Critical：无。方案没有削弱证据、来源、Office 或 provider-neutral 边界。
- Major：实施前必须先更新/新增 ADR；不能在未定义 migration 和 Gate 语义时直接扩展 Schema。代表页校准若被做成所有任务的强制人工步骤，会错误拖慢内部阅读场景，故明确采用条件式策略。
- Minor：`presentation_posture` 和 `visual_idiom` 的最终字段名可在 Batch A schema 评审中调整，但二者的语义分离不可丢失。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 跨案例解释力 | 5 | FDE、珠宝、酒店香薰均映射到同一传播链，且保留场景差异 | 需实现后用新 Attempt 验证 |
| 架构一致性 | 5 | 单主编排、provider-neutral、planning before render、Office gate 保持 | 需要新 ADR 正式接受 |
| 控制边界 | 5 | workflow/reasoning/evidence/checkpoint 各自职责明确 | reasoning provider capability 需要实现级协议 |
| 可测试性 | 5 | 每批有 negative fixture、跨案例 acceptance 和 Office 证据 | 视觉相似度不可退化为像素硬阈值 |
| 过拟合风险 | 4.5 | 无主题模板、无图片/图表配额、规则以合同/lineage 表达 | 真实 provider prompt 仍需 Round-A 审计 |
| 降级与停止 | 5 | 缺能力显式 degraded；accepted delivery frozen | 需要 Delivery/Review 实现落地 |

## 15. Final outcome

- 已完成：基于三组真实案例的统一归因、目标工作流、控制边界、工件/Gate 变更、Taste 边界、实施批次和验收矩阵。
- 未完成：尚未修改生产 Schema、provider、planning、renderer 或 review 代码；尚未新增 ADR。
- 推荐下一步：只启动 Batch A，先把 ADR、Schema migration 设计和跨案例失败 fixtures 固定下来；Batch A 评审通过后再进入行为实现，避免在新的视觉需求下再次用局部代码补救。
- 相关 ADR：ADR-0026、ADR-0027、ADR-0028；实施前需要新增一份覆盖 two-stage art direction、VisualReferenceSet 与 Office-first propagation regression 的 ADR。
