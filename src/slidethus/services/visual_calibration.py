"""Office-backed sample calibration and whole-deck visual admission."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import VisualQualityError
from slidethus.io_utils import ensure_within, read_json, sha256_file, sha256_json
from slidethus.protocols import VisualReviewProvider
from slidethus.render_backends.artifact_tool import ArtifactToolRenderBackend
from slidethus.services.render_preflight import RenderPreflightResult
from slidethus.visual_quality import (
    derive_visual_quality_decision,
    persist_visual_quality_review,
    persist_visual_reference_set,
    representative_slide_selection,
)


@dataclass(frozen=True)
class CalibrationAdmissionResult:
    review_path: Path
    decision_path: Path
    reference_set_path: Path | None
    authorization: dict[str, Any] | None
    decision: dict[str, Any]


@dataclass(frozen=True)
class WholeDeckAdmissionResult:
    review_path: Path
    decision_path: Path
    decision: dict[str, Any]


def _receipt(workspace: Path, receipt_path: Path) -> tuple[Path, dict[str, Any]]:
    path = ensure_within(workspace.resolve(), receipt_path)
    data = read_json(path)
    if data.get("schema_version") != "0.3.0":
        raise VisualQualityError("Visual calibration requires Host Candidate Receipt 0.3")
    if data.get("status") != "candidate_office_review_pending":
        raise VisualQualityError("Visual calibration requires a successful render candidate")
    if data.get("office", {}).get("status") != "available":
        raise VisualQualityError("Real Office-rendered page evidence is not registered")
    for page in data["office"]["pages"]:
        target = ensure_within(workspace, workspace / str(page["path"]))
        if not target.is_file() or sha256_file(target) != page["sha256"]:
            raise VisualQualityError(
                f"Office page evidence changed or is missing: {page['path']}"
            )
    return path, data


def _image_set(receipt: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "slide_id": str(item["slide_id"]),
            "kind": "office_page",
            "path": str(item["path"]),
            "sha256": str(item["sha256"]),
        }
        for item in receipt["office"]["pages"]
    ]


class VisualCalibrationService:
    """Use one immutable IR/producer for representative sample and full render."""

    def __init__(
        self,
        workspace: Path,
        *,
        backend: ArtifactToolRenderBackend,
        reviewer: VisualReviewProvider,
        author_identities: tuple[str, ...] = (),
    ) -> None:
        self.workspace = workspace.resolve()
        self.backend = backend
        self.reviewer = reviewer
        self.author_identities = author_identities

    def representative_selection(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        runtime = ArtifactRuntime(self.workspace)
        return representative_slide_selection(
            runtime.show_artifact("deck_outline"),
            runtime.show_artifact("slide_specs"),
        )

    def render_sample(self, preflight: RenderPreflightResult) -> dict[str, Any]:
        selected, _coverage = self.representative_selection()
        return self.backend.render(
            self.workspace,
            preflight,
            slide_ids=selected,
            scope="sample",
        )

    def review_sample(self, receipt_path: Path) -> CalibrationAdmissionResult:
        path, receipt = _receipt(self.workspace, receipt_path)
        if receipt.get("scope") != "sample":
            raise VisualQualityError("Calibration review requires a sample receipt")
        selected, dimensions = self.representative_selection()
        if tuple(receipt["slide_ids"]) != selected:
            raise VisualQualityError(
                "Calibration receipt does not use the deterministic representative selection"
            )
        required_coverage = [
            *[f"slide_{item.lower().replace('-', '')}" for item in selected],
            *dimensions,
        ]
        images = _image_set(receipt)
        paths = tuple(self.workspace / item["path"] for item in images)
        proposal = self.reviewer.review(
            paths,
            {
                "review_stage": "calibration",
                "mode": "office_sample_calibration",
                "receipt": copy.deepcopy(receipt),
                "required_coverage": required_coverage,
                "rules": {
                    "reviewer_emits_findings_not_approval": True,
                    "evaluate": [
                        "hierarchy",
                        "composition",
                        "palette",
                        "typography",
                        "imagery",
                        "carrier_fitness",
                        "office_fidelity",
                    ],
                },
            },
        )
        review_path, _review = persist_visual_quality_review(
            self.workspace,
            stage="calibration",
            dependency_key=str(receipt["dependency_key"]),
            provider=self.reviewer,
            image_set=images,
            coverage=required_coverage,
            proposal=proposal,
            author_identities=self.author_identities,
        )
        decision_path, decision = derive_visual_quality_decision(
            self.workspace,
            review_path=review_path,
            required_coverage=required_coverage,
        )
        if not decision["quality_approved"]:
            return CalibrationAdmissionResult(
                review_path=review_path,
                decision_path=decision_path,
                reference_set_path=None,
                authorization=None,
                decision=decision,
            )
        reference_path, _reference = persist_visual_reference_set(
            self.workspace,
            receipt_path=path,
            decision_path=decision_path,
        )
        authorization = {
            "dependency_key": str(receipt["dependency_key"]),
            "decision_path": decision_path.relative_to(self.workspace).as_posix(),
            "reference_set_path": reference_path.relative_to(self.workspace).as_posix(),
            "renderer_ir_sha256": str(receipt["renderer_ir"]["sha256"]),
            "producer": copy.deepcopy(receipt["producer_identity"]),
        }
        return CalibrationAdmissionResult(
            review_path=review_path,
            decision_path=decision_path,
            reference_set_path=reference_path,
            authorization=authorization,
            decision=decision,
        )

    def render_full(
        self,
        preflight: RenderPreflightResult,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        return self.backend.render(
            self.workspace,
            preflight,
            scope="full",
            calibration_authorization=authorization,
        )

    def review_whole_deck(self, receipt_path: Path) -> WholeDeckAdmissionResult:
        path, receipt = _receipt(self.workspace, receipt_path)
        if receipt.get("scope") != "full":
            raise VisualQualityError("Whole-deck review requires a full receipt")
        runtime = ArtifactRuntime(self.workspace)
        expected = tuple(
            str(item["slide_id"])
            for item in runtime.show_artifact("slide_specs")["slides"]
        )
        if tuple(receipt["slide_ids"]) != expected:
            raise VisualQualityError("Whole-deck Office evidence does not cover the full deck")
        required_coverage = [
            "whole_deck",
            "deck_rhythm",
            *[f"slide_{item.lower().replace('-', '')}" for item in expected],
        ]
        dependency = "sha256:" + sha256_json(
            {
                "kind": "whole_deck_office_review",
                "calibration_dependency": receipt["dependency_key"],
                "receipt_sha256": sha256_file(path),
                "office_pages": receipt["office"]["pages"],
            }
        )
        images = _image_set(receipt)
        proposal = self.reviewer.review(
            tuple(self.workspace / item["path"] for item in images),
            {
                "review_stage": "whole_deck",
                "mode": "office_whole_deck_admission",
                "receipt": copy.deepcopy(receipt),
                "required_coverage": required_coverage,
                "rules": {
                    "reviewer_emits_findings_not_approval": True,
                    "evaluate": [
                        "whole_deck_rhythm",
                        "repetition",
                        "visual_hierarchy",
                        "palette_distribution",
                        "imagery_distribution",
                        "office_fidelity",
                    ],
                },
            },
        )
        review_path, _review = persist_visual_quality_review(
            self.workspace,
            stage="whole_deck",
            dependency_key=dependency,
            provider=self.reviewer,
            image_set=images,
            coverage=required_coverage,
            proposal=proposal,
            author_identities=self.author_identities,
        )
        decision_path, decision = derive_visual_quality_decision(
            self.workspace,
            review_path=review_path,
            required_coverage=required_coverage,
        )
        return WholeDeckAdmissionResult(
            review_path=review_path,
            decision_path=decision_path,
            decision=decision,
        )
