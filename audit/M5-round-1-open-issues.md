# M5 Review Round A — Open Issue Mining

## Review rule

This round was performed without scores. It reviewed M5 as an independent review/repair boundary on top of frozen M2/M3/M4 truth, with special attention to monotonic Gates, provider admission, immutable review lineage, repair safety, full-page evidence, cross-deck regression and truthful G8 aggregation.

## Initial result

```text
Critical: 0
Major:    7
Minor:    3
Waivers:  0
```

No waiver was used.

## Major findings and root fixes

### M5-A-MAJ-001 — Downstream P7 corruption reversed already-passed early Gates

- Risk: a missing render output made G0–G6 fail because every Gate consumed whole-workspace validation; M4 could therefore not responsibly regenerate its own P7 output.
- Root fix: deterministic Gate validation now admits only validation failures at or before the Gate's responsibility stage. A P7 defect leaves G0–G6 monotonic and fails G7.
- Evidence: `tests/test_review_repair.py::test_downstream_render_failure_does_not_reverse_early_gates`.

### M5-A-MAJ-002 — Deterministic Review identity depended on unrelated Project State revisions

- Risk: a successful first G8 changed Project State revision and caused a second M5 run to produce a different M5.1 report even though every consumed M2–M4 input was unchanged.
- Root fix: `state_revision` was removed from the Deterministic Review contract. DVR identity is derived from the current M2–M4 artifacts/check results it actually consumes.
- Evidence: M5 Application idempotency test.

### M5-A-MAJ-003 — Persisted review facts could become a side channel without runtime validation

- Risk: content-addressed DVR/SVR/SCR/VVR/Repair/Regression files could be tampered after publication and still be treated as review evidence.
- Root fix: each M5 runtime fact has a Draft 2020-12 schema, content-derived identity, admitted runtime root, historical/current input validation and workspace-wide tamper checks.
- Evidence: deterministic/semantic/visual/quality tamper negative controls.

### M5-A-MAJ-004 — Reviewer proposals could invent identities or repair authority

- Risk: a semantic/visual provider could cite nonexistent Slide/Block/Region/Evidence IDs or mark arbitrary model suggestions as automatic repairs.
- Root fix: providers return proposals only. Deterministic admission validates all references, recomputes stable issue IDs and downgrades unimplemented automatic repair claims to assisted.
- Evidence: `test_semantic_admission_rejects_unknown_slide`, `test_visual_review_rejects_unknown_slide` and repairability controls.

### M5-A-MAJ-005 — Scorecard could mask blocking Round A findings

- Risk: a 5/5 average could make a report appear healthy while Critical/Major issues remained open.
- Root fix: scorecard runs only after Round A, low scores require an explicit Round A issue, and Critical/Major counts independently force `issues`; Production Quality/G8 uses severity before scores.
- Evidence: semantic and Quality Report tests with a Major issue plus overall score 5.0.

### M5-A-MAJ-006 — Repair execution could overwrite an existing corrupted deliverable

- Risk: treating any P7 signature failure as automatically repairable could silently replace user-visible bytes and hide a corruption/tamper event.
- Root fix: automatic P7 regeneration is admitted only when referenced generated files are missing and confined under `outputs/`. Existing corrupt files route to assisted repair and are never automatically overwritten.
- Evidence: `test_existing_corrupt_output_is_not_overwritten_automatically`.

### M5-A-MAJ-007 — Production G8 lacked immutable review lineage

- Risk: `review/quality_report.json` could claim pass without proving which deterministic, semantic, scorecard, visual and regression facts it aggregated.
- Root fix: Production Quality Report binds DVR/SVR/SCR/VVR/optional RRR/REG by path/hash/status and maps every current source issue to exactly one Quality `ISS-*`. G8 recomputes this lineage and capability state.
- Evidence: clean G8 integration plus semantic-report-tamper negative control.

## Minor findings and fixes

### M5-A-MIN-001 — Capability-missing scorecard placeholders were misclassified as low quality

The first scorecard validator applied the “score < 3 must cite a Round A issue” rule to capability-missing placeholder scores. The rule now applies only when scorecard capability is available; missing capability is represented as blocked, not as a quality judgment.

### M5-A-MIN-002 — Full-page visual admission initially read the wrong Layout collection key

M3 Layout uses `plans`, not `slides`. M5.4 now consumes the frozen M3 contract directly and the regression is covered by full-page integration tests.

### M5-A-MIN-003 — Quality Report publisher assumed the catalog artifact was pre-registered

A DRAFT_RENDERED workspace legitimately has no Quality Report registry entry. First Production review now publishes Quality Report with `expected_version=0`; subsequent identical runs are idempotent and do not advance G8 again.

## Round A disposition

- Critical open issues: 0.
- Major open issues: 0.
- Minor blocking M5 Exit: 0.
- Waivers: 0.

Round B is permitted after M5.1–M5.7 verification, M2–M4 Exit regression, Node sidecar tests, Package Audit and `git diff --check` pass.
