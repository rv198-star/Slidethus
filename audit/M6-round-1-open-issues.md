# M6 Round A — Open Issue Mining

Date: 2026-08-30

## Scope

Repository-wide M6 Exit review after M6.1–M6.5 freeze and the Round 4–6 Preview Hardening sequence. This review does not reopen frozen M2–M5 contracts and does not treat aesthetic preferences as release blockers.

## Closed Critical and Major systemic issues

The Preview sequence identified and root-fixed these framework-level patterns:

1. P7 font fallback admitted a family match without proving required glyph coverage.
2. P7 process/timeline decorations ignored approved dynamic layout geometry.
3. P4 content headlines stopped at source-clause selection rather than page propositions.
4. P4 structural slides serialized orchestration meta-copy as visible content.
5. P5A action blocks repeated the primary decision instead of assigning distinct responsibilities.
6. P4 headline synthesis could expose ellipsis-truncated fragments rather than closed propositions.
7. P5A/P5B lacked one deterministic text-capacity contract shared with render preflight.

Each fix is owned by the responsible phase, uses an unrelated regression fixture, and avoids case/page/title/language special cases. Round 6 retrospective synthesis `SYN-E17A689D3096E148` found no open Critical or Major systemic candidate.

## Remaining non-blockers

- Major, case-local: the frozen Brief intentionally uses `V1 Preview Trial` as its audience-facing title. The renderer correctly preserves that admitted input. This is not promoted into Production logic.
- Minor, systemic candidate but not promotion-eligible: mixed Chinese/Latin wrapping can split an ordinary Latin token between characters. Content remains readable and unclipped; recurrence evidence does not justify another hardening batch.
- Capability boundary: the standalone Preview has no configured `SemanticReviewProvider`, so M5/G8 blocks explicitly after real M4 outputs rather than fabricating semantic review.

## Release-tooling issue found and fixed

The first M6 Exit run assumed the formal Python environment contained `pip`. The Python 3.11 release environment intentionally did not. The wheel reproducibility check now selects an available PEP 517 build frontend (`pip` when present, otherwise `uv`) and retains a fixed `SOURCE_DATE_EPOCH`.

## Round A decision

No open Critical or Major systemic issue remains. Proceed to Round B on the exact Python 3.11 + Node 22 baseline, including all frozen milestone validators, reproducible Plugin/wheel builds, full tests, schema/package validation, rights/SBOM audit, and Git diff review.
