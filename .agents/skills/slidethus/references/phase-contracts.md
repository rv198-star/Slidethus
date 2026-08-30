# Phase Contracts

| Phase | Required input | Required output | Pass condition |
|---|---|---|---|
| P0 | user request/material hints; bounded orientation scan when permitted | Project Brief | purpose/audience/outcome/constraints known; no blocking question |
| P1 | files/links/deck/orientation sources | Source Ledger | all intended sources inventoried and readable or explicitly unavailable |
| P2 | sources/research; brief needs; post-outline page needs | Evidence Ledger | orientation baseline exists; used factual claims are supported; conflicts surfaced; page-level evidence gaps are resolved before P5A |
| P3 | brief/evidence | Narrative Blueprint | thesis, arc, sections, objections, transitions coherent |
| P4 | narrative/evidence | Deck Outline | stable slide IDs, page target, unique messages, no major repetition |
| P5A | outline/evidence | Slide Specs | one spec per slide; blocks and evidence complete |
| P5B | slide specs | Layout Plans/wireframes | every block mapped; readable geometry; layout rationale |
| P6 | brief/layout/assets/brand refs | immutable Art Direction Packet + Visual System | Packet hash/provider/input lineage valid; tokens and diversity/forbidden rules complete |
| P7 | specs/layout/visual/assets | rendered draft/manifest | file valid; preview generated; warnings recorded; actual editability measured |
| P8 | draft/all artifacts | Quality Report/repair plan | Critical=0, Major=0, regression pass |
| P9 | approved versions | Delivery Manifest | requested formats, hashes, limitations, target and actual editability declared |

## Two-pass research contract

P2 is one evidence domain with two execution passes, not two independent truth stores:

1. The **orientation pass** may begin before or during P0/P1 so questions and narrative choices reflect the supplied material and current context.
2. The **targeted pass** runs after P4 because only the outline reveals the exact page-level evidence burden.
3. If the targeted pass adds, removes, disputes, or materially changes evidence, transition `OUTLINE_READY → EVIDENCE_READY`, update the ledger, and revalidate P3/P4 before P5A.
4. Record both passes in one Evidence Ledger using stable evidence IDs and `research_cycles`; M2 should add query/task lineage, caching, and invalidation.

A failed gate does not advance project state. Return to the earliest responsible phase.
