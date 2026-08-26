# Developer Workflow Map

The executable Skill workflows live under `.agents/skills/slidethus/workflows/`. This directory gives repository developers a compact dependency view.

| Workflow | Entry artifact | Main mutation boundary | Required regression |
|---|---|---|---|
| Create | Project Brief | full artifact chain | all affected gates |
| Rebuild | Existing deck + Brief | reconstructed semantics onward | source/deck fidelity + all changed slides |
| Improve | Existing approved chain | earliest defective phase onward | local + cross-deck |
| Audit | Existing artifacts/renders | none unless repair is authorized | deterministic + semantic + visual |
| Revise Slide | Stable slide ID | minimal dependency closure | target slide + deck consistency |
| Extract Style | Reference deck | Visual System only | token consistency + license/provenance |

Do not duplicate workflow logic here; update the Skill workflow and the applicable phase contracts.
