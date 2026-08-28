# M4 — Production Rendering Backends

## 1. Objective

- 用户价值：把冻结的 M2/M3 语义与页面策划资产编译为可验证的最终视觉文件，并在视觉自由度、原生编辑性和跨平台一致性之间做显式选择。
- 本轮边界：Production Visual System 编译、Final SVG、PptxGenJS Native PPTX、Hybrid PPTX、图片/图标/图表/表格资产合同、字体探测与替代、overflow/collision/safe-area 检查、PPTX/PDF/PNG 导出、Render Manifest、实际编辑等级测量、独立 preview、M4 Application/CLI、M4-wide audit/Exit Gate。
- 明确不做：重写 M2 Source/Evidence；重写 M3 Narrative/Outline/Specs/Layout；LLM/视觉模型质量审计与自动视觉修复（M5）；内置图片搜索/生成供应商；把无法编辑的 SVG 页面冒充 E3/E4。
- 退出条件：同一 current M3 semantic/planning graph 可由 Final SVG 与至少一种 PPTX Production backend 渲染；PptxGenJS Native 与 Hybrid 具备真实、可重新打开的输出；manifest 精确绑定输入版本/hash、backend、资产、字体、警告、preview 和实际 editability；geometry/font/assets fail closed；后端切换不修改 M2/M3 Schema；Python 3.11/3.12、Node renderer tests、M2/M3 Exit regression、M4 Exit、Package Audit、diff check 全部 PASS。

## 2. Current state

- 当前 HEAD / Git：`main` at `077ec3b`，`origin/main` 同步；M2.2–M3 与当前 M4 工作仍处于未提交工作区，本轮不执行 Git 操作。
- 已存在能力：M2/M3 Exit PASS；Production Slide Specs、Layout Plans、immutable planning wireframes；Visual System/Asset/Render Manifest Schema；Minimal `python-pptx` debug/design backends；LibreOffice preview adapter；Node 22/npm 10 可用。
- 已知缺口：M4 Production Rendering 已完成；当前只保留 M5 independent visual review/repair、Office/Poppler host capability 差异和后续产品化工作，不再把这些后续能力归入 M4。
- 环境事实：OCI host 有 Node/npm；当前 host 未发现 `pdftoppm`，因此独立 PNG preview 必须作为显式 host capability，不能假装可用。

## 3. Decisions and assumptions

| ID | 类型 | 内容 | 依据 | 可逆性 |
|---|---|---|---|---|
| D-401 | Decision | M4 保持一个 `M4ApplicationService`；renderer/asset/font/preview services 是受控子服务，不反向拥有 Planning truth。 | 单一主编排器 / M3 frozen | 高 |
| D-402 | Decision | Production renderer 只消费 current approved/frozen M3 artifacts；renderer 不能改写 Narrative/Outline/Specs/Layout。 | semantic/render separation | 高 |
| D-403 | Decision | Visual System 作为 M4 的第一个 Production semantic-to-style compile step；它绑定 Brief/Outline/Specs/Layout lineage，但不改变事实内容。 | P6/P7 边界 | 中 |
| D-404 | Decision | Final SVG 是每页独立、content-addressed 的矢量最终视觉后端，编辑性按 E1 测量；它不是 PPTX。 | capability truthfulness | 高 |
| D-405 | Decision | PptxGenJS Native 通过 Node sidecar 实现，文本、简单形状、表格、基础图表优先原生；sidecar 输入是 renderer IR，不读取/修改领域 JSON。 | TASKS / provider neutrality | 中 |
| D-406 | Decision | Hybrid PPTX 保留正文/简单形状原生，把复杂 visual primitive 作为 SVG/PNG 嵌入；manifest 按元素/输出声明编辑等级，整体实际等级取保守下界。 | ADR-0003 | 中 |
| D-407 | Decision | `python-pptx` Debug/Minimal backends继续作为兼容/回归切片，不升级命名为 Production PptxGenJS/Hybrid。 | 不冒充能力 | 高 |
| D-408 | Decision | Renderer 前统一执行 Geometry/Content/Asset/Font preflight；overflow 不通过时返回 P5A/P5B rework，不靠全局缩字掩盖。 | docs/06 / M3 Gate | 高 |
| D-409 | Decision | 实际 editability 必须在真实输出生成后通过结构检查测量；目标值只能是请求，不参与实测结论。 | ADR-0003 | 高 |
| D-410 | Decision | PDF/PNG preview/export 依赖 host adapter；缺 LibreOffice/Poppler 时保留 SVG/PPTX 输出并显式降级，不产生伪 preview。 | host capability truthfulness | 高 |
| A-401 | Assumption | M4 deterministic baseline 的视觉质量目标是可交付的工程化视觉系统，而不是宣称通用设计模型达到人类创意上限；M5 才做独立视觉评分/修复。 | 里程碑边界 | 高 |

