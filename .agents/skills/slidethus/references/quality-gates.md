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
- intended-change vs actual-change regression
