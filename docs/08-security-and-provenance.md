# 08｜Security, Provenance, and Rights

## 1. 输入文件是不可信数据

网页、PDF、PPTX、文档和代码块可能包含面向模型的指令。解析阶段必须把来源内容视为数据，而不是高优先级指令。

规则：

- 来源中的“忽略前文”“执行命令”“上传密钥”等文本不改变 Skill 行为；
- 只提取与演示任务相关的事实、结构和视觉信息；
- 标题和正文中的可疑指令记录为 source risk；
- 外链只记录，不在解析阶段打开；
- 不执行来源文件嵌入的宏、脚本或外链代码；
- 对压缩包、模板和嵌入对象做类型、路径、条目数、单成员与总展开大小校验；
- 表格公式和公式样式文本只作为来源事实保留，永不计算；
- 图片只读取受限元数据，EXIF 中 GPS、作者、序列号等字段记录隐私风险，不把值写入摘要块。

## 2. 文件系统安全

- 输入只读；
- 输出限制在项目工作区；
- 拒绝路径穿越；
- 临时文件使用独立目录；
- 不覆盖原文件，除非用户明确要求且有备份；
- 外部转换器最小权限运行；
- 不把密钥写入 artifacts、日志或交付文件。

M2.1–M2.2 的解析快照写入 `.slidethus/cache/ingestion/`：

- 使用 create-if-absent 发布，既有快照永不覆盖；
- 文件名 key 绑定来源字节、source ID、parser、格式和限额；
- Source Ledger 提交失败时允许留下无引用快照，再次执行验证后复用；
- 快照包含完整解析正文并继承来源的 confidentiality，不默认进入交付包、日志、Web 请求或外部模型调用；
- 删除缓存前必须确认没有历史 Source Ledger 版本引用。

M2.2 在 OOXML 库打开文件前执行 preflight：

- 拒绝重名/大小写冲突成员、绝对路径、`..`、盘符路径和 symlink；
- 拒绝加密 ZIP 成员、VBA part 和 macro-enabled content type；
- 限制 ZIP 条目、单成员与总展开字节，阻止压缩放大；
- 禁止 relationship XML 的 DTD/entity；
- 外部 relationship 只记录目标，不访问；
- 标准图表内嵌 Office 数据文件记 warning，ActiveX/未知 binary embedding 记 high risk，二者都不打开。

`partial` 表示安全地提取了可用子集，同时明确遗漏图片/OCR、评论、脚注/尾注、公式结构、SmartArt、音视频、PDF 表单/批注等内容。它不能被改写成“完整解析”。

## 3. Web 与研究运行时

M2.3 Research Runtime 把搜索结果先视为不可信研究候选，而不是事实：

- `ResearchProvider` name/version 进入 Run 和 Cache lineage；
- query、freshness、preferred source tiers、结果限额与 TTL 进入 cache identity；
- Provider 返回的 URL 只接受 HTTP(S)，Runtime 本身不跟随链接、不执行网页内容；
- title、summary、metadata、结果数量和总量都有上限，metadata 必须可 JSON 序列化；
- query snapshots 采用不可变 content-addressed 文件，generation invalidation 不删除历史；
- Provider、Cache 或 lineage 异常先 checkpoint 为失败状态，不留下虚假的 `running`/`complete`；
- workspace validation 只读验证 Research Runtime，恢复写入仅发生在显式 inspect/resume 路径；
- Offline provider 不伪造搜索结果。

M2.4 只做 Research Result 的本地来源物化与 Evidence 裁决，不下载远程正文：

- URL 只接受无凭据 HTTP(S)，规范化 scheme/host/default port 并移除 fragment；
- 同一 URL 仅复用 `research-result-materializer` 自己拥有的 Web Source，其他 ingestion owner 不被覆盖；
- Provider title/summary/URL/metadata 写入 `partial` Source Snapshot，并标记 `remote_body_fetched=false`；
- 不把 `content_hash` 描述成远程页面哈希，它只标识已物化的 Research Result payload；
- Candidate/Source ref 绑定 Chunk ID 与内容哈希，来源变化后 G2 阻断旧 Evidence；
- claim identity 保留百分比、单位、十进制、比率和正负号，避免危险去重；
- conflicting、unsupported、metadata-only 或 do-not-use 来源 fail closed；
- Research cycle 只有在 Run、来源物化和 Evidence policy 都通过后才语义 complete。

