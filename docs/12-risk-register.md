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
