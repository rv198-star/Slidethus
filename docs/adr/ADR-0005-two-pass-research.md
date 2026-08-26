# ADR-0005｜Two-pass Research in One Evidence Domain

- Status: Accepted
- Date: 2026-08-26

## Context

来源方法同时要求在提问前了解主题背景，并在大纲形成后围绕每页检索材料。单次前置研究无法知道逐页证据负担；只在大纲后研究又会让需求问题和叙事建立在未知或过时的背景上。

## Decision

P2 Evidence 使用两次执行、一个事实源：

1. P0/P1 附近执行有界的方向性扫描，建立最小上下文与证据基线；
2. P4 后执行逐页定向证据补全；
3. 定向研究若改变关键证据，使用 `OUTLINE_READY → EVIDENCE_READY` 返工边，并重新验证 Narrative 与 Outline；
4. 所有结果写入同一个 Evidence Ledger，以稳定 evidence IDs 维持可追溯性。

## Consequences

- 保留来源工作流的两个研究时点；
- 减少无目标的大规模搜索；
- P5A 前增加一次明确的证据完成检查；
- M2 需要查询任务、缓存、失效和来源去重机制。
