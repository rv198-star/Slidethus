# Slidethus Notice

Copyright 2026 Slidethus contributors.

Slidethus project-owned code, documentation, schemas, Skill files, examples authored by the project, and renderer source are licensed under the Apache License, Version 2.0. See `LICENSE`.

## Materials not automatically licensed by Apache-2.0

The project license does **not** grant rights in content that Slidethus does not own or cannot relicense. In particular:

- files under `source_material/` are retained for provenance/research and remain subject to the rights of their original authors or providers;
- user-supplied decks, documents, data, images, fonts, templates, brand assets and other inputs retain their existing rights and restrictions;
- third-party dependencies retain their own licenses;
- model/provider outputs and downloaded assets are governed by the applicable provider terms and source licenses;
- host-discovered fonts are not distributed by Slidethus merely because they were used for local rendering or preview.

See `THIRD_PARTY_NOTICES.md`, `source_material/LICENSE.md`, and `release/rights-policy.json` for the executable distribution boundary.

## Distribution policy

The default Python wheel and Slidethus Plugin bundle do not vendor:

- Python dependency wheels;
- downloaded Node `node_modules`;
- model binaries or model weights;
- host fonts;
- private/user source material;
- unlicensed third-party visual assets.

A separately redistributed environment, container, prepared renderer cache, asset pack, or model bundle must carry the licenses/notices required by the exact third-party components it contains and should regenerate the release SBOM.
