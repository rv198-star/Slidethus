# 06｜Rendering Strategy

## 1. 逻辑画布

默认使用 `1280 × 720` 逻辑坐标：

- 与原素材公开的 SVG 画布一致；
- 便于整数坐标、几何检测和网页预览；
- 后端可转换为 13.333 × 7.5 英寸、1920 × 1080 像素等目标尺寸。

逻辑画布是内部合同，不要求所有最终文件以像素为单位。

## 2. 后端类型

### 2.1 Wireframe SVG

当前基础包已实现。用途：

- 验证 `slide_specs` 与 `layout_plans`；
- 提前发现内容过载、块遗漏和结构单调；
- 用户在最终视觉前确认策划稿；
- 作为 deterministic fixture。

它不是最终设计稿。

### 2.2 Final SVG

优势：视觉自由、矢量、生成一致。缺点：内部编辑性有限、字体和 Office 兼容需验证。

### 2.3 PPTX Native

文本框、形状、表格和图表尽量原生。优势是编辑性；缺点是复杂视觉和兼容性成本高。

v0.4 提供两种职责不同的后端：`DebugPptxRenderBackend` 验证布局编译和稳定 ID 映射；`MinimalDesignPptxRenderBackend` 应用视觉 tokens 与布局家族并生成 E3 最终稿。两者都重新打开文件验证页数与必要内容。图片、图表、复杂 SVG、母版和数据绑定仍未实现。

### 2.4 Hybrid PPTX

推荐 MVP：

- 文本、简单形状、页码和基础图表原生；
- 复杂图形、插画和背景作为 SVG/图片；
- 通过 manifest 声明每个元素的编辑等级。

### 2.5 Preview Renderer

将 PPTX/PDF 渲染为 PNG 供视觉审计。至少使用一种与生成器独立的渲染路径，避免“生成成功”被误认为“显示正确”。

当前 `LibreOfficeDocumentRenderer` 使用隔离 profile 和 Poppler；调试稿与最终稿分别渲染。需要中文时只把本机可发现字体临时复制到 profile，预览完成即删除，不把字体打包进 PPTX 或交付。

## 3. Renderer contract

输入：

- project brief ref；
- deck outline ref；
- slide specs ref；
- layout plans ref；
- visual system ref；
- asset manifest ref；
- target format；
- target editability level；
- locale/font policy。

输出：

- output files；
- previews；
- render manifest；
- warnings/errors；
- font substitutions；
- unsupported feature list；
- actual measured editability level。

目标与实测不得使用同一字段：渲染前只能声明目标，渲染成功并检查输出后才能声明实际等级。待渲染 manifest 的实际等级使用 `not_measured`。

## 4. Layout families

| Family | 适合内容 | 不适合 |
|---|---|---|
| hero | 单一强观点、封面、章节 | 多证据并列 |
| split | 对比、前后、两类信息 | 三项以上并列 |
| process | 步骤、机制、流程 | 无顺序信息 |
| timeline | 时间演进 | 非时间因果 |
| matrix | 二维分类与优先级 | 长文本 |
| architecture | 层次、组件、关系 | 纯观点 |
| chart-story | 数据结论 | 无可靠数据 |
| case | 背景—行动—结果 | 多主题混合 |
| full-bleed | 情绪、品牌、人物 | 信息密集 |
| bento | 模块摘要、仪表盘、并列重点 | 线性故事、单一主命题 |

布局选择由 slide purpose 和 content relationships 驱动，不由随机模板编号驱动。

## 5. 几何与可读性

建议默认：

- safe area：左右 56、上 48、下 44 逻辑像素；
- content gap：至少 20；
- 正文最小字号：目标显示环境下等效 18 pt；
- 图表轴和注释不得低于正文可读下限；
- 标题不超过两行；
- 单页主视觉焦点 1 个；
- reading order 明确；
- 重要信息不放在投影裁切风险区。

规则应由 quality profile 和场景配置，而不是写死在 renderer。

## 6. 文本溢出策略

优先顺序：

1. 精简重复或非关键内容；
2. 拆页；
3. 改变内容组织；
4. 调整区域比例；
5. 在可读范围内缩小字号。

禁止直接全局缩小字体作为默认修复。

## 7. 字体策略

- Visual System 记录首选、跨平台替代和 fallback；
- render manifest 记录实际使用字体；
- 导出前探测字体存在性；
- 中英文分别配置；
- 使用字体文件必须有许可；
- 不把容器内字体文件打包给用户。

## 8. 图表策略

图表从“要证明什么”开始：

- 比较 → bar/dot；
- 趋势 → line/area；
- 构成 → stacked bar，谨慎使用 pie；
- 相关 → scatter；
- 分布 → histogram/box；
- 流量 → funnel/sankey；
- 关系 → network/architecture。

图表必须绑定数据来源、单位、时间口径和转换逻辑。

## 9. 资产策略

每个图片/图标/插画必须：

- 有 asset ID；
- 记录来源或生成提示；
- 记录许可/可用范围；
- 记录裁切和变换；
- 记录色彩/风格标签；
- 具备缺失 fallback。

## 10. 回归

每次渲染至少检查：

- slide count；
- output file validity；
- preview page count；
- missing assets；
- font substitutions；
- overflow/collision；
- image resolution；
- cross-page token consistency；
- changed slides vs intended impact set。
