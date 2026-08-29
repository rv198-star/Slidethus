# ADR-0025 — License, Rights and SBOM Boundary

- Status: Accepted
- Date: 2026-08-29
- Scope: M6.5 License & Third-party Policy

## Context

M6.3 made the Skill and renderer distributable, and M6.4 made product claims executable. The repository still carried a deliberate pre-release state: no project license had been selected, `source_material/` required a distinct rights boundary, and the wheel/Plugin did not yet carry a complete license/NOTICE/SBOM policy.

A single top-level open-source license cannot grant rights in user inputs, third-party source excerpts, fonts, brand assets, dependency code, model outputs or provider services that Slidethus does not own. The release system therefore needs both a project license and an explicit non-project rights boundary.

## Decision

### 1. Apache-2.0 is the Slidethus project license

Project-owned code, schemas, documentation, Skill files, tests, project-authored examples and renderer source use Apache License 2.0. `pyproject.toml` declares `License-Expression: Apache-2.0` and includes `LICENSE`, `NOTICE.md` and `THIRD_PARTY_NOTICES.md` as license files.

Apache-2.0 was selected because Slidethus is an embeddable framework/Skill and benefits from an explicit patent grant plus NOTICE redistribution mechanics.

### 2. Project license does not relicense external material

`source_material/` has a directory-level `LICENSE.md` stating that user-provided/third-party research material is not automatically licensed under Apache-2.0. The default wheel and Plugin exclude the directory.

The same principle applies to:

- user workspace inputs;
- third-party dependency code;
- external logos/templates/media;
- host fonts;
- production model/provider outputs and services.

### 3. Machine-readable rights policy

`release/rights-policy.json`, validated by `release_rights_policy.schema.json`, defines:

- project-owned scopes;
- excluded/review-only scopes;
- default release exclusions;
- asset/font/model policy;
- prepared-environment redistribution policy.

The policy is shipped in the wheel and Plugin.

### 4. Default releases do not vendor dependency binaries

The Python wheel declares dependencies but does not vendor dependency wheels. The Plugin contains renderer source + lockfile but not downloaded `node_modules`. Host tools, fonts and model binaries are also excluded by default.

If an environment/container/prepared renderer cache is redistributed, that artifact becomes a separate third-party redistribution surface and must include the applicable dependency licenses/notices and an artifact-specific SBOM.

### 5. SPDX SBOM is generated from dependency truth

`src/slidethus/sbom.py` builds a deterministic SPDX 2.3 source-distribution SBOM from:

- Python project metadata/direct dependency constraints;
- the exact Node `package-lock.json` transitive graph, including declared license and integrity metadata.

The Plugin builder embeds the generated document as `release/sbom.spdx.json`. `scripts/generate_sbom.py` exposes the same builder for standalone release artifacts. A large generated SBOM is not maintained as a second hand-edited dependency truth in Git.

### 6. Provenance manifests remain authoritative

Changing a file under `source_material/` requires updating `source_material/manifest.json`. Adding the directory-level rights notice therefore also updates its provenance manifest rather than silently modifying the research corpus.

## Consequences

- Public release recipients get an explicit project license and NOTICE.
- Third-party/user rights are not accidentally implied by the repository license.
- Plugin/wheel default distribution avoids unnecessary binary redistribution obligations.
- The Node transitive dependency graph is license-visible without vendoring `node_modules`.
- Release containers or prepared caches need their own artifact-specific compliance pass.

## Verification

- `python scripts/validate_m6_5_licenses.py`
- `pytest tests/test_distribution.py`
- Python 3.11 wheel metadata inspection
- clean wheel install → `slidethus plugin build`
- Package Audit / source manifest check
