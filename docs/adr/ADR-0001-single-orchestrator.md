# ADR-0001｜Single Primary Orchestrator

- Status: Accepted
- Date: 2026-08-26

## Context

PPT 流程可以被描述成需求、研究、策划、设计和审计等角色，但这些阶段共享强依赖事实和状态。把每个角色实现为长期独立 Agent 会增加自然语言交接、上下文复制、冲突和成本。

## Decision

使用一个主 Skill 统一管理状态、artifact、Gate 和用户交互。子代理只用于独立、可并行、读密集任务，并向主线程返回结构化摘要。

## Consequences

- 更清晰的责任和状态；
- 更少的上下文损耗；
- 主线程可能较重，因此依赖 artifacts 和 progressive disclosure；
- 并行写能力受限，但可减少冲突。
