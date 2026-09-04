# Quality Gates

## Review order

1. Deterministic validation
2. Open issue mining without scores
3. Fix Critical and Major issues
4. Local retest
5. Cross-deck regression
6. Dimension scorecard
7. Gate decision

## Severity

- Critical: factual harm, unusable file, missing core content, severe render/security/rights issue
- Major: broken narrative, unreadable slide, unsupported key claim, major inconsistency, false editability promise
- Minor: localized polish issue
- Suggestion: optional improvement

## Delivery rule

- Critical = 0
- Major = 0 unless the user explicitly accepts a documented waiver
- factual integrity, narrative, readability, and export dimensions should score at least 4/5
- every other dimension should score at least 3/5
- scores never override severity

## Key deterministic checks

- schema and cross refs
- source/evidence status
- unique slide/block/region IDs
- page count and layout coverage
- overflow/collision/safe area
- font and asset availability
- output/preview page count
- render input hashes
- Art Direction Packet schema/hash/provider/input lineage and bundled-provider provenance
- exact-Brief VisualAdmissionPolicy and fixed independent reviewer capability
- representation/view ownership, semantic preview hashes and qualitative planning decision
- closed P6 grammar, producer capability and Renderer IR consumption trace
- sample/full exact IR/producer/dependency identity and shared full-render authorization
- immutable same-page finding history and adjudication
- real PowerPoint application/build/profile/page hashes for calibration and whole-deck review
- intended-change vs actual-change regression

Artifact Tool previews, successful export, object counts, a `Taste-generated` label or an attractive cover are not visual approval. Reviewed/critical full render requires current representative Office calibration; delivery requires current whole-deck Office decision.
