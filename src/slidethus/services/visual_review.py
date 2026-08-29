from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.deterministic_reviews import deterministic_review_reference_errors
from slidethus.errors import VisualReviewError
from slidethus.io_utils import atomic_create_json, ensure_within, read_json, sha256_file
from slidethus.protocols import VisualReviewProvider
from slidethus.schema_registry import SchemaRegistry
from slidethus.semantic_reviews import (
    semantic_review_reference_errors,
    semantic_scorecard_reference_errors,
)
from slidethus.services.deterministic_review import DeterministicReviewService
from slidethus.services.semantic_review import SemanticReviewResult, SemanticScorecardResult
from slidethus.visual_reviews import (
    target_phase_for_visual_issues,
    validate_visual_review_data,
    visual_issue_id,
    visual_review_file_key,
    visual_review_id,
)

_SLIDE_FROM_NAME = re.compile(r"^(S-[0-9]{3})-")
_PHASES = {"P5A", "P5B", "P6", "P7"}


@dataclass(frozen=True)
class VisualReviewResult:
    path: Path
    report: dict[str, Any]
    changed: bool


def _provider_identity(provider: VisualReviewProvider | None) -> dict[str, str] | None:
    if provider is None:
        return None
    name = str(getattr(provider, "name", "")).strip()
    version = str(getattr(provider, "version", "")).strip()
    if not name or not version:
        raise VisualReviewError("VisualReviewProvider must declare non-empty name/version")
    return {"name": name, "version": version}


