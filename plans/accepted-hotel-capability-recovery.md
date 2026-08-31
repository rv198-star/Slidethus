# 认可版产出恢复与复现

Date: 2026-08-31
Status: recovery in progress; optimization paused

## Objective and boundary

按用户要求，重现酒店香薰低奢统一版的既有产出，不做优化、不替换默认实现、不扩展行业、不发布版本。
仓库 HEAD 为 e34b62a，已有未提交文档变更保持原样。
本轮使用历史原脚本和原素材独立重建，不复制成品冒充重建，不以默认 CLI 替代历史实际路径。

## Source and decisions

- 历史脚本：`/private/tmp/slidethus-hotel-scent-full/build/build_full.mjs`。
- 历史素材：同工作区 `workspace/assets/` 的8张PNG。
- 对照成品：`dist/2026中国酒店业香薰市场现状与供应链进入建议_低奢统一版.pptx`。
- 原件 SHA-256：2967e80fa9df341750e5c34b2b2daaadca2f29359286ef5a35751af8d507ece1。
- 复现工作区：`build/accepted-hotel-replay-20260831.lkTlKr/`。
- 保留原脚本逐字副本；执行副本仅调整路径，所有内容、布局、图片、图表、字体及生成逻辑不变。
- 复用冻结研究，不重查或更新市场事实；不把历史脚本运行声称为新的正式G0–G9工作流通过。

## Execution and acceptance

1. 保全原脚本与素材，记录差异仅为输入输出路径。
2. 从源重新生成16页PPTX；核对原文、图表数据、媒体与逐页渲染。
3. 原始新文件在Microsoft PowerPoint直接打开，不经修复；实际逐页检查。
4. 将可重跑脚本、素材、运行说明及校验结果保留在非临时目录；交付独立重建副本。

## Risk and status

不修改生产Python/Node、Schema、Gate、Skill及包版本。图片使用历史资产，不新生成。
如历史脚本和认可成品不一致，先定位差异，不静默优化成新版本。
原件不覆盖。若PowerPoint检查失败，记录失败，不宣称恢复完成。
这次验证只证明历史认可产出可重新生成，不证明默认CLI或任意新主题已达到同等品质。

## Reproduction evidence

已从历史脚本独立重建16页，不是复制原PPTX；历史原件未覆盖。

- 新成品：`dist/2026中国酒店业香薰市场_认可版原路径重建_20260831.pptx`。
- 新成品SHA-256：`92f79b510d854c703efde7e84e633fec5488165817d83537918e5fb492b66ce0`。
- 8张原素材已保留，11处图片实例；第4、5、14页共3个原生图表。
- 全包比较无新增/丢失部件、无未解释差异。仅排除生成的creation ID、解析到实际目标后的关系ID和文档创建/修改时间；文字、几何、样式、媒体、图表及备注一致。
- 已逐页查看16张新Artifact渲染；不声称与旧PNG像素一致，不作为Office验收替代。
- 可重跑脚本、资产、说明及只读核对程序：`dist/recovery/accepted-hotel-20260831/`；不再依赖历史`/tmp`资产。
- 运行环境：Node v24.19.0、Codex bundled `@oai/artifact-tool` 2.8.52、原字体PingFang SC。不新增生产依赖，不声称离开该私有运行环境仍可开箱执行。

当前：**历史认可产出重新生成及结构对照通过，PowerPoint验收未完成。**
桌面控制工具出现`native pipe closed`和`noWindowsAvailable`，未取得实际打开证据；已向用户交付副本请其确认是否仍有修复提示。
不以工具故障推断PPTX损坏，也不以结构对照推断Office必定正常；在实际确认前不宣布能力恢复完成。

## Checks

- `.venv/bin/python -m pytest`：335 passed，42 skipped，623.23秒；不将跳过项计作通过。
- `.venv/bin/python scripts/validate_all.py`：PASS，16 schemas、示例workspace、G0–G6、G7 negative control及3 wireframes。
- `.venv/bin/python scripts/audit_package.py`：PASS，21/21 checks。
- 复现包ZIP完整性检查通过；`dist/2026酒店香薰_认可版原路径复现包_20260831.zip`保留源码、资产、运行说明及校验记录，不包含私有运行库。
- 本轮无生产代码改动。上述工程检查不是PPTX实际打开验收，也不是重新发布的批准。
