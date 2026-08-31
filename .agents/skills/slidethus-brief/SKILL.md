---
name: slidethus-brief
description: Define or clarify a presentation Project Brief, audience, purpose, delivery context, constraints, assumptions and approval mode before production. Use for PPT requirements/intake only or as Slidethus P0; not for research, page design or rendering. Use using-slidethus for a complete deck request.
---

# Slidethus Brief — P0

Read the [shared contract](../slidethus/references/shared-contract.md), [artifact map](../slidethus/references/artifact-map.md) and [capability matrix](../slidethus/references/capability-matrix.md).

## Input and scope

User objective/materials, existing Brief if any, available host tools. Direct invocation produces a Brief, not a deck. When invoked by the entry skill, return the admitted Brief and continue through that orchestrator.

## Work

1. Inspect supplied materials first. If permitted, make a bounded orientation scan to understand the topic and likely evidence gaps; this is context, not a completed Research/Evidence stage.
2. Resolve purpose, audience knowledge, desired action, live presentation versus read-ahead use, time/page limits, language, target formats/editability, source/freshness policy, brand references and approval mode.
3. Distinguish communication purpose from visual treatment. “External showcase” specifies attention/communication needs, not a technology palette. Record explicit visual preferences without turning one example into an industry default.
4. Ask only materially consequential questions. Infer safe defaults and record assumptions; do not create a questionnaire for facts already known. Carry an existing user-approved Brief forward unless the request changes it.
5. Check parsing, current research, asset creation, script execution, target renderer and actual Office inspection capabilities. Record blocked/degraded work truthfully; no one-shot promise overrides a missing required capability.
6. Persist Project Brief and approval/assumption facts using the existing runtime and schema. For host Create, read the [host entry](../slidethus/references/host-create.md); resolve pending Brief questions with `slidethus m3 answer <workspace> <Q-id> "<answer>"` and resume. Do not fabricate Gate status.

For a newly initialized one-shot workspace, the scaffold defaults to `checkpoint`. Persist the intended `auto` mode through the existing Brief service before planning; do not leave it only in chat, invent a `create --approval-mode` flag, or run the deterministic M3 planner merely to set the Brief:

```python
from pathlib import Path
from slidethus.protocols import BriefCompletionHints
from slidethus.services.brief_completion import BriefCompletionService

result = BriefCompletionService(Path("<workspace>")).complete(
    BriefCompletionHints(approval_mode="auto")
)
```

Use this only when establishing the new task's intended mode. Preserve an existing user-chosen checkpoint/strict mode. The result can still contain blocking Brief questions; an approval-mode update does not resolve them or advance planning by itself.

## Exit

Brief has an actionable objective, audience/outcome, material constraints, source policy and no unresolved blocking question. Report the Brief path, assumptions, delivery level and next prerequisite (source/evidence work). Stop here for a Brief-only request. If a required user choice is missing, ask that specific question rather than doing unrequested downstream work.
