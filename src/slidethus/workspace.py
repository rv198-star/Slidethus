from __future__ import annotations

import hashlib
import re
from pathlib import Path

from slidethus.artifact_runtime import build_artifact_entry, utc_now
from slidethus.constants import PROJECT_STATE_SCHEMA_VERSION, SCHEMA_VERSION
from slidethus.errors import WorkspaceError
from slidethus.io_utils import atomic_write_json


def normalize_project_id(title: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", title.strip()).strip("-_").upper()
    if len(normalized) < 3 or not normalized[0].isalnum():
        digest = hashlib.sha256(title.strip().encode("utf-8")).hexdigest()[:10].upper()
        normalized = f"ST-{digest}"
    return normalized[:64]


def _artifact_entry(
    *,
    project_id: str,
    artifact_type: str,
    relative_path: str,
    schema: str,
    data: dict[str, object],
    created_at: str,
) -> dict[str, object]:
    return build_artifact_entry(
        project_id=project_id,
        artifact_type=artifact_type,
        path=relative_path,
        schema=schema,
        schema_version=SCHEMA_VERSION,
        version=1,
        status="draft",
        data=data,
        created_by="slidethus-init",
        created_at=created_at,
    )


def init_workspace(
    workspace: Path,
    *,
    title: str,
    language: str = "zh-CN",
    force: bool = False,
    delivery_level: str = "D4",
) -> Path:
    """Create a safe stage-0 workspace with schema-valid early artifacts."""

    if not title.strip():
        raise WorkspaceError("Project title must not be blank")
    if delivery_level not in {"D0", "D1", "D2", "D3", "D4", "D5"}:
        raise WorkspaceError(f"Unknown delivery level: {delivery_level}")
    workspace = workspace.resolve()
    directories = ["brief", "sources", "evidence", "narrative", "outline", "slides", "layout", "design", "assets", "renders", "review", "delivery", "gates", "decisions", "cache", "outputs"]
    if workspace.exists() and any(workspace.iterdir()):
        if not force:
            raise WorkspaceError(f"Workspace is not empty: {workspace}")
        allowed_files = {
            Path("project_state.json"),
            Path("brief/project_brief.json"),
            Path("sources/source_ledger.json"),
            Path("evidence/evidence_ledger.json"),
            Path("assets/asset_manifest.json"),
            Path("gates/gate_results.json"),
            Path("decisions/decision_log.json"),
            Path("decisions/assumption_log.json"),
        }
        unexpected = [
            path.relative_to(workspace)
            for path in workspace.rglob("*")
            if path.is_file() and path.relative_to(workspace) not in allowed_files
        ]
        if unexpected:
            shown = ", ".join(item.as_posix() for item in unexpected[:5])
            raise WorkspaceError(f"Refusing --force because workspace contains non-stage-0 files: {shown}")
    workspace.mkdir(parents=True, exist_ok=True)
    for directory in directories:
        (workspace / directory).mkdir(parents=True, exist_ok=True)

    project_id = normalize_project_id(title)
    brief = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "title": title,
        "language": language,
        "intent": {
            "purpose": "待补充",
            "desired_outcome": "待补充",
            "presentation_mode": "both",
            "delivery_context": "待补充",
            "call_to_action": "",
        },
        "audiences": [
            {
                "audience_id": "AUD-01",
                "role": "待补充",
                "needs": [],
                "objections": [],
                "decision_power": "mixed",
                "knowledge_level": "mixed",
            }
        ],
        "constraints": {
            "page_count": {"min": 1, "target": 10, "max": 30},
            "duration_minutes": None,
            "aspect_ratio": "16:9",
            "output_formats": ["artifacts_only"],
            "editability_target": "E2",
            "deadline": None,
            "brand_requirements": [],
            "forbidden_content": [],
        },
        "source_policy": {
            "use_user_sources": True,
            "external_research": False,
            "citation_required": True,
            "freshness_requirement": None,
            "allowed_source_tiers": ["user", "primary", "secondary"],
        },
        "approval_mode": "checkpoint",
        "quality_profile": "standard",
        "assumptions": [],
        "open_questions": [
            {
                "question_id": "Q-001",
                "question": "请补充用途、核心受众和期望行动。",
                "blocking": True,
                "status": "open",
                "answer": None,
            }
        ],
    }
    source_ledger = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "sources": []}
    evidence_ledger = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "research_cycles": [
            {
                "cycle_id": "RSC-001",
                "kind": "orientation",
                "status": "pending",
                "basis": "none_required",
                "outline_version": None,
                "source_ids": [],
                "query_count": 0,
                "waiver_reason": None,
                "notes": ["Complete after supplied materials and permitted orientation research are inspected."],
            }
        ],
        "claims": [],
    }
    asset_manifest = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "assets": []}
    gate_results = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "records": []}
    decision_log = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "decisions": []}
    assumption_log = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "assumptions": []}

    atomic_write_json(workspace / "brief" / "project_brief.json", brief)
    atomic_write_json(workspace / "sources" / "source_ledger.json", source_ledger)
    atomic_write_json(workspace / "evidence" / "evidence_ledger.json", evidence_ledger)
    atomic_write_json(workspace / "assets" / "asset_manifest.json", asset_manifest)
    atomic_write_json(workspace / "gates" / "gate_results.json", gate_results)
    atomic_write_json(workspace / "decisions" / "decision_log.json", decision_log)
    atomic_write_json(workspace / "decisions" / "assumption_log.json", assumption_log)

    created_at = utc_now()
    artifacts = [
        _artifact_entry(project_id=project_id, artifact_type="project_brief", relative_path="brief/project_brief.json", schema="project_brief.schema.json", data=brief, created_at=created_at),
        _artifact_entry(project_id=project_id, artifact_type="source_ledger", relative_path="sources/source_ledger.json", schema="source_ledger.schema.json", data=source_ledger, created_at=created_at),
        _artifact_entry(project_id=project_id, artifact_type="evidence_ledger", relative_path="evidence/evidence_ledger.json", schema="evidence_ledger.schema.json", data=evidence_ledger, created_at=created_at),
        _artifact_entry(project_id=project_id, artifact_type="asset_manifest", relative_path="assets/asset_manifest.json", schema="asset_manifest.schema.json", data=asset_manifest, created_at=created_at),
        _artifact_entry(project_id=project_id, artifact_type="gate_results", relative_path="gates/gate_results.json", schema="gate_results.schema.json", data=gate_results, created_at=created_at),
        _artifact_entry(project_id=project_id, artifact_type="decision_log", relative_path="decisions/decision_log.json", schema="decision_log.schema.json", data=decision_log, created_at=created_at),
        _artifact_entry(project_id=project_id, artifact_type="assumption_log", relative_path="decisions/assumption_log.json", schema="assumption_log.schema.json", data=assumption_log, created_at=created_at),
    ]
    state = {
        "schema_version": PROJECT_STATE_SCHEMA_VERSION,
        "project_id": project_id,
        "current_phase": "CREATED",
        "status": "blocked",
        "delivery_level": delivery_level,
        "artifacts": artifacts,
        "completed_gates": [],
        "blockers": [
            {
                "blocker_id": "BKR-001",
                "description": "Project Brief contains unanswered blocking questions",
                "status": "open",
            }
        ],
        "decisions": [],
        "revision": 1,
    }
    atomic_write_json(workspace / "project_state.json", state)
    return workspace
