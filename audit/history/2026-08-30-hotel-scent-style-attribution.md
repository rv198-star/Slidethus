# 2026 中国酒店业香薰市场 PPT 风格贯穿归因分析

## 结论

这次“封面有味道，正文逐渐走向内部汇报”的问题，不应归结为某一种页面风格不够高级，也不说明 Slidethus 的内容与证据链路失效。

直接原因是本次初稿采用了脱离正式语义工件链的定制渲染脚本，并在脚本里主动建立了卡片、胶囊标签、评分点和等分面板等 UI 化组件。更深层的共性问题有三项：艺术指导进入流程偏晚，现有 Taste 默认实现仍偏通用，Visual System 中已经存在的页面角色与节奏语义没有真正驱动 Renderer。

因此，归因应分成两部分：

- 本次执行偏差：没有让 `ArtDirectionPacket`、Layout Plan、Visual System 和 M5 Review 形成闭环，直接在渲染脚本中做了大量页面局部判断。
- 共性能力缺口：艺术指导、图片席位、组件语法和全篇视觉回归之间尚未建立可执行的传播契约。

本次低奢统一版已经证明：内容本身无需重写，只要先冻结视觉母版约束，再把页面映射到不同但同源的页面家族，整篇可以保持低奢、高雅、可对外宣讲的气质。

## 一、这次迁移做对了什么

16 页没有套用一个固定模板，而是统一了视觉母语，再按信息关系选择页面家族。

- 统一母语：深松绿、冷瓷白、石材灰、克制琥珀色；PingFang SC；直角编辑面；不使用阴影和悬浮式卡片。
- 页面家族：封面/结论、证据图表、全幅场景、阶梯关系、供应链叙事、竞争矩阵、合规清单、情景模型、进入决策、行动收束。
- 图片承担任务：酒店场景用于品牌与体验语境，设备静物用于供应链说明，团队与实验室图片用于采购委员会、合规和能力边界。
- 图表不被装进“仪表盘卡片”：酒店基盘、连锁率和市场情景均使用可编辑原生图表，并直接标注结论。
- 跨页节奏：深色与浅色交替，照片页与证据页交替，避免连续多页同构。

这些改动说明，优秀结果的关键不是“统一使用某个科技风或奢华风”，而是先定义场景合适的展示语法，再让所有页面在同一语法内变化。

## 二、五层归因

### 1. 执行路径：初稿绕开了正式工作流

初稿脚本 `/private/tmp/slidethus-hotel-scent-2026/build/build_deck.mjs` 直接把内容编译成 PPTX。它在第 81 至 93 行定义了 `pill`，在第 144 至 148 行定义了 `scoreDot`，并在正文中持续使用圆角面板、等分卡片和评分点。例如第 163 行在封面使用胶囊标签，第 701 至 702 行在方案比较中使用评分点与“推荐”胶囊。

这不是 Taste 或 Art Direction 推导出的组件语法，而是渲染阶段的局部便利选择。它天然会把外部宣讲稿拉向产品后台、咨询看板或内部运营汇报。

责任性质：本次执行主因，不是底层内容模型失效。

### 2. Art Direction 时点：在布局之后才冻结，无法预留图片与构图

当前 ADR 规定 `ArtDirectionPacket` 在 G5B 之后、Visual System 之前生成，并绑定已经完成的 Layout Plans。见 `docs/adr/ADR-0028-provider-neutral-art-direction-packet-and-taste-default.md` 第 15 至 33 行。

这保证了 provider neutrality 和审计性，但也造成一个结构性限制：当艺术指导出现时，图片区域、留白比例、主视觉位置和页面家族已经由 P5B 决定。Packet 可以改变颜色、字体和表面处理，却不能自然地要求“这页必须有一张承担场景证据的图片”或“这一页需要 40% 的呼吸区”。

用户观察到“规划时没有考虑图片占位，后面自然没有图片填充”，正是这个时序问题的外显结果。

