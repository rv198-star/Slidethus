# ADR-0004｜Open-Issue Review Before Scorecard

- Status: Accepted
- Date: 2026-08-26

## Context

先给维度分数会产生锚定，reviewer 容易为已有高分寻找解释，重大具体问题也可能被平均分掩盖。

## Decision

每个重要 Gate 先执行不设维度的开放问题审计，修复 Critical/Major 后再执行维度评分。严重度规则优先于分数。

## Consequences

- 问题更具体、可修复；
- 审计轮次增加；
- 评分更可信；
- Quality Report 需要支持不同 review mode。
