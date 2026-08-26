# Final SVG Backend — Planned

Target: high-fidelity 1280×720 SVG pages with validated text, shapes, charts, diagrams and licensed assets.

Required before implementation:

- stable Visual System token resolution;
- font measurement and fallback service;
- editable chart/diagram strategy;
- overflow and collision detector;
- sanitization of generated SVG;
- screenshot/render regression tests;
- output manifest and repair loop.

Bento is one layout family. The backend must render all supported layout families without forcing cards onto every slide.
