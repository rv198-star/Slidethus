# M2 — Ingestion, Research, Evidence

## 1. Objective

- 用户价值：把用户文件和允许的外部研究可靠地转化为可定位、可恢复、可审计的来源与证据事实，阻止无来源、冲突、过期或不可用声明进入叙事和页面。
- 本轮边界：按可替换 ProductionImpl 逐模块完成 P1 Source 与 P2 Evidence；保持 M1 Artifact Runtime、MVP1 动作链和 M3–M5 MinimalImpl 可继续运行。
- 明确不做：生产级叙事生成、最终视觉升级、图片生成、PptxGenJS/Hybrid renderer、自动视觉修复。
- 退出条件：M2 roadmap 的全部任务有真实实现和失败路径；任一外部事实可追溯到来源与 locator；两阶段研究 lineage、缓存、失效、恢复和离线降级通过测试；G1/G2/G5A 相关 Gate 无 Critical/Major 缺口。

## 2. Current state

- 当前 HEAD / 工作区状态：`1c898eca811747512f19b14a1470fab3c477e676`，开始前工作区干净。
- 已存在能力：M1 journaled Artifact Runtime；Markdown/TXT `PlainTextSourceParser`；用户材料限定的 Minimal Evidence；两阶段 research cycle Schema；完整 MVP1 分阶段输出链。
- 已知缺口：解析协议只有 `parse(path, source_id)`；解析结果未作为可恢复事实持久化；无 parser registry、格式识别、query/task lineage、研究缓存、证据去重/冲突/时效引擎和生产 CLI。
- 基线测试：Python 3.11 容器中 `57 passed`；`validate_all.py` PASS；`audit_package.py` PASS 18/18、212 files hashed。宿主仅有 Python 3.10，后续验证固定使用已存在的 `python:3.11-slim` 容器。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-001 | Decision | 按 M2.1–M2.7 顺序替换模块，先完成 Ingestion Core，再扩展格式、研究和证据；不先升级渲染。 | `TASKS.md`、`CODEX_KICKOFF.md`、R-001/R-003 | 高 |
| D-002 | Decision | ProductionImpl 继续实现 provider-neutral protocol；供应商、模型和网络参数不得进入领域 Schema。 | ADR-0005/0007、架构依赖规则 | 高 |
| D-003 | Decision | 解析输出必须有稳定 chunk identity、locator、内容哈希、parser lineage、warnings 与 source risks，并能够在中断后恢复。 | M2 Exit Gate、`docs/10-codex-build-plan.md` | 中 |
| D-004 | Decision | 保留 MinimalImpl 作为显式兼容/降级路径；ProductionImpl 通过相同应用入口逐项替换，不修改后续语义 artifacts 的含义。 | ADR-0007/0008 | 高 |
| D-005 | Decision | 新生产依赖优先放入可选 extras；确定性核心保持轻量，缺少适配器依赖时返回可解释 capability failure。 | AGENTS.md、D3/D4 降级规则 | 高 |
| A-001 | Assumption | M2 可新增辅助 Schema/运行时事实，只要更新 ADR、示例、校验和迁移策略，并保持旧 MVP 工作区可验证。 | Artifact-first 原则 | 中 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| M2.1 | Ingestion Core：格式识别、parser registry、稳定 chunk/locator/hash、source inventory、风险记录、可恢复持久化、Markdown/TXT Production adapter | M1 runtime | 单元、集成、故障注入、旧 MVP 回归 | complete |
| M2.2 | Multi-format adapters：HTML、PDF、DOCX、PPTX、CSV/TSV、XLSX、图片元数据/能力降级 | M2.1 | 每格式 golden fixture、损坏/加密/空文件/超限/partial 测试 | complete |
| M2.3 | Research planning/runtime：orientation + targeted query plan、task lineage、cache、resume、invalidation、offline provider | M2.1 | 网络无关 contract tests、缓存/中断/过期测试 | complete |
| M2.4 | Evidence engine：claim normalization、稳定 ID、dedupe、support、conflict、freshness、authority、use policy | M2.2–M2.3 | 对抗数据集、跨来源冲突、不可用声明阻断 | complete |
| M2.5 | Block-level evidence binding 与 outline-driven gap analysis / rework route | M2.4 | G2/G5A、`OUTLINE_READY → EVIDENCE_READY` 回归 | complete |
| M2.6 | CLI/application integration、capability degradation、source-instruction isolation、安全限额 | M2.1–M2.5 | 端到端 CLI、离线/缺依赖/风险输入测试 | complete |
| M2.7 | 文档、ADR、完整基线、开放问题审计、修复、维度评分和 M2 Exit Gate | 全部 | required checks + audit evidence | complete |

