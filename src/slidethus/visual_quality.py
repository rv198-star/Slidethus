"""Quality-by-construction facts, immutable review history and render admission."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus.artifact_runtime import ArtifactRuntime, utc_now
from slidethus.errors import VisualQualityError
from slidethus.io_utils import (
    atomic_create_json,
    ensure_within,
    read_json,
    sha256_file,
    sha256_json,
)
from slidethus.schema_registry import SchemaRegistry

POLICY_VERSION = "1.0.0"
SELECTION_POLICY_VERSION = "1.0.0"
QUALITY_ROOT = Path(".slidethus/visual-quality")
_SCHEMAS = {
    "policy": "visual_admission_policy.schema.json",
    "preview": "semantic_preview_receipt.schema.json",
    "review": "visual_quality_review.schema.json",
    "decision": "visual_quality_decision.schema.json",
    "adjudication": "review_adjudication.schema.json",
    "reference_set": "visual_reference_set.schema.json",
}
_STAGE_ROOTS = {
    "direction": QUALITY_ROOT / "direction/reviews",
    "planning": QUALITY_ROOT / "planning/reviews",
    "calibration": QUALITY_ROOT / "calibration/reviews",
    "whole_deck": QUALITY_ROOT / "whole-deck/reviews",
}
_DECISION_ROOTS = {
    stage: Path(str(root).replace("/reviews", "/decisions"))
    for stage, root in _STAGE_ROOTS.items()
}
_REQUIRED_CAPABILITY = {
    "direction": "native_prototype",
    "planning": "semantic_preview",
    "calibration": "office_pages",
    "whole_deck": "whole_deck",
}


def _schema(schema_dir: Path, kind: str) -> dict[str, Any]:
    path = schema_dir / _SCHEMAS[kind]
    if not path.is_file():
        raise VisualQualityError(f"Missing visual-quality schema: {path}")
    schema = read_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def _schema_errors(data: dict[str, Any], schema_dir: Path, kind: str) -> list[str]:
    return [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(_schema(schema_dir, kind)).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]


def _identity(data: dict[str, Any], field: str, prefix: str) -> str:
    payload = copy.deepcopy(data)
    payload.pop(field, None)
    return prefix + sha256_json(payload)[:16].upper()


def _artifact_ref(snapshot: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "version": int(snapshot["version"]),
        "content_hash": str(snapshot["content_hash"]),
    }


def _unlocked_snapshot(workspace: Path, artifact_type: str) -> dict[str, Any]:
    """Read one current registry entry without taking the already-held runtime lock."""

    state = read_json(workspace / "project_state.json")
    entry = next(
        (
            item
            for item in state.get("artifacts", [])
            if item.get("artifact_type") == artifact_type
        ),
        None,
    )
    if entry is None:
        raise VisualQualityError(f"Current artifact is missing: {artifact_type}")
    return {**copy.deepcopy(entry), "data": read_json(workspace / str(entry["path"]))}


def _file_ref(workspace: Path, path: Path, identity: str) -> dict[str, str]:
    safe = ensure_within(workspace, path)
    if not safe.is_file():
        raise VisualQualityError(f"Visual-quality fact is missing: {safe}")
    return {
        "id": identity,
        "path": safe.relative_to(workspace).as_posix(),
        "sha256": sha256_file(safe),
    }


def _persist_fact(
    workspace: Path,
    data: dict[str, Any],
    *,
    kind: str,
    root: Path,
    identity_field: str,
    prefix: str,
    schema_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    admitted = (schema_dir or SchemaRegistry().schema_dir).resolve()
    candidate = copy.deepcopy(data)
    candidate[identity_field] = _identity(candidate, identity_field, prefix)
    errors = _schema_errors(candidate, admitted, kind)
    if errors:
        raise VisualQualityError("Invalid visual-quality fact: " + "; ".join(errors))
    path = workspace / root / f"{sha256_json(candidate)}.json"
    created = atomic_create_json(path, candidate)
    if not created and read_json(path) != candidate:
        raise VisualQualityError(f"Immutable visual-quality fact differs: {path}")
    return path, candidate


def build_visual_admission_policy(
    workspace: Path,
    *,
    runtime: ArtifactRuntime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Derive and persist risk/evidence policy from the exact current Brief."""

    workspace = workspace.resolve()
    admitted_runtime = runtime
    snapshot = (
        admitted_runtime.read_artifact_graph_snapshot(("project_brief",))[
            "project_brief"
        ]
        if admitted_runtime is not None
        else _unlocked_snapshot(workspace, "project_brief")
    )
    brief = snapshot["data"]
    quality = str(brief["quality_profile"])
    approval = str(brief["approval_mode"])
    risk = {"draft": "controlled", "standard": "reviewed", "critical": "critical"}[
        quality
    ]
    required = risk != "controlled"
    reasons = [f"quality_profile_{quality}"]
    if approval == "auto" and required:
        reasons.append("auto_requires_independent_evidence")
    candidate = {
        "schema_version": "0.1.0",
        "project_id": str(brief["project_id"]),
        "policy_id": "",
        "generated_at": str(snapshot.get("updated_at") or utc_now()),
        "policy_version": POLICY_VERSION,
        "brief_ref": _artifact_ref(snapshot, "project_brief"),
        "risk_class": risk,
        "reason_codes": sorted(reasons),
        "approval_mode": approval,
        "required_evidence": {
            "direction": required,
            "semantic_preview": required,
            "calibration": required,
            "whole_deck_office": required,
        },
        "approval_authority_policy": (
            "workflow_derived" if approval == "auto" else "human_checkpoint"
        ),
        "reviewer_requirements": {
            "independent_from_author": required,
            "office_image_capable": required,
            "immutable_findings": True,
        },
    }
    return _persist_fact(
        workspace,
        candidate,
        kind="policy",
        root=QUALITY_ROOT / "policies",
        identity_field="policy_id",
        prefix="VAP-",
    )


