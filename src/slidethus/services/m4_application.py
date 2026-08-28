from __future__ import annotations

import copy
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import ArtifactError, RenderCapabilityError, RenderingError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import atomic_create_json, read_json, sha256_file, sha256_json
from slidethus.m4_application_reports import (
    m4_finding_id,
    m4_report_file_key,
    m4_report_id,
    m4_report_reference_errors,
    validate_m4_report_data,
)
from slidethus.pptx_backend import LibreOfficeDocumentRenderer
from slidethus.protocols import RenderRequest
from slidethus.render_backends.final_svg import FinalSvgRenderBackend
from slidethus.render_backends.pptxgenjs import (
    PptxGenJSHybridRenderBackend,
    PptxGenJSNativeRenderBackend,
)
from slidethus.render_backends.svg_export import SvgPreviewExportService
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.m3_application import evaluate_m3_workspace_gate
from slidethus.services.render_manifest import ProductionRenderManifestService
from slidethus.services.render_preflight import RenderPreflightResult, RenderPreflightService
from slidethus.services.visual_system import VisualSystemService
from slidethus.state_machine import FORWARD_SEQUENCE, Phase, can_transition

_BACKENDS = ("final-svg", "pptxgenjs-hybrid", "pptxgenjs-native")


@dataclass(frozen=True)
class M4ApplicationRunResult:
    """One persisted M4 application run plus its current Render Manifest, if available."""

    report: dict[str, Any]
    path: Path
    changed: bool
    manifest: dict[str, Any] | None


def _phase_index(phase: Phase) -> int:
    return FORWARD_SEQUENCE.index(phase)


