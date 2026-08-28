from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from slidethus.constants import find_repository_root
from slidethus.errors import RenderCapabilityError
from slidethus.io_utils import read_json


def renderer_root(explicit: Path | None = None) -> Path:
    """Resolve the PptxGenJS/preview sidecar root."""

    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get("SLIDETHUS_PPTXGENJS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return find_repository_root() / "renderers/pptxgenjs"


def node_executable(explicit: str | None = None) -> str:
    """Resolve and version-check an admitted Node.js executable."""

    value = explicit or os.environ.get("SLIDETHUS_NODE") or shutil.which("node")
    if not value:
        raise RenderCapabilityError("Node renderer requires Node.js 20 or newer")
    process = subprocess.run(
        [value, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if process.returncode != 0:
        raise RenderCapabilityError("Node.js version check failed")
    match = re.search(r"v(\d+)", process.stdout.strip())
    if match is None or int(match.group(1)) < 20:
        raise RenderCapabilityError(
            f"Node renderer requires Node.js >=20, got {process.stdout.strip()}"
        )
    return value


def validate_sidecar(
    root: Path,
    *,
    script_name: str,
    dependencies: dict[str, str],
) -> Path:
    """Validate one sidecar script and its exact direct dependency versions."""

    script = root / script_name
    if not script.is_file():
        raise RenderCapabilityError(f"Node sidecar script is missing: {script}")
    for package_name, expected_version in dependencies.items():
        package_path = root / "node_modules" / package_name / "package.json"
        if not package_path.is_file():
            raise RenderCapabilityError(
                "Node renderer dependencies are not installed. Run "
                f"`npm ci --prefix {root}` before rendering."
            )
        package = read_json(package_path)
        if package.get("version") != expected_version:
            raise RenderCapabilityError(
                f"Node renderer requires {package_name}@{expected_version}, "
                f"got {package.get('version')}"
            )
    return script
