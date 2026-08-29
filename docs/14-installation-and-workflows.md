# Installation and Product Workflows

## 1. Install the Python package

Slidethus requires Python 3.11 or newer. The M6 release baseline is Python 3.11.

```bash
python -m pip install slidethus
slidethus --version
slidethus doctor
```

A wheel install includes:

- Python runtime and packaged schemas;
- the canonical Slidethus Skill/workflow tree under the environment `share/slidethus/skill`;
- the renderer source/lock under `share/slidethus/renderer`.

## 2. Install the Skill into a host workspace

```bash
slidethus plugin install-skill /path/to/host-workspace
```

This creates:

```text
/path/to/host-workspace/.agents/skills/slidethus/
```

Existing byte-identical files are reused. Modified or structurally different files are never silently overwritten.

## 3. Prepare the Production renderer

Production M4 rendering requires Node.js >=20 and npm >=9. M6 release verification uses Node 22 / npm 10.

```bash
slidethus plugin bootstrap-renderer
slidethus plugin status
```

Bootstrap installs exact locked renderer dependencies into the managed user cache. Rendering never runs `npm install` implicitly.

The renderer can also be supplied explicitly with `--renderer-root` or `SLIDETHUS_PPTXGENJS_ROOT`.

## 4. Product workflows

The six product workflows use one `WorkflowApplicationService` and immutable workflow/operation/event facts. They reuse M2–M5 instead of creating a second state machine.

### Create

Creates a new workspace from topic/material sources. The complete Production path needs semantic and visual review providers before it can claim G8.

See `examples/workflows/README.md` for the full command.

### Rebuild

Reconstructs a new workspace from an existing PPTX/PDF/image reference. Original source bytes are preserved read-only.

### Improve

Audits first. Repair is limited to existing admitted repair capabilities. Unsupported content/aesthetic judgment remains assisted/manual.

### Audit

Runs review without hidden semantic/render edits. `--no-auto-repair` is the normal audit policy.

### Revise

Accepts structured updates keyed by stable `S-*` IDs, versions the Outline through its existing Change service, regenerates dependencies, rerenders and re-runs review regression.

### Extract Style

Extracts a Visual System candidate from a PPTX reference. It records reusable visual tokens and provenance but does not copy font or media bytes.

## 5. Provider boundaries

The core package deliberately does not bundle production Research/SemanticReview/VisualReview providers. Python hosts inject provider implementations through the existing protocols.

CLI-only workflows that reach a missing provider stop at an explicit capability boundary; they do not fabricate review results or G8.

## 6. Operational controls

Each workflow attempt is protected by:

- an exclusive workspace lease;
- immutable started/terminal events;
- cache currentness + TTL policy;
- file + structured-request byte budgets;
- target slide-update budget;
- wall-time budget;
- optional host-measured provider-cost budget;
- tamper-evident Workflow Application/Operation/Event facts.

## 7. Plugin bundle

Build a deterministic transport bundle:

```bash
slidethus plugin build dist/slidethus-plugin.zip
```

The bundle contains the Skill, schemas, renderer source and a schema-valid file-hash manifest. It does not include downloaded `node_modules`, model binaries, fonts or third-party user assets.
