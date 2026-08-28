# 12｜Risk Register

| ID | 风险 | 概率 | 影响 | 预防 | 触发后处理 |
|---|---|---:|---:|---|---|
| R-001 | 过早追求最终视觉，合同未稳定 | 高 | 高 | M1-M3 Gate 前不扩张 renderer | 回退到 artifact/plan 修复 |
| R-002 | Bento 形成新的模板化 | 高 | 中 | layout diversity policy | 重跑 P5B/P6 |
| R-003 | 模型生成无来源事实 | 高 | 高 | Evidence binding 与 Gate | 阻断并回到 P2 |
| R-004 | 多代理并行写冲突 | 中 | 高 | 单 writer、只读子代理 | 恢复 artifact 版本并重审 |
| R-005 | SVG 漂亮但 PPT 不可编辑 | 高 | 中 | editability level 与 Hybrid | 在交付清单明示或换后端 |
| R-006 | PPTX 生成成功但实际显示错误 | 高 | 高 | 独立 preview renderer | 阻断 G8 |
| R-007 | 字体/Office 跨平台差异 | 高 | 中 | font fallback、预览矩阵 | 替换字体并回归 |
| R-008 | Source prompt injection | 中 | 高 | 输入数据隔离 | 标记风险、拒绝执行指令 |
| R-009 | 版权不清的图片/字体 | 中 | 高 | Asset Manifest | 使用占位/替换/请求授权 |
| R-010 | Schema 过度复杂导致模型难用 | 中 | 中 | progressive disclosure、示例 | 拆分 artifacts、简化字段 |
| R-011 | Schema 过于宽松失去约束 | 中 | 高 | additionalProperties=false、Gate | 收紧 Schema 与迁移 |
| R-012 | 审计模型自我偏袒 | 高 | 中 | 独立轮次、开放审计先行 | 使用独立 reviewer/人工抽检 |
| R-013 | 局部修复破坏跨页一致性 | 高 | 中 | dependency graph + regression | 全 deck 回归 |
| R-014 | 长 deck 上下文污染 | 高 | 中 | artifacts、分块、只读子代理 | 从 frozen artifacts 恢复 |
| R-015 | 供应商 API/模型变更 | 中 | 中 | provider-neutral protocols | 替换 adapter |
| R-016 | 项目被误解为“Prompt 集合” | 高 | 高 | 可运行 core、schemas、tests | 强化 deterministic runtime |
| R-017 | 原素材与新增设计混淆 | 中 | 中 | source boundary 和 notices | 修正文档/来源映射 |
| R-018 | 分数达标但仍有重大问题 | 中 | 高 | severity overrides score | Gate fail，回到具体阶段 |
| R-019 | OOXML/PDF/图片造成压缩、对象或像素资源放大 | 中 | 高 | source/ZIP/member/page/cell/pixel/risk limits，preflight | fail closed，调低范围或取得等价文本 |
| R-020 | `partial` 来源被误当完整解析或 OCR/视觉理解 | 高 | 高 | parse status、warnings、Evidence use policy | 阻断相关 claim，补适配器/OCR/人工核验 |
| R-021 | 缺少可选解析依赖却把格式标为 unreadable/parsed | 中 | 中 | SourceCapabilityError、doctor/CLI 说明 | 安装 `slidethus[ingestion]` 或显式降级 |
| R-022 | 把 Research Result 当 Evidence，或在 provider/freshness/TTL 漂移后复用错误缓存 | 高 | 高 | Result/Evidence 分层、provider/version/input-key lineage、immutable cache、generation invalidation | 阻断 Evidence 推进，失效相关 query 并从 M2.3/M2.4 重跑 |
| R-023 | Claim normalization 删除百分比、单位、小数或正负号而误合并事实 | 中 | 高 | 保守 exact normalization、语义符号对抗测试 | 停止 G2，拆分 claim keys 并重建引用 |
| R-024 | Source 更新后旧 Evidence 仍引用相同 locator 的新内容 | 高 | 高 | Source/locator/Chunk ID/content hash 绑定、downstream draft、G2 stale-lineage blocker | 重新裁决并保留旧 EVD 历史 ID 为 blocked |
| R-025 | 增量冲突只阻断新 claim，旧 claim 继续可用 | 中 | 高 | Persisted candidate bindings、explicit conflict group 全组重算 | 将全组设为 disputed/do_not_use，修复后重新裁决 |
| R-026 | 已连接 ResearchProvider 被误认为已授权外发内部 Brief/Outline | 中 | 高 | provider capability 与 external-disclosure approval 分离 | 阻断执行，记录 D5 或显式 D3 waiver |
| R-027 | 旧 inventory 或 preflight 后文件增长绕过应用级 Source budget | 中 | 高 | requested/current count/byte 双重检查、摄取后 fingerprint rebinding | 在 Evidence/Provider 前阻断并缩小输入范围 |
| R-028 | high-risk Source 指令被自动提升为 Evidence | 中 | 高 | 默认排除 high-severity Source、显式 override 记录 | 降级/阻断 G2，人工审阅后再决定 |
| R-029 | Application Report 未绑定 Project State/history，伪造最终 phase 或 Gate | 低 | 高 | content-addressed report、Project State revision/artifact hash/history validation | 标记 runtime invalid，重跑 M2 application |
| R-030 | PlanningProvider 输出直接变成页面事实或自行控制 ID/Gate | 中 | 高 | complete proposal admission、Evidence subset、deterministic identity/lineage/Gate | 拒绝 proposal，修复 adapter 或回 P2/P3 |
| R-031 | Outline 重排导致 Slide ID 重编号和反馈丢失 | 高 | 中 | stable `S-*`、ordinal 分离、excluded history、Change Report mappings | 从历史 Outline/Change Report 恢复并重跑下游 |
| R-032 | Sticky-note/Repair 以相同 idempotency key 在不同策略下误复用 | 中 | 高 | payload/reason/limits/provider 进入 request identity；key 单一归属 | 显式冲突，要求新 key 或复用原 policy |
| R-033 | 旧 Planning Review 与新 Specs/Layout 拼接后伪称通过 | 中 | 高 | ready M3 Report 要求 Review inputs 精确等于最终 artifacts | 标记 Report invalid，重跑 Planning Review |
| R-034 | 自动 Repair 语义越权或失败后隐藏部分写入 | 中 | 高 | automatic allowlist、provider/limits binding、Artifact Runtime checkpoint、result review | 停在最早安全 phase，发布 failed/rework report |
| R-035 | Layout 灰模被当成最终视觉，或通过缩字掩盖内容过载 | 高 | 中 | G5B geometry/capacity/min-font、wireframe role、M4/M5 capability wording | 回 P5A/P5B，不进入最终渲染 Gate |