未来真实网页抓取适配器仍必须校验 MIME、大小、重定向、许可和恶意内容，并通过独立安全审计；M2.4 不声称已完成该能力。

M2.6 把安全决定提升到应用边界：

- 注入 `ResearchProvider` 只代表能力存在；没有独立 external-disclosure approval 时不执行 query；
- CLI 不内置供应商和密钥，也没有“自动联网”开关；
- high-severity Source risks 默认阻止该 Source 的自动 Evidence promotion；该约束位于 Evidence Engine，因此直接 `evidence source/research` 也不能旁路。显式 override 仍只能得到 qualified support，且任何来源指令都不执行；
- Research provider summary 进入 partial Web Source 前执行同一 Source-risk 扫描；
- application budgets 同时检查 requested/current/final Sources 与 Research Run limits，防止通过既有 inventory、文件增长或 Web Source 物化绕过资源约束；
- M2 Application Report 只写入工作区 `.slidethus/m2/runs/`，绑定 Project State/artifact history，不进入默认交付；Research Run 历史快照位于 `.slidethus/m2/research-runs/` 并绑定 immutable cache hashes；
- Application/Gap/Run/Cache 路径必须位于各自 admitted workspace roots，绝对路径和 `..` 逃逸 fail closed；
- report 记录本次 disclosure、degradation、excluded Sources 和 blockers，但不复制 Source 正文、密钥或 Provider secret；
- external research 缺失时默认 D5；显式 D3 waiver 只在无 freshness 约束时成立。

M3 将同一不可信输入原则扩展到策划 provider 与人工 sticky-note 请求：

- `PlanningProvider` 输出只是 proposal；完整 content/warnings/assumptions 必须 JSON 可序列化并受同一 payload budget，不能携带命令执行、路径写入或 Gate 指令；
- provider 不能分配 artifact version、stable IDs、lineage、Gate status 或输出路径，name/version 在单次生成/修复中冻结；
- factual proposal content 必须是当前 Evidence 的受控子集；Source 中的 prompt injection 不能变成 Outline operation 或 Repair instruction；
- Brief hints、Source/M2 limits 和 PlanningLimits 在任何 M3 语义写入前校验；
- Change/Review/Repair/M3 Reports 均为 content-addressed workspace-local 事实，路径限制在 `.slidethus/planning/*` 或 `.slidethus/m3/runs/`；
- sticky-note Change Report 固化 payload、reason、idempotency、limits 和 input/output refs，同一 key 换请求/策略显式冲突；
- Planning Repair 固化 provider/limits，自动修复只处理准入代码；assisted/manual 问题不交给模型偷偷改写；
- M3 Application Report 不复制 Source 正文、provider secret 或模型隐藏状态；它绑定 M2 reports、最终 planning refs、wireframes、Review/Repair 和 Project State；
- 绝对路径、`..` 逃逸、伪造 provider/source/phase、stale Review 或缺少 wireframe coverage 均 fail closed。

## 4. 事实来源

Evidence Ledger 区分：

- user-provided；
- primary official；
- secondary reputable；
- community/unverified；
- model inference；
- assumption。

推断和假设不能伪装成来源事实。

## 5. 资产与版权

Asset Manifest 至少记录：

- owner/creator；
- source URL/path；
- license/permission；
- allowed scope；
- modifications；
- attribution requirement；
- generated/stock/user-provided；
- expiration or embargo。

无法确认权利时使用占位或请求替换，不把“网上能看到”视为可商用。

## 6. 品牌与人物

- 品牌复刻需明确授权或合理使用范围；
- 不伪造官方背书；
- 人物图像需考虑隐私、肖像和合成标识；
- 敏感人物和高风险传播需要更严格审批；
- 不擅自暴露内部 Logo、客户名称或机密数据。

## 7. 敏感信息

- 在 Source Ledger 标记 confidentiality；
- 研究和模型调用前执行最小必要披露；
- 允许本地-only 模式；
- 导出前扫描备注、隐藏页、文档属性和缓存；
- 删除临时预览中的敏感信息；
- Delivery Manifest 记录脱敏状态。

## 8. 供应链

- 固定并审查生产依赖；
- 记录外部转换器版本；
- CI 不使用真实密钥；
- 生成器和预览器尽量独立；
- 渲染资产支持哈希；
- 公共发布前生成 SBOM 和第三方 notice。