## 4. Work breakdown

| Step | 产出 | 依赖 | 验证 | 状态 |
|---|---|---|---|---|
| M4.1 | Render contracts、Production Visual System、Renderer IR、font/asset preflight | M3 frozen | lineage/schema/capability tests | complete |
| M4.2 | Final SVG renderer + immutable pages/manifest refs | M4.1 | page/hash/text/geometry tests | complete |
| M4.3 | PptxGenJS Native renderer sidecar | M4.1 | pptx reopen/native text/table/chart/editability tests | complete |
| M4.4 | Hybrid renderer + complex SVG/image embedding | M4.2/M4.3 | mixed-native/embed/editability tests | complete |
| M4.5 | Asset contracts + fonts + overflow/collision/safe-area + export/preview | M4.1–M4.4 | missing asset/font/host degradation tests | complete |
| M4.6 | Render Manifest vProduction + M4 Application/CLI + idempotent cache/history | M4.1–M4.5 | end-to-end/backend-switch/history tests | complete |
| M4.7 | Docs/ADRs、Round A/root fixes/Round B、M4 Exit validator | 全部 | dual Python + Node + M2/M3 regression + package audit | complete |

## 5. Quality and risk controls

- 受影响 Schema：Visual System、Asset Manifest、Render Manifest；新增 renderer IR / render report runtime Schemas；M2/M3 semantic Schemas 不因 renderer 需求而改形。
- 受影响 Gate：G6/G7；G5B 作为必要前置，不降低 G0–G5B；M4 Exit 是 repository Gate，不加入 deck G0–G9。
- 回归范围：M0–M3、MVP1、wireframes、python-pptx compatibility、Schema examples、CLI、workspace validation、M2/M3 Exit。
- 降级路径：缺 Node/PptxGenJS → backend capability blocked；缺 preview host → render success 可保留但 independent-preview capability 明确 unavailable；缺字体/资产 → substitute/placeholder 只有合同允许时可继续，否则 fail closed。
- 安全/版权：renderer 不联网；资产必须来自 Asset Manifest admitted path/rights；SVG 禁止 active script/external reference；字体只探测/引用，不复制进用户交付除非许可合同明确允许。

## 6. Verification

```bash
# Python 3.11 / 3.12 分组全覆盖
python -m compileall -q src tests scripts
ruff check src tests scripts
pytest
python scripts/validate_all.py
python scripts/validate_m2_exit.py
python scripts/validate_m3_exit.py
python scripts/validate_m4_exit.py

# Node renderer
npm test --prefix renderer

python scripts/audit_package.py
git diff --check
```

- 期望：全部 PASS；M2/M3 Exit 继续 PASS；至少两个 Production backend 对同一 semantic graph 通过；backend switch 不改领域 artifacts。
- 实际：Python 3.11/3.12 均完成 280/280 非 M4 Exit 测试；Node sidecar 4/4 PASS；Round A 0 Critical / 9 Major / 4 Minor，Critical/Major 全部根修，无 waiver。最终 Exit/Package 结果以 `audit/M4-BUILD_REPORT.md` 为准。

## 7. Review

### Round A — Open issue mining

- 不评分；实现后跨 Python/Node/Office/Schema/asset/editability 边界寻找 Critical/Major。

### Round B — Dimension scorecard

- Correctness
- backend independence
- visual/render contract fidelity
- editability truthfulness
- font/asset/security
- geometry/readability
- portability/degradation
- testability/maintainability

## 8. Final outcome

- 已完成：M4.1–M4.7 Production Rendering boundary 与 repository-wide audit。
- 已冻结前置：M2 Exit PASS、M3 Exit PASS。
- 未完成：M5 independent visual review/repair 与后续产品化。
- 下一里程碑：进入 M5 Review and Repair Loop，不重做 M2/M3/M4。
- **M4 Exit Gate：PASS（2026-08-28）。**
