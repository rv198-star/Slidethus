# M6 Build Report

Date: 2026-08-30

## Outcome

M6 Exit Gate: REOPENED

v1.0 Release Gate: DO NOT RELEASE — pending user visual review

The PASS recorded by the original report is revoked. Real Office inspection later exposed Major P5A/P5B/P6/P7 defects that the Round 6 evidence did not detect. See `audit/M6.6-round-7-office-visual-reopen.md`.

## Formal environment

- Python 3.11.11
- Node 22.20.0
- Platform: macOS arm64

Python 3.11 and Node 22 are the frozen release baseline. Host-default Python or Node versions are not substituted into this evidence.

## Preview evidence

- Frozen input: `evals/manual/v1-preview/source.md` plus the unchanged Preview Brief
- Final Attempt: `WFR-928E28C10F896F5C`
- M3: ready
- M4: ready with Final SVG, eight PNGs, PDF, Native PPTX, Hybrid PPTX, measurements, and Office previews
- M5: explicit missing-`SemanticReviewProvider` capability block after `DRAFT_RENDERED`
- Retrospective: nine SAR reports plus `SYN-E17A689D3096E148`
- Open Critical systemic candidates: 0
- Open Major systemic candidates: 0

The frozen case-local cover title was not repaired in Production logic. The remaining Minor mixed-script word-wrap observation is recorded and not promoted.

## Release validation

- M2 Exit: 12/12 PASS
- M3 Exit: 13/13 PASS
- M4 Exit: 15/15 PASS
- M5 Exit: 16/16 PASS
- M6.3 Distribution: 7/7 PASS
- M6.4 Evaluation: 6/6 PASS
- M6.5 Licenses: 7/7 PASS
- Node renderer: 4/4 PASS
- Python suite: 331 passed, 42 skipped
- Compileall / Ruff / `git diff --check`: PASS
- Schema/example validator: PASS (16 schemas, G0–G6, G7 negative control, three wireframes)
- Plugin build: byte-reproducible, SHA-256 `ccf1d4b0710b95d0a8c7e77231425b5cc28ae0c71da4a71f0aeed434213ccf75`
- Wheel build: byte-reproducible with fixed `SOURCE_DATE_EPOCH`, SHA-256 `53fdd848629d1da60f3c2fb212d5df7a93c365ffee1d3805f1cde6fdfe1c1748`
- Standalone SPDX 2.3 SBOM: SHA-256 `bdd084e89a540cab14d5f2820fd15438f41f158d782a96dd1ea38f1f3f1abf0b`
- Package Audit: PASS

## Capability truth

v1.0 provides real deterministic ingestion/evidence/planning baseline, page planning, production rendering, review/repair contracts, workflow runtime, distribution, evaluation, and rights boundaries. Search, general model reasoning, semantic/visual review, and image generation remain provider protocols. A missing provider is a visible capability boundary, not an implicit success.

## Stable point

M0–M5 and M6.1–M6.5 remain frozen. M6.6 is reopened until the Round 7 Office candidate receives user visual approval.
