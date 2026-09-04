from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.art_direction_seed import validate_seed_reference_for_graph
from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.constants import SCHEMA_VERSION
from slidethus.errors import ArtifactError, LayoutPlanningError, PlanningError
from slidethus.gates import evaluate_gate
from slidethus.io_utils import (
    atomic_create_bytes,
    atomic_write_bytes,
    sha256_bytes,
    sha256_json,
)
from slidethus.layout_geometry import admit_authored_layout, build_layout_plan
from slidethus.planning_limits import (
    admit_planning_proposal,
    validate_planning_limits,
)
from slidethus.planning_lineage import (
    accepted_gate_current,
    build_planning_lineage,
    planning_artifact_reusable,
    reuse_semantically_current_lineage,
)
from slidethus.planning_provider import DeterministicPlanningProvider
from slidethus.planning_rules import layout_gate_reasons, slide_spec_content_hash
from slidethus.protocols import PlanningLimits, PlanningProvider
from slidethus.semantic_preview import render_semantic_previews
from slidethus.visual_quality import quality_path_required
from slidethus.wireframe import build_wireframe_svg


@dataclass(frozen=True)
class LayoutPlanningResult:
    """One versioned Production Layout Plans and immutable wireframe result."""

    layout_plans: dict[str, Any]
    changed: bool
    version: int
    wireframe_paths: tuple[Path, ...]
    gate_reasons: tuple[str, ...]


def _text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()[:limit]


def _generated_at(graph: dict[str, dict[str, Any]]) -> str:
    values = [
        str(item.get("updated_at") or "")
        for item in graph.values()
        if item.get("updated_at")
    ]
    return max(values) if values else utc_now()


