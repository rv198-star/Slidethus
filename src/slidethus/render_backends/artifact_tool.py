"""Optional host-provided Artifact Tool adapter. No installation or silent fallback."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from jsonschema import Draft202012Validator

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.distribution import skill_source_root
from slidethus.errors import RenderBackendError, RenderCapabilityError
from slidethus.io_utils import atomic_create_json, read_json, sha256_file
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.render_preflight import RenderPreflightResult


class ArtifactToolRenderBackend:
    """Render a selection of one current IR; selections never re-plan the deck."""

    name = "artifact-tool"

    def __init__(self, *, node: str | None = None, modules: Path | None = None) -> None:
        self.node = node or os.environ.get("RUNTIME_NODE")
        self.modules = modules or (
            Path(os.environ["RUNTIME_NODE_MODULES"]) if os.environ.get("RUNTIME_NODE_MODULES") else None
        )
        self.script = skill_source_root() / "scripts/render_artifact.mjs"

    def check_available(self) -> dict[str, str]:
        """Resolve only the explicitly supplied host runtime, without mutating it."""

        if not self.node or not Path(self.node).is_file() or self.modules is None:
            raise RenderCapabilityError("Artifact Tool requires host RUNTIME_NODE and RUNTIME_NODE_MODULES")
        package = self.modules / "@oai/artifact-tool/package.json"
        if not package.is_file() or not self.script.is_file():
            raise RenderCapabilityError("Host Artifact Tool package or Slidethus adapter is missing")
        return {"name": self.name, "version": str(read_json(package)["version"])}

    def render(
        self, workspace: Path, preflight: RenderPreflightResult, *, slide_ids: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        """Write a uniquely located candidate and receipt, never a delivery approval."""

        identity = self.check_available()
        if preflight.report["status"] != "pass" or preflight.report["backends"] != [self.name]:
            raise RenderBackendError("Artifact Tool requires its own passing current preflight")
        ir = preflight.compiled.ir
        try:
            snapshots_match = read_json(preflight.compiled.path) == ir and read_json(preflight.path) == preflight.report
        except (OSError, ValueError) as exc:
            raise RenderBackendError(f"Cannot read admitted render snapshots: {exc}") from exc
        if not snapshots_match:
            raise RenderBackendError("Render inputs differ from their admitted snapshots")
        active = [p["slide_id"] for p in ir["slides"]]
        selected = list(slide_ids) if slide_ids else active
        if not selected or len(selected) != len(set(selected)) or not set(selected).issubset(active):
            raise RenderBackendError("Unknown, duplicate or empty slide selection")
        # Preserve deck order and original slide identity for a sample.
        selected = [s for s in active if s in selected]
        runtime = ArtifactRuntime(workspace)
        current = {a["artifact_type"]: a for a in runtime.list_artifacts()}
        for ref in ir["input_artifacts"]:
            entry = current[ref["artifact_type"]]
            if any(entry[key] != ref[key] for key in ("version", "content_hash")):
                raise RenderBackendError("Preflight IR is stale; compile again before rendering")
        claims = {c["evidence_id"]: c for c in runtime.show_artifact("evidence_ledger")["claims"]}
        notes = {}
        for page in ir["slides"]:
            evidence_ids = sorted({e for r in page["regions"] for e in r["evidence_ids"]})
            note_lines = ["[Sources]"]
            for eid in evidence_ids:
                note_lines.append(f"{eid}: {claims[eid]}")
            for aid in sorted({a for r in page["regions"] for a in r["asset_refs"]}):
                asset = preflight.assets[aid]
                if sha256_file(asset.path) != asset.content_hash.removeprefix("sha256:"):
                    raise RenderBackendError(f"Asset changed after preflight: {aid}")
                note_lines.append(f"{aid}: {asset.attribution or asset.path.name}")
            notes[page["slide_id"]] = "\n".join(note_lines)
        root = workspace / "outputs/host-candidates"
        root.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="candidate-", dir=root))
        payload = output / "input.json"
        atomic_create_json(payload, {
            "ir": ir,
            "assets": {key: value.as_sidecar_value() for key, value in preflight.assets.items()},
            "slide_ids": selected,
            "notes": notes,
        })
        try:
            result = subprocess.run(
                [str(self.node), str(self.script), str(payload), str(output), str(self.modules)],
                capture_output=True, text=True, timeout=300, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RenderBackendError(f"Artifact Tool invocation failed: {exc}") from exc
        if result.returncode:
            raise RenderBackendError("Artifact Tool failed: " + (result.stderr or result.stdout)[-4000:])
        pptx = output / "candidate.pptx"
        try:
            with zipfile.ZipFile(pptx) as archive:
                if archive.testzip():
                    raise RenderBackendError("PPTX archive integrity failure")
                members = archive.namelist()
                slides = [n for n in members if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
                if len(slides) != len(selected):
                    raise RenderBackendError("PPTX slide coverage mismatch")
                for name in members:
                    if name.endswith((".xml", ".rels")):
                        ET.fromstring(archive.read(name))
        except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
            raise RenderBackendError(f"Invalid candidate PPTX: {exc}") from exc
        files = [pptx, *[output / f"{s}.png" for s in selected], *[output / f"{s}.layout.json" for s in selected]]
        if any(not file.is_file() or file.stat().st_size == 0 for file in files):
            raise RenderBackendError("Artifact Tool omitted required candidate/preview outputs")
        receipt = {
            "schema_version": "0.1.0",
            "status": "candidate_office_review_pending",
            "scope": "full" if selected == active else "sample",
            "slide_ids": selected,
            "renderer": {**identity, "adapter_sha256": sha256_file(self.script)},
            "renderer_ir": {"path": str(preflight.compiled.path), "sha256": sha256_file(preflight.compiled.path)},
            "preflight": {"path": str(preflight.path), "sha256": sha256_file(preflight.path)},
            "outputs": [{"path": str(file), "sha256": sha256_file(file)} for file in files],
            "office_review": "pending",
            "release_approved": False,
        }
        schema = read_json(SchemaRegistry().schema_dir / "host_candidate_receipt.schema.json")
        Draft202012Validator(schema).validate(receipt)
        atomic_create_json(output / "receipt.json", receipt)
        return {**receipt, "receipt_path": str(output / "receipt.json")}
