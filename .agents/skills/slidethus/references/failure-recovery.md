# Failure Recovery

## Triage

1. Identify the failing artifact, slide, block, region, or output.
2. Locate the earliest phase that created the defect.
3. Invalidate only dependent downstream artifacts.
4. Repair the root artifact.
5. Rerun local checks.
6. Rerender affected pages.
7. Run cross-deck regression.

## Do not

- shrink all text to hide overload;
- add a note that contradicts the slide;
- duplicate facts to compensate for weak narrative;
- patch renderer coordinates when the layout plan is wrong;
- rewrite source-preserved prompts;
- advance state after a failed gate.

## Interrupted execution

Run `slidethus artifact recover <workspace>` before resuming. The runtime confirms a fully written and valid journal or restores every file to its pre-transaction value. Then resume from the latest Gate whose artifact versions still match the registry.

Use `slidethus artifact validate <workspace>` after recovery. A version/hash conflict means a human or concurrent process changed the artifact; preserve that edit and reconcile it explicitly instead of using `--force`.
