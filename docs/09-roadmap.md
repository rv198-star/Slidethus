# 09｜Roadmap

## v0.1 Foundation

目标：Skill、合同、状态、Gate、示例和 Codex 接手能力成立。

已完成：本基础包。

## v0.2 Artifact Runtime

目标：可靠项目状态与产物版本。

关键产出：

- artifact registry；
- atomic persistence；
- migrations；
- dependency invalidation；
- gate history；
- recovery tests。

## v0.3 Planning Proof

目标：以可替换 MinimalImpl 证明从本地文本到结构化策划稿及其 PPTX 预览的链路。

关键产出：

- Markdown/TXT + line locators；
- 用户来源限定 evidence；
- 规则式 narrative/page planning；
- python-pptx 策划稿预览；
- LibreOffice 可行性验证。

该版本不再称为完整 MVP，因为调试、设计和最终渲染没有形成不同产出。

## v0.4 Complete Action-Chain MVP

目标：让每个基本动作都有独立产出物和验收。

关键产出：Planning SVG、Layout Diagnostics、Debug PPTX/PNG、Design SVG、Final PPTX/PNG，以及逐阶段 Render Manifest。

## v0.5 Planning Pipeline

目标：从素材到经审计的页面策划稿。

关键产出：

- multi-format ingestion；
- evidence engine；
- narrative and outline；
- slide spec/layout generation；
- interactive checkpoints；
- wireframe review。

## v0.6 Rendering

目标：至少两种可替换渲染后端。

关键产出：

- final SVG；
- PptxGenJS hybrid；
- asset and chart pipeline；
- preview renderer；
- overflow/collision tests；
- editability report。

## v0.7 Review and Repair

目标：全 deck 可自动发现问题、定位阶段并局部修复。

关键产出：

- semantic review；
- visual review；
- repair planner；
- regression；
- golden corpus；
- quality dashboard artifacts。

## v0.8 Multi-workflow

目标：Create、Rebuild、Improve、Audit、Revise、Extract Style 稳定可用。

## v0.9 Distribution Candidate

目标：Plugin 包、文档、示例、许可证、供应链和兼容矩阵完成。

## v1.0

发布条件：

- 核心 workflows 通过 golden corpus；
- 多宿主验证；
- 至少两个 render backend；
- Critical/Major 发布阻断问题为零；
- 文档与自动审计一致；
- 来源和资产权利策略完成；
- 可恢复执行和局部返工通过故障注入。

## 里程碑依赖

```mermaid
flowchart LR
    F[v0.1 Foundation] --> A[v0.2 Artifact Runtime]
    A --> M0[v0.3 Planning Proof]
    M0 --> M1[v0.4 Complete MVP]
    M1 --> P[v0.5 Planning]
    P --> R[v0.6 Rendering]
    R --> Q[v0.7 Review/Repair]
    Q --> W[v0.8 Workflows]
    W --> RC[v0.9 RC]
    RC --> V[v1.0]
```

不得为了演示视觉效果跳过 Artifact Runtime 和 Planning Pipeline。
