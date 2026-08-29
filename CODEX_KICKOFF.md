# Codex Kickoff Prompt

将下面整段复制给在本仓库根目录启动的 Codex：

---

你现在接手 Slidethus。它是一套 Agentic Presentation Engineering Skill，不是简单 PPT 模板生成器。

## 当前事实

- M0 Foundation Contract：PASS。
- M1 Artifact Runtime：PASS。
- MVP0 Planning Proof 与 MVP1 Complete Action Chain：PASS，但仍是跨里程碑 MinimalImpl 回归切片。
- **M2 Exit Gate: PASS（2026-08-27）**。
- **M3 Exit Gate: PASS（2026-08-27）**。
- **M4 Exit Gate: PASS（2026-08-28）**。
- **M5 Exit Gate: PASS（2026-08-29）**。
- **M6 Exit Gate: PASS（2026-08-30）**。
- **v1.0 Release Gate: PASS（2026-08-30）**。
- M2 Source/Research/Evidence、M3 Narrative/Planning、M4 Production Rendering 与 M5 Production Review/Repair boundaries 均已冻结，无 waiver。
- M5 使用 independent DVR/SVR/SCR/VVR review facts、phase-correct Repair Plan/Report、cross-deck Regression、Production Quality Report/G8、Golden baseline 与 M5 Application/CLI。
- M6 Productization and Distribution 已冻结；缺少外部 Planning/Semantic/Visual providers 时继续按 capability boundary 显式降级或阻断。

## 接手动作

1. 先读取根目录 `AGENTS.md`，并按其中顺序读取核心文档、`TASKS.md`、适用 ADR 和 `.agents/skills/slidethus/SKILL.md`。
2. 运行当前冻结基线：
   - `python -m compileall -q src tests scripts`
   - `ruff check src tests scripts`
   - `python scripts/validate_all.py`
   - `python scripts/validate_m2_exit.py`
   - `python scripts/validate_m3_exit.py`
   - `python scripts/validate_m4_exit.py`
   - `python scripts/validate_m5_exit.py`
   - `npm test --prefix renderers/pptxgenjs`
   - `python scripts/audit_package.py`
3. 阅读最终证据：
   - `audit/M2-BUILD_REPORT.md`
   - `audit/M3-BUILD_REPORT.md`
   - `audit/M4-BUILD_REPORT.md`
   - `audit/M5-round-1-open-issues.md`
   - `audit/M5-round-2-scorecard.md`
   - `audit/M5-BUILD_REPORT.md`
4. **不要重做 M2、M3、M4 或 M5**，不要绕过已经冻结的 Production 合同：
   - immutable Source Snapshot 与 stable Source/Chunk/locator/hash；
   - provider-neutral Research Plan/Run/Cache 与 Result ≠ Source ≠ Evidence；
   - deterministic Evidence identity、conflict/freshness/authority/use policy；
   - current Outline/Block Evidence Gap、G2/G5A 与正式 P2 rework；
   - minimum-question Brief completion 与 provider-neutral PlanningProposal admission；
   - stable `S-*` sticky notes、Evidence-qualified `BLK-*` Slide Specs、stable `REG-*` Layout 与 immutable wireframes；
   - Production Visual System → immutable Renderer IR → Final SVG / PptxGenJS Native / Hybrid；
   - Asset/Font/Geometry Preflight、PNG/PDF export、measured editability、Production Render Manifest、M4 Application 与 G6/G7；
   - independent deterministic/semantic/scorecard/visual review facts；
   - severity-first issue handling、earliest-phase routing、Repair Plan/Report、cross-deck regression；
   - Production Quality Report lineage、G8、Golden baseline 与 M5 Application Report。
5. 从 v1.0 的 provider-neutral 扩展点继续：新增真实 provider 适配与独立评测时，不得伪造 capability，也不得重开已冻结的 M2–M6 核心边界。
6. M6 不得把产品化需求反向塞入 Evidence、Planning、Renderer 或 Review 的私有状态；Production boundaries 继续通过已有 artifacts/protocols 交互。
7. 保持单一主编排器。只对独立只读审计、测试分析或代码探索使用子代理；重叠代码由一个 writer 修改。
8. 做根因修复，直接替换错误逻辑；架构变化同步 ADR、Schema、示例、文档和测试。
9. 不需要为每个子模块重复跑多个 Python minor 版本。选择一个正式支持环境做完整冻结回归，并保留必要的兼容/发布级矩阵即可。
10. 每个 M6 子模块继续采用 Open Issue Mining → 根修 → Scorecard/Gate，不允许评分掩盖 Critical/Major。

最终汇报必须包含：变更清单、关键设计决策、测试结果、审计结果、仍存风险、下一稳定点，并引用具体文件路径。

---
