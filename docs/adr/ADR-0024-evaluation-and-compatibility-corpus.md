# ADR-0024 — Evaluation and Compatibility Corpus

- Status: Accepted
- Date: 2026-08-29
- Scope: M6.4 Examples & Evaluation

## Context

M6.1 turned six documented workflows into real runtime behavior, M6.2 added operational controls, and M6.3 made the Skill and renderer distributable. The repository still lacked one machine-readable source of truth describing which workflow scenarios are exercised, which execution tier they belong to, which host capabilities are required, and which claims have actually been verified.

A single monolithic end-to-end evaluation is also unsuitable for normal development because Create/Rebuild/Revise deliberately exercise real M3→M4→M5 chains and can exceed one bounded tool invocation when grouped together.

## Decision

### 1. One six-workflow evaluation corpus

`evals/m6/suite.json` is the machine-readable corpus. It contains exactly one canonical case for each product workflow:

- Create
- Rebuild
- Improve
- Audit
- Revise
- Extract Style

Each case records an execution tier, request fixture, expected workflow status/Gate behavior, invariants and the concrete pytest selector that exercises the Production implementation.

### 2. Quick and Production tiers are separate truths

`quick` validates the complete corpus and compatibility matrix, then executes only offline/cheap cases. It is the default local regression tier.

`production` is the release-quality workflow evidence. It may be executed as bounded groups rather than one monolithic pytest process as long as the corpus selector set is unchanged. Splitting execution does not change the evaluated contract.

### 3. Compatibility claims are machine-readable

`docs/compatibility-matrix.json` records host/platform/capability status with explicit values such as required, optional, degraded or unsupported. The matrix distinguishes:

- repository support policy;
- host capability requirements;
- optional Office preview;
- semantic/visual provider injection;
- Python and Node baselines;
- platform verification state.

Unverified platforms are not described as tested.

### 4. Evaluation fixtures are not Production model providers

Deterministic semantic/visual fixtures used by integration tests verify provider-neutral contracts and orchestration. They are evaluation fixtures only and do not claim production semantic or visual model quality.

### 5. Corpus schemas are packaged runtime/reference schemas

`evaluation_suite.schema.json` and `compatibility_matrix.schema.json` are Draft 2020-12 schemas with packaged mirrors. M6.4 repository validation checks the canonical files against those schemas and verifies all pytest selectors resolve to existing test files.

## Consequences

- Six workflow product claims now have an inspectable, executable corpus.
- Normal local evaluation stays fast while release evaluation preserves real renderer/G8 paths.
- Host/platform statements become explicit and reviewable rather than prose-only claims.
- Future workflow cases can be added without creating a second orchestration system.
- M6.4 does not itself certify every OS/Office/model provider combination; it records what is verified and what is not.

## Verification

- `python scripts/run_m6_evals.py --validate-only`
- `python scripts/run_m6_evals.py --tier quick`
- `python scripts/validate_m6_4_evaluation.py`
- bounded Production selectors recorded in `evals/m6/suite.json`
