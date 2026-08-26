# Source Material

本目录保留用户提供的《应该是目前最强的 PPT Agent》素材及其拆解，目的是让后续开发者能区分：

1. **来源明确公开的内容**：工作流、原始提示词、例图链接和原作者表述；
2. **Slidethus 的设计推导**：我们基于来源进行的架构扩展；
3. **尚未被来源覆盖的工程能力**：Schema、证据链、渲染后端、状态机、质量 Gate 等。

## 目录

- `raw/README.md`：说明为何发布包不携带浏览器原始 HTML；
- `source-preserved/`：原始提示词，禁止静默改写；
- `cleaned-main-post.md`：清洗后的主帖；
- `source-workflow.md`：来源工作流摘要；
- `visual-*`：例图索引、画廊和视觉解读；
- `derived-analysis/`：Slidethus 对来源的独立分析，不属于原作者原文；
- `manifest.json`：来源文件 SHA-256。

第三方素材的版权和许可不因被打包而改变。未来仓库采用何种开源许可证，需要把本目录与项目代码分别处理。
