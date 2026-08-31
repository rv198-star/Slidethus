# 宿主设计入口收敛（仅本轮第 1、2 项）

Status: complete for scoped items 1–2; engineering verified; DO NOT RELEASE

## Objective / boundary

宿主 Agent 负责研究、叙事、页面关系、Taste 原生视觉探索与设计判断；代码负责准入、版本、执行与可计算检查。固定规划不是已执行的模型设计。样板与全篇必须使用同一组正式工件和同一个生成函数。

本轮不新增行业案例、不重做用户认可的酒店文件、不打包完整复现档案、不发布。第 3 项完整生成包固化、第 4 项新案例/样板/全篇 PowerPoint 视觉验收由用户后续推进。自动化工程测试不代替这些验收。

## Changes

1. 增加宿主文件提案桥，复用 PlanningProvider / ArtDirectionProvider。缺失输入输出具体待办并停止；不调用固定 provider 补全设计。提案绑定当前上下文，经过现有阶段服务准入。
2. Layout 接收宿主明确坐标；Visual System 接收逐页明确外观。语义仍归 Slide Specs，坐标仍归 Layout，外观归 Visual System。已明确设计的页面不再套固定 hero/卡片装饰。
3. 增加一个 Create 宿主入口，串联既有 M3、P6、IR 与 Artifact Tool 薄适配器。样板仅选择同一 IR 的 slide IDs；不得以样板标记整篇通过。旧 deterministic CLI 仅在显式 baseline 模式可用。
4. 缺资产、失效提案、越界布局、不支持的表示或宿主依赖缺失均明确失败。生成候选记录绑定实际文件与 IR，不伪造 G7/M5/Office 通过。

## Dependencies

不新增 Python 生产依赖。Artifact Tool 是宿主提供的可选渲染能力，通过明确的 Node/模块目录接入；不硬编码个人缓存路径，不安装、不重新分发私有包，不静默切换后端。适配器源码随 Skill 分发。

## Acceptance

- 宿主非默认提案实际影响正式工件及 PPTX；缺失/陈旧输入不能假成功。
- 工程夹具证明同一 IR 的样板和全篇使用同一生成函数，图片真正内嵌、图表保留数据；不要求所有页有图片/图表。
- pytest、validate_all、audit_package、compileall、ruff；审阅 diff。
- 本轮完成只代表入口和职责落地，不代表新案例美学或 PowerPoint 验收完成。

## Progress

- 已确认退化链路：默认固定规划缺少真实设计，Layout 丢弃提案几何；仅更换导出库不足以解决。
- 已增加 `slidethus create` 与五阶段宿主提案桥。缺失、陈旧、格式错误和非有限数输入明确失败；实际提案继续经过既有 M3/P6 准入，不以提交记录代替通过记录。
- Layout 保留宿主明确坐标，Visual System 保留完整逐页外观，IR 不再给已明确设计的页面添加默认布局家族装饰。仅渲染现有设计时复用当前已准入输入，避免空需求触发重新策划。
- Artifact Tool 适配器消费同一正式 IR；样板仅按 Slide IDs 选择。生成候选 PPTX、逐页预览和文件回执；不改写 OOXML、不依赖 LibreOffice，不自动设置 G7/M5/发布通过。
- 工程夹具已实际走过五阶段暂停/提交/恢复，并导出全篇与样板：对应页 PNG 字节一致，图片内嵌，原生图表 XML 中保留 A/B 分类和 2/5 数值。这是合成夹具，不是 Taste 视觉样板或真实行业案例。
- Skill、CLI 帮助、README、分发内容和 ADR-0029 已同步。Taste 上游资源原文未改。

## Verification

- 全量 `python -m pytest`：339 passed，43 skipped（可选能力/环境条件；没有把跳过计为通过）。之后针对本轮新增非法输入检查及最终细节单独复跑专项。
- 最终专项 `test_host_design.py`、`test_skill_layout.py`、`test_distribution.py`、`test_schema_examples.py`：24 passed；显式提供宿主 Artifact Tool 运行时，真实 PPTX 样板/全篇、资源内嵌、图表数据、当前输入绑定及分发检查均实际执行。
- `python scripts/validate_all.py`：PASS；既有 16 类语义工件示例、工作区、G0–G6、G7 负控及 wireframe 检查通过。
- `python scripts/audit_package.py`：21/21 PASS；最终源码清单在收口时刷新。
- `compileall`、`ruff check`、`git diff --check`：PASS。
- 独立 Skill quick validator 因本地缺少 PyYAML 未运行成功；未为此安装依赖。仓库 Skill 结构测试与分发测试通过，保留这一验证限制。
- 已检查职责归属、显式失败、语义/外观一致性和旧基线回归风险。保留既有用户未提交改动；没有提交、推送或发布。
- 认可酒店文件 SHA-256 仍为 `2967e80fa9df341750e5c34b2b2daaadca2f29359286ef5a35751af8d507ece1`，未覆盖或重做。

## Remaining boundary (not part of this round)

- 第 3 项完整复现生成包、第 4 项用户新场景/案例及真实 PowerPoint 全页验收，继续延期。不以工程夹具扩大本轮验收范围。
- 适配器支持原生基础文本/表格/数值图表与内嵌 PNG/JPEG。可编辑复杂图解、SVG/vector、复杂图表和富文本尚未声称支持；遇到不支持的表示须明确失败并返回规划，而非偷偷降级。
- Artifact Tool 来自宿主可选能力，版本与适配器哈希进入回执；原生库预览、XML 合法性和数值检查不证明 PowerPoint 无修复提示，也不证明美学合格。
- 当前候选仍是 `candidate_office_review_pending`。只有后续真实文件验收能确认这条链路在新案例上达到用户标准；本轮不解除 `DO NOT RELEASE`。
