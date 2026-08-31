# Third-Party Notices and Redistribution Boundary

Slidethus project-owned code is licensed under Apache-2.0. Third-party software and source material retain their own licenses and rights.

## Bundled Taste Skill

Slidethus bundles the upstream `design-taste-frontend` Skill as its default art-direction provider resource:

- Source: `https://github.com/Leonxlnx/taste-skill`
- Pinned commit: `ccbc15639c97057cbfcf32ecebc38ef716e4bb37`
- License: MIT
- Copyright: Copyright (c) 2026 Leonxlnx
- Bundled path: `.agents/skills/slidethus/providers/art-direction/taste/`

The original `SKILL.md` is retained verbatim with its MIT `LICENSE` and machine-readable `PROVENANCE.json`. Slidethus slide-specific adapter code is separately licensed under Apache-2.0. The bundled Skill remains third-party material and is not relicensed by the Slidethus project license.

## User-provided / third-party source material

### Optional design reference adaptations

Eight reference cards under `.agents/skills/slidethus/references/design-library/cards/` are adapted from `acnlie/open-kimi-ppt-skill` at commit `c32890fe0985bdf668f2722fed30f1010bdf24c9` (MIT; Copyright (c) 2026 Binaryify Zhuang). The adjacent `LICENSE` preserves the upstream notice and `PROVENANCE.json` records exact source paths, hashes and optional preview URLs. These adaptations retain the MIT notice; Slidethus selection policy and index are project-authored Apache-2.0 material.

Repository-only originals are preserved verbatim in `source_material/source-preserved/open-kimi-ppt-skill/` and excluded from wheel/Plugin. The distributed cards are optional design references, not another provider, executable Skill or automatic theme engine. No upstream photos, font binaries, renderer or sample deck is bundled. Linked previews are reference-only; their content must not be copied into a delivery without an independent asset-rights decision. The source-distribution SBOM records the adapted reference component.

### Original workflow material

The repository retains provenance material derived from a user-provided saved HTML page titled “应该是目前最强的PPT Agent，附上完整思路分享”. Relevant files live under `source_material/`.

Rules:

- `source_material/` is excluded from the Apache-2.0 project grant unless a specific file states otherwise;
- source-preserved excerpts/prompts remain distinguishable from project-authored repairs/extensions;
- no ownership, endorsement, or license transfer is implied;
- the default wheel and Plugin bundle do not ship `source_material/`;
- any public redistribution of original third-party excerpts/assets requires a separate rights review.

See `source_material/LICENSE.md`.

## Python direct dependencies

The Python package declares but does not vendor these direct runtime/optional dependencies. Their transitive dependencies also retain their own licenses.

| Dependency | Use | License |
|---|---|---|
| `jsonschema` | Draft 2020-12 validation | MIT |
| `python-pptx` | PPTX generation/parsing | MIT |
| `pypdf` | optional PDF extraction | BSD-3-Clause |
| `python-docx` | optional DOCX extraction | MIT |
| `openpyxl` | optional XLSX extraction | MIT |
| `Pillow` | optional raster verification/metadata | MIT-CMU |

If you redistribute a Python environment, container, zipapp, executable or vendor directory containing resolved dependency packages, include the notices/licenses required by the exact versions contained in that artifact and regenerate the SBOM from the release environment.

## Node renderer dependencies

The renderer source is shipped with `package.json` and `package-lock.json`; downloaded `node_modules` are **not** part of the default wheel or Plugin bundle. `slidethus plugin bootstrap-renderer` performs a local `npm ci` into a user cache.

Direct renderer dependencies are:

| Dependency | Pinned version | License |
|---|---:|---|
| `@resvg/resvg-js` | 2.6.2 | MPL-2.0 |
| `pdf-lib` | 1.17.1 | MIT |
| `pptxgenjs` | 4.0.1 | MIT |

The Plugin builder and `scripts/generate_sbom.py` deterministically generate `release/sbom.spdx.json` from the exact Node lock graph and the declared Python dependency boundary.

If you redistribute a prepared renderer cache or another artifact containing downloaded `node_modules`, you are the redistributor of those dependency files and must include the applicable license texts/notices. The default Slidethus release intentionally avoids this by distributing only renderer source + lockfile.

## Optional host tools

LibreOffice, Poppler and Fontconfig are optional host capabilities and are not bundled by the default Slidethus wheel/Plugin. Review the licenses supplied by the platform/distribution from which those tools are installed before redistributing them.

## Fonts, brand assets and generated media

Host-discovered fonts may be used temporarily for local rendering/preview but are not copied into Slidethus packages or deliveries by default. User/third-party logos, templates, icons, images, videos and other assets require an `Asset Manifest` rights decision before redistribution. Extract Style records reusable tokens and provenance; it does not copy font/media bytes merely because they exist in a reference deck.

## Models and providers

Slidethus is provider-neutral and does not bundle production LLM/vision model weights. Any external provider SDK, model, generated asset or hosted service is subject to its own terms. Provider output does not override source copyright, trademark, privacy or asset-license obligations.

## SBOM

`scripts/generate_sbom.py` generates the source-distribution SPDX 2.3 SBOM. The default Plugin bundle embeds that generated document as `release/sbom.spdx.json`. It records the project package, curated Python direct dependency constraints and the exact Node lock dependency graph. Release environments that vendor or bundle resolved binaries must generate an artifact-specific SBOM in addition to this source-distribution SBOM.
