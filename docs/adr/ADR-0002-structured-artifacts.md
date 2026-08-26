# ADR-0002｜Structured Intermediate Artifacts

- Status: Accepted
- Date: 2026-08-26

## Context

长对话和 Prompt-only 流程无法可靠支持恢复、审计、局部修改和多后端渲染。

## Decision

所有阶段输出写入 JSON Schema 约束的 artifacts。自然语言说明仅作为投影或补充，不是唯一事实源。

## Consequences

- 支持版本、引用、Gate 和回归；
- 增加 Schema 设计与迁移成本；
- 模型输出必须被解析和修复，而不能直接信任。
