# Python PPTX MVP Backends

The MVP deliberately uses two different PowerPoint outputs:

- `DebugPptxRenderBackend` consumes Slide Specs and Layout Plans, then exposes grid, safe area, Region IDs, Block IDs, and mappings;
- `MinimalDesignPptxRenderBackend` additionally consumes Visual System tokens and emits the separate final deck;
- both emit native editable text and shapes and reopen their outputs for validation;
- the final backend emits design SVG proofs;
- declares actual editability E3;
- uses `LibreOfficeDocumentRenderer` independently for both PPTX files;
- copies discoverable local fonts only into a temporary LibreOffice profile for preview and never packages them in the deck or delivery.

Limitations: no images, charts, tables, masters, complex SVG, data binding or automatic repair. PptxGenJS/Hybrid remains the planned ProductionImpl.