class LayoutPlanningService:
    """Map every current Block to safe-area geometry and immutable gray wireframes."""

    def __init__(
        self,
        workspace: Path,
        *,
        provider: PlanningProvider | None = None,
        runtime: ArtifactRuntime | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.provider = provider or DeterministicPlanningProvider()
        self.provider_name = _text(getattr(self.provider, "name", ""), limit=128)
        self.provider_version = _text(
            getattr(self.provider, "version", ""), limit=128
        )
        if not self.provider_name or not self.provider_version:
            raise LayoutPlanningError(
                "Planning provider must declare bounded name and version"
            )
        self.immutable_dir = self.workspace / ".slidethus/planning/wireframes"
        self.current_dir = self.workspace / "outputs/wireframes"

    def _proposal(self, context: dict[str, Any], limits: PlanningLimits):
        try:
            proposal = self.provider.propose("layout_plans", context, limits)
        except PlanningError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LayoutPlanningError(f"Planning provider failed: {exc}") from exc
        if _text(getattr(self.provider, "name", ""), limit=128) != self.provider_name or _text(
            getattr(self.provider, "version", ""), limit=128
        ) != self.provider_version:
            raise LayoutPlanningError(
                "Planning provider identity changed during Layout generation"
            )
        return admit_planning_proposal(
            proposal,
            artifact_type="layout_plans",
            limits=limits,
        )

    def _wireframes(
        self,
        specs: dict[str, Any],
        plans: list[dict[str, Any]],
        *,
        canvas: dict[str, int],
        safe_area: dict[str, float],
    ) -> tuple[list[dict[str, Any]], tuple[Path, ...]]:
        specs_by_id = {
            str(item["slide_id"]): item for item in specs.get("slides", [])
        }
        references: list[dict[str, Any]] = []
        current_paths: list[Path] = []
        for plan in plans:
            slide_id = str(plan["slide_id"])
            svg = build_wireframe_svg(
                specs_by_id[slide_id],
                plan,
                width=int(canvas["width"]),
                height=int(canvas["height"]),
                safe_area=safe_area,
            )
            payload = svg.encode("utf-8")
            digest = sha256_bytes(payload)
            immutable_path = self.immutable_dir / f"{digest}.svg"
            created = atomic_create_bytes(immutable_path, payload)
            if not created and immutable_path.read_bytes() != payload:
                raise LayoutPlanningError(
                    f"Immutable wireframe path contains different content: {immutable_path}"
                )
            current_path = self.current_dir / f"{slide_id}.svg"
            atomic_write_bytes(current_path, payload)
            current_paths.append(current_path)
            references.append(
                {
                    "slide_id": slide_id,
                    "path": immutable_path.relative_to(self.workspace).as_posix(),
                    "sha256": digest,
                    "mime_type": "image/svg+xml",
                    "width": int(canvas["width"]),
                    "height": int(canvas["height"]),
                }
            )
        return references, tuple(current_paths)

    def _admit_representation_view(
        self,
        raw: dict[str, Any],
        *,
        slide: dict[str, Any],
        plan: dict[str, Any],
        canvas: dict[str, int],
    ) -> None:
        """Bind placement/view geometry to the P5A representation without copying semantics."""

        slide_id = str(slide["slide_id"])
        representation = slide.get("representation")
        if not isinstance(representation, dict):
            raise LayoutPlanningError(
                f"Reviewed/critical Layout {slide_id} requires P5A representation"
            )
        view = copy.deepcopy(raw.get("view"))
        if not isinstance(view, dict):
            raise LayoutPlanningError(
                f"Reviewed/critical Layout {slide_id} requires executable view geometry"
            )
        view["kind"] = str(representation["kind"])
        root_schema = self.runtime.registry.schema("layout_plans")
        schema = {
            "$schema": root_schema["$schema"],
            "$ref": "#/$defs/representationView",
            "$defs": root_schema["$defs"],
        }
        errors = sorted(
            Draft202012Validator(schema).iter_errors(view),
            key=lambda item: list(item.absolute_path),
        )
        if errors:
            raise LayoutPlanningError(
                f"Invalid representation view for {slide_id}: "
                + "; ".join(f"{item.json_path}: {item.message}" for item in errors)
            )
        region_ids = {str(item["region_id"]) for item in plan["regions"]}
        block_by_region = {
            str(item["region_id"]): str(item["block_id"])
            for item in plan["regions"]
        }
        blocks = {str(item["block_id"]): item for item in slide["content_blocks"]}
        primary_region = str(view["primary_region_id"])
        if primary_region not in region_ids:
            raise LayoutPlanningError(
                f"Representation view for {slide_id} references unknown primary region"
            )
        kind = str(representation["kind"])
        primary_type = str(blocks[block_by_region[primary_region]]["content_type"])
        if kind in {"image", "chart", "table", "diagram"} and primary_type != kind:
            raise LayoutPlanningError(
                f"Representation view for {slide_id} places {kind} on a {primary_type} Block"
            )
        focal = [str(item) for item in raw.get("focal_order", [])]
        if len(focal) != len(set(focal)) or set(focal) != region_ids:
            raise LayoutPlanningError(
                f"Layout {slide_id} focal_order must cover every Region exactly once"
            )
        if focal[0] != primary_region:
            raise LayoutPlanningError(
                f"Layout {slide_id} first focal Region must be representation primary_region_id"
            )
        occupied = sum(
            float(item["w"]) * float(item["h"]) for item in plan["regions"]
        ) / (float(canvas["width"]) * float(canvas["height"]))
        expected_space = "compact" if occupied >= 0.62 else ("balanced" if occupied >= 0.36 else "expansive")
        if view["negative_space"] != expected_space:
            raise LayoutPlanningError(
                f"Layout {slide_id} negative_space must be {expected_space} for observable geometry"
            )
        details = view["details"]
        semantics = representation["semantics"]
        if kind == "diagram":
            node_ids = {str(item["id"]) for item in semantics["nodes"]}
            geometry_ids = {str(item["node_id"]) for item in details["node_geometry"]}
            if node_ids != geometry_ids:
                raise LayoutPlanningError(
                    f"Diagram view for {slide_id} must place every semantic node exactly once"
                )
            for item in details["node_geometry"]:
                if float(item["x"]) + float(item["w"]) > 1 or float(item["y"]) + float(item["h"]) > 1:
                    raise LayoutPlanningError(
                        f"Diagram node geometry exceeds normalized bounds on {slide_id}"
                    )
            edge_ids = {str(item["id"]) for item in semantics["edges"]}
            route_ids = {str(item["edge_id"]) for item in details["routing"]}
            if edge_ids != route_ids:
                raise LayoutPlanningError(
                    f"Diagram view for {slide_id} must route every semantic edge exactly once"
                )
            if not {
                str(item["edge_id"]) for item in details["label_anchors"]
            }.issubset(edge_ids):
                raise LayoutPlanningError(
                    f"Diagram label anchor on {slide_id} references an unknown edge"
                )
        elif kind == "table":
            emphasized = details["emphasized_column"]
            if emphasized is not None and int(emphasized) >= len(semantics["columns"]):
                raise LayoutPlanningError(
                    f"Table emphasized column is outside the P5A schema on {slide_id}"
                )
        elif kind == "image":
            if details["fit"] not in {"cover", "contain"}:
                raise LayoutPlanningError(f"Image fit is unsupported on {slide_id}")
        plan.update(
            {
                "representation_ref": {
                    "representation_id": str(representation["representation_id"]),
                    "content_hash": "sha256:" + sha256_json(representation),
                },
                "focal_order": focal,
                "view": view,
            }
        )

    def _admit(
        self,
        proposal_content: dict[str, Any],
        *,
        graph: dict[str, dict[str, Any]],
        warnings: tuple[str, ...],
        assumptions: tuple[str, ...],
        limits: PlanningLimits,
    ) -> tuple[dict[str, Any], tuple[Path, ...]]:
        brief = graph["project_brief"]["data"]
        outline = graph["deck_outline"]["data"]
        specs = graph["slide_specs"]["data"]
        raw_by_id = {
            str(item.get("slide_id")): item
            for item in proposal_content.get("plans", [])
        }
        existing_snapshot = graph.get("layout_plans")
        existing = (
            copy.deepcopy(existing_snapshot["data"])
            if existing_snapshot is not None
            else None
        )
        if existing and existing.get("status") == "frozen":
            raise LayoutPlanningError(
                "Frozen Layout Plans require explicit repair operations, not regeneration"
            )
        existing_by_id = {
            str(item["slide_id"]): item for item in existing.get("plans", [])
        } if existing else {}
        canvas = {"width": 1280, "height": 720}
        safe_area = {"top": 60.0, "right": 80.0, "bottom": 60.0, "left": 80.0}
        if "safe_area" in proposal_content:
            safe_area = copy.deepcopy(proposal_content["safe_area"])
            schema = self.runtime.registry.schema("layout_plans")["properties"]["safe_area"]
            if list(Draft202012Validator(schema).iter_errors(safe_area)):
                raise LayoutPlanningError("Invalid authored safe_area")
        if len(raw_by_id) != len(proposal_content.get("plans", [])) or set(raw_by_id) != {
            slide["slide_id"] for slide in specs.get("slides", [])
        }:
            raise LayoutPlanningError("Layout proposal contains duplicate or mismatched slides")
        if len(specs.get("slides", [])) > limits.max_slides:
            raise LayoutPlanningError("Slide Specs exceed max_slides")
        plans: list[dict[str, Any]] = []
        for slide in specs.get("slides", []):
            slide_id = str(slide["slide_id"])
            raw = raw_by_id.get(slide_id)
            if raw is None:
                raise LayoutPlanningError(
                    f"Planning provider omitted Slide Spec {slide_id}"
                )
            spec_hash = slide_spec_content_hash(slide)
            prior = existing_by_id.get(slide_id)
            if prior and prior.get("status") == "frozen":
                if quality_path_required(self.workspace) and not prior.get(
                    "representation_ref"
                ):
                    raise LayoutPlanningError(
                        f"Frozen legacy Layout {slide_id} cannot enter the reviewed/critical path"
                    )
                if prior.get("slide_spec_ref", {}).get("content_hash") != spec_hash:
                    raise LayoutPlanningError(
                        f"Frozen Layout Plan {slide_id} is stale for current Slide Spec"
                    )
                plans.append(copy.deepcopy(prior))
                continue
            family = str(raw.get("layout_family") or "")
            suggested = list(
                slide.get("visual_intent", {}).get("suggested_layout_families", [])
            )
            if not family:
                family = str(suggested[0]) if suggested else "custom"
            if family not in set(suggested):
                raise LayoutPlanningError(
                    f"Layout provider selected {family} outside Slide Spec intent for {slide_id}"
                )
            plan = (
                admit_authored_layout(
                    slide,
                    {
                        key: copy.deepcopy(raw[key])
                        for key in (
                            "slide_id",
                            "layout_family",
                            "regions",
                            "rationale",
                        )
                        if key in raw
                    },
                )
                if "regions" in raw
                else build_layout_plan(slide, family=family, canvas=canvas, safe_area=safe_area)
            )
            plan.update(
                {
                    "status": "approved",
                    "slide_spec_ref": {
                        "slide_id": slide_id,
                        "content_hash": spec_hash,
                    },
                    "revision_note": _text(
                        prior.get("revision_note") if prior else "",
                        limit=500,
                    ),
                }
            )
            if quality_path_required(self.workspace):
                self._admit_representation_view(
                    raw,
                    slide=slide,
                    plan=plan,
                    canvas=canvas,
                )
            plans.append(plan)
        wireframes, current_paths = self._wireframes(
            specs,
            plans,
            canvas=canvas,
            safe_area=safe_area,
        )
        lineage_inputs = {
            "deck_outline": graph["deck_outline"],
            "project_brief": graph["project_brief"],
            "slide_specs": graph["slide_specs"],
        }
        lineage = build_planning_lineage(
            lineage_inputs,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            proposal=copy.deepcopy(proposal_content),
            policy={"service": "layout", "limits": asdict(limits)},
            generated_at=_generated_at(lineage_inputs),
            warnings=warnings,
            assumptions=assumptions,
        )
        lineage = reuse_semantically_current_lineage(
            lineage,
            existing.get("planning_lineage") if existing else None,
            lineage_inputs,
            required_inputs=("deck_outline", "project_brief", "slide_specs"),
        )
        return (
            {
                "schema_version": (
                    "0.2.0" if quality_path_required(self.workspace) else SCHEMA_VERSION
                ),
                "project_id": brief["project_id"],
                "deck_id": str(outline["deck_id"]),
                "status": "approved",
                "repair_ids": list(existing.get("repair_ids", [])) if existing else [],
                "planning_lineage": lineage,
                "canvas": canvas,
                "safe_area": safe_area,
                "wireframes": wireframes,
                "plans": plans,
            },
            current_paths,
        )

    def generate(
        self,
        *,
        limits: PlanningLimits | None = None,
        force: bool = False,
        created_by: str = "layout-planning-service",
    ) -> LayoutPlanningResult:
        """Generate current Layout Plans and immutable wireframes after G5A."""

        admitted_limits = limits or PlanningLimits()
        validate_planning_limits(admitted_limits)
        g5a = evaluate_gate(self.workspace, "G5A")
        if not g5a.passed:
            raise LayoutPlanningError(
                "G5A must pass before Layout generation: " + "; ".join(g5a.reasons)
            )
        graph = self.runtime.read_artifact_graph_snapshot(
            (
                "project_brief",
                "deck_outline",
                "slide_specs",
                "layout_plans",
            ),
            optional_artifact_types=("layout_plans",),
        )
        existing = graph.get("layout_plans")
        current_policy = {"service": "layout", "limits": asdict(admitted_limits)}
        if (
            not force
            and existing is not None
            and str(existing["data"].get("schema_version", "")).startswith(
                "0.2." if quality_path_required(self.workspace) else "0.1."
            )
            and planning_artifact_reusable(
                existing["data"],
                graph,
                artifact_status=str(existing["status"]),
                gate_current=accepted_gate_current(
                    self.runtime.show_artifact("project_state"), "G5B"
                ),
                required_inputs=("deck_outline", "project_brief", "slide_specs"),
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                policy=current_policy,
            )
        ):
            reasons = layout_gate_reasons(
                self.workspace,
                brief=graph["project_brief"]["data"],
                outline=graph["deck_outline"]["data"],
                slide_specs=graph["slide_specs"]["data"],
                layout_plans=existing["data"],
                graph=graph,
            )
            if not reasons:
                if quality_path_required(self.workspace):
                    render_semantic_previews(self.workspace, runtime=self.runtime)
                return LayoutPlanningResult(
                    layout_plans=copy.deepcopy(existing["data"]),
                    changed=False,
                    version=int(existing["version"]),
                    wireframe_paths=tuple(
                        self.workspace / str(item["path"])
                        for item in existing["data"].get("wireframes", [])
                    ),
                    gate_reasons=(),
                )
        context = {
            "project_brief": copy.deepcopy(graph["project_brief"]["data"]),
            "deck_outline": copy.deepcopy(graph["deck_outline"]["data"]),
            "slide_specs": copy.deepcopy(graph["slide_specs"]["data"]),
        }
        seed_ref = graph["slide_specs"]["data"].get("art_direction_seed")
        if seed_ref is not None:
            try:
                context["art_direction_seed"] = validate_seed_reference_for_graph(
                    self.workspace,
                    seed_ref,
                    {
                        "project_brief": graph["project_brief"],
                        "deck_outline": graph["deck_outline"],
                    },
                    schema_registry=self.runtime.registry,
                )
            except ArtifactError as exc:
                raise LayoutPlanningError(str(exc)) from exc
        proposal = self._proposal(context, admitted_limits)
        candidate, wireframe_paths = self._admit(
            proposal.content,
            graph=graph,
            warnings=proposal.warnings,
            assumptions=proposal.assumptions,
            limits=admitted_limits,
        )
        reasons = layout_gate_reasons(
            self.workspace,
            brief=graph["project_brief"]["data"],
            outline=graph["deck_outline"]["data"],
            slide_specs=graph["slide_specs"]["data"],
            layout_plans=candidate,
            graph=graph,
        )
        if reasons:
            raise LayoutPlanningError(
                "Layout proposal does not meet Production gate: " + "; ".join(reasons)
            )
        existing = graph.get("layout_plans")
        if existing is not None and existing["data"] == candidate:
            return LayoutPlanningResult(
                layout_plans=copy.deepcopy(candidate),
                changed=False,
                version=int(existing["version"]),
                wireframe_paths=wireframe_paths,
                gate_reasons=(),
            )
        expected_version = int(existing["version"]) if existing is not None else 0
        entry = self.runtime.write_artifact(
            "layout_plans",
            candidate,
            expected_version=expected_version,
            status="approved",
            created_by=created_by,
        )
        if quality_path_required(self.workspace):
            render_semantic_previews(self.workspace, runtime=self.runtime)
        return LayoutPlanningResult(
            layout_plans=self.runtime.show_artifact("layout_plans"),
            changed=True,
            version=int(entry["version"]),
            wireframe_paths=wireframe_paths,
            gate_reasons=(),
        )

    def audit(self) -> tuple[str, ...]:
        """Audit current Layout Plans, geometry, capacity, lineage and wireframes."""

        graph = self.runtime.read_artifact_graph_snapshot(
            ("project_brief", "deck_outline", "slide_specs", "layout_plans")
        )
        return layout_gate_reasons(
            self.workspace,
            brief=graph["project_brief"]["data"],
            outline=graph["deck_outline"]["data"],
            slide_specs=graph["slide_specs"]["data"],
            layout_plans=graph["layout_plans"]["data"],
            graph=graph,
        )
