# ADR-0023｜Plugin and Renderer Distribution Boundary

- Status: Accepted
- Date: 2026-08-29

## Context

M6.1–M6.2 established the product workflow and operational control boundaries, but the repository checkout was still implicitly required for two critical resources:

- the canonical Slidethus Skill/workflow tree under `.agents/skills/slidethus/`;
- the PptxGenJS/preview Node sidecar under `renderers/pptxgenjs/`.

A production distribution must work after a clean Python wheel install, avoid maintaining duplicate Skill/renderer source trees, and install Node dependencies explicitly rather than during rendering.

## Decision

### 1. Canonical repository files remain the only authoring source

Slidethus does not create a second maintained copy of Skill/workflow markdown or renderer source inside the Python package source tree.

`setuptools.data-files` installs the canonical files into:

```text
share/slidethus/skill/
share/slidethus/renderer/
```

The normal repository checkout remains preferred while developing; installed-mode discovery uses the share tree when no repository root exists.

### 2. Plugin bundles are deterministic, schema-backed release artifacts

`slidethus plugin build` creates a deterministic ZIP containing:

- `.agents/skills/slidethus/**`;
- all packaged runtime schemas;
- runtime renderer source (`README.md`, package manifests, `render.mjs`, `preview.mjs`);
- `plugin-manifest.json`.

The Plugin Manifest has stable `PLG-*` identity, exact file hashes, Python/Node requirements and renderer source/lock hashes. Bundle entry ordering, timestamps and file modes are fixed; ZIP uses stored entries to reduce platform/zlib reproducibility drift.

A different existing output file is never silently overwritten.

### 3. Skill materialization is explicit and non-destructive

`slidethus plugin install-skill <host-root>` materializes the canonical Skill tree to:

```text
<host-root>/.agents/skills/slidethus/
```

The action is idempotent when bytes match and refuses to overwrite a modified or structurally different existing tree.

### 4. Renderer dependency installation is an explicit bootstrap operation

Rendering does not run `npm install` or `npm ci` implicitly.

`slidethus plugin bootstrap-renderer`:

1. resolves canonical/installed renderer source;
2. verifies exact direct dependency pins and package-lock root pins;
3. verifies Node >=20 and npm >=9;
4. creates a content-addressed user-cache root from the complete renderer source digest;
5. removes any prior dependency tree for that cache identity;
6. runs `npm ci --omit=dev --ignore-scripts --no-audit --no-fund`;
7. validates required direct dependency versions;
8. records a byte-level dependency-tree digest manifest;
9. re-verifies the prepared cache before returning success.

### 5. Prepared renderer cache is tamper-evident

A prepared renderer is reusable only when:

- every canonical renderer source file remains byte-identical;
- source and lock digests match;
- direct dependency versions match;
- the complete installed dependency tree matches the post-bootstrap digest/count manifest.

Normal npm-created relative symlinks are permitted only when they resolve inside `node_modules`; absolute or escaping symlinks fail closed.

If the dependency tree drifts, a subsequent bootstrap performs a clean dependency reinstall instead of trusting the modified cache.

### 6. Renderer resolution prefers the managed prepared cache

Absent an explicit renderer path or environment override, runtime resolution is:

```text
managed prepared cache
→ repository renderer source
→ installed share/slidethus/renderer source
```

An unprepared source tree is still discoverable, but render validation truthfully reports missing dependencies and instructs the user to run the explicit bootstrap command.

## Consequences

- A clean wheel install carries the Skill and renderer source without repository access.
- Renderer dependencies stay outside the wheel and are installed under an explicit user-controlled bootstrap step.
- Plugin/renderer release artifacts are reproducible and hash-verifiable.
- Local cache tampering does not silently become a trusted renderer runtime.
- M6.5 still owns final project licensing, NOTICE/SBOM and third-party redistribution policy; M6.3 only establishes the technical distribution boundary.
