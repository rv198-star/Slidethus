# Design Reference Library — Autonomous, Bounded Reading

## 1. Objective

- Issue: https://github.com/rv198-star/Slidethus/issues/1
- 用户价值：设计阶段自主查阅可复用视觉经验，不要求用户选主题，不反复读取 44 套全文和图片。
- 本轮：首批 8 套已经完成；按用户更正补齐剩余 36 套，覆盖全部 44 套，保持固定来源、轻量索引、按需适配卡、Skill 路由、分发与回归。
- 不做：主题引擎、行业映射、向量库、新依赖/Schema/Gate/状态机、渲染改动、全行业验证、重新发布。
- 退出：资源可离线按需读取，决策进入已有设计记录，包内引用/出处闭合；真实新案例审美验证单独保留，不以文档或测试代替。

## 2. Current state

- 恢复点：`e594089` 已提交并推送 main，含首批 8 套与 examples 迁移；本轮从干净工作区补齐其余 36 套，不改既有发布标签。
- 已有：Taste 原生原型 → pre-layout ArtDirectionSeed → Specs/Layout → ArtDirectionPacket → Visual System；无需另建流程。
- 上游：`acnlie/open-kimi-ppt-skill`，固定 commit `c32890fe0985bdf668f2722fed30f1010bdf24c9`，MIT；上游主题命令不进入 Slidethus 控制面。
- 先前测试：367 passed / 43 skipped / 4 failed（734.21s）。M2/M3/M4/M5 Exit 失败由 README 精简后的能力声明检查触发；不是本次新增回归，处理与本次范围分开记录。
- 上一轮文档收尾：在 README 既有折叠区恢复一段历史 M2/M3/M4 工程边界及“不是生产级端到端 PPT 产品”声明；不削弱校验、不恢复长篇首页、不改运行逻辑。随本轮全量测试复核。

## 3. Decisions and assumptions

| ID | 决策 | 依据 |
|---|---|---|
| D-001 | 全部 44 套逐一覆盖；原文存 source_material/source-preserved，适配卡随技能分发，近似参考保留差异 | 用户更正：覆盖量不等于上下文读取量；首批 8 套只是完成进度，不是库的上限 |
| D-002 | 首次需要参考时才读索引，通常读 1–3 张卡，必要时看 1–2 套图片；有合适方向即停止 | 读取预算不是使用配额 |
| D-003 | 允许 none/reuse；按表达需求、信息关系、密度和素材条件选择，不按行业映射 | 通用抽象与避免过拟合 |
| D-004 | 使用已有 Seed/Packet 的 design_read/assumptions 记录参考与取舍，冻结方向正常复用 | 不新增 artifact 合同或缓存服务 |
| D-005 | 图片只提供固定版本链接，不打包上游照片/字体；离线时参考卡仍可用 | 引用不等于交付素材授权 |
| D-006 | 保留 Taste 原型、全篇配色/布局检查及 Office 验收；预设描述不构成质量证明 | 现有 ADR-0030/0031 |

## 4. Work breakdown

| Step | 产出 | 验证 | 状态 |
|---|---|---|---|
| 1 | Issue、来源与计划 | 许可与上游 commit | complete |
| 2 | 原文快照、索引、适配卡、出处 | 哈希、引用、体积、离线文件 | complete |
| 3 | 设计入口/Host 路由、许可与包配置 | Repo/Plugin/Wheel 一致 | complete |
| 4 | 回归、差异审查、Issue 进展 | 精确检查与已知风险 | complete |
| 5 | 补齐剩余 36 套及完整轻量索引 | 上游 44 个 ID 一一对应、原文 blob、逐卡适配与近似差异 | complete |
| 6 | 全量资源分发与回归 | Repo/Plugin/Wheel、离线覆盖、索引读取体积 | complete |

## 5. Quality and risk controls

