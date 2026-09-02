"""Single runtime resolution contract for the optional host Artifact Tool."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from slidethus.distribution import skill_source_root
from slidethus.errors import RenderCapabilityError
from slidethus.io_utils import read_json
from slidethus.render_backends.node_toolchain import node_executable


@dataclass(frozen=True)
class ArtifactToolRuntime:
    """Resolved host-owned runtime inputs used by preflight and rendering."""

    node: str
    modules: Path
    script: Path
    version: str

    def capability_detail(self) -> str:
        """Return the exact runtime paths used by doctor, preflight, and render."""

        return (
            f"Artifact Tool {self.version}; node={self.node}; "
            f"node_modules={self.modules}"
        )


def _host_bundled_node_roots() -> tuple[Path, ...]:
    """Return conservative, read-only Codex bundled-runtime candidates."""

    roots: list[Path] = []
    cache_root = os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        roots.append(
            Path(cache_root)
            / "codex-runtimes/codex-primary-runtime/dependencies/node"
        )
    roots.append(
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    )
    return tuple(dict.fromkeys(path.expanduser() for path in roots))


def resolve_artifact_tool_runtime(
    *,
    node: str | None = None,
    modules: Path | None = None,
) -> ArtifactToolRuntime:
    """Resolve explicit arguments before host-injected runtime environment paths."""

    raw_node: str | Path | None = node or os.environ.get("RUNTIME_NODE")
    raw_modules: Path | None = modules or (
        Path(os.environ["RUNTIME_NODE_MODULES"])
        if os.environ.get("RUNTIME_NODE_MODULES")
        else None
    )
    if raw_node is None or raw_modules is None:
        for root in _host_bundled_node_roots():
            candidate_node = root / "bin/node"
            candidate_modules = root / "node_modules"
            if (
                candidate_node.is_file()
                and (
                    candidate_modules / "@oai/artifact-tool/package.json"
                ).is_file()
            ):
                raw_node = raw_node or candidate_node
                raw_modules = raw_modules or candidate_modules
                break
    if not raw_node or raw_modules is None:
        raise RenderCapabilityError(
            "Artifact Tool requires --node/--node-modules, host-provided "
            "RUNTIME_NODE/RUNTIME_NODE_MODULES, or an admitted Codex bundled runtime"
        )
    try:
        executable = node_executable(str(raw_node))
    except (RenderCapabilityError, OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RenderCapabilityError(f"Artifact Tool Node.js is unavailable: {exc}") from exc
    module_root = Path(raw_modules).expanduser().resolve()
    package = module_root / "@oai/artifact-tool/package.json"
    script = skill_source_root() / "scripts/render_artifact.mjs"
    if not module_root.is_dir():
        raise RenderCapabilityError(
            f"Artifact Tool node_modules directory is missing: {module_root}"
        )
    if not package.is_file():
        raise RenderCapabilityError(
            f"Host Artifact Tool package is missing: {package}"
        )
    if not script.is_file():
        raise RenderCapabilityError(f"Slidethus Artifact Tool adapter is missing: {script}")
    try:
        version = str(read_json(package).get("version") or "").strip()
    except (OSError, TypeError, ValueError) as exc:
        raise RenderCapabilityError(
            f"Host Artifact Tool package metadata is invalid: {package}"
        ) from exc
    if not version:
        raise RenderCapabilityError("Host Artifact Tool package has no version")
    return ArtifactToolRuntime(
        node=executable,
        modules=module_root,
        script=script,
        version=version,
    )
