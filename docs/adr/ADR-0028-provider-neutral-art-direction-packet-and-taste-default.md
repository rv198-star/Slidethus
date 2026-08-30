# ADR-0028 — Provider-neutral Art Direction Packet and Taste Default

- Status: Accepted
- Date: 2026-08-30
- Scope: M6.6 Preview Hardening / P6 Visual System

## Context

M6.6 的真实 PPTX 评审表明，内容和结构正确并不会自动产生优秀的配色、构图、节奏与视觉层级。一次隔离的 Taste-informed 样板实验把可感知质量从约 75 分提高到接近 90 分，但实验结果尚未进入 Slidethus 的正式、可审计工作流。

Slidethus 必须避免两个相反错误：一是继续把视觉质量锁死在硬编码默认值；二是让某个外部 Skill 直接接管渲染器，从而破坏 provider neutrality、结构化工件和真实 Office 验收边界。

## Decision

### 1. ArtDirectionPacket 是 P6 的正式输入事实

在 G5B 通过后、Production Visual System 发布前，系统生成一个 schema-backed `ArtDirectionPacket`。Packet 是不可变、内容寻址的运行事实，存放在：

`.slidethus/art-direction/packets/<sha256>.json`

它不是新的用户可编辑主工件阶段，也不改变现有 Project State 枚举。Visual System 必须记录 Packet ID、相对路径、内容 hash、provider identity 和执行模式。G6 校验该引用存在且内容未被篡改。

### 2. Provider proposal 与确定性 admission 分离

领域层定义 `ArtDirectionProvider` 协议。Provider 只能针对当前 Brief、Outline、Slide Specs、Layout Plans 和 Asset Manifest 提交受限 proposal。确定性服务负责：

- 绑定完整输入 lineage；
- 补充稳定 ID、provider identity、时间戳和 hash；
- 执行 payload 上限、schema 与路径校验；
- 将 Packet 与 Visual System 原子发布；
- 拒绝缺失、越界、无效或身份漂移的 provider 输出。

渲染器不读取 provider，也不读取 Taste Skill；它们继续只消费已批准的 Visual System、Layout Plans、Slide Specs 和 Asset Manifest。

### 3. Taste Skill 是默认 adapter，不是核心依赖

默认实现为 `TasteSkillArtDirectionProvider`。Slidethus 随 wheel/Plugin 分发固定版本的上游 Taste Skill，并保留 MIT License、commit、来源 URL 和 SHA-256。

默认 adapter 只把适用于静态演示文稿的原则翻译为 Packet，例如：

- brief inference 与一行 design read；
- design variance / motion intensity / visual density dials；
- 单一主题、强调色和圆角体系；
- 非模板化但可控的构图变化；
- 页面角色差异、deck rhythm 和重复布局限制；
- anti-slop forbidden patterns 与 preflight 意图。

网页框架选择、DOM、导航、按钮、滚动触发器、GSAP/React 代码和营销网站专属规则不进入 Packet。

### 4. 固定版本和授权是发行契约

默认 Taste 资源固定到上游 commit `ccbc15639c97057cbfcf32ecebc38ef716e4bb37`。原始 Skill 文件 hash 为 `aa194351b246b8b4799099d4ed7b033d29eab6e6e3d58d8d2172978be7b3ec89`，许可文件 hash 为 `4575a543ab88dad12ccea7d97e563d0bce5b448b06072e65d3264497dad326df`。

Plugin Manifest、distribution status、THIRD_PARTY_NOTICES、rights policy 和 SPDX SBOM 必须可见该第三方组件。资源缺失或 hash 漂移时，默认 provider fail closed；不得静默宣称使用了 Taste。

### 5. Provider 可替换，Packet 契约保持稳定

调用者可注入人工、企业设计系统、其他 Skill 或模型驱动的 `ArtDirectionProvider`。Provider 名称、版本、执行模式和来源会进入 Packet lineage，但 Visual System 和 render backend 不因供应商而改变 schema。

## Consequences

- 默认安装具备可审计的 Taste 视觉指导基础，不要求用户另行安装 Skill。
- Taste 影响停留在艺术指导层，不成为 PPTX/SVG backend 的隐式依赖。
- 同一输入与同一默认 provider 生成相同 Packet 和 Visual System，便于回归与发行复现。
- 未来接入生成式 art-direction provider 时，仍需经过相同 admission 和 Office-rendered visual gate。
- Taste 自身的 MIT 许可与 Slidethus 的 Apache-2.0 项目许可保持可区分。

## Verification

- Packet schema、provider 边界和内容寻址测试；
- Visual System 幂等性和 G6 篡改/缺失拒绝测试；
- wheel/Plugin 内置资源、hash、NOTICE、rights policy 与 SPDX 测试；
- 真实 Office-rendered PPTX 的 M6.6 视觉评审。
