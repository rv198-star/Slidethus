from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from slidethus.deterministic_reviews import (
    deterministic_check_id,
    deterministic_review_file_key,
    deterministic_review_id,
    target_phase_for_checks,
    validate_deterministic_review_data,
)
from slidethus.errors import DeterministicReviewError, WorkspaceError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import (
    atomic_create_json,
    ensure_within,
    read_json,
    sha256_file,
    sha256_json,
)
from slidethus.render_backends.pptxgenjs import measure_pptx_structure
from slidethus.render_manifest import production_render_manifest_reference_errors
from slidethus.schema_registry import SchemaRegistry
from slidethus.validation import ValidationIssue, validate_workspace

_REQUIRED_INPUTS = (
    "asset_manifest",
    "deck_outline",
    "evidence_ledger",
    "layout_plans",
    "narrative_blueprint",
    "project_brief",
    "render_manifest",
    "slide_specs",
    "source_ledger",
    "visual_system",
)
_GATE_PHASE = {
    "G0": "P0",
    "G1": "P1",
    "G2": "P2",
    "G3": "P3",
    "G4": "P4",
    "G5A": "P5A",
    "G5B": "P5B",
    "G6": "P6",
    "G7": "P7",
}
_PATH_PHASE_PREFIXES = (
    ("brief/", "P0"),
    ("sources/", "P1"),
    ("evidence/", "P2"),
    ("narrative/", "P3"),
    ("outline/", "P4"),
    ("slides/", "P5A"),
    ("layout/", "P5B"),
    ("design/", "P6"),
    ("assets/", "P6"),
    ("renders/", "P7"),
    ("outputs/", "P7"),
    (".slidethus/render/", "P7"),
    ("review/", "P8"),
)
_PHASE_ORDER = {phase: index for index, phase in enumerate(("P0", "P1", "P2", "P3", "P4", "P5A", "P5B", "P6", "P7", "P8"))}


@dataclass(frozen=True)
class DeterministicReviewResult:
    path: Path
    report: dict[str, Any]
    changed: bool


def _phase_for_validation_issue(issue: ValidationIssue) -> str:
    path = issue.path.replace("\\", "/")
    for prefix, phase in _PATH_PHASE_PREFIXES:
        if path.startswith(prefix):
            return phase
    if issue.code.startswith(("render_", "invalid_m4", "unsafe_workspace_path")):
        return "P7"
    if issue.code.startswith(("source_", "invalid_source")):
        return "P1"
    if issue.code.startswith(("evidence_", "invalid_evidence", "targeted_")):
        return "P2"
    return "P8"


def _earliest(phases: list[str], default: str = "P8") -> str:
    return min(phases, key=lambda phase: _PHASE_ORDER[phase]) if phases else default


def _check(
    *,
    code: str,
    category: str,
    severity: str,
    earliest_phase: str,
    ok: bool,
    finding: str,
    evidence: str,
    verification: str,
    refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "check_id": "",
        "code": code,
        "category": category,
        "severity": severity,
        "earliest_phase": earliest_phase,
        "status": "pass" if ok else "fail",
        "finding": finding,
        "evidence": evidence,
        "verification": verification,
        "refs": sorted(set(refs)),
    }
    item["check_id"] = deterministic_check_id(item)
    return item


