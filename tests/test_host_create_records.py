from __future__ import annotations

import copy
from pathlib import Path

import pytest

from slidethus.errors import HostCreateConflictError
from slidethus.host_create_records import (
    build_host_create_config,
    create_host_create_session,
    finish_host_create_operation,
    host_create_workspace_errors,
    load_host_create_session,
    normalize_pending_request,
    recover_incomplete_host_create_operations,
    resolve_session_config,
    save_host_create_session,
    start_host_create_operation,
    terminal_reference,
)
from slidethus.io_utils import atomic_create_json, read_json
from slidethus.protocols import BriefCompletionHints, PlanningLimits
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.m2_application import M2ApplicationLimits
from slidethus.workspace import init_workspace


class _PlanningProvider:
    name = "test-host-planning"
    version = "1.0.0"


class _ArtDirectionProvider:
    name = "test-host-art-direction"
    version = "1.0.0"
    mode = "host-authored"


def _config(source: Path | None = None) -> dict:
    sources = []
    if source is not None:
        sources = [
            {
                "path": str(source.resolve()),
                "size_bytes": source.stat().st_size,
                "sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
            }
        ]
    return build_host_create_config(
        title="Stable Create",
        source_fingerprints=sources,
        brief_hints=BriefCompletionHints(
            request_text="Create a stable presentation",
            audience_needs=("clear decision",),
            output_formats=("pptx",),
        ),
        planning_limits=PlanningLimits(),
        m2_limits=M2ApplicationLimits(),
        allow_research_degraded=False,
        approve_external_disclosure=False,
        allow_high_risk_source_evidence=False,
        planning_provider=_PlanningProvider(),
        research_provider=None,
        art_direction_provider=_ArtDirectionProvider(),
    )


def _session(tmp_path: Path, source: Path | None = None) -> tuple[Path, dict]:
    workspace = init_workspace(tmp_path / "workspace", title="Stable Create")
    session = create_host_create_session(workspace, _config(source))
    return workspace, session


def test_session_config_is_schema_backed_and_omission_reuses_it(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Fact\nStable evidence.\n", encoding="utf-8")
    workspace, session = _session(tmp_path, source)

    resolved = resolve_session_config(
        session,
        title=None,
        sources=None,
        brief_hints=None,
        planning_limits=None,
        m2_limits=None,
        allow_research_degraded=None,
        approve_external_disclosure=None,
        allow_high_risk_source_evidence=None,
        planning_provider=_PlanningProvider(),
        research_provider=None,
        art_direction_provider=_ArtDirectionProvider(),
    )

    assert resolved == session["config"]
    assert load_host_create_session(workspace) == session
    assert host_create_workspace_errors(workspace, SchemaRegistry().schema_dir) == ()


def test_explicit_changed_request_is_rejected_without_session_mutation(tmp_path: Path) -> None:
    workspace, session = _session(tmp_path)
    before = (workspace / ".slidethus/host-create/session.json").read_bytes()

    with pytest.raises(HostCreateConflictError, match="brief_hints"):
        resolve_session_config(
            session,
            title=None,
            sources=None,
            brief_hints=BriefCompletionHints(request_text="A different request"),
            planning_limits=None,
            m2_limits=None,
            allow_research_degraded=None,
            approve_external_disclosure=None,
            allow_high_risk_source_evidence=None,
            planning_provider=_PlanningProvider(),
            research_provider=None,
            art_direction_provider=_ArtDirectionProvider(),
        )

    assert (workspace / ".slidethus/host-create/session.json").read_bytes() == before


def test_changed_canonical_source_requires_explicit_source_revision(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("version one", encoding="utf-8")
    _workspace, session = _session(tmp_path, source)
    source.write_text("version two", encoding="utf-8")

    with pytest.raises(HostCreateConflictError, match="Sources changed"):
        resolve_session_config(
            session,
            title=None,
            sources=None,
            brief_hints=None,
            planning_limits=None,
            m2_limits=None,
            allow_research_degraded=None,
            approve_external_disclosure=None,
            allow_high_risk_source_evidence=None,
            planning_provider=_PlanningProvider(),
            research_provider=None,
            art_direction_provider=_ArtDirectionProvider(),
        )


def test_started_and_terminal_facts_close_one_invocation(tmp_path: Path) -> None:
    workspace, session = _session(tmp_path)
    request_path = workspace / ".slidethus/host-design/requests/request.json"
    response_path = workspace / ".slidethus/host-design/responses/response.json"
    atomic_create_json(request_path, {"stage": "narrative_blueprint"})
    pending = {
        "stage": "narrative_blueprint",
        "request_hash": "sha256:" + "a" * 64,
        "request_path": str(request_path),
        "response_path": str(response_path),
    }

    operation = start_host_create_operation(
        workspace,
        session,
        action="start",
        invocation_payload={"render": False, "sources": []},
    )
    terminal_path, terminal = finish_host_create_operation(
        operation,
        status="host_input_required",
        pending_request=pending,
        message="Host Narrative response is required.",
        target_phase="P3",
        allowed_next_actions=("submit_host_response", "resume"),
    )

    candidate = copy.deepcopy(session)
    candidate["pending_request"] = normalize_pending_request(workspace, pending)
    candidate["last_terminal"] = terminal_reference(
        workspace, terminal_path, terminal
    )
    saved = save_host_create_session(
        workspace,
        candidate,
        expected_revision=int(session["session_revision"]),
    )

    attempt_root = workspace / ".slidethus/host-create/operations" / operation.attempt_id
    assert read_json(attempt_root / "started.json")["status"] == "started"
    assert read_json(attempt_root / "terminal.json")["status"] == "host_input_required"
    assert saved["pending_request"]["request_path"] == request_path.relative_to(
        workspace
    ).as_posix()
    assert host_create_workspace_errors(workspace, SchemaRegistry().schema_dir) == ()


def test_next_invocation_recovers_an_orphaned_started_fact(tmp_path: Path) -> None:
    workspace, session = _session(tmp_path)
    operation = start_host_create_operation(
        workspace,
        session,
        action="resume",
        invocation_payload={"render": False},
    )

    recovered = recover_incomplete_host_create_operations(workspace, session)

    assert len(recovered) == 1
    terminal = read_json(recovered[0])
    assert terminal["attempt_id"] == operation.attempt_id
    assert terminal["status"] == "failed"
    assert terminal["result"]["allowed_next_actions"] == ["resume", "inspect_report"]
    assert host_create_workspace_errors(workspace, SchemaRegistry().schema_dir) == ()