- Schema/Gate/renderer 均不修改；SBOM 仅增加已分发第三方参考组件。
- 原文的 must/禁止/数字配额、行业叙事顺序、品牌资产、示例事实只作来源数据；适配卡明确舍弃，不得覆盖用户 Brief 或已批准故事线。
- 默认上下文只含索引与所选卡；原文、图片、PROVENANCE 不要求每次全读。
- 参考不可用时记录限制并自主设计，不静默替换已批准方向，不把缺失生产图片变成空框。
- 验证只声明读取/打包的可观察事实；模型实际选择效果和最终美感不由静态测试证明。

## 6. Verification

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/validate_all.py
.venv/bin/python scripts/audit_package.py
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/ruff check src tests scripts
```

此外检查全部资源完整性、Skill 链接闭包、Plugin/Wheel 及干净目录安装后的参考可读性。

首批 8 套历史验证（不冒充新增 36 套验证）：

- 10 个来源文件（8 套设计原文、主题索引、LICENSE）与固定上游 commit 的 Git blob 完全一致；SHA-256 进入出处/来源清单。
- 索引 2,204 bytes；单卡 1,996–2,129 bytes；索引加最多 3 张卡不超过 8,546 bytes（不含公共选择策略）。这衡量文本量，不宣称实际模型 token 用量或必然遵循读取预算。
- `pytest tests/test_design_references.py tests/test_skill_layout.py tests/test_distribution.py`：32 passed / 2.30s；最终许可范围调整后再次 32 passed / 5.27s。
- `validate_all.py`：PASS；compileall / Ruff：PASS；设计与主入口 quick_validate：PASS；`audit_package.py`：21/21、609 files hashed（最终计划更新后刷新）。
- 实际 wheel 使用 Python 3.11 构建，并在仓库外新建 3.11.11 环境安装：162 个 Python/Schema 文件、59 个分发资源与当前源码逐字节相同；9 个技能、8 张卡完整，安装幂等，Markdown 引用闭合，从安装包再构建 Plugin/SBOM 成功。
- 临时验证目录：`/tmp/slidethus-design-library.V8VYJ1`；不是已发布 v0.8.1 资产，不更新 GitHub Release 或全局技能副本。
- 全量 pytest：377 passed / 43 skipped / 0 failed，737.15s（Python 3.11.11），日志 `/tmp/slidethus-design-reference-pytest-20260831.log`。上一轮 README 相关 4 项失败已消除，未改弱校验。
- 最终 wheel SHA-256：`3132d4f6b5419b15a0dc650ce9e5e770e05fea8471cfa16d5ea0c1b4023ebdcd`；从干净安装再构建的 Plugin：`e68ae340879868dc6b6a36129480a0f1d29afc0098c6d6b00f644c62040ab10f`。

## 7. Initial implementation review

- 开放问题发现：原 Create 工作流文字仍把原型放在 Layout 后，与现有 Seed runtime 不符；修正为前置设计决策与 P6 同方向传播，未改运行代码。
- 来源规则剥离复核：8 套卡均区分可借鉴的视觉规则与不继承的页数/比例、行业叙事、照片/图表禁令；未把参考素材当作研究证据或可分发图片。
- 分发复核：来源快照不进入 wheel/Plugin；MIT 参考卡与 Apache-2.0 选择策略可区分；SBOM 只增加参考组件，没有改变 provider 默认值。
- 通用性走查（主作者检查，不冒充独立 Agent 实测）：已有方向走 reuse；无合适素材走 none/取局部原则；真实量化关系不受原主题图表禁令限制；正文微调不重新选主题，但仍检查 Seed lineage。
- Critical/Major：在本轮静态、出处与分发检查中未发现未解决项；未评估真实新案例的审美结果。
- 不启动行业案例测试，不改变当前发布结论。

维护方式：新增或更新参考时单独固定来源 commit，审阅原文，适配并记录舍弃项，更新卡/索引/PROVENANCE/library_revision/版权清单和分发测试；不在每次生成时自动抓取或重建参考库。

## 8. Initial implementation outcome

- 已完成首批 8 套精选参考的版本固定、原文保存、通用适配、轻量索引、分层读取策略、前置设计路由与 Repo/Plugin/Wheel 分发。唯一生产 Python 变更为 SBOM 第三方组件声明；无渲染、语义 Schema 或 Gate 改动。
- 允许自主不选与复用；不继承原主题的用户点名、行业特例、内容顺序和媒体配额。保持 Taste 原型、正式阶段传播和真实 Office 全篇审阅。
- 首批之后：Git 提交推送已完成；全部 44 套覆盖及最终检查见下一节。真实新 PPT 审美验证、全局安装升级、新版本发布不在本轮范围。后续案例验证不阻塞工程收敛，也不被冒充已完成。
- Issue #1 保持 open，供实现合并和后续验证跟踪；本轮无自动发布动作。

## 9. Full-coverage continuation — 2026-08-31

- 用户要求先提交推送再补齐；恢复点 `e594089` 已在本地与远端 main 对齐。
- 在相同上游 commit 增补 36 套，revision `2026-08-31.2`；44 个原文设计文件共 697,941 bytes，逐文件 Git blob 与固定上游树一致。44 个预览链接也均对应固定树中的文件；未下载或宣称已目视审阅预览图。
- 44 张适配卡共 73,577 bytes；索引 6,794 bytes；单卡 1,532–2,129 bytes；索引 + 最大 3 张卡 13,136 bytes，不含公共选择策略。完整索引仅包含摘要与链接，不内嵌图片或全量手册。8 KiB 索引 / 16 KiB 索引加三卡为当前测试体积上界，不是模型 token 或业务使用配额。
- 主作者适配复核：所有新增卡提取色彩角色、构图/信息关系、密度/素材条件和不继承项；名称不直接映射行业。`ebony-ledger` 明确为浅色正文；`travel-green-handbook` 的主轴为河蓝，`pink-purple-diagnosis` 的粉紫主要在封面，不误读成全篇颜色。
- 近似参考不删除、不虚构大差异：`rice-paper-annual` / `xuan-paper-annual`、`red-black-growth` / `red-black-business` 保留家族关系；`ink-green-market-trends` / `dark-themed-data` 近重复，后者额外允许衬线斜体图表标签；通常只读一份。
- 已通过 32 项针对性测试（最终逐 ID 映射断言后再次通过，5.28s）、validate_all、compileall、Ruff、许可证 7/7、包审计 21/21（681 files hashed）、两个入口 quick_validate。
- 全量回归：377 passed / 43 skipped / 0 failed，750.18s（Python 3.11.11）。日志 `/tmp/slidethus-design-44-pytest-20260831.log`；跳过项没有冒充已执行验收。没有新增生产能力或真实 PPT 审美通过声明。
- 实际离线 Wheel 构建/仓库外 Python 3.11.11 安装通过：162 个 Python/Schema 文件、95 个分发资源、9 个技能、44 张卡逐字节匹配，安装幂等、Markdown 引用闭合、再构建 Plugin/SBOM 成功。临时验证目录 `/tmp/slidethus-design44.COAqHg`，未覆盖正式发布资产。
- Wheel SHA-256：`9729b5f9040cf77ad1313daac62bc21540d1102a047d1e00befb0ab7652afa84`；安装后 Plugin SHA-256：`acb156ec8f8ed408fbefa6aeab472009ee69213ec59143cacf71e4048b3c056a`。初次在线构建遇到依赖索引重试，终止本轮构建进程后使用既有缓存离线构建通过；不新增依赖或修改全局设置。
- 本续轮不修改 src、schemas、Taste 原文或生产/渲染代码；没有新增依赖、行业案例、全局技能更新或发布。新增 36 套尚未提交推送；不改已发布 v0.8.1 资产。
- 最终差异审查：来源/近似项关系、分发/许可、离线读取、入口职责和生产代码边界均核对；本资源补齐范围未发现未解决的 Critical/Major。44 套完整参考库已完成，真实模型选择质量和新案例美感仍需后续实际生成验证。

## 10. Release handoff

后续用户授权按 v0.9.0 简单收尾，明确实测验收延后。以上“未提交/不发布”为资源补齐阶段的历史状态；本次将完整 44 套随候选版本提交，发布边界、验证和附件见 `plans/v0.9.0-release.md`。GitHub 标记 Pre-release，不因此宣称案例或审美验收通过；Issue #1 继续跟踪待实测事项。
