# Quality Gates

| Gate | Phase | Pass condition |
|---|---|---|
| G0 | Brief | Purpose, outcome, audience and material constraints are resolved; no blocking question remains. |
| G1 | Sources | Required sources are inventoried, parsed or explicitly waived. |
| G2 | Evidence | Orientation research cycle is complete/waived; required claims are traceable; unsupported/disputed claims are blocked or qualified. |
| G3 | Narrative | Central thesis, audience journey, sections and objections form a coherent story. |
| G4 | Outline | Active slides have stable IDs, contiguous ordinals, distinct takeaways and evidence links. |
| G5A | Slide Specs | Targeted research is complete/waived for the current outline version; every active slide has semantic blocks, density budget and visual intent. |
| G5B | Layout | Every block is placed, reading order is complete, and regions fit the canvas. |
| G6 | Visual System | Deck-wide visual tokens, fallbacks, diversity and forbidden patterns are declared. |
| G7 | Render | Backend succeeded, outputs and previews exist, hashes/font substitutions are recorded, and actual editability is measured at or above the declared target. |
| G8 | Review | No open Critical/Major issue; deterministic and visual regression pass. |
| G9 | Delivery | Requested outputs are validated; target and actual editability are declared, the actual level meets the target, and limitations and waivers are recorded. |

A numerical average cannot override a failed Gate.

A Quality Report from an earlier planning gate cannot satisfy G8. G8 requires `gate_result.gate_id = G8`, a passing gate result, a successful render, and review evidence tied to the rendered outputs.