## 5. Quality and risk controls

- 受影响 Schema：Source Ledger、Evidence Ledger；必要时新增解析/研究辅助 Schema，并提供兼容策略。
- 受影响 Gate：G1 Sources、G2 Evidence、G5A targeted-evidence completion；不得降低既有标准。
- 回归范围：workspace init、Artifact Runtime、跨引用、状态机、Minimal MVP、CLI、package audit。
- 降级路径：缺少格式适配器或可选依赖时返回 explicit unsupported/capability failure；存在可用子集但遗漏图片、评论、媒体等时 `partial`；无联网时使用 D3；要求最新事实而无来源时 D5 blocked。
- 安全/来源/版权风险：路径穿越、压缩炸弹、宏/脚本/外链、prompt injection、敏感信息外发、错误 MIME、重复/冲突来源、来源许可不明。

## 6. Verification

```bash
docker run --rm -v "$PWD":/work -w /work python:3.11-slim \
  sh -lc 'python -m pip install --disable-pip-version-check --no-cache-dir -q -e ".[dev]" && \
  python -m compileall -q src tests scripts && ruff check src tests scripts && \
  python -m pytest && python scripts/validate_all.py'

docker run --rm -v "$PWD":/work -w /work python:3.11-slim \
  sh -lc 'apt-get update -qq && apt-get install -y -qq git && \
  python -m pip install --disable-pip-version-check --no-cache-dir -q -e ".[ingestion]" && \
  git config --global --add safe.directory /work && python scripts/audit_package.py'
```

- 期望结果：全部测试与校验通过，M2 新增失败路径可重复，旧 MVP 输出链不回退。
- 实际结果：M2.1 为 `70 passed`，M2.2 为 `92 passed`，M2.3 为 `111 passed`；M2.4–M2.6 逐步扩展到 Source/Research/Evidence/Binding/Application Production 边界。最终 M2.7 在 Python 3.11 与 3.12 下均 `190 passed`，`validate_all.py` PASS，M2 Exit validator `12/12` PASS，Package Audit `20/20` PASS、286 files hashed，`git diff --check` PASS。

## 7. Review

### 第一轮：开放问题发现

- Critical：0。
- Major：6。缓存复用忽略策略/限额、Source ID 可重绑、不可变快照 check-then-replace 竞态、解析正文与哈希可能来自不同字节观察、UTF-16/CSV admission 错误、长行 locator 与标题风险扫描不完整。
- Minor：1。快照引用未重算 input key、Chunk identity、risk ID 和限额绑定。
- 详细证据：`audit/M2.1-round-1-open-issues.md`。

### 修复记录

- 元数据更新与解析缓存解耦；显式策略变化版本化 Ledger，限额变化生成新快照。
- Source ID 与 canonical user-file path 建立一对一约束。
- 新增 create-if-absent 原子文件发布，既有快照不覆盖。
- Parser 的正文、大小和 SHA-256 统一来自同一 payload。
- UTF-16 BOM 优先检测；CSV/TSV 独立识别并在 M2.2 前 fail closed。
- 同行分片加入字符范围 locator；风险扫描覆盖标题和正文。
- Workspace validation 重算快照 key、Chunk/Risk identity 与 Ledger lineage。

### 第二轮：维度评审

| 维度 | 分数（0-5） | 证据 | 未解决问题 |
|---|---:|---|---|
| 正确性 | 5 | 70 tests、Schema/引用校验、策略/限额/身份/格式/locator 对抗测试 | M2.1 范围内无已知问题 |
| 架构一致性 | 5 | provider-neutral Protocol/Registry、ADR-0009、M1 仍为唯一 Ledger writer | 无 |
| 可测试性 | 5 | 单元、CLI、集成、篡改、unsupported、create-if-absent、故障注入、MVP 回归 | 多进程压力测试留待 CI 扩展 |
| 可维护性 | 4 | parser/cache/service 分层、typed DTO、Schema 镜像与文档一致 | M2.2 扩张时评估拆分 SourceIngestionService |
| 降级与恢复 | 5 | unsupported fail closed、snapshot-before-ledger、orphan reuse、rollback | v1.0 前扩大文件系统矩阵 |

