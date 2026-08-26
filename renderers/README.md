# Renderer Adapters

Renderers consume stable semantic and layout artifacts; they do not own factual or narrative decisions.

## Common contract

A renderer must:

1. declare backend name/version and target format;
2. read Slide Specs, Layout Plans, Visual System and Asset Manifest;
3. refuse missing block/region/asset references;
4. enforce canvas, safe area, minimum font and overflow policy;
5. emit output files, previews, warnings, font substitutions and SHA-256 values;
6. populate a schema-valid Render Manifest;
7. support deterministic reruns from the same inputs where the backend permits;
8. never label a file visually verified until previews were rendered and inspected.

Current implementations:

- gray planning-wireframe SVG in `src/slidethus/wireframe.py`;
- `DebugPptxRenderBackend`, producing a native E3 layout-debug deck with stable mappings;
- `MinimalDesignPptxRenderBackend`, producing a different native E3 final deck after applying the Visual System;
- `LibreOfficeDocumentRenderer` for independent PDF/PNG preview with workspace-isolated profiles and temporary local-font staging.

Both PPTX backends are MVP MinimalImpls, not the planned PptxGenJS/Hybrid ProductionImpl.
