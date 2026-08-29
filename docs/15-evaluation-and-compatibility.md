# Evaluation and Compatibility

## Evaluation corpus

The M6 workflow corpus is `evals/m6/suite.json`. It contains exactly one case for each product workflow:

- Create
- Rebuild
- Improve
- Audit
- Revise
- Extract Style

Each case records its fixture contract, representative request, expected status/Gate, invariants and the concrete pytest selector that verifies the Production behavior.

## Evaluation tiers

### Quick

```bash
python scripts/run_m6_evals.py --tier quick
```

Quick evaluation always validates the complete six-workflow corpus and compatibility matrix, then executes only cases marked `quick`. It is intended for normal local changes and does not imply Production renderer/G8 coverage for all workflows.

### Production

```bash
slidethus plugin bootstrap-renderer
python scripts/run_m6_evals.py --tier production
```

Production evaluation executes all six workflow selectors. It requires a prepared renderer. The test harness supplies deterministic semantic/visual fixture providers to verify the provider-neutral review contract; those fixtures are not production model implementations.

Because full Create/Rebuild/Revise chains are intentionally real and expensive, release verification may split the selectors into bounded groups. Passing individual bounded groups is equivalent to one monolithic pytest invocation when the corpus/selector set is unchanged.

## Compatibility matrix

The machine-readable authority is `docs/compatibility-matrix.json` and is validated against `schemas/compatibility_matrix.schema.json`.

Current M6 release baseline:

| Component | Baseline | Meaning |
|---|---|---|
| Python | 3.11 | formal M6 complete validation baseline |
| Node | 22 | verified Production renderer runtime |
| npm | 10 | verified renderer bootstrap runtime |

Declared runtime minimums remain Python >=3.11, Node >=20 and npm >=9.

## Platform claims

- **Linux arm64 container — verified.** Current M6 implementation, wheel install, renderer bootstrap and workflow tests execute here.
- **Linux x86_64 — declared, not release-verified yet.** No M6 evidence may claim certification until the final matrix is executed there.
- **macOS arm64/x86_64 — declared, not release-verified yet.** Packaging is designed to be portable but not yet certified.
- **Windows — unsupported in M6.** `WorkflowLease` uses POSIX `fcntl` and fails closed when unavailable.

This distinction is intentional: packaging portability is not the same as tested platform support.

## Capability degradation

The compatibility matrix also records whether a capability is required, conditional or optional and what the system does when it is missing.

Important boundaries:

- missing Node renderer → planning/review artifacts remain available, final M4/G7 path blocks;
- missing semantic/visual review provider → Production G8 blocks rather than fabricating review;
- missing Office preview → Final SVG→PNG/PDF remains the minimum independent page evidence;
- missing cost meter with no cost cap → status is `not_measured`;
- missing cost meter when a cost cap is requested → workflow blocks before provider work;
- missing online Research provider → user-material workflows follow the explicit M2 degradation policy.

## Adding evaluation cases

New cases must:

1. use a stable case ID;
2. reference a safe fixture or declared generated fixture;
3. identify one concrete workflow;
4. state expected status/Gate and invariants;
5. bind an existing pytest selector;
6. avoid network-dependent fixture truth unless a separate provider contract explicitly owns it.

A new workflow capability is not considered productized merely because a corpus row exists; the selector must exercise the real runtime behavior.
