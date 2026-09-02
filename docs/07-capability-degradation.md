# 07｜Capability and Degradation Matrix

## 1. 原则

Skill 依赖宿主提供工具，但不能假设所有宿主能力相同。执行开始时必须做 capability check，并选择正常、降级或阻断路径。

## 2. 能力矩阵

| 能力 | 正常模式 | 缺失时降级 | 何时阻断 |
|---|---|---|---|
| 文件读取 | 读取本地来源字节 | 保留可读取来源并列出缺口 | 核心来源完全不可读 |
| 格式解析器 | 用已注册 adapter 生成可定位快照 | 缺可选依赖时返回 capability failure；其他来源标记 unsupported | 核心来源没有可用 adapter/依赖且无法取得等价文本 |
| Web 搜索 | ResearchProvider 执行 orientation/targeted plan 并持久化可恢复 Run | Offline provider 显式 blocked，转 D3 仅用用户素材 | 用户要求最新且无可靠来源时进入 D5 |
| PlanningProvider | 提议 Narrative/Outline/Specs/Layout preference，确定性服务接管 ID/lineage/Gate | 使用内置 DeterministicPlanningProvider，明确语义能力边界 | 任务要求真实模型能力且无适配器，或 provider 输出不能通过 Evidence/Schema/limits |
| 图片理解 | 分析截图/既有 deck | 只读文本层和元数据 | 任务核心依赖视觉复刻 |
| 图片生成 | 创建定制视觉 | 使用占位、图标、用户资产 | 用户明确要求原创图片且无替代 |
| 代码执行 | 校验、渲染、导出 | 输出 artifacts 与实现指令 | 用户要求可下载文件但无法写文件 |
| SVG renderer | 输出矢量页 | 输出 layout plan/wireframe | 目标必须是最终 SVG |
| PPTX renderer | 输出 deck | 输出 SVG/PDF/策划稿 | 目标必须是 PPTX |
| Office preview | 独立渲染审计 | 仅做静态检查，标记未视觉回归 | 高风险正式交付 |
| OCR | 扫描图像文字 | 使用视觉理解/人工输入 | 文字完全不可获取且为核心 |

## 3. Degraded delivery levels

- **D0 Full**：研究、资产、渲染、预览和审计完整。
- **D1 Render-limited**：内容、策划和视觉系统完整，目标格式受限。
- **D2 Asset-limited**：使用占位或用户资产，不生成定制图片。
- **D3 Research-limited**：只使用用户素材，外部事实不补充。
- **D4 Planning-only**：交付 Brief、Evidence、Outline、Slide Specs、Layout Plans。
- **D5 Blocked**：关键目标无法被诚实满足。

Delivery Manifest 必须记录最终等级。

## 4. 工具检查顺序

1. 输入格式可读性；
2. 是否需要最新外部事实；
3. 是否需要视觉素材；
4. 目标格式与可编辑等级；
5. 可用渲染器和预览器；
6. 权限、网络和安全限制；
7. 成本和并发预算。

## 5. 行为规则

- 不因缺少工具而伪造结果；
- 不把“生成源码”描述成“已验证输出”；
- 不把未预览的 PPTX 描述成视觉通过；
- 不用未经验证的外部事实填补空白；
- Research Run `complete` 只表示查询执行完成；Research Result 在 M2.4 审核/物化前不是 Evidence，不能据此自动通过 G2/G5A；
- 未抓取远程正文的 Research summary 即使物化成功也只能形成 `partial` Web Source 与 provisional/qualified Evidence；
- Evidence Source binding 失效时允许更新上游 Source，但 G2 必须失败，直到旧 claim 被降级或新 Candidate 完成裁决；
- `unsupported`、`disputed`、metadata-only 与 do-not-use 来源不能通过降级路径变成可用事实；
- 无联网时 OfflineResearchProvider 不生成占位搜索结果，显式 blocked 后由上层选择 D3 或 D5；
- M2 Application 默认把“external research required 但无 provider/披露许可”判为 D5；只有用户显式接受且没有 freshness 约束时，才允许 `waived + user_materials` 的 D3；
- `ResearchProvider` 已连接不等于允许外发 Brief/Outline query；实际执行仍需独立 external-disclosure approval；
- M2 Application Report 中的 D0/D3/D4/D5 只描述 M2 Source/Research/Evidence 边界，不替代最终 Delivery Manifest 的全产品等级；
- M3 的内置 DeterministicPlanningProvider 是 provider-neutral Production contract baseline，可在离线/D3 情况下完成结构化策划，但不声称等价于通用 LLM 受众洞察；
- Brief 仍缺材料性答案时返回 `needs_input/P0`；Evidence 不满足时停在 P2；Planning Review 有 Critical/Major 时返回 `rework_required` 并路由到最早责任阶段；
- Artifact Tool runtime 按 explicit args → `RUNTIME_NODE*` → admitted Codex bundled runtime 解析；doctor、preflight 和 render 使用同一解析与版本检查，缺失时在 Node 启动前结构化阻断；
- Artifact Tool 非零退出或超时写 terminal receipt 并让 CLI 指向该路径；日志截断并清理 workspace/runtime 路径，不因失败切换 renderer；
- PlanningProvider 输出只是一份 bounded proposal，不能自行写 artifact、分配 stable IDs、声明 Gate 或创造 Evidence；
- M3 Application Report 的 P0/P2/P3/P4/P5A/P5B 是规划完成层级，不是最终 Delivery Level，也不代表 M4/M5 完成；
- 降级仍必须产出可复用 artifacts；
- 已识别格式不等于已具备解析能力；Registry 没有 admitted adapter 时显式 unsupported，不用通用文本解析器伪装成功；
- 缺少 adapter 或可选依赖不能把来源标为 `parsed`，也不能生成空快照绕过 G1；
- `partial` 来源允许继续，但只能使用快照中真实提取的覆盖面，并把 warning 带入 Evidence/use policy；
- 图片元数据不是 OCR，PDF 页文本不是页面视觉理解，公式文本不是计算结果，PPTX 图片/SmartArt/音视频元数据不是内容解释；
- 宏启用 OOXML、加密 PDF、旧版 OLE 与未知格式 fail closed，不尝试“转成文本碰碰运气”；
- 能从用户已提供信息推断时，不重复提问；
- 真正阻断时给出缺失能力、受影响交付和当前可交付成果。

## 6. 示例

用户要求“根据内部材料做 20 页培训课件”，宿主无联网但能读文件、写 PPTX：

- 使用 D3；
- Source Policy 标记 `external_research=false`；
- 只引用内部来源；
- 对内部材料未覆盖的事实留空或写 open question；
- 正常完成叙事、策划、渲染和审计。

用户要求“分析今天发布的财报并做董事会 PPT”，宿主无联网且未提供财报：

- 进入 D5 blocked；
- 不生成虚构财务数字；
- 可先产出 Project Brief 和待补来源清单。