class M4ApplicationService:
    """Orchestrate the frozen M3 graph through Production multi-backend rendering."""

    def __init__(
        self,
        workspace: Path,
        *,
        renderer_root: Path | None = None,
        node: str | None = None,
        font_match: str | None = None,
        document_renderer: Any | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.renderer_root = renderer_root
        self.node = node
        self.font_match = font_match
        self.document_renderer = document_renderer or LibreOfficeDocumentRenderer(
            font_match=font_match
        )
        self.schemas = schema_registry or SchemaRegistry()
        self.report_dir = self.workspace / ".slidethus/m4/runs"

    @staticmethod
    def _add_action(
        actions: list[dict[str, Any]],
        *,
        stage: str,
        status: str,
        detail: str,
        refs: tuple[str, ...] = (),
    ) -> None:
        actions.append(
            {
                "action_id": f"M4A-{len(actions) + 1:03d}",
                "stage": stage,
                "status": status,
                "detail": " ".join(detail.split()).strip()[:4000],
                "refs": sorted(set(str(item) for item in refs)),
            }
        )

    @staticmethod
    def _add_finding(
        findings: list[dict[str, str]],
        *,
        kind: str,
        code: str,
        message: str,
    ) -> None:
        normalized = " ".join(message.split()).strip()[:4000]
        item = {
            "finding_id": m4_finding_id(kind, code, normalized),
            "code": code,
            "message": normalized,
        }
        if item["finding_id"] not in {value["finding_id"] for value in findings}:
            findings.append(item)

    def _current_gate_summary(self, gate_id: str) -> dict[str, Any] | None:
        state = self.runtime.show_artifact("project_state")
        summary = next(
            (
                item
                for item in state.get("completed_gates", [])
                if item.get("gate_id") == gate_id
                and item.get("status") in {"pass", "waived"}
            ),
            None,
        )
        if summary is None:
            return None
        entries = {
            str(item["artifact_type"]): item for item in state.get("artifacts", [])
        }
        for reference in summary.get("artifact_versions", []):
            current = entries.get(str(reference.get("artifact_type")))
            if current is None:
                return None
            if (
                int(current.get("version", 0)) != int(reference.get("version", -1))
                or current.get("sha256") != reference.get("sha256")
            ):
                return None
        return summary

    def _ensure_gate(self, gate_id: str, target: Phase) -> None:
        if self._current_gate_summary(gate_id) is not None:
            return
        result = evaluate_gate(self.workspace, gate_id)
        if not result.passed:
            raise RenderingError(f"{gate_id} did not pass: {'; '.join(result.reasons)}")
        state = self.runtime.show_artifact("project_state")
        current = Phase(str(state["current_phase"]))
        target_phase: Phase | None = None
        if _phase_index(current) < _phase_index(target):
            if not can_transition(current, target):
                raise RenderingError(
                    f"Cannot advance {gate_id}: {current.value} -> {target.value}"
                )
            target_phase = target
        self.runtime.record_gate(
            gate_id,
            approved_by="m4-application-service",
            target_phase=target_phase,
        )

    def _manifest_ref(self) -> dict[str, Any] | None:
        entry = next(
            (
                item
                for item in self.runtime.list_artifacts()
                if item.get("artifact_type") == "render_manifest"
            ),
            None,
        )
        if entry is None:
            return None
        return {
            "artifact_type": "render_manifest",
            "version": int(entry["version"]),
            "content_hash": str(entry["content_hash"]),
            "path": str(entry["path"]),
        }

    def _persist(self, report: dict[str, Any]) -> M4ApplicationRunResult:
        report["report_id"] = m4_report_id(report)
        errors = validate_m4_report_data(report, self.schemas.schema_dir)
        if errors:
            raise RenderingError("Invalid M4 Application Report: " + "; ".join(errors))
        path = self.report_dir / f"{m4_report_file_key(report)}.json"
        created = atomic_create_json(path, report)
        if not created and read_json(path) != report:
            raise RenderingError(
                f"Immutable M4 Application Report path contains different content: {path}"
            )
        reference_errors = m4_report_reference_errors(
            self.workspace,
            path,
            self.schemas.schema_dir,
        )
        if reference_errors:
            if created and path.exists():
                path.unlink()
            raise RenderingError(
                "M4 Application Report references are invalid: "
                + "; ".join(reference_errors)
            )
        manifest_ref = report.get("render_manifest")
        manifest = (
            self.runtime.show_artifact("render_manifest")
            if manifest_ref is not None
            else None
        )
        return M4ApplicationRunResult(
            report=copy.deepcopy(report),
            path=path,
            changed=created,
            manifest=manifest,
        )

    def _finalize(
        self,
        *,
        status: str,
        config: dict[str, Any],
        capabilities: list[dict[str, str]],
        actions: list[dict[str, Any]],
        blockers: list[dict[str, str]],
        warnings: list[dict[str, str]],
        preflight: RenderPreflightResult | None,
    ) -> M4ApplicationRunResult:
        state = self.runtime.show_artifact("project_state")
        manifest_ref = self._manifest_ref()
        manifest = (
            self.runtime.show_artifact("render_manifest")
            if manifest_ref is not None
            else None
        )
        g7 = evaluate_gate(self.workspace, "G7")
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": str(state["project_id"]),
            "report_id": "",
            "generated_at": (
                str(manifest.get("generated_at"))
                if manifest is not None
                else (
                    str(preflight.report["generated_at"])
                    if preflight is not None
                    else "1970-01-01T00:00:00Z"
                )
            ),
            "status": status,
            "config": config,
            "config_hash": f"sha256:{sha256_json(config)}",
            "capabilities": sorted(
                {item["capability"]: item for item in capabilities}.values(),
                key=lambda item: item["capability"],
            ),
            "actions": actions,
            "blockers": sorted(blockers, key=lambda item: item["finding_id"]),
            "warnings": sorted(warnings, key=lambda item: item["finding_id"]),
            "preflight": (
                {
                    "preflight_id": str(preflight.report["preflight_id"]),
                    "path": preflight.path.relative_to(self.workspace).as_posix(),
                    "sha256": sha256_file(preflight.path),
                    "status": str(preflight.report["status"]),
                }
                if preflight is not None
                else None
            ),
            "render_manifest": manifest_ref,
            "outputs": [
                {
                    "path": str(item["path"]),
                    "sha256": str(item["sha256"]),
                    "role": str(item.get("role", "")),
                    "backend": item.get("backend"),
                }
                for item in (manifest or {}).get("outputs", [])
            ],
            "final_phase": str(state["current_phase"]),
            "g7": {"status": g7.status, "reasons": list(g7.reasons)},
            "project_state": {
                "revision": int(state["revision"]),
                "content_hash": f"sha256:{sha256_json(state)}",
            },
        }
        self._add_action(
            report["actions"],
            stage="report",
            status="complete",
            detail=f"M4 Application Report finalized with status={status}.",
        )
        return self._persist(report)

    def run(
        self,
        *,
        require_office_preview: bool = False,
    ) -> M4ApplicationRunResult:
        """Run/resume the complete M4 multi-backend rendering boundary."""

        config = {
            "backends": list(_BACKENDS),
            "include_exports": True,
            "require_office_preview": require_office_preview,
            "target_editability_level": "E2",
        }
        actions: list[dict[str, Any]] = []
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        capabilities: list[dict[str, str]] = []
        preflight: RenderPreflightResult | None = None

        m3 = evaluate_m3_workspace_gate(self.workspace)
        if m3.get("status") != "pass":
            self._add_finding(
                blockers,
                kind="blocker",
                code="m3_not_ready",
                message="M4 requires current M3 planning readiness: "
                + "; ".join(str(item) for item in m3.get("reasons", [])),
            )
            self._add_action(
                actions,
                stage="visual_system",
                status="blocked",
                detail="M3 planning boundary is not ready for rendering.",
            )
            return self._finalize(
                status="blocked",
                config=config,
                capabilities=capabilities,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                preflight=None,
            )

        try:
            visual = VisualSystemService(self.workspace, runtime=self.runtime).compile()
            self._ensure_gate("G6", Phase.VISUAL_SYSTEM_READY)
            self._add_action(
                actions,
                stage="visual_system",
                status="complete",
                detail="Production Visual System is current and G6 is accepted.",
                refs=(str(visual["theme_id"]),),
            )
            preflight = RenderPreflightService(
                self.workspace,
                renderer_root=self.renderer_root,
                node=self.node,
                font_match=self.font_match,
            ).run(_BACKENDS, include_exports=True)
        except (ArtifactError, RenderingError) as exc:
            self._add_finding(
                blockers,
                kind="blocker",
                code="render_preflight_failed",
                message=str(exc),
            )
            self._add_action(
                actions,
                stage="preflight",
                status="failed",
                detail=str(exc),
            )
            return self._finalize(
                status="failed",
                config=config,
                capabilities=capabilities,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                preflight=preflight,
            )

        capabilities.extend(copy.deepcopy(preflight.report["capabilities"]))
        self._add_action(
            actions,
            stage="preflight",
            status="complete" if preflight.report["status"] == "pass" else "blocked",
            detail=(
                "Production render preflight passed."
                if preflight.report["status"] == "pass"
                else "Production render preflight found blocking issues."
            ),
            refs=(str(preflight.report["preflight_id"]),),
        )
        if preflight.report["status"] != "pass":
            for item in preflight.report.get("checks", []):
                if item.get("status") == "fail" and item.get("severity") in {
                    "critical",
                    "major",
                }:
                    self._add_finding(
                        blockers,
                        kind="blocker",
                        code=str(item["code"]),
                        message=str(item["message"]),
                    )
            return self._finalize(
                status="blocked",
                config=config,
                capabilities=capabilities,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                preflight=preflight,
            )

        office_available = bool(getattr(self.document_renderer, "available", False))
        capabilities.append(
            {
                "capability": "pptx_office_preview",
                "status": "available" if office_available else "missing",
                "detail": (
                    "Independent Office-compatible PPTX preview is available."
                    if office_available
                    else "Independent Office-compatible PPTX preview is unavailable on this host."
                ),
            }
        )
        if require_office_preview and not office_available:
            self._add_finding(
                blockers,
                kind="blocker",
                code="office_preview_required",
                message="This run requires independent PPTX Office preview, but the capability is unavailable.",
            )
            self._add_action(
                actions,
                stage="office_preview",
                status="blocked",
                detail="Required Office preview capability is unavailable.",
            )
            return self._finalize(
                status="blocked",
                config=config,
                capabilities=capabilities,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                preflight=preflight,
            )

        output_root = self.workspace / "outputs/m4"
        try:
            final_svg = FinalSvgRenderBackend(
                compiled=preflight.compiled,
                assets=preflight.assets,
            ).render(
                RenderRequest(
                    workspace=self.workspace,
                    target_format="svg",
                    target_editability_level="E1",
                    output_dir=output_root,
                )
            )
            self._add_action(
                actions,
                stage="final_svg",
                status="complete",
                detail="Final SVG rendered for every slide.",
                refs=tuple(
                    path.relative_to(self.workspace).as_posix()
                    for path in final_svg.output_paths
                ),
            )
            native_target = (
                "E2"
                if any(
                    region.get("content_type") == "image" or region.get("asset_refs")
                    for slide in preflight.compiled.ir["slides"]
                    for region in slide["regions"]
                )
                else "E3"
            )
            native = PptxGenJSNativeRenderBackend(
                renderer_root=self.renderer_root,
                node=self.node,
                compiled=preflight.compiled,
                assets=preflight.assets,
            ).render(
                RenderRequest(
                    workspace=self.workspace,
                    target_format="pptx",
                    target_editability_level=native_target,
                    output_dir=output_root,
                )
            )
            self._add_action(
                actions,
                stage="native_pptx",
                status="complete",
                detail=(
                    "Native PptxGenJS PPTX rendered, reopened and measured "
                    f"{native.actual_editability_level}."
                ),
                refs=(native.output_paths[0].relative_to(self.workspace).as_posix(),),
            )
            hybrid = PptxGenJSHybridRenderBackend(
                renderer_root=self.renderer_root,
                node=self.node,
                compiled=preflight.compiled,
                assets=preflight.assets,
            ).render(
                RenderRequest(
                    workspace=self.workspace,
                    target_format="pptx",
                    target_editability_level="E2",
                    output_dir=output_root,
                )
            )
            self._add_action(
                actions,
                stage="hybrid_pptx",
                status="complete",
                detail="Hybrid PptxGenJS PPTX rendered, reopened and measured E2.",
                refs=(hybrid.output_paths[0].relative_to(self.workspace).as_posix(),),
            )
            export = SvgPreviewExportService(
                self.workspace,
                renderer_root=self.renderer_root,
                node=self.node,
            ).export(
                final_svg.output_paths,
                generated_at=str(preflight.compiled.ir["generated_at"]),
                output_dir=output_root / "export",
            )
            self._add_action(
                actions,
                stage="export",
                status="complete",
                detail="Final SVG was independently exported to PNG pages and PDF.",
                refs=(export.pdf_path.relative_to(self.workspace).as_posix(),),
            )

            office_previews: tuple[Path, ...] = ()
            office_detail = "Independent Office-compatible PPTX preview is unavailable on this host."
            if office_available:
                try:
                    office_previews = tuple(
                        self.document_renderer.preview(
                            hybrid.output_paths[0],
                            output_root / "office-preview",
                        )
                    )
                    if len(office_previews) != len(preflight.compiled.ir["slides"]):
                        raise RuntimeError(
                            "Office preview page count differs from Renderer IR slide count"
                        )
                    office_detail = (
                        f"Independent Office-compatible preview produced {len(office_previews)} pages."
                    )
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    office_previews = ()
                    office_detail = f"Independent Office preview failed: {exc}"
                    if require_office_preview:
                        raise RenderCapabilityError(office_detail) from exc
                    self._add_finding(
                        warnings,
                        kind="warning",
                        code="office_preview_degraded",
                        message=office_detail,
                    )
            self._add_action(
                actions,
                stage="office_preview",
                status="complete" if office_previews else "skipped",
                detail=office_detail,
                refs=tuple(
                    path.relative_to(self.workspace).as_posix()
                    for path in office_previews
                ),
            )
            published = ProductionRenderManifestService(
                self.workspace,
                runtime=self.runtime,
            ).publish(
                preflight=preflight,
                final_svg=final_svg,
                native_pptx=native,
                hybrid_pptx=hybrid,
                export=export,
                office_previews=office_previews,
                office_preview_detail=office_detail,
            )
            self._add_action(
                actions,
                stage="manifest",
                status="complete",
                detail="Production multi-backend Render Manifest is current.",
                refs=(str(published.manifest["render_id"]),),
            )
            self._ensure_gate("G7", Phase.DRAFT_RENDERED)
            self._add_action(
                actions,
                stage="g7",
                status="complete",
                detail="Production G7 is current and accepted.",
            )
        except (ArtifactError, RenderingError) as exc:
            self._add_finding(
                blockers,
                kind="blocker",
                code="production_render_failed",
                message=str(exc),
            )
            self._add_action(
                actions,
                stage="manifest",
                status="failed",
                detail=str(exc),
            )
            return self._finalize(
                status="failed",
                config=config,
                capabilities=capabilities,
                actions=actions,
                blockers=blockers,
                warnings=warnings,
                preflight=preflight,
            )

        return self._finalize(
            status="ready",
            config=config,
            capabilities=capabilities,
            actions=actions,
            blockers=blockers,
            warnings=warnings,
            preflight=preflight,
        )


def evaluate_m4_workspace_gate(workspace: Path) -> dict[str, Any]:
    """Evaluate current M4 rendering readiness without mutating the workspace."""

    workspace = workspace.resolve()
    reasons: list[str] = []
    m3 = evaluate_m3_workspace_gate(workspace)
    if m3.get("status") != "pass":
        reasons.extend(f"M3:{item}" for item in m3.get("reasons", []))
    gates: list[dict[str, Any]] = []
    for gate_id in ("G6", "G7"):
        result = evaluate_gate(workspace, gate_id)
        gates.append(
            {
                "gate_id": gate_id,
                "status": result.status,
                "reasons": list(result.reasons),
            }
        )
        if not result.passed:
            reasons.extend(f"{gate_id}:{item}" for item in result.reasons)
    return {
        "status": "pass" if not reasons else "fail",
        "reasons": reasons,
        "gates": gates,
    }
