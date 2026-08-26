# Audit Round 4 — Buildability, Installation, and Executable Verification

## Scope

Verify that the deterministic M0 core compiles, its contracts execute, the example behaves truthfully, and the Python package runs after installation outside the repository.

## Environment

- Python: 3.13.5
- pytest: 9.0.2
- jsonschema: 4.26.0
- setuptools: 82.0.1
- pip: 25.1.1

The package declares Python 3.11+. CI is configured for Python 3.11 and 3.12; this builder exposed only Python 3.13, so those two matrix versions remain CI verification items.

## Commands and results

### Compile and tests

```bash
PYTHONPATH=src python -m compileall -q src tests scripts
PYTHONPATH=src python -m pytest -q
```

Result: **PASS — 40 tests**.

The suite covers schema validity and mirrors, workspace safety, ID normalization, phase transitions, cumulative artifact persistence, G0–G9 prerequisites, registered hashes, source/evidence/asset references, two-pass research cycles, section and objection references, slide/block/region identity, full block placement, page-count and aspect contracts, render/delivery truthfulness, measured editability, editability promises, wireframe generation, and negative controls.

### Integrated validation

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python scripts/validate_all.py
```

Result: **PASS — 13 schemas, the example workspace, G0–G6, a deliberate G7 negative control, and three 1280×720 planning wireframes**.

### Wheel build

```bash
python -m pip wheel . --no-build-isolation --no-deps -w /tmp/slidethus-wheel-final
```

Result: **PASS**.

- Artifact: `slidethus-0.1.0-py3-none-any.whl`
- Size: 42,908 bytes
- SHA-256: `50df8d6b99618049e7b815d62d2c19b96f5d5c3d4b5e0c9ec67abbb511a02c22`

### Standalone installed-mode smoke

The Wheel was installed into `/tmp/slidethus-wheel-target-final`, then executed from `/tmp` with the source repository absent from `PYTHONPATH`.

- `python -m slidethus --version` → `0.1.0`
- `python -m slidethus doctor` → Python and 13 packaged schemas PASS
- `python -m slidethus schemas` → 13 entries
- `python -m slidethus init ...` → valid stage-0 workspace
- `python -m slidethus validate ... --check-hashes` → PASS
- `python -m slidethus gate ... G0` → `blocked` as expected because purpose/outcome questions remain unresolved

This verifies that packaged schemas are available in installed mode and that the CLI does not depend on repository-relative files.

## Findings corrected during this round

- The initial Wheel omitted schema files; package data and a byte-identical `_schemas` mirror fixed installed-mode failure.
- Wheel construction creates `build/` and `*.egg-info`; the release audit now rejects those directories in the source package.
- A planning wireframe is explicitly labeled as non-production output; no Node renderer package is shipped as a fake implementation.

## Lint limitation

`ruff` is not installed in this offline builder, so no local Ruff pass is claimed. The Ruff configuration exists and CI runs `ruff check src tests scripts` after installing development dependencies.

## Result

**PASS for M0 buildability and standalone deterministic-core installation. Ruff and the declared Python 3.11/3.12 matrix remain external CI checks.**
