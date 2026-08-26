# ADR-0003｜Multiple Render Backends

- Status: Accepted
- Date: 2026-08-26

## Context

整页 SVG 的视觉自由度高，但原生编辑有限；原生 PPTX 可编辑，但复杂视觉成本高。单一后端无法满足所有场景。

## Decision

保持 semantic artifacts 与 renderer 解耦，支持 Wireframe SVG、Final SVG、PPTX Native 和 Hybrid。MVP 推荐 Hybrid，并在 Render/Delivery Manifest 中分别记录目标编辑等级与真实输出的实测编辑等级。未生成输出时实际等级为 `not_measured`。

## Consequences

- 渲染选择更灵活；
- 需要统一 render contract 和预览回归；
- 后端能力差异必须被显式记录；
- 成功渲染与正式交付必须测量实际编辑等级，不能把目标值冒充结果。