详细证据：`audit/M2.1-round-2-scorecard.md`。

### M2.2 独立审计

- Round A：0 Critical、9 Major、3 Minor；全部根修，无 waiver。
- 重点修复：完整 MVP 默认 Registry 分叉、格式资源放大、OOXML 重名/路径/symlink/宏/外部关系、解析中途源变化、`parsed/partial` 能力失真、CSV/XLSX/PPTX locator/value 语义、公式与嵌入对象风险口径、遗漏 Office/PDF 内容类。
- Round B：M2.2 Submodule Gate PASS；正确性、架构、安全/资源、能力诚实、可测试性、恢复兼容均通过，可维护性 4/5。
- 详细证据：`audit/M2.2-round-1-open-issues.md`、`audit/M2.2-round-2-scorecard.md`、`audit/M2.2-BUILD_REPORT.md`。

### M2.3 独立审计

- Round A：0 Critical、9 Major、3 Minor；全部根修，无 waiver。
- 重点修复：Research Result/Evidence 边界、TTL/provider/cache identity、自校验 cache lineage、失败 checkpoint、无限结果/metadata 资源边界、cycle ID 重绑、只读 validation、副作用恢复、占位 Brief 查询和 M2.2 Protocol 回归。
- Round B：M2.3 Submodule Gate PASS；正确性、架构、缓存 lineage、恢复、安全、能力诚实、可测试性 5/5，可维护性 4/5。
- 详细证据：`audit/M2.3-round-1-open-issues.md`、`audit/M2.3-round-2-scorecard.md`、`audit/M2.3-BUILD_REPORT.md`。

### M2.4–M2.6 独立审计

- M2.4 Evidence Engine：Round A `0 Critical / 9 Major / 3 Minor`；完成 stable claim/candidate identity、Research Result → partial Web Source、conflict/freshness/authority/use policy、Source lineage invalidation 与 semantic cycle completion；Round B PASS。
- M2.5 Binding/Gap/Rework：Round A `0 Critical / 9 Major / 3 Minor`；完成 required slide/block Evidence、qualification、content-addressed Gap Report、targeted handoff 与 optimistic P2 rework；Round B PASS。
- M2.6 Application/Capability/Security：Round A `0 Critical / 11 Major / 3 Minor`；完成单一编排、provider/disclosure 分离、D3/D4/D5、high-risk isolation、requested/current budgets、G1/G2/G5A revalidation 与 M2 Application Report；Round B PASS。
- 详细证据：对应 `audit/M2.4-*`、`audit/M2.5-*`、`audit/M2.6-*` 文件。

### M2.7 Repository-wide audit

- Round A 从直接 CLI/service 旁路、旧 runtime facts、high-risk Source/Research summary、G2、Report history、provider/disclosure、resource limits、current-version Gate 和文档状态进行跨模块审计。
- 所有 Critical/Major 均在最早责任层根修；无 waiver。
- Round B 与 deterministic `validate_m2_exit.py` 共同给出 M2-wide PASS；详细证据见 `audit/M2.7-round-1-open-issues.md`、`audit/M2.7-round-2-scorecard.md` 和 `audit/M2-BUILD_REPORT.md`。

## 8. Final outcome

- 已完成：M2.1 Ingestion Core、M2.2 Multi-format Adapters、M2.3 Research Planning/Runtime、M2.4 Evidence Engine、M2.5 Block-level Binding/Gap/Rework、M2.6 Application/Capability/Security，以及 M2.7 repository-wide audit。
- 六个 Submodule Gate 与 M2.7 repository-wide Gate 均 PASS，Critical/Major open 为 0，waiver 为 0。
- **M2 Exit Gate：PASS（2026-08-27）。** Source → Research → Evidence → Block Binding → Application 边界已经形成可追溯、可恢复、provider-neutral、显式降级且 fail-closed 的 ProductionImpl。
- 能力边界：M2 完成不代表 M3 Narrative/Planning、M4 Rendering、M5 Review/Repair 或生产级端到端 PPT 产品完成；下一里程碑是 M3。
- 相关 ADR：ADR-0005、ADR-0007、ADR-0008、ADR-0009、ADR-0010、ADR-0011、ADR-0012、ADR-0013、ADR-0014。
- 最终证据：`audit/M2.7-round-2-scorecard.md`、`audit/M2-BUILD_REPORT.md`。
