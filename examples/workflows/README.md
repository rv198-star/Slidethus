# Product Workflow Examples

These examples mirror the six M6 product workflows. The executable expectations live in `evals/m6/suite.json`; this directory provides user-facing inputs and invocation patterns.

## Create

```bash
slidethus workflow run create /tmp/slidethus-create \
  --source examples/workflows/create/source.md \
  --title "Enterprise Agent Operating Model" \
  --purpose "Present the enterprise agent operating model" \
  --desired-outcome "Approve implementation" \
  --call-to-action "Approve project initiation" \
  --delivery-context "Management decision meeting" \
  --audience-role "Executive management" \
  --page-target 8
```

The CLI intentionally does not bundle semantic/visual review providers. Without host-injected review providers, Create stops truthfully at the M5 capability boundary rather than claiming G8.

## Rebuild

Use a PPTX/PDF/image reference as `--source` and a new workspace path. Rebuild never overwrites the original file. The production evaluation generates a small PPTX fixture and verifies byte-identical preservation.

## Audit

```bash
slidethus workflow run audit <reviewed-workspace> --title "Deck Audit" --no-auto-repair
```

Audit may add immutable review/operational facts but must not silently modify frozen semantic/render truth.

## Improve

```bash
slidethus workflow run improve <reviewed-workspace> --title "Deck Improve"
```

Improve audits first, then uses only admitted M5 repair paths. Unsupported semantic/aesthetic repairs remain explicit assisted/manual work.

## Revise

Create a JSON object keyed by stable slide ID:

```json
{
  "S-001": {
    "headline": "Revised enterprise agent operating model"
  }
}
```

Then run:

```bash
slidethus workflow run revise <workspace> \
  --slide-updates-json /path/to/revision.json \
  --reason "Clarify the opening proposition"
```

Revise keeps stable IDs/history and regenerates dependent artifacts before review regression.

## Extract Style

```bash
slidethus workflow run extract_style /tmp/slidethus-style \
  --source /path/to/reference.pptx \
  --title "Reference Style"
```

The output is a Visual System candidate. It records token/provenance facts and does not copy font or media bytes from the reference deck.

## Evaluation tiers

```bash
python scripts/run_m6_evals.py --tier quick
python scripts/run_m6_evals.py --tier production
```

`quick` validates the complete six-workflow corpus/compatibility contracts and executes only offline-fast cases. `production` executes the real workflow selectors and requires the Production renderer/review test capabilities.
