# ADR-0007｜Minimal Vertical Implementations Before Full Milestones

- Status: Accepted
- Date: 2026-08-26

## Context

M1 已经建立可靠的 Artifact Runtime，但 M2–M5 尚未实现。继续按水平层只扩展接口会让项目长时间无法证明真实用户价值；直接把未完成能力伪装成完整实现又会破坏 Gate 和来源诚信。

## Decision

在稳定的 provider/phase 边界后提供一组可替换的 MinimalImpl，先形成真实纵向链路：本地文本摄取、用户来源限定的证据、规则式叙事与页面规划、原生 PPTX 渲染、独立预览和确定性审计。

- MinimalImpl 必须消费和产生正式 Schema artifacts，不得绕过 Artifact Runtime。
- MinimalImpl 只能使用用户来源中的内容，不生成未经支持的外部事实。
- 每项能力和交付限制必须记录在 Project State、Render Manifest、Quality Report 和 Delivery Manifest。
- 正式 Gate 标准不因 MVP 降低；独立预览缺失时允许产出 PPTX，但 G8/G9 保持阻断。
- 后续 ProductionImpl 通过同一 Protocol 替换，不改变语义 artifacts。
- MVP0 是跨里程碑的验证切片，不代表 M2、M3、M4 或 M5 Exit Gate 完成。

首个渲染适配器采用 `python-pptx`，因为它能以小型 Python 依赖生成真实、原生可编辑的 PPTX。PptxGenJS、Final SVG 和 Hybrid 后端仍保留为后续实现。

ADR-0008 补充本决策的完成标准：MVP0 证明了策划与文件写入，但不能把策划稿的格式转换算作独立的调试、设计和最终渲染阶段。完整 MVP 必须逐阶段产生不同输出并通过各自验收。

## Consequences

- 项目可以较早证明从输入到真实文件的工程闭环。
- 规则式内容和基础视觉质量有限，但限制可审计、可替换。
- 增加一个生产依赖与 Office/LibreOffice 可选运行时。
- CI 可以验证 PPTX 结构；正式视觉 Gate 仍依赖独立预览器。
- Roadmap 必须分别记录“纵向链路可运行”和“完整里程碑完成”。