def current_visual_admission_policy(
    workspace: Path,
    *,
    create: bool = False,
    runtime: ArtifactRuntime | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Return the policy bound to the current Brief; optionally derive it."""

    workspace = workspace.resolve()
    admitted_runtime = runtime
    snapshot = (
        admitted_runtime.read_artifact_graph_snapshot(("project_brief",))[
            "project_brief"
        ]
        if admitted_runtime is not None
        else _unlocked_snapshot(workspace, "project_brief")
    )
    expected = _artifact_ref(snapshot, "project_brief")
    root = workspace / QUALITY_ROOT / "policies"
    if root.exists():
        for path in sorted(root.glob("*.json")):
            data = read_json(path)
            if data.get("brief_ref") == expected and data.get("policy_version") == POLICY_VERSION:
                errors = validate_visual_policy_data(data, SchemaRegistry().schema_dir)
                if errors:
                    raise VisualQualityError("Invalid VisualAdmissionPolicy: " + "; ".join(errors))
                return path, data
    return build_visual_admission_policy(workspace, runtime=admitted_runtime) if create else None


def validate_visual_policy_data(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    errors = _schema_errors(data, schema_dir, "policy")
    if errors:
        return tuple(errors)
    if data.get("policy_id") != _identity(data, "policy_id", "VAP-"):
        errors.append("VisualAdmissionPolicy identity mismatch")
    required = data.get("risk_class") != "controlled"
    if any(bool(value) != required for value in data.get("required_evidence", {}).values()):
        errors.append("VisualAdmissionPolicy evidence requirements disagree with risk_class")
    return tuple(errors)


def persist_semantic_preview_receipt(
    workspace: Path, data: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    """Persist one content-addressed semantic planning preview receipt."""

    return _persist_fact(
        workspace.resolve(),
        data,
        kind="preview",
        root=QUALITY_ROOT / "planning/semantic-previews",
        identity_field="receipt_id",
        prefix="SPR-",
    )


def current_semantic_preview_receipt(
    workspace: Path,
) -> tuple[Path, dict[str, Any]] | None:
    """Return the semantic preview receipt bound to exact current planning artifacts."""

    workspace = workspace.resolve()
    graph = {
        artifact_type: _unlocked_snapshot(workspace, artifact_type)
        for artifact_type in (
            "project_brief",
            "deck_outline",
            "slide_specs",
            "layout_plans",
        )
    }
    expected = [
        _artifact_ref(snapshot, artifact_type)
        for artifact_type, snapshot in sorted(graph.items())
    ]
    root = workspace / QUALITY_ROOT / "planning/semantic-previews"
    if not root.exists():
        return None
    for path in sorted(root.glob("*.json")):
        data = read_json(path)
        if data.get("inputs") != expected:
            continue
        errors = _schema_errors(data, SchemaRegistry().schema_dir, "preview")
        if data.get("receipt_id") != _identity(data, "receipt_id", "SPR-"):
            errors.append("Semantic Preview Receipt identity mismatch")
        for page in data.get("pages", []):
            try:
                target = ensure_within(workspace, workspace / str(page["path"]))
                if not target.is_file() or sha256_file(target) != page.get("sha256"):
                    errors.append(f"Semantic preview page mismatch: {page.get('path')}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Semantic preview page is invalid: {exc}")
        if errors:
            raise VisualQualityError("Invalid semantic preview receipt: " + "; ".join(errors))
        return path, data
    return None


def planning_admission_dependency_key(
    policy: dict[str, Any], receipt: dict[str, Any]
) -> str:
    return "sha256:" + sha256_json(
        {
            "kind": "planning_admission",
            "policy_id": policy["policy_id"],
            "policy_version": policy["policy_version"],
            "preview_receipt_id": receipt["receipt_id"],
            "preview_receipt_hash": "sha256:" + sha256_json(receipt),
        }
    )


def current_visual_quality_decision(
    workspace: Path,
    *,
    stage: str,
    dependency_key: str,
) -> tuple[Path, dict[str, Any]] | None:
    root = workspace.resolve() / _DECISION_ROOTS[stage]
    if not root.exists():
        return None
    for path in sorted(root.glob("*.json"), reverse=True):
        data = read_json(path)
        if data.get("dependency_key") == dependency_key:
            return path, data
    return None


def planning_admission_errors(workspace: Path) -> tuple[str, ...]:
    """Return G5B blockers for a reviewed/critical semantic preview admission."""

    current = current_visual_admission_policy(workspace, create=False)
    if current is None or current[1]["risk_class"] == "controlled":
        return ()
    preview = current_semantic_preview_receipt(workspace)
    if preview is None:
        return ("reviewed/critical G5B requires a current semantic preview receipt",)
    dependency = planning_admission_dependency_key(current[1], preview[1])
    decision = current_visual_quality_decision(
        workspace,
        stage="planning",
        dependency_key=dependency,
    )
    if decision is None:
        return ("reviewed/critical G5B requires a current qualitative planning decision",)
    data = decision[1]
    if data.get("outcome") != "approved" or not data.get("quality_approved"):
        return (
            "qualitative planning decision is not approved: "
            + ", ".join(str(item) for item in data.get("open_finding_ids", [])),
        )
    return ()


def whole_deck_admission_errors(workspace: Path) -> tuple[str, ...]:
    """Return P8 blockers for the current full Office-rendered candidate."""

    current = current_visual_admission_policy(workspace, create=False)
    if current is None or current[1]["risk_class"] == "controlled":
        return ()
    root = workspace.resolve() / "outputs/host-candidates"
    candidates: list[tuple[Path, dict[str, Any]]] = []
    if root.exists():
        for path in sorted(root.glob("candidate-*/receipt*.json"), reverse=True):
            data = read_json(path)
            if (
                data.get("schema_version") == "0.3.0"
                and data.get("scope") == "full"
                and data.get("office", {}).get("status") == "available"
            ):
                candidates.append((path, data))
    if not candidates:
        return ("reviewed/critical P8 requires a full Office-rendered receipt",)
    current_artifacts = {
        str(item["artifact_type"]): item
        for item in read_json(workspace / "project_state.json").get("artifacts", [])
    }
    observed_blockers: list[str] = []
    for path, receipt in candidates:
        if any(
            current_artifacts.get(str(ref["artifact_type"]), {}).get("content_hash")
            != ref.get("content_hash")
            for ref in receipt.get("artifacts", [])
        ):
            continue
        dependency = "sha256:" + sha256_json(
            {
                "kind": "whole_deck_office_review",
                "calibration_dependency": receipt["dependency_key"],
                "receipt_sha256": sha256_file(path),
                "office_pages": receipt["office"]["pages"],
            }
        )
        decision = current_visual_quality_decision(
            workspace,
            stage="whole_deck",
            dependency_key=dependency,
        )
        if decision is None:
            continue
        if decision[1].get("quality_approved"):
            return ()
        observed_blockers.extend(decision[1].get("open_finding_ids", []))
    if observed_blockers:
        return (
            "whole-deck review has unresolved blockers: "
            + ", ".join(sorted(set(observed_blockers))),
        )
    return ("reviewed/critical P8 requires a current whole-deck decision",)


def quality_path_required(workspace: Path) -> bool:
    current = current_visual_admission_policy(workspace, create=False)
    return bool(current and current[1].get("risk_class") in {"reviewed", "critical"})


def reviewer_identity(
    provider: Any,
    *,
    required_capability: str,
    author_identities: Iterable[str] = (),
) -> dict[str, Any]:
    """Admit a bounded reviewer identity and calculate independence."""

    name = str(getattr(provider, "name", "")).strip()
    version = str(getattr(provider, "version", "")).strip()
    capabilities = sorted(set(str(item) for item in getattr(provider, "capabilities", ())))
    if not name or not version or len(name) > 128 or len(version) > 128:
        raise VisualQualityError("Visual reviewer must declare bounded name/version")
    if required_capability not in capabilities:
        raise VisualQualityError(
            f"Visual reviewer {name}@{version} lacks capability {required_capability}"
        )
    authors = {str(item).strip() for item in author_identities if str(item).strip()}
    return {
        "name": name,
        "version": version,
        "capabilities": capabilities,
        "independent_from_author": name not in authors,
    }


def _normalize_text(value: Any, field: str, *, limit: int = 4000) -> str:
    text = " ".join(str(value or "").split()).strip()[:limit]
    if not text:
        raise VisualQualityError(f"Visual finding requires {field}")
    return text


def _finding_id(item: dict[str, Any]) -> str:
    """Exclude severity so downgrade cannot manufacture a new finding identity."""

    payload = {
        "dimension": item.get("dimension"),
        "normalized_issue": item.get("normalized_issue"),
        "slide_id": item.get("slide_id"),
        "page_sha256": item.get("page_sha256"),
        "location": item.get("location"),
    }
    return "VQF-" + sha256_json(payload)[:16].upper()


def persist_visual_quality_review(
    workspace: Path,
    *,
    stage: str,
    dependency_key: str,
    provider: Any,
    image_set: Sequence[dict[str, str]],
    coverage: Sequence[str],
    proposal: dict[str, Any],
    author_identities: Iterable[str] = (),
) -> tuple[Path, dict[str, Any]]:
    """Admit reviewer findings as immutable evidence; reviewers never author pass."""

    workspace = workspace.resolve()
    if stage not in _STAGE_ROOTS:
        raise VisualQualityError(f"Unknown visual-quality review stage: {stage}")
    if not isinstance(proposal, dict) or not isinstance(proposal.get("findings", []), list):
        raise VisualQualityError("Visual reviewer must return an object with findings[]")
    if any(key in proposal for key in ("approved", "outcome", "quality_approved", "status")):
        raise VisualQualityError("Reviewer evidence cannot contain an approval decision")
    images = [copy.deepcopy(item) for item in image_set]
    page_hash = {str(item["slide_id"]): str(item["sha256"]) for item in images}
    findings: list[dict[str, Any]] = []
    for raw in proposal.get("findings", []):
        if not isinstance(raw, dict):
            raise VisualQualityError("Visual findings must be objects")
        slide_id = _normalize_text(raw.get("slide_id"), "slide_id", limit=64)
        if slide_id not in page_hash:
            raise VisualQualityError(f"Visual finding references an unreviewed page: {slide_id}")
        severity = str(raw.get("severity", ""))
        if severity not in {"critical", "major", "minor"}:
            raise VisualQualityError(f"Unsupported visual severity: {severity}")
        owner = str(raw.get("earliest_owner", ""))
        if owner not in {"P4", "direction", "P5A", "P5B", "P6", "P7", "P8"}:
            raise VisualQualityError(f"Unsupported earliest visual owner: {owner}")
        finding = {
            "finding_id": "",
            "dimension": _normalize_text(raw.get("dimension"), "dimension", limit=80)
            .lower()
            .replace(" ", "_"),
            "normalized_issue": _normalize_text(
                raw.get("normalized_issue") or raw.get("finding"),
                "normalized_issue",
                limit=500,
            ).casefold(),
            "severity": severity,
            "earliest_owner": owner,
            "slide_id": slide_id,
            "page_sha256": page_hash[slide_id],
            "location": _normalize_text(raw.get("location", "whole_page"), "location", limit=500),
            "finding": _normalize_text(raw.get("finding"), "finding"),
            "impact": _normalize_text(raw.get("impact"), "impact"),
            "recommended_fix": _normalize_text(raw.get("recommended_fix"), "recommended_fix"),
        }
        finding["finding_id"] = _finding_id(finding)
        findings.append(finding)
    if len({item["finding_id"] for item in findings}) != len(findings):
        raise VisualQualityError("Visual reviewer proposed duplicate finding identities")
    runtime = ArtifactRuntime(workspace)
    project_id = str(runtime.show_artifact("project_state")["project_id"])
    reviewer = reviewer_identity(
        provider,
        required_capability=_REQUIRED_CAPABILITY[stage],
        author_identities=author_identities,
    )
    candidate = {
        "schema_version": "0.1.0",
        "project_id": project_id,
        "review_id": "",
        "generated_at": utc_now(),
        "stage": stage,
        "dependency_key": dependency_key,
        "reviewer": reviewer,
        "image_set": sorted(images, key=lambda item: (item["slide_id"], item["kind"])),
        "coverage": sorted(set(str(item) for item in coverage)),
        "findings": sorted(findings, key=lambda item: item["finding_id"]),
    }
    return _persist_fact(
        workspace,
        candidate,
        kind="review",
        root=_STAGE_ROOTS[stage],
        identity_field="review_id",
        prefix="VQR-",
    )


def validate_visual_quality_review_data(
    data: dict[str, Any], schema_dir: Path
) -> tuple[str, ...]:
    errors = _schema_errors(data, schema_dir, "review")
    if errors:
        return tuple(errors)
    if data.get("review_id") != _identity(data, "review_id", "VQR-"):
        errors.append("Visual Quality Review identity mismatch")
    ids = [str(item.get("finding_id")) for item in data.get("findings", [])]
    if len(ids) != len(set(ids)):
        errors.append("Visual Quality Review contains duplicate findings")
    for item in data.get("findings", []):
        if item.get("finding_id") != _finding_id(item):
            errors.append(f"Visual Quality finding identity mismatch: {item.get('finding_id')}")
    images = {(str(item["slide_id"]), str(item["sha256"])) for item in data.get("image_set", [])}
    for item in data.get("findings", []):
        if (str(item["slide_id"]), str(item["page_sha256"])) not in images:
            errors.append(f"Visual finding page binding mismatch: {item.get('finding_id')}")
    return tuple(errors)


def persist_review_adjudication(
    workspace: Path,
    *,
    review_path: Path,
    finding_id: str,
    resolution: str,
    reason: str,
    authority_kind: str,
    authority_identity: str,
) -> tuple[Path, dict[str, Any]]:
    """Persist an immutable false-positive or accepted-risk fact."""

    workspace = workspace.resolve()
    review = read_json(ensure_within(workspace, review_path))
    if finding_id not in {str(item["finding_id"]) for item in review.get("findings", [])}:
        raise VisualQualityError(f"Adjudication references unknown finding: {finding_id}")
    candidate = {
        "schema_version": "0.1.0",
        "project_id": str(review["project_id"]),
        "adjudication_id": "",
        "generated_at": utc_now(),
        "finding_id": finding_id,
        "review_ref": _file_ref(workspace, review_path, str(review["review_id"])),
        "resolution": resolution,
        "reason": _normalize_text(reason, "reason"),
        "authority": {
            "kind": authority_kind,
            "identity": _normalize_text(authority_identity, "authority identity", limit=256),
        },
    }
    return _persist_fact(
        workspace,
        candidate,
        kind="adjudication",
        root=QUALITY_ROOT / "adjudications",
        identity_field="adjudication_id",
        prefix="VQA-",
    )


def _all_adjudications(workspace: Path) -> list[tuple[Path, dict[str, Any]]]:
    root = workspace / QUALITY_ROOT / "adjudications"
    if not root.exists():
        return []
    return [(path, read_json(path)) for path in sorted(root.glob("*.json"))]


def _historical_blockers(
    workspace: Path,
    review: dict[str, Any],
) -> set[str]:
    """Preserve admitted Critical/Major for unchanged page bytes across re-review."""

    stage_root = workspace / _STAGE_ROOTS[str(review["stage"])]
    current_pages = {str(item["sha256"]) for item in review["image_set"]}
    # Resolution follows the immutable finding identity, not the newest review.
    # Otherwise omitting the old finding from a new review could also omit its
    # valid adjudication and make identical page bytes oscillate between states.
    all_adjudications = _all_adjudications(workspace)
    resolved = {
        str(data["finding_id"])
        for _path, data in all_adjudications
        if data.get("resolution") == "false_positive"
    }
    blockers: set[str] = set()
    for path in sorted(stage_root.glob("*.json")):
        historical = read_json(path)
        for item in historical.get("findings", []):
            if (
                item.get("severity") in {"critical", "major"}
                and str(item.get("page_sha256")) in current_pages
                and str(item.get("finding_id")) not in resolved
            ):
                blockers.add(str(item["finding_id"]))
    return blockers


def derive_visual_quality_decision(
    workspace: Path,
    *,
    review_path: Path,
    required_coverage: Sequence[str],
) -> tuple[Path, dict[str, Any]]:
    """Derive approval mechanically from coverage, independence and immutable history."""

    workspace = workspace.resolve()
    review_path = ensure_within(workspace, review_path)
    review = read_json(review_path)
    errors = validate_visual_quality_review_data(review, SchemaRegistry().schema_dir)
    if errors:
        raise VisualQualityError("Invalid review evidence: " + "; ".join(errors))
    blocking = _historical_blockers(workspace, review)
    relevant_adjudications = [
        (path, data)
        for path, data in _all_adjudications(workspace)
        if str(data.get("finding_id"))
        in {
            str(item["finding_id"])
            for historical_path in sorted(
                (workspace / _STAGE_ROOTS[str(review["stage"])]).glob("*.json")
            )
            for item in read_json(historical_path).get("findings", [])
            if str(item.get("page_sha256"))
            in {str(page["sha256"]) for page in review["image_set"]}
        }
    ]
    required = sorted(set(str(item) for item in required_coverage))
    observed = sorted(set(str(item) for item in review["coverage"]))
    coverage_complete = set(required).issubset(observed)
    independent = bool(review["reviewer"]["independent_from_author"])
    if not coverage_complete or not independent:
        outcome = "blocked"
    elif blocking:
        outcome = "rework"
    else:
        outcome = "approved"
    candidate = {
        "schema_version": "0.1.0",
        "project_id": str(review["project_id"]),
        "decision_id": "",
        "generated_at": utc_now(),
        "kind": str(review["stage"]),
        "dependency_key": str(review["dependency_key"]),
        "review_ref": _file_ref(workspace, review_path, str(review["review_id"])),
        "adjudication_refs": [
            _file_ref(workspace, path, str(data["adjudication_id"]))
            for path, data in relevant_adjudications
        ],
        "required_coverage": required,
        "observed_coverage": observed,
        "open_finding_ids": sorted(blocking),
        "outcome": outcome,
        "quality_approved": outcome == "approved",
    }
    return _persist_fact(
        workspace,
        candidate,
        kind="decision",
        root=_DECISION_ROOTS[str(review["stage"])],
        identity_field="decision_id",
        prefix="VQD-",
    )


def persist_visual_reference_set(
    workspace: Path,
    *,
    receipt_path: Path,
    decision_path: Path,
) -> tuple[Path, dict[str, Any]]:
    """Derive evidence-only accepted pages from one approved calibration decision."""

    workspace = workspace.resolve()
    receipt_path = ensure_within(workspace, receipt_path)
    decision_path = ensure_within(workspace, decision_path)
    receipt = read_json(receipt_path)
    decision = read_json(decision_path)
    if decision.get("kind") != "calibration" or not decision.get("quality_approved"):
        raise VisualQualityError("VisualReferenceSet requires approved calibration decision")
    if receipt.get("scope") != "sample" or receipt.get("dependency_key") != decision.get(
        "dependency_key"
    ):
        raise VisualQualityError("VisualReferenceSet receipt/decision dependency mismatch")
    office_pages = list(receipt.get("office", {}).get("pages", []))
    if not office_pages:
        raise VisualQualityError("VisualReferenceSet requires real Office page refs")
    candidate = {
        "schema_version": "0.1.0",
        "project_id": str(decision["project_id"]),
        "reference_set_id": "",
        "generated_at": utc_now(),
        "dependency_key": str(decision["dependency_key"]),
        "receipt_ref": _file_ref(workspace, receipt_path, str(receipt["attempt_id"])),
        "decision_ref": _file_ref(workspace, decision_path, str(decision["decision_id"])),
        "office_pages": [
            {
                "slide_id": str(item["slide_id"]),
                "path": str(item["path"]),
                "sha256": str(item["sha256"]),
            }
            for item in office_pages
        ],
        "coverage": list(decision["observed_coverage"]),
        "design_authority": False,
    }
    return _persist_fact(
        workspace,
        candidate,
        kind="reference_set",
        root=QUALITY_ROOT / "calibration/reference-sets",
        identity_field="reference_set_id",
        prefix="VRS-",
    )


def representative_slide_selection(
    outline: dict[str, Any], specs: dict[str, Any]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Choose the smallest stable set covering actual high-risk role/carrier classes."""

    outline_by_id = {
        str(item["slide_id"]): item
        for item in outline.get("slides", [])
        if item.get("status") != "excluded"
    }
    dimensions_by_slide: dict[str, set[str]] = {}
    for slide in specs.get("slides", []):
        slide_id = str(slide["slide_id"])
        role = str(outline_by_id[slide_id]["slide_type"])
        kind = str(slide.get("representation", {}).get("kind", "text"))
        dimensions = {f"role_{role}", f"representation_{kind}"}
        if role == "cover":
            dimensions.add("statement_cover")
        if kind == "chart":
            dimensions.add("quantitative_evidence")
        if kind == "image":
            dimensions.add("image_led_story")
        if kind == "diagram":
            dimensions.add("material_diagram")
        if kind in {"table", "mixed"} or role in {"matrix", "architecture", "comparison"}:
            dimensions.add("dense_decision")
        dimensions_by_slide[slide_id] = dimensions
    required = {
        dimension
        for dimensions in dimensions_by_slide.values()
        for dimension in dimensions
        if dimension
        in {
            "statement_cover",
            "quantitative_evidence",
            "image_led_story",
            "material_diagram",
            "dense_decision",
        }
    }
    if not required:
        required = {"role_" + str(next(iter(outline_by_id.values()))["slide_type"])}
    selected: list[str] = []
    uncovered = set(required)
    ordered_ids = list(outline_by_id)
    while uncovered:
        best = max(
            ordered_ids,
            key=lambda slide_id: (
                len(dimensions_by_slide[slide_id] & uncovered),
                -ordered_ids.index(slide_id),
            ),
        )
        gained = dimensions_by_slide[best] & uncovered
        if not gained:
            raise VisualQualityError("Representative selection cannot cover required dimensions")
        selected.append(best)
        uncovered -= gained
        ordered_ids.remove(best)
    return tuple(selected), tuple(sorted(required))


def calibration_dependency_key(payload: dict[str, Any]) -> str:
    """Hash the complete conservative sample/full dependency tuple."""

    return "sha256:" + sha256_json(payload)


class RenderAdmissionPolicy:
    """Shared fail-closed policy for every formal full-render entry."""

    @staticmethod
    def assert_full_render(
        workspace: Path,
        *,
        dependency_key: str | None,
        renderer_ir_sha256: str,
        producer: dict[str, Any],
        authorization: dict[str, Any] | None,
    ) -> None:
        current = current_visual_admission_policy(workspace, create=False)
        if current is None or current[1]["risk_class"] == "controlled":
            return
        if dependency_key is None or authorization is None:
            raise VisualQualityError(
                "Reviewed/critical full render requires current approved calibration authorization"
            )
        decision_path = ensure_within(workspace, workspace / str(authorization["decision_path"]))
        reference_path = ensure_within(
            workspace, workspace / str(authorization["reference_set_path"])
        )
        decision = read_json(decision_path)
        reference = read_json(reference_path)
        failures: list[str] = []
        if authorization.get("dependency_key") != dependency_key:
            failures.append("authorization dependency is stale")
        if decision.get("kind") != "calibration":
            failures.append("authorization decision is not a calibration decision")
        if not decision.get("quality_approved") or decision.get("outcome") != "approved":
            failures.append("calibration decision is not approved")
        if decision.get("dependency_key") != dependency_key:
            failures.append("calibration decision dependency is stale")
        if reference.get("dependency_key") != dependency_key:
            failures.append("VisualReferenceSet dependency is stale")
        if reference.get("design_authority") is not False:
            failures.append("VisualReferenceSet incorrectly claims design authority")
        decision_ref = reference.get("decision_ref", {})
        if (
            decision_ref.get("path") != decision_path.relative_to(workspace).as_posix()
            or decision_ref.get("sha256") != sha256_file(decision_path)
            or decision_ref.get("id") != decision.get("decision_id")
        ):
            failures.append("VisualReferenceSet does not bind the authorized decision")
        if authorization.get("renderer_ir_sha256") != renderer_ir_sha256:
            failures.append("full render IR differs from calibrated IR")
        if authorization.get("producer") != producer:
            failures.append("full render producer differs from calibrated producer")
        if failures:
            raise VisualQualityError("Full render admission failed: " + "; ".join(failures))


def visual_quality_workspace_errors(
    workspace: Path, schema_dir: Path
) -> tuple[tuple[str, str], ...]:
    """Validate every persisted quality-by-construction fact and local file ref."""

    workspace = workspace.resolve()
    root = workspace / QUALITY_ROOT
    if not root.exists():
        return ()
    errors: list[tuple[str, str]] = []
    validators = {
        "policies": ("policy", "policy_id", "VAP-"),
        "semantic-previews": ("preview", "receipt_id", "SPR-"),
        "reviews": ("review", "review_id", "VQR-"),
        "decisions": ("decision", "decision_id", "VQD-"),
        "adjudications": ("adjudication", "adjudication_id", "VQA-"),
        "reference-sets": ("reference_set", "reference_set_id", "VRS-"),
    }
    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(workspace).as_posix()
        parent_kind = next((key for key in validators if key in path.parts), None)
        if parent_kind is None:
            errors.append((relative, "Unknown visual-quality fact directory"))
            continue
        kind, identity_field, prefix = validators[parent_kind]
        try:
            data = read_json(path)
            messages = _schema_errors(data, schema_dir, kind)
            if data.get(identity_field) != _identity(data, identity_field, prefix):
                messages.append(f"{identity_field} mismatch")
            if path.name != f"{sha256_json(data)}.json":
                messages.append("content-addressed filename mismatch")
            if kind == "review":
                messages.extend(validate_visual_quality_review_data(data, schema_dir))
                for image in data.get("image_set", []):
                    target = ensure_within(workspace, workspace / str(image["path"]))
                    if not target.is_file() or sha256_file(target) != image.get("sha256"):
                        messages.append(
                            f"review image mismatch: {image.get('path')}"
                        )
            refs: list[dict[str, Any]] = []
            if kind == "decision":
                refs = [data.get("review_ref", {}), *data.get("adjudication_refs", [])]
            elif kind == "adjudication":
                refs = [data.get("review_ref", {})]
            elif kind == "reference_set":
                refs = [data.get("receipt_ref", {}), data.get("decision_ref", {})]
                for page in data.get("office_pages", []):
                    target = ensure_within(workspace, workspace / str(page["path"]))
                    if not target.is_file() or sha256_file(target) != page.get("sha256"):
                        messages.append(
                            f"reference Office page mismatch: {page.get('path')}"
                        )
            for reference in refs:
                target = ensure_within(workspace, workspace / str(reference.get("path", "")))
                if not target.is_file() or sha256_file(target) != reference.get("sha256"):
                    messages.append(
                        f"visual-quality file reference mismatch: {reference.get('path')}"
                    )
        except Exception as exc:  # noqa: BLE001
            messages = [f"Visual-quality fact cannot be read: {exc}"]
        for message in sorted(set(messages)):
            errors.append((relative, message))
    return tuple(errors)