责任性质：共性架构缺口，需通过前置的 provider-neutral Art Direction Seed 或允许 P6 触发有边界的 P5B 回流解决。

### 3. Taste 默认实现：具备契约，但审美推导仍偏固定和通用

`schemas/art_direction_packet.schema.json` 第 122 至 179 行已经能够表达页面角色处理、组件变体、全篇节奏、变化规则和禁用模式，契约方向是正确的。

但当前 `TasteSkillArtDirectionProvider` 的实际 proposal 主要是固定代码映射：

- `src/slidethus/art_direction.py` 第 143 至 146 行生成通用的 editorial design read；
- 第 188 至 259 行固定主题、配色、圆角、页面角色、组件变体、节奏和 forbidden patterns；
- 对主题内容的适配主要来自受众、用途、演示模式、语言和可选品牌色，尚未真正推导“酒店低奢”“珠宝时尚”“技术展示”等不同视觉语法。

因此，当前实现可以防止明显模板化，但不能单靠它稳定地产生场景级艺术方向。它更像一个安全、可审计的通用 editorial 默认值，而不是完整的 Taste 推理代理。

责任性质：共性实现深度不足，不是对 Taste 的依赖问题。

### 4. Layout 与 Renderer：语义字段存在，但没有形成执行闭环

布局层存在两个限制。

第一，`schemas/layout_plans.schema.json` 第 97 至 250 行只要求页面家族、Block 到 Region 的几何映射和容量诊断，没有 `visual_lineage_id`、`page_role_treatment`、`image_role`、`asset_slot`、焦点/裁切意图或组件家族约束。Slide Specs 虽可声明 image/chart Block 和 `asset_refs`，但不足以说明图片在叙事中的作用。

第二，确定性布局实现仍然偏通用网格。`src/slidethus/layout_geometry.py` 第 37 至 65 行以等分网格作为基础；第 311 至 320 行甚至让 architecture、bento、custom 和 full-bleed 共享同一网格生成逻辑。页面家族名称因此可能不同，实际拓扑却趋同。

Visual System 已把艺术指导字段保存下来：`src/slidethus/services/visual_system.py` 第 169 至 172 行写入 `page_role_treatments`、`component_variants`、`deck_rhythm` 和 `variation_rule`。但 Renderer 没有消费这些字段。`src/slidethus/services/render_compile.py` 第 47 至 115 行按 Block 角色硬编码 surface/card 表面，第 257 至 323 行又按 family 硬编码侧边强调条、圆角块和连接线。代码库搜索显示，这些高层艺术指导字段除测试和序列化外，没有进入渲染决策。

这就是最关键的“契约存在但未落地”：颜色 token 传下去了，构图与组件语法没有传下去。

责任性质：共性实现主因。

### 5. Review 与 Gate：能发现重复，但还不能证明风格贯穿

现有 Planning Review 已有价值：`src/slidethus/services/planning_review.py` 第 649 至 728 行能发现关系拓扑坍缩、Bento 过度使用和连续布局家族重复。这说明项目并非没有节奏意识。

但仍有三处缺口：

- 阈值是 Planning Review 内部固定值，没有读取 `ArtDirectionPacket` 的 `max_same_family_consecutive` 与 `max_bento_ratio`。
- 它检查 family 与粗拓扑，不检查组件词汇，例如卡片覆盖率、胶囊标签、评分点、进度轨迹、图片分布和明暗节奏。
- `src/slidethus/services/review_regression.py` 第 210 至 257 行的 cross-deck regression 主要验证工件未意外变化、页面存在和 Gate 完整性，不是视觉母版回归。

另外，`src/slidethus/services/visual_review.py` 第 99 至 157 行会登记 Office preview，但第 239 至 263 行交给 VisualReviewProvider 的主图像参数仍是 `final_paths`，即 Final SVG PNG；Office 页面更多是状态与路径元数据。真实 Office 页面尚未成为视觉 provider 的一等输入。

责任性质：共性质量门禁缺口。