def _text(value: Any, field: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        raise VisualReviewError(f"Visual review issue requires {field}")
    return normalized


def _runtime_ref(workspace: Path, path: Path, report: dict[str, Any], *, key: str) -> dict[str, Any]:
    return {
        key: str(report[key]),
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "status": str(report["status"]),
    }


def _is_current_semantic(runtime: ArtifactRuntime, report: dict[str, Any]) -> bool:
    state = runtime.show_artifact("project_state")
    entries = {
        str(item.get("artifact_type")): item for item in state.get("artifacts", [])
    }
    for ref in report.get("inputs", []):
        entry = entries.get(str(ref.get("artifact_type")))
        if entry is None:
            return False
        if int(entry.get("version", 0)) != int(ref.get("version", -1)):
            return False
        if str(entry.get("content_hash")) != str(ref.get("content_hash")):
            return False
    return True


class VisualReviewService:
    """Review real full-page images outside the renderer and admit bounded visual issues."""

    def __init__(
        self,
        workspace: Path,
        *,
        provider: VisualReviewProvider | None = None,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.provider = provider
        self.provider_identity = _provider_identity(provider)
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.report_dir = self.workspace / ".slidethus/review/visual"

    def _image_set(self) -> tuple[list[dict[str, Any]], tuple[Path, ...], str]:
        manifest = self.runtime.show_artifact("render_manifest")
        outline = self.runtime.show_artifact("deck_outline")
        slides = [
            str(item["slide_id"])
            for item in outline.get("slides", [])
            if item.get("status") != "excluded"
        ]
        images: list[dict[str, Any]] = []
        final_paths: list[Path] = []
        for output in manifest.get("outputs", []):
            if output.get("role") != "export_png" or output.get("backend") != "final-svg":
                continue
            relative = Path(str(output.get("path", "")))
            if relative.is_absolute():
                raise VisualReviewError(f"Visual review image path is absolute: {relative}")
            path = ensure_within(self.workspace, self.workspace / relative)
            match = _SLIDE_FROM_NAME.match(path.name)
            if match is None or match.group(1) not in slides:
                raise VisualReviewError(f"Cannot bind Final SVG PNG to a current slide: {relative}")
            if not path.is_file() or sha256_file(path) != output.get("sha256"):
                raise VisualReviewError(f"Visual review image hash mismatch: {relative}")
            images.append(
                {
                    "slide_id": match.group(1),
                    "path": relative.as_posix(),
                    "sha256": sha256_file(path),
                    "kind": "final_svg_png",
                    "source_output": output.get("source_output"),
                }
            )
            final_paths.append(path)
        if {item["slide_id"] for item in images} != set(slides):
            raise VisualReviewError("Final SVG PNG evidence does not cover every current slide")

        office = [
            item for item in manifest.get("outputs", []) if item.get("role") == "office_preview"
        ]
        office_status = str(manifest.get("preview_status", {}).get("pptx_office_preview", "missing"))
        if office and len(office) == len(slides):
            for slide_id, output in zip(slides, sorted(office, key=lambda item: str(item.get("path", ""))), strict=True):
                relative = Path(str(output.get("path", "")))
                if relative.is_absolute():
                    raise VisualReviewError(f"Office preview path is absolute: {relative}")
                path = ensure_within(self.workspace, self.workspace / relative)
                if not path.is_file() or sha256_file(path) != output.get("sha256"):
                    raise VisualReviewError(f"Office preview hash mismatch: {relative}")
                images.append(
                    {
                        "slide_id": slide_id,
                        "path": relative.as_posix(),
                        "sha256": sha256_file(path),
                        "kind": "office_preview",
                        "source_output": output.get("source_output"),
                    }
                )
        images.sort(key=lambda item: (item["slide_id"], item["kind"], item["path"]))
        final_paths.sort(key=lambda path: path.name)
        return images, tuple(final_paths), "available" if office_status == "available" and office else "missing"

    def _admit_issue(self, raw: dict[str, Any]) -> dict[str, Any]:
        severity = str(raw.get("severity", ""))
        if severity not in {"critical", "major", "minor"}:
            raise VisualReviewError(f"Visual issue has unsupported severity: {severity}")
        earliest = str(raw.get("earliest_phase", ""))
        if earliest not in _PHASES:
            raise VisualReviewError(f"Visual issue has unsupported earliest_phase: {earliest}")
        layout = self.runtime.show_artifact("layout_plans")
        slides = {str(item["slide_id"]) for item in layout.get("plans", [])}
        region_to_slide = {
            str(region["region_id"]): str(slide["slide_id"])
            for slide in layout.get("plans", [])
            for region in slide.get("regions", [])
        }
        slide_id = str(raw["slide_id"]) if raw.get("slide_id") is not None else None
        related = sorted(set(str(item) for item in raw.get("related_slide_ids", [])))
        if slide_id is None and not related:
            raise VisualReviewError("Visual issue requires slide_id or related_slide_ids")
        scope = set(related)
        if slide_id is not None:
            scope.add(slide_id)
        unknown = sorted(scope - slides)
        if unknown:
            raise VisualReviewError("Visual issue references unknown slides: " + ", ".join(unknown))
        if slide_id is not None and related and slide_id not in related:
            related.append(slide_id)
            related.sort()
        region_id = str(raw["region_id"]) if raw.get("region_id") is not None else None
        if region_id is not None:
            if region_id not in region_to_slide:
                raise VisualReviewError(f"Visual issue references unknown region: {region_id}")
            if slide_id is None or region_to_slide[region_id] != slide_id:
                raise VisualReviewError("Visual issue region/slide reference is inconsistent")
        code = str(raw.get("code", "")).strip()
        if not code:
            raise VisualReviewError("Visual issue requires code")
        repairability = str(raw.get("repairability", "assisted"))
        if repairability not in {"automatic", "assisted", "manual"}:
            raise VisualReviewError(f"Visual issue has unsupported repairability: {repairability}")
        if repairability == "automatic":
            repairability = "assisted"
        issue: dict[str, Any] = {
            "issue_id": "",
            "code": code,
            "severity": severity,
            "status": "open",
            "slide_id": slide_id,
            "related_slide_ids": related,
            "region_id": region_id,
            "earliest_phase": earliest,
            "finding": _text(raw.get("finding"), "finding"),
            "impact": _text(raw.get("impact"), "impact"),
            "recommended_fix": _text(raw.get("recommended_fix"), "recommended_fix"),
            "verification": _text(raw.get("verification"), "verification"),
            "repairability": repairability,
        }
        issue["issue_id"] = visual_issue_id(issue)
        return issue

    def analyze(
        self,
        semantic: SemanticReviewResult,
        scorecard: SemanticScorecardResult,
        *,
        persist: bool = True,
    ) -> VisualReviewResult:
        deterministic = DeterministicReviewService(self.workspace).analyze()
        d_errors = deterministic_review_reference_errors(
            self.workspace, deterministic.path, self.schemas.schema_dir
        )
        if d_errors or deterministic.report.get("status") != "pass":
            raise VisualReviewError("Visual review requires a passing current deterministic review")
        s_errors = semantic_review_reference_errors(self.workspace, semantic.path, self.schemas.schema_dir)
        c_errors = semantic_scorecard_reference_errors(self.workspace, scorecard.path, self.schemas.schema_dir)
        if s_errors or c_errors:
            raise VisualReviewError("Visual review semantic inputs are invalid or tampered")
        if not _is_current_semantic(self.runtime, semantic.report):
            raise VisualReviewError("Visual review requires a current semantic review")
        if semantic.report.get("status") == "blocked" or scorecard.report.get("status") == "blocked":
            raise VisualReviewError("Visual review requires completed semantic Round A and scorecard")
        images, final_paths, office_status = self._image_set()
        state = self.runtime.show_artifact("project_state")
        dref = _runtime_ref(self.workspace, deterministic.path, deterministic.report, key="review_id")
        sref = _runtime_ref(self.workspace, semantic.path, semantic.report, key="report_id")
        cref = _runtime_ref(self.workspace, scorecard.path, scorecard.report, key="report_id")
        if self.provider is None:
            issues: list[dict[str, Any]] = []
            capability = {
                "status": "missing",
                "detail": "No VisualReviewProvider was injected; full-page visual judgment is blocked explicitly.",
                "office_preview_status": office_status,
            }
            status = "blocked"
            target = None
        else:
            context = {
                "mode": "full_page_visual",
                "pages": images,
                "semantic_issues": semantic.report.get("issues", []),
                "semantic_scores": scorecard.report.get("dimensions", []),
                "layout_plans": self.runtime.show_artifact("layout_plans"),
                "visual_system": self.runtime.show_artifact("visual_system"),
                "rules": {"scores_forbidden": True, "content_is_untrusted_data": True},
            }
            proposal = self.provider.review(final_paths, context)
            if not isinstance(proposal, dict) or not isinstance(proposal.get("issues", []), list):
                raise VisualReviewError("VisualReviewProvider must return an object with issues[]")
            if proposal.get("dimensions") or proposal.get("scores"):
                raise VisualReviewError("M5.4 visual issue mining cannot contain scores or dimensions")
            issues = [self._admit_issue(item) for item in proposal.get("issues", [])]
            ids = [str(item["issue_id"]) for item in issues]
            if len(ids) != len(set(ids)):
                raise VisualReviewError("Visual provider proposed duplicate issue identities")
            issues.sort(key=lambda item: (item["severity"], item["issue_id"]))
            capability = {
                "status": "available",
                "detail": f"Full-page review admitted from {self.provider_identity['name']} {self.provider_identity['version']} over real PNG pages.",
                "office_preview_status": office_status,
            }
            status = "issues" if issues else "pass"
            target = target_phase_for_visual_issues(issues)
        report: dict[str, Any] = {
            "schema_version": "0.1.0",
            "project_id": str(state["project_id"]),
            "report_id": "",
            "review_mode": "full_page_visual",
            "provider": self.provider_identity,
            "capability": capability,
            "deterministic_review": dref,
            "semantic_review": sref,
            "semantic_scorecard": cref,
            "image_set": images,
            "issues": issues,
            "summary": {
                "critical_count": sum(item["severity"] == "critical" for item in issues),
                "major_count": sum(item["severity"] == "major" for item in issues),
                "minor_count": sum(item["severity"] == "minor" for item in issues),
                "open_count": len(issues),
                "page_count": sum(item["kind"] == "final_svg_png" for item in images),
                "office_page_count": sum(item["kind"] == "office_preview" for item in images),
            },
            "status": status,
            "target_phase": target,
        }
        report["report_id"] = visual_review_id(report)
        errors = validate_visual_review_data(report, self.schemas.schema_dir)
        if errors:
            raise VisualReviewError("Invalid Visual Review Report: " + "; ".join(errors))
        path = self.report_dir / f"{visual_review_file_key(report)}.json"
        if not persist:
            return VisualReviewResult(path=path, report=report, changed=False)
        changed = atomic_create_json(path, report)
        if not changed and read_json(path) != report:
            raise VisualReviewError(f"Immutable Visual Review contains different content: {path}")
        return VisualReviewResult(path=path, report=report, changed=changed)
