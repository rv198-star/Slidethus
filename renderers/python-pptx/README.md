# Python PPTX Minimal Backend

`MinimalPptxRenderBackend` is the first real `RenderBackend` implementation.

- consumes Slide Specs, Layout Plans and Visual System;
- emits native editable text and simple shapes;
- reopens the PPTX and verifies slide count plus native text coverage;
- emits same-model SVG previews for debugging;
- declares actual editability E3;
- uses `LibreOfficeDocumentRenderer` for an independent PDF/PNG path;
- copies discoverable local fonts only into a temporary LibreOffice profile for preview and never packages them in the deck or delivery.

Limitations: no images, charts, tables, masters, complex SVG, data binding or automatic repair. PptxGenJS/Hybrid remains the planned ProductionImpl.