## 三、哪些不是问题

- 不是所有 PPT 都应当低奢。技术展示、时尚品牌、内部决策、深度阅读应有不同视觉语法。
- 当前内容主线、证据来源和供应链建议不需要因视觉问题整体推倒。
- Bento、卡片、时间线和图表都不是禁用组件；问题在于是否符合场景、是否承担信息关系，以及是否被滥用为默认布局。
- 图表能力不是缺失，而是策划阶段没有把“哪些数字值得形成视觉证据”作为强制选择题，导致使用不足。

## 四、建议的共性解决方案

### P0：让艺术指导在布局前产生约束，在布局后冻结事实

采用两段式 provider-neutral 设计：

1. P5B 前生成轻量 `ArtDirectionSeed`，只表达场景、视觉母语、图片方向、图表方向、页面角色和禁用组件，不绑定最终几何。
2. Layout Planning 消费 Seed，预留图片、图表和呼吸区。
3. G5B 后生成最终不可变 `ArtDirectionPacket`，绑定 Layout Plans 与 Asset Manifest，保持当前审计和 provider-neutral 设计。

如果不新增工件，也可以允许 P6 在发现“艺术指导与布局冲突”时生成结构化 repair request，有限回流 P5B。

### P0：让 Renderer 真正消费 Art Direction 的语义字段

- `page_role_treatments` 必须映射为可执行页面骨架，而不是仅保存为字符串。
- `component_variants` 必须成为允许列表；Renderer 不应再默认把 body/evidence/chart 统一绘制为 surface card。
- `forbidden_patterns` 必须进入 preflight 和视觉审查，例如检测胶囊、评分点、过高卡片覆盖率、连续相同组件语法。
- 页面家族要有可区别的空间拓扑，不能仅依靠 family 名称。

### P1：把图片与图表变成策划阶段的一等公民

建议给 Slide Specs/Layout Plans 增加或等价表达：

- `image_role`: scene / evidence / material / portrait / texture / none；
- `asset_slot`: 必须、可选、降级策略、焦点、裁切方向与预计占比；
- `chart_intent`: 要回答的问题、比较维度、图表类型候选、数据成熟度；
- `visual_lineage_id`: 该页属于哪个已批准样板或页面家族。

这样“是否要图”“为什么要图”“图放在哪里”会在规划阶段被决定，而不是渲染末端临时补图。

### P1：建立样板到全篇的视觉回归

在正式生成全篇前，先选择 4 个代表性页面家族制作样板，例如封面/主结论、证据图表、图片叙事、行动页。用户确认后冻结为 `VisualReferenceSet`。

全篇 Review 至少检查：

- 页面家族是否来自批准的 visual lineage；
- 同一组件语法连续出现的页数；
- 卡片、圆角、胶囊、评分点等组件覆盖率；
- 图片页、图表页、纯文字页的分布；
- 深浅页面与信息密度节奏；
- 与 4 页样板在字体、配色、留白、图片处理和组件边界上的一致性。

### P0：Office 页面必须成为最终视觉审查的一等输入

VisualReviewProvider 应直接接收 Office-rendered page paths，并在有 Office 预览时优先审查 Office 页面；Final SVG 可作为差异对照，不能替代真实交付物。

## 五、最终判断

本次初稿的视觉漂移，以执行绕行和硬编码 UI 组件为直接主因；Slidethus 的共性缺口则集中在艺术指导时点、图片/图表策划、Visual System 到 Renderer 的语义落地，以及样板到全篇的 Office 视觉回归。

因此不建议为“酒店低奢”写一套专用模板，也不建议让 Taste 直接接管渲染器。正确方向是：保留 provider-neutral `ArtDirectionPacket`，把 Taste 作为默认艺术指导来源，同时补齐从场景推导、布局预留、组件翻译到全篇回归的通用能力。

本次 16 页低奢统一版可作为下一轮实现这些共性能力时的视觉基准，而不是作为酒店行业专用规则写入代码。
