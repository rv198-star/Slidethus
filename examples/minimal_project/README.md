# Minimal Project

这个三页项目展示 Slidethus 的 M0 合同如何协同：来源 → 证据 → 叙事 → 数字便利贴 → Slide Specs → Layout Plans → Visual System。

```bash
slidethus validate examples/minimal_project --check-hashes
slidethus gate examples/minimal_project G6
slidethus render-wireframe examples/minimal_project
```

`current_phase` 故意停在 `VISUAL_SYSTEM_READY`。`render_manifest` 和 `delivery_manifest` 是草稿，不能据此声称生产级 SVG/PPTX 已完成。