def _artifact_inputs(workspace: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    entries = {str(item.get("artifact_type")): item for item in state.get("artifacts", [])}
    missing = [artifact_type for artifact_type in _REQUIRED_INPUTS if artifact_type not in entries]
    if missing:
        raise DeterministicReviewError(
            "M5 deterministic review requires current M2-M4 artifacts: " + ", ".join(missing)
        )
    refs: list[dict[str, Any]] = []
    for artifact_type in _REQUIRED_INPUTS:
        entry = entries[artifact_type]
        relative = Path(str(entry["path"]))
        if relative.is_absolute():
            raise DeterministicReviewError(
                f"Current artifact path is absolute: {artifact_type}: {relative}"
            )
        try:
            path = ensure_within(workspace, workspace / relative)
            observed = read_json(path)
        except Exception as exc:  # noqa: BLE001
            raise DeterministicReviewError(
                f"Cannot observe current artifact for deterministic review: {artifact_type}: {exc}"
            ) from exc
        refs.append(
            {
                "artifact_type": artifact_type,
                "path": str(entry["path"]),
                "version": int(entry["version"]),
                "content_hash": str(entry["content_hash"]),
                "observed_content_hash": f"sha256:{sha256_json(observed)}",
            }
        )
    return sorted(refs, key=lambda item: item["artifact_type"])


def _admitted_path(workspace: Path, raw_path: Any) -> Path:
    relative = Path(str(raw_path))
    if relative.is_absolute():
        raise WorkspaceError(f"absolute review input path is not allowed: {raw_path}")
    return ensure_within(workspace, workspace / relative)


def _role_outputs(manifest: dict[str, Any], role: str, backend: str | None = None) -> list[dict[str, Any]]:
    return [
        item
        for item in manifest.get("outputs", [])
        if item.get("role") == role and (backend is None or item.get("backend") == backend)
    ]


def _svg_valid(path: Path) -> bool:
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return False
    return root.tag.endswith("svg")


def _png_valid(path: Path) -> bool:
    try:
        return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def _pdf_valid(path: Path) -> bool:
    try:
        payload = path.read_bytes()
    except OSError:
        return False
    return payload.startswith(b"%PDF-") and b"%%EOF" in payload[-2048:]


class DeterministicReviewService:
    """Independently recompute current M2-M4 integrity before semantic/visual review."""

    def __init__(
        self,
        workspace: Path,
        *,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.schemas = schema_registry or SchemaRegistry()
        self.report_dir = self.workspace / ".slidethus/review/deterministic"

    def analyze(self, *, persist: bool = True) -> DeterministicReviewResult:
        """Run M5.1 review without mutating M2-M4 artifacts."""

        state = read_json(self.workspace / "project_state.json")
        inputs = _artifact_inputs(self.workspace, state)
        manifest = read_json(self.workspace / "renders/render_manifest.json")
        checks: list[dict[str, Any]] = []

        validation = validate_workspace(self.workspace, check_hashes=True)
        validation_errors = [item for item in validation.issues if item.severity == "error"]
        validation_phases = [_phase_for_validation_issue(item) for item in validation_errors]
        checks.append(
            _check(
                code="workspace_integrity",
                category="workspace_integrity",
                severity="critical",
                earliest_phase=_earliest(validation_phases),
                ok=not validation_errors,
                finding=(
                    "Current workspace schemas, cross-references, state and hashes are valid."
                    if not validation_errors
                    else "Current workspace contains deterministic integrity failures."
                ),
                evidence=(
                    "validate_workspace(check_hashes=True): PASS"
                    if not validation_errors
                    else "; ".join(
                        f"{item.code}@{item.path or '-'}" for item in validation_errors[:20]
                    )
                ),
                verification="Re-run validate_workspace with hash checking on the same artifact versions.",
                refs=tuple(item.path for item in validation_errors if item.path),
            )
        )

        for gate_id, phase in _GATE_PHASE.items():
            result = evaluate_gate(self.workspace, gate_id)
            validation_only = bool(result.reasons) and all(
                str(reason).startswith("validation:") for reason in result.reasons
            )
            gate_phase = (
                _earliest(validation_phases, phase) if validation_only else phase
            )
            checks.append(
                _check(
                    code=f"{gate_id.lower()}_regression",
                    category="gate_regression",
                    severity="critical" if gate_id in {"G0", "G1", "G2"} else "major",
                    earliest_phase=gate_phase,
                    ok=result.status == "pass",
                    finding=(
                        f"{gate_id} independently re-evaluates to PASS."
                        if result.status == "pass"
                        else f"{gate_id} no longer satisfies its frozen contract."
                    ),
                    evidence=(
                        "no gate reasons"
                        if not result.reasons
                        else "; ".join(result.reasons[:20])
                    ),
                    verification=f"Re-run evaluate_gate(workspace, '{gate_id}').",
                    refs=(gate_id,),
                )
            )

        manifest_errors = production_render_manifest_reference_errors(
            self.workspace,
            manifest,
            self.schemas.schema_dir,
        )
        checks.append(
            _check(
                code="production_render_lineage",
                category="render_lineage",
                severity="critical",
                earliest_phase="P7",
                ok=not manifest_errors,
                finding=(
                    "Production Render Manifest, Renderer IR, Preflight and output hashes are current."
                    if not manifest_errors
                    else "Production render lineage is missing, stale, unsafe or hash-inconsistent."
                ),
                evidence="PASS" if not manifest_errors else "; ".join(manifest_errors[:20]),
                verification="Recompute Production Render Manifest runtime reference validation.",
                refs=("renders/render_manifest.json",),
            )
        )

        ir_ref = manifest.get("renderer_ir", {})
        try:
            ir_path = _admitted_path(self.workspace, ir_ref.get("path", ""))
            ir = read_json(ir_path)
            slide_count = len(ir.get("slides", []))
        except Exception:  # noqa: BLE001
            ir = {}
            slide_count = 0
        role_counts = {
            "final_svg": len(_role_outputs(manifest, "final_svg", "final-svg")),
            "native_pptx": len(_role_outputs(manifest, "native_pptx", "pptxgenjs-native")),
            "hybrid_pptx": len(_role_outputs(manifest, "hybrid_pptx", "pptxgenjs-hybrid")),
            "export_png": len(_role_outputs(manifest, "export_png", "final-svg")),
            "export_pdf": len(_role_outputs(manifest, "export_pdf", "final-svg")),
        }
        coverage_ok = (
            slide_count > 0
            and role_counts["final_svg"] == slide_count
            and role_counts["export_png"] == slide_count
            and role_counts["native_pptx"] == 1
            and role_counts["hybrid_pptx"] == 1
            and role_counts["export_pdf"] == 1
        )
        checks.append(
            _check(
                code="production_output_coverage",
                category="output_integrity",
                severity="major",
                earliest_phase="P7",
                ok=coverage_ok,
                finding=(
                    "Production outputs cover every Renderer IR slide across required backends."
                    if coverage_ok
                    else "Production output roles do not cover the current Renderer IR consistently."
                ),
                evidence=f"slides={slide_count}; roles={role_counts}",
                verification="Compare Renderer IR slide count with Final SVG/PNG and single Native/Hybrid/PDF outputs.",
                refs=("renders/render_manifest.json", str(ir_ref.get("path", ""))),
            )
        )

        signature_failures: list[str] = []
        for output in manifest.get("outputs", []):
            role = str(output.get("role", ""))
            if role not in {"final_svg", "native_pptx", "hybrid_pptx", "export_png", "export_pdf"}:
                continue
            try:
                path = _admitted_path(self.workspace, output.get("path", ""))
            except (WorkspaceError, OSError, ValueError):
                signature_failures.append(str(output.get("path", "")))
                continue
            valid = path.is_file() and sha256_file(path) == output.get("sha256")
            if valid and role == "final_svg":
                valid = _svg_valid(path)
            elif valid and role == "export_png":
                valid = _png_valid(path)
            elif valid and role == "export_pdf":
                valid = _pdf_valid(path)
            if not valid:
                signature_failures.append(str(output.get("path", "")))
        checks.append(
            _check(
                code="real_output_signatures",
                category="output_integrity",
                severity="critical",
                earliest_phase="P7",
                ok=not signature_failures,
                finding=(
                    "Required Production files have matching hashes and valid format signatures."
                    if not signature_failures
                    else "One or more Production outputs fail independent file/signature verification."
                ),
                evidence="PASS" if not signature_failures else "; ".join(signature_failures),
                verification="Reopen/hash SVG, PNG, PDF and PPTX outputs from the current Render Manifest.",
                refs=tuple(signature_failures),
            )
        )

        pptx_failures: list[str] = []
        measured_levels: dict[str, str] = {}
        for backend, role, mode in (
            ("pptxgenjs-native", "native_pptx", "native"),
            ("pptxgenjs-hybrid", "hybrid_pptx", "hybrid"),
        ):
            outputs = _role_outputs(manifest, role, backend)
            if len(outputs) != 1:
                pptx_failures.append(f"{backend}:output_count={len(outputs)}")
                continue
            try:
                path = _admitted_path(self.workspace, outputs[0]["path"])
                measurement = measure_pptx_structure(path, mode=mode)
            except Exception as exc:  # noqa: BLE001
                pptx_failures.append(f"{backend}:{exc}")
                continue
            measured_levels[backend] = measurement.editability_level
            if measurement.slide_count != slide_count:
                pptx_failures.append(
                    f"{backend}:slides={measurement.slide_count}!={slide_count}"
                )
        checks.append(
            _check(
                code="pptx_reopen_consistency",
                category="cross_backend_consistency",
                severity="major",
                earliest_phase="P7",
                ok=not pptx_failures,
                finding=(
                    "Native and Hybrid PPTX reopen with the same slide count as Renderer IR."
                    if not pptx_failures
                    else "Native/Hybrid PPTX structure diverges from the current Renderer IR."
                ),
                evidence="PASS" if not pptx_failures else "; ".join(pptx_failures),
                verification="Reopen both PPTX outputs and measure their real object structure.",
                refs=tuple(str(item.get("path")) for role in ("native_pptx", "hybrid_pptx") for item in _role_outputs(manifest, role)),
            )
        )

        declared_levels = {
            str(item.get("backend")): str(item.get("editability_level"))
            for item in manifest.get("backend_runs", [])
        }
        editability_ok = (
            declared_levels.get("final-svg") == "E1"
            and declared_levels.get("pptxgenjs-hybrid") == "E2"
            and measured_levels.get("pptxgenjs-hybrid") == declared_levels.get("pptxgenjs-hybrid")
            and measured_levels.get("pptxgenjs-native") == declared_levels.get("pptxgenjs-native")
            and declared_levels.get("pptxgenjs-native") in {"E2", "E3"}
        )
        checks.append(
            _check(
                code="editability_remeasurement",
                category="editability_truthfulness",
                severity="major",
                earliest_phase="P7",
                ok=editability_ok,
                finding=(
                    "Declared Production editability agrees with independently reopened outputs."
                    if editability_ok
                    else "Declared editability disagrees with real Production output structure."
                ),
                evidence=f"declared={declared_levels}; remeasured={measured_levels}",
                verification="Compare backend_runs editability with fresh PPTX structure measurements.",
                refs=("renders/render_manifest.json",),
            )
        )

        png_outputs = _role_outputs(manifest, "export_png", "final-svg")
        pdf_outputs = _role_outputs(manifest, "export_pdf", "final-svg")
        preview_ok = slide_count > 0 and len(png_outputs) == slide_count and len(pdf_outputs) == 1
        checks.append(
            _check(
                code="independent_page_preview_coverage",
                category="preview_coverage",
                severity="major",
                earliest_phase="P7",
                ok=preview_ok,
                finding=(
                    "Every slide has an independently rasterized Final SVG PNG and deck PDF."
                    if preview_ok
                    else "Independent page-preview evidence does not cover the full deck."
                ),
                evidence=f"slides={slide_count}; png={len(png_outputs)}; pdf={len(pdf_outputs)}",
                verification="Compare Final SVG independent exports with Renderer IR slide count.",
                refs=tuple(str(item.get("path")) for item in [*png_outputs, *pdf_outputs]),
            )
        )

        preview_state = manifest.get("preview_status", {})
        capability_rows = {
            str(item.get("capability")): str(item.get("status"))
            for item in manifest.get("capabilities", [])
        }
        office_state = str(preview_state.get("pptx_office_preview", ""))
        office_capability = capability_rows.get("pptx_office_preview")
        disclosure_ok = (
            office_state in {"available", "missing"}
            and office_capability == office_state
            and str(preview_state.get("svg_export")) == "available"
        )
        checks.append(
            _check(
                code="preview_capability_disclosure",
                category="capability_disclosure",
                severity="minor",
                earliest_phase="P7",
                ok=disclosure_ok,
                finding=(
                    "Independent preview capabilities are explicitly and consistently disclosed."
                    if disclosure_ok
                    else "Preview capability state is inconsistent or implicit."
                ),
                evidence=f"preview_status={preview_state}; office_capability={office_capability}",
                verification="Compare Render Manifest preview_status with capability rows.",
                refs=("renders/render_manifest.json",),
            )
        )

        failed = [item for item in checks if item["status"] == "fail"]
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(state["project_id"]),
            "review_id": "",
            "review_mode": "deterministic",
            "inputs": inputs,
            "checks": checks,
            "summary": {
                "passed_count": sum(item["status"] == "pass" for item in checks),
                "failed_count": len(failed),
                "critical_count": sum(item["severity"] == "critical" for item in failed),
                "major_count": sum(item["severity"] == "major" for item in failed),
                "minor_count": sum(item["severity"] == "minor" for item in failed),
            },
            "status": "issues" if failed else "pass",
            "target_phase": target_phase_for_checks(checks),
        }
        report["review_id"] = deterministic_review_id(report)
        errors = validate_deterministic_review_data(report, self.schemas.schema_dir)
        if errors:
            raise DeterministicReviewError(
                "Invalid Deterministic Review Report: " + "; ".join(errors)
            )
        path = self.report_dir / f"{deterministic_review_file_key(report)}.json"
        if not persist:
            return DeterministicReviewResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise DeterministicReviewError(
                f"Immutable Deterministic Review contains different content: {path}"
            )
        return DeterministicReviewResult(path=path, report=report, changed=changed)
