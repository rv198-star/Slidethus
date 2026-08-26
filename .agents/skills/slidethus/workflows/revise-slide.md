# Revise Slide Workflow

## Trigger

Modify specific slide IDs or respond to targeted feedback.

## Steps

1. Resolve target slide IDs and protected content.
2. Trace upstream evidence/spec/layout/style dependencies.
3. Determine the earliest affected phase.
4. Create new artifact versions; do not mutate frozen history.
5. Rerender only affected pages where possible.
6. Run local checks and whole-deck consistency regression.
7. Report changed slides, unchanged slides, and any propagated changes.
