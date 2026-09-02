"""Optional host-provided Artifact Tool adapter. No installation or silent fallback."""

from __future__ import annotations

import copy
import re
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from jsonschema import Draft202012Validator

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.errors import RenderAttemptError, RenderBackendError
from slidethus.io_utils import (
    atomic_create_json,
    atomic_write_json,
    read_json,
    sha256_file,
)
from slidethus.render_backends.artifact_tool_runtime import (
    ArtifactToolRuntime,
    resolve_artifact_tool_runtime,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.render_preflight import RenderPreflightResult


def _bounded_diagnostic(value: str | bytes | None, redactions: dict[str, str]) -> str:
    """Return a bounded diagnostic without persisting admitted runtime paths."""

    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    for sensitive, replacement in sorted(
        redactions.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if sensitive:
            text = text.replace(sensitive, replacement)
    return text[-4000:]


class ArtifactToolRenderBackend:
    """Render a selection of one current IR; selections never re-plan the deck."""

    name = "artifact-tool"

    def __init__(self, *, node: str | None = None, modules: Path | None = None) -> None:
        self.node = node
        self.modules = modules

    def _runtime(self) -> ArtifactToolRuntime:
        return resolve_artifact_tool_runtime(node=self.node, modules=self.modules)

    def check_available(self) -> dict[str, str]:
        """Resolve the same host runtime used by preflight and rendering."""

        runtime = self._runtime()
        return {"name": self.name, "version": runtime.version}

    @staticmethod
    def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
        schema = read_json(
            SchemaRegistry().schema_dir / "host_candidate_receipt.schema.json"
        )
        Draft202012Validator(schema).validate(receipt)
        atomic_write_json(path, receipt)

    @staticmethod
    def _terminal_receipt(
        receipt: dict[str, Any],
        *,
        started: float,
        status: str,
        stage: str,
        exit_code: int | None,
        timed_out: bool,
        stdout: str,
        stderr: str,
        error: str | None,
        outputs: tuple[Path, ...] = (),
    ) -> dict[str, Any]:
        terminal = copy.deepcopy(receipt)
        terminal["status"] = status
        terminal["outputs"] = [
            {"path": str(path), "sha256": sha256_file(path)}
            for path in outputs
        ]
        terminal["office_review"] = (
            "pending"
            if status == "candidate_office_review_pending"
            else "not_started"
        )
        terminal["diagnostics"] = {
            "stage": stage,
            "started_at": receipt["diagnostics"]["started_at"],
            "finished_at": utc_now(),
            "duration_seconds": round(max(0.0, time.monotonic() - started), 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
        }
        return terminal

    def render(
        self,
        workspace: Path,
        preflight: RenderPreflightResult,
        *,
        slide_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Write a unique candidate plus a terminal receipt for every started attempt."""

        runtime_config = self._runtime()
        identity = {"name": self.name, "version": runtime_config.version}
        if preflight.report["status"] != "pass" or preflight.report["backends"] != [self.name]:
            raise RenderBackendError("Artifact Tool requires its own passing current preflight")
        ir = preflight.compiled.ir
        try:
            snapshots_match = (
                read_json(preflight.compiled.path) == ir
                and read_json(preflight.path) == preflight.report
            )
        except (OSError, ValueError) as exc:
            raise RenderBackendError(f"Cannot read admitted render snapshots: {exc}") from exc
        if not snapshots_match:
            raise RenderBackendError("Render inputs differ from their admitted snapshots")
        active = [page["slide_id"] for page in ir["slides"]]
        selected = list(slide_ids) if slide_ids else active
        if not selected or len(selected) != len(set(selected)) or not set(selected).issubset(active):
            raise RenderBackendError("Unknown, duplicate or empty slide selection")
        selected = [slide_id for slide_id in active if slide_id in selected]
        artifact_runtime = ArtifactRuntime(workspace)
        current = {
            artifact["artifact_type"]: artifact
            for artifact in artifact_runtime.list_artifacts()
        }
        for reference in ir["input_artifacts"]:
            entry = current[reference["artifact_type"]]
            if any(
                entry[key] != reference[key]
                for key in ("version", "content_hash")
            ):
                raise RenderBackendError(
                    "Preflight IR is stale; compile again before rendering"
                )

        root = workspace / "outputs/host-candidates"
        root.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="candidate-", dir=root))
        payload = output / "input.json"
        receipt_path = output / "receipt.json"
        started = time.monotonic()
        receipt: dict[str, Any] = {
            "schema_version": "0.2.0",
            "attempt_id": "HCA-" + uuid.uuid4().hex[:16].upper(),
            "status": "render_started",
            "scope": "full" if selected == active else "sample",
            "slide_ids": selected,
            "renderer": {
                **identity,
                "adapter_sha256": sha256_file(runtime_config.script),
            },
            "artifacts": copy.deepcopy(ir["input_artifacts"]),
            "renderer_ir": {
                "path": str(preflight.compiled.path),
                "sha256": sha256_file(preflight.compiled.path),
            },
            "preflight": {
                "path": str(preflight.path),
                "sha256": sha256_file(preflight.path),
            },
            "input": None,
            "outputs": [],
            "office_review": "not_started",
            "release_approved": False,
            "diagnostics": {
                "stage": "prepared",
                "started_at": utc_now(),
                "finished_at": None,
                "duration_seconds": None,
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": "",
                "error": None,
            },
        }
        self._write_receipt(receipt_path, receipt)
        redactions = {
            str(workspace.resolve()): "<workspace>",
            str(output.resolve()): "<candidate>",
            str(runtime_config.modules): "<node_modules>",
            str(runtime_config.node): "<node>",
            str(runtime_config.script): "<adapter>",
        }
        stage = "input"
        exit_code: int | None = None
        stdout = ""
        stderr = ""
        try:
            claims = {
                claim["evidence_id"]: claim
                for claim in artifact_runtime.show_artifact("evidence_ledger")["claims"]
            }
            notes: dict[str, str] = {}
            for page in ir["slides"]:
                evidence_ids = sorted(
                    {
                        evidence_id
                        for region in page["regions"]
                        for evidence_id in region["evidence_ids"]
                    }
                )
                note_lines = ["[Sources]"]
                for evidence_id in evidence_ids:
                    note_lines.append(f"{evidence_id}: {claims[evidence_id]}")
                for asset_id in sorted(
                    {
                        asset_id
                        for region in page["regions"]
                        for asset_id in region["asset_refs"]
                    }
                ):
                    asset = preflight.assets[asset_id]
                    if (
                        sha256_file(asset.path)
                        != asset.content_hash.removeprefix("sha256:")
                    ):
                        raise RenderBackendError(
                            f"Asset changed after preflight: {asset_id}"
                        )
                    note_lines.append(
                        f"{asset_id}: {asset.attribution or asset.path.name}"
                    )
                notes[page["slide_id"]] = "\n".join(note_lines)
            atomic_create_json(
                payload,
                {
                    "ir": ir,
                    "assets": {
                        key: value.as_sidecar_value()
                        for key, value in preflight.assets.items()
                    },
                    "slide_ids": selected,
                    "notes": notes,
                },
            )
            receipt["input"] = {
                "path": str(payload),
                "sha256": sha256_file(payload),
            }
            receipt["diagnostics"]["stage"] = "adapter"
            self._write_receipt(receipt_path, receipt)
            stage = "adapter"
            result = subprocess.run(
                [
                    runtime_config.node,
                    str(runtime_config.script),
                    str(payload),
                    str(output),
                    str(runtime_config.modules),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            exit_code = result.returncode
            stdout = _bounded_diagnostic(result.stdout, redactions)
            stderr = _bounded_diagnostic(result.stderr, redactions)
            if result.returncode:
                raise RenderBackendError(
                    "Artifact Tool failed: "
                    + (stderr or stdout or str(result.returncode))
                )

            stage = "integrity"
            pptx = output / "candidate.pptx"
            with zipfile.ZipFile(pptx) as archive:
                if archive.testzip():
                    raise RenderBackendError("PPTX archive integrity failure")
                members = archive.namelist()
                slides = [
                    name
                    for name in members
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
                ]
                if len(slides) != len(selected):
                    raise RenderBackendError("PPTX slide coverage mismatch")
                for name in members:
                    if name.endswith((".xml", ".rels")):
                        ET.fromstring(archive.read(name))

            stage = "outputs"
            files = [
                pptx,
                *[output / f"{slide_id}.png" for slide_id in selected],
                *[
                    output / f"{slide_id}.layout.json"
                    for slide_id in selected
                ],
            ]
            if any(
                not file.is_file() or file.stat().st_size == 0
                for file in files
            ):
                raise RenderBackendError(
                    "Artifact Tool omitted required candidate/preview outputs"
                )
        except subprocess.TimeoutExpired as exc:
            terminal = self._terminal_receipt(
                receipt,
                started=started,
                status="render_timed_out",
                stage=stage,
                exit_code=None,
                timed_out=True,
                stdout=_bounded_diagnostic(exc.stdout, redactions),
                stderr=_bounded_diagnostic(exc.stderr, redactions),
                error="Artifact Tool timed out after 300 seconds.",
            )
            self._write_receipt(receipt_path, terminal)
            raise RenderAttemptError(
                str(terminal["diagnostics"]["error"]),
                receipt_path=str(receipt_path),
            ) from exc
        except Exception as exc:
            error = _bounded_diagnostic(str(exc), redactions) or type(exc).__name__
            terminal = self._terminal_receipt(
                receipt,
                started=started,
                status="render_failed",
                stage=stage,
                exit_code=exit_code,
                timed_out=False,
                stdout=stdout,
                stderr=stderr,
                error=error,
            )
            self._write_receipt(receipt_path, terminal)
            raise RenderAttemptError(
                error,
                receipt_path=str(receipt_path),
            ) from exc

        terminal = self._terminal_receipt(
            receipt,
            started=started,
            status="candidate_office_review_pending",
            stage="complete",
            exit_code=exit_code,
            timed_out=False,
            stdout=stdout,
            stderr=stderr,
            error=None,
            outputs=tuple(files),
        )
        self._write_receipt(receipt_path, terminal)
        return {**terminal, "receipt_path": str(receipt_path)}
