# Audit Round 5 — Adversarial, Degradation, Security, and Package Integrity

## Scope

Attempt to make the foundation report false completion, accept stale or unsafe artifacts, omit facts while retaining a later phase, confuse planning review with final review, overpromise editability, leak browser metadata, or ship generated build debris.

## Adversarial mutations covered by tests

The 40-test suite includes negative mutations for:

- unknown source, evidence, asset, section, slide, block, region, or issue references;
- duplicate IDs and invalid slide/block/region identity encoding;
- missing content-block placement, duplicate/incomplete reading order, and out-of-canvas/safe-area geometry;
- inconsistent Project/Deck IDs and invalid page-count contracts;
- unsupported/disputed evidence or `do_not_use` sources entering presentation facts;
- complete research cycles without their claimed material sources;
- stale targeted research for a different outline version;
- unsafe absolute or parent-traversal workspace paths;
- present but unregistered artifacts, deleted upstream artifacts, registry type/schema drift, and stale hashes;
- missing prior Gates, G8 attempted before G7, G9 attempted before review/delivery readiness, and a G6 planning report impersonating G8;
- successful render or ready delivery with `not_measured` editability;
- actual editability below the declared target;
- force initialization over a workspace containing advanced or user files;
- blank titles, non-Latin collisions, and IDs beginning with invalid punctuation.

All current adversarial tests pass.

## Degradation and capability truthfulness

- D0–D5 delivery levels make missing search, image, render, preview, or review capabilities explicit.
- M0 contains only a deterministic planning-wireframe renderer.
- G7 remains a deliberate negative control for the bundled example.
- Renderer interfaces, prompts, and directories are not counted as completed production features.
- Final SVG, native PPTX, Hybrid rendering, Office validation, and model-based visual review remain M4/M5 work.

## Source and security checks

- Browser-saved raw HTML is absent from the release tree.
- Source material has an internal SHA-256 manifest.
- The three source-preserved prompt mirrors are byte-identical.
- Source-derived material and Slidethus engineering additions are separated by directory and policy.
- Embedded source instructions are treated as untrusted data rather than repository instructions.
- Absolute paths and `..` escapes are rejected for registered, render, and delivery files.

## Automated package audit

The release audit checks required paths, Skill frontmatter, all 13 schemas, packaged-schema parity, instruction budget, raw HTML omission, phase/status alignment, the minimal project with hashes, relative links, unresolved markers, source hashes, source-prompt mirrors, two-pass research contracts, target/actual editability contracts, five substantive audit reports, release-tree hygiene, and the absence of a fake renderer.

`audit/manifest.sha256` hashes the source release tree while excluding caches, build output, and the manifest itself. The final ZIP is separately tested with `unzip -t`, extracted into a clean directory, and checked against this manifest. Its sibling `.sha256` file records the archive digest without creating a self-referential hash.

## Residual risks

- External image URLs in the example gallery may expire.
- Public redistribution still requires a final license and third-party-rights decision.
- CI Python 3.11/3.12 and Ruff were not executable in this offline builder.
- Production renderer, preview, accessibility, Office round-trip, and visual-review behavior are intentionally unimplemented.
- M1 must add transactional artifact history and dependency invalidation; M0 validates current facts but is not a complete workflow database.

## Result

**PASS for M0 adversarial, degradation, security, and package-integrity controls, subject to the declared production and CI limitations.**
