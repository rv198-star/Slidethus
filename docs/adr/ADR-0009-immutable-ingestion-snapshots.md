# ADR-0009｜Immutable Source Ingestion Snapshots

- Status: Accepted
- Date: 2026-08-27

## Context

MVP1 的 `PlainTextSourceParser.parse(path, source_id)` 只返回内存 Chunk。它能够证明纵向链路，但不能回答以下生产问题：

- 文件究竟由哪个 parser 版本、哪些限额和哪次格式识别结果解析；
- Chunk、locator、warning 与 source risk 如何在中断后恢复；
- Source Ledger 提交失败时如何避免半写入事实；
- 同一来源重跑、策略修改、parser 升级或限额变化时如何保持稳定身份；
- 如何验证缓存没有被替换、错绑或篡改。

把解析正文直接塞入 Source Ledger 会放大版本、复制和迁移成本；只保留临时内存结果又无法形成可审计事实。

## Decision

M2.1 采用“版本化 Source Ledger 引用不可变解析快照”的结构：

1. `SourceParser` 接收 `SourceParseRequest` 和确定性格式识别结果，返回包含 parser lineage、来源哈希、稳定 Chunk IDs、精确 locator、warning 与 source risks 的 `SourceParseResult`。
2. Parser Registry 按显式格式支持和优先级选择一个适配器；同优先级歧义和无适配器格式均失败，不猜测能力。
3. 解析结果写入 `.slidethus/cache/ingestion/<input-key>.json`。Key 由 source ID、来源字节哈希、parser 名称/版本、格式识别结果和解析限额共同决定。
4. 快照使用 create-if-absent 原子发布。已存在路径永不被覆盖；并发或中断后的调用必须验证并复用原快照。
5. 快照先落盘，Source Ledger 再通过 Artifact Runtime 事务提交引用。Ledger 提交失败只留下无引用缓存；再次执行可安全复用。
6. Source Ledger 记录 parser、格式、快照路径/哈希、Chunk/warning/risk 数量和解析限额。工作区校验同时验证快照 Schema、文件哈希、输入 key、Chunk identity、内容哈希和 Ledger 引用一致性。
7. `source_id` 一旦绑定到用户文件路径就不能重绑；同一路径也不能创建第二个别名 ID。
8. 未变化来源允许复用快照，但 title、ownership、confidentiality、authority 和 allowed-use 的修改仍会创建新的 Source Ledger 版本。Parser 版本、来源字节或解析限额变化必须生成新快照。
9. 来源正文始终是不可信数据。解析器只记录指令性文字、活动内容和外链风险，不执行宏、脚本、链接或来源中的工作流指令。
10. M2.1 的 Production adapter 只承诺 Markdown/TXT。CSV、HTML、PDF、DOCX、PPTX、XLSX 和图片即使可被识别，也在对应适配器完成前显式返回 unsupported。

`source_snapshot.schema.json` 是运行时辅助事实合同，不进入顶层 Artifact Registry；它随 Python 包分发并由 Source Ledger 引用和工作区校验负责完整性。

## Consequences

- 中断、重复执行和并发创建不会把半解析结果发布为正式来源事实。
- Source Ledger 保持轻量，解析正文可按输入身份复用，同时仍受完整性验证。
- Parser 或限额改变会产生新的缓存文件，旧文件可供历史版本审计；缓存清理必须先做引用分析。
- 快照包含来源正文并继承其保密等级，不能默认上传、打包到交付物或发送给外部模型。
- 旧 Source Ledger 记录可以暂时没有 `ingestion` 字段；所有由 M2 ProductionImpl 新建且使用 `sha256:` 内容哈希的 parsed 来源必须有有效快照。
- 多格式适配器必须复用同一协议、快照和失败语义，不能各自建立旁路缓存。
