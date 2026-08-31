# Create Deck Workflow

## Trigger

Create a new presentation from a topic, prompt, documents, data, images, or research.

## Steps

Use `references/host-create.md` for the callable entry and response format. Execute host reasoning yourself; code must not invent a proposal when the host has not supplied one.

1. Check host capabilities and select a declared delivery level.
2. Inspect supplied materials and, when permitted, run a bounded orientation scan before asking questions.
3. Initialize the workspace and complete the Project Brief using only material questions.
4. Inventory, parse, and classify all sources.
5. Build the orientation evidence baseline; research only where policy permits.
6. Create the Narrative Blueprint.
7. Create the Deck Outline as stable digital-sticky-note slide objects.
8. Run targeted page-level evidence completion against the outline. If evidence changes materially, return to P2 and revalidate Narrative and Outline before proceeding.
9. Propose Slide Specs. Consider text, image, numerical chart, table and diagram on their communication merits. Plan needed media slots, aspect ratios and evidence/data before creating assets. No image/chart quota, automatic technology style or industry-specific template.
10. Propose explicit Layout Plans and wireframes; checkpoint when required. Check host requests after each resume because admitted stable IDs may differ from a proposal's ordering.
11. Read the bundled Taste resource. When establishing a new art direction, use it to drive an isolated native visual prototype (such as HTML/CSS with real assets), inspect it, and obtain the required approval. The lab is not gate evidence. Translate the approved direction into Layout/Visual System, including every page's actual appearance, imagery and composition; do not just copy palette words. Only an actual native prototype may be called Taste-generated. If a required capability is absent, pause and report it.
12. Use `slidethus create ... --render` for both sample and full candidates. `--slide-id` selects from the same complete IR, not an independent sample script. Inspect the exported PPTX in PowerPoint; Artifact Tool PNG/layout outputs are debugging previews, not Office approval. The current host entry stops at a candidate receipt, with release integration/visual acceptance pending.
13. When acceptance work is in scope, run deterministic checks, open issue mining, targeted repair, regression, and scorecard review. If the user defers Office/case acceptance, stop at the candidate and report the pending work.
14. Create the Delivery Manifest and deliver only after the required gates and real Office review pass. A host candidate receipt alone does not authorize this step.

## Hard gates

No final rendering before Brief, Evidence, Outline, Slide Specs, and Layout gates pass. No Slide Specs before the outline-driven targeted evidence pass is complete or explicitly waived.
