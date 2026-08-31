# 小米 YU7｜新版 Skills 实际案例

Status: candidate produced; Office acceptance pending

2026-08-31 用户认可本版本并同意软件按 v0.8.1 发布；这不是对 PowerPoint 打开无修复提示等未执行检查的补记。软件发布另见 `plans/v0.8.1-release.md`。

## 1. Objective

- 产出：面向消费者的中文 16:9 产品介绍 PPT，目标 12 页，附 PDF 便于阅读。
- 路径：新版 using-slidethus → Host Create；Taste 原生 HTML 样板 → Seed → Specs → Layout → Packet → 同一 IR 导出。
- 不做：本案例不修改框架代码，不发布版本，不用行业特例替代正式规划。
- 验收：来源可追踪、实际图片嵌入、字体正常、数字/版本准确；全篇在 PowerPoint 渲染检查。

## 2. Current state

- 当前仓库含上一轮新版 Skills/Seed 能力的未提交变更，全部保留。
- 独立工作区：dist/xiaomi-yu7-20260831。
- 可用：官方资料研究、官方产品图片、Host Create、Artifact Tool；本机PowerPoint UI未稳定定位本案例文件，真实Office验收尚未完成。

## 3. Decisions and assumptions

- A-001：用户未设逐阶段确认；使用 auto，完成整套产品介绍。
- D-001：资料截至 2026-08-31；覆盖 YU7 家族（含 2026 标准版、GT），价格不包含选装和临时权益。
- D-002：采用统一宝石绿/银灰/浅暖色体系，图像和构图承担变化；Taste-generated 只说明路径。
- D-003：官方产品图用于本次介绍并署名来源；不声明图片获得开放商用许可。

## 4. Work breakdown

1. 核实官方规格、价格、图片出处，完成 Brief/两轮研究。
2. Host Narrative/Outline，12 页独立职责。
3. Taste 原生样板与全篇视觉计划，冻结 Seed。
4. 语义和版式正式入库，图片 manifest，P6 全篇样式。
5. 导出 PPTX，在 PowerPoint 检查全篇并导出 PDF；记录问题和修复。

## 5. Quality and risk controls

- GT/Max/长续航/标准版数据不混用；选装注明。
- CLTC 不等于真实通勤/高速续航；充电数据附测试条件。
- 辅助驾驶不等于自动驾驶。
- 视觉反馈仅修本案例工件；框架问题留明确记录。

## 6. Verification

- 工作区 validate --check-hashes、artifact validate、G0–G6。
- PPTX 嵌图/字体/页数检查、实际 PowerPoint 导出并逐页审阅。

## 7. Review

已逐页检查12张程序渲染预览，无可见缺图、文字溢出或图表缺失。正式工件、来源与原型路径齐全；具体见 `dist/xiaomi-yu7-20260831/review/candidate-review.md`。流程中发现的章节结论问题已修正，状态返工异常作为案例观察记录，未修改框架。

## 8. Final outcome

已生成12页中文PPTX，包含9个嵌入图片部件、2个原生图表和1张原生表格；另附程序预览PDF（不是Office导出）。

交付路径：`dist/xiaomi-yu7-20260831/delivery/小米YU7_产品介绍_20260831.pptx`。

未完成项：等哈希文件在PowerPoint实际打开、无修复提示及逐页字体/媒体检查。UI多次回到另一个四页候选稿，故停止操作其他文稿，不将该窗口算作本案例验收。原始receipt仍为candidate/release false。未发布、未提交或推送代码。
