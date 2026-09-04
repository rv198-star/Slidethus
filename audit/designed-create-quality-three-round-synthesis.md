# Designed Create Quality-by-Construction — Three-Round Audit Synthesis

Date: 2026-09-04
Baseline: `8ad3e49c8b3a6929d3d871da025282b7db2e2653` (`v0.9.2-rc.1`)
Final design decision: **ACCEPT FOR IMPLEMENTATION**
Production/release decision: **NOT IMPLEMENTED; DO NOT RELEASE**

## 1. Independence and inputs

Three independent read-only reviewers received the same first candidate and were instructed not to read or reuse each other's conclusions:

| Round | Lens | Initial verdict | Closure verdict |
|---|---|---|---|
| 1 | artifact/contract/ownership | REWORK | ACCEPT FOR IMPLEMENTATION |
| 2 | adversarial workflow/transactions | REWORK | ACCEPT FOR IMPLEMENTATION |
| 3 | historical/regression attribution | REWORK | ACCEPT FOR IMPLEMENTATION |

Initial candidate hashes:

- Plan: `3bfc6e8f7c2afe2ab9c20f9fe5e390484a7ab03ceeb7c23b42dcd6e53ed6c89e`
- ADR: `8d5996bea31ad2ba2b4de04edf73e3f87b8604aeacea2c5a212ffd6c9cb35714`

Revised substantive design hashes independently accepted by all three reviewers:

- Plan: `b0503db1f8345bb14ec4e4a95839ec839f3cfd7a0498b7a834a42cfeab13804b`
- ADR: `376e9cda4d78c64c045f4398d9425b2bbe7e7f05cb1625e8a95ff32400835833`

The later status/final-outcome edits in the plan and ADR record these verdicts and do not change the audited workflow decision.

## 2. Cross-round convergence

All three reviewers independently found the same original Critical contradiction: the candidate proposed sample approval before P6/P7 full-deck expansion, while the current formal contract can select samples only from one already-complete full-deck IR. Leaving that unresolved would create either self-invalidating approval or another custom/partial IR bypass.

The final design makes one explicit choice:

```text
complete full-deck P5/P6/page designs
  → one frozen complete admitted IR
  → sample render from that IR
  → Office evidence and calibration authorization
  → full render from the identical IR/producer identity
```

No post-sample design expansion exists in this architecture.

## 3. Finding disposition

### Critical findings

| Finding family | Disposition |
|---|---|
| sample/full IR contradiction and self-invalidation | complete IR is frozen before sample; only identical-IR full render is authorized |
| reviewer omission/severity downgrade clears blocker | immutable finding identity/history; workflow derives decision; same-page blocker cannot disappear |
| new high-risk role bypasses calibration | any page/role/design mutation changes the conservative dependency key and revokes authorization |

All Critical findings: **CLOSED**.

### Major finding groups

| Group | Final control |
|---|---|
| duplicate render authority | Host Candidate Receipt remains the sole sample/full attempt receipt |
| calibration resume/orphan/full-entry bypass | one pending lifecycle plus shared `RenderAdmissionPolicy` at every formal full-render entry |
| risk/approval drift | deterministic Brief-hash-bound VisualAdmissionPolicy; approval mode controls pauses, not evidence skipping |
| self-review/provider authority | reviewer only emits evidence; Session fixes identity/capability/independence; workflow derives decision |
| semantic ownership leakage | Outline/Seed/Specs/Layout/Visual/IR/ReferenceSet each has one owner |
| renderer guessing | closed producer vocabulary, capability bindings, no reviewed/critical fallback, mutation-sensitive trace tests |
| planning preview without evidence | content-addressed semantic preview and exact qualitative review binding |
| incomplete dependency identity | complete artifacts, direction evidence/decision/adjudication, compiler/producer/assets/fonts/Office all in key |
| Schema migration | explicit new generations; Candidate Receipt 0.2.0 → additive 0.3.0, breaking bump if semantics change |
| Seed replay regression omitted | exact Seed hash test extends through calibration stop/resume and full render |
| historical overfitting | locked YU7/hotel/FDE/employment matrix plus post-freeze holdout |

All Major findings: **CLOSED**.

## 4. What is confirmed

The three audits confirm that the proposed main workflow is architecturally capable of enforcing quality-by-construction in the following precise sense:

- reviewed/critical work cannot reach full render without current, same-path Office sample evidence;
- quality approval cannot be produced while admitted Critical/Major findings remain open;
- semantic choices cannot legally leak to a generic renderer fallback;
- sample/full currentness, reviewer authority and failure recovery have mechanical evidence and invalidation rules;
- full-deck Office review remains mandatory and may revoke sample approval.

This is a control/evidence guarantee, not a guarantee of universal visual taste or reviewer infallibility.

## 5. What remains unconfirmed

No production code, Schema, Gate, service, renderer or Skill behavior was changed in this design/audit task. Therefore the following remain open implementation evidence, not design findings:

1. negative controls and schema migrations;
2. semantic planning preview quality;
3. closed Artifact Tool grammar and consumption traces;
4. Session calibration lifecycle and render admission;
5. Office reviewer input and immutable finding behavior;
6. historical regression matrix and genuine post-freeze holdout;
7. real PowerPoint first-pass and whole-deck quality results.

## 6. Final decision

- Architecture/design: **ACCEPT FOR IMPLEMENTATION**.
- Known open Critical/Major design findings: **0 / 0**.
- Production capability: **UNPROVEN**.
- Release: **DO NOT RELEASE**.
- Next action: execute Batch 0 of the accepted plan before changing behavior.

## 7. Post-audit implementation addendum

The statements above describe the frozen design-audit point. The accepted design has since been implemented on `codex/issue3-visual-repair-trial`; see `audit/designed-create-quality-implementation-report.md` for the code/schema/workflow evidence and the remaining Batch 4 boundary. The release decision remains **DO NOT RELEASE** until the historical matrix and genuine holdout have current real Microsoft PowerPoint evidence.
