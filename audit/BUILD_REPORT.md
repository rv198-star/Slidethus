# Slidethus Bootstrap v0.1.0 — Build Report

## Build identity

- Package: `Slidethus_Bootstrap_v0.1.0`
- Python distribution: `slidethus 0.1.0`
- Milestone: M0 Foundation Contract
- Production deck generation: intentionally not implemented
- Build environment: Python 3.13.5 on Linux

## Verification matrix

| Check | Result | Evidence |
|---|---|---|
| Python compile | PASS | `python -m compileall -q src tests scripts` |
| Unit/contract/adversarial suite | PASS | 40 tests |
| Schema inventory | PASS | 13 Draft 2020-12 schemas |
| Repository/package schema parity | PASS | byte-identical mirrors |
| Integrated example | PASS | workspace validation and G0–G6 |
| Negative production claim | PASS | bundled example fails G7 by design |
| Planning wireframes | PASS | three SVG files at 1280×720 |
| Wheel build | PASS | `slidethus-0.1.0-py3-none-any.whl` |
| Standalone installed mode | PASS | doctor, schemas, init, validate, blocked G0 |
| Local Ruff | NOT RUN | Ruff unavailable in offline builder; CI configured |
| Python 3.11/3.12 matrix | NOT RUN LOCALLY | GitHub Actions configuration included |

## Wheel record

- Size: 42,908 bytes
- SHA-256: `50df8d6b99618049e7b815d62d2c19b96f5d5c3d4b5e0c9ec67abbb511a02c22`
- Installed schema source: packaged `slidethus/_schemas`
- Runtime smoke directory: outside the source repository

## Release hygiene

Before source packaging, generated `build/`, `dist/`, `*.egg-info`, caches, bytecode, and temporary output are removed. The package audit then creates `audit/manifest.sha256`. ZIP integrity and extracted-manifest verification are release steps executed after the source tree is frozen; the archive digest is stored in the sibling `.zip.sha256` file.

## Honest capability boundary

The package includes contracts, a repository Skill, provider interfaces, a deterministic CLI, Gates, validation, and planning wireframes. It does not include production search/model/image adapters, Final SVG, native PPTX, Hybrid rendering, Office round-trip validation, or visual-model repair. Those remain explicit M1–M6 roadmap work.
