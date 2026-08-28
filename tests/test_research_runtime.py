from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.constants import find_repository_root
from slidethus.errors import (
    ResearchCacheError,
    ResearchPlanningError,
    ResearchProviderError,
    ResearchRuntimeError,
)
from slidethus.io_utils import read_json
from slidethus.protocols import ResearchLimits, ResearchQuery, ResearchResult
from slidethus.services.research import (
    OfflineResearchProvider,
    ResearchRuntime,
    plan_orientation_research,
    plan_targeted_research,
)
from slidethus.validation import validate_workspace
from slidethus.workspace import init_workspace


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


class RecordingProvider:
    name = "fixture-search"
    version = "1.0.0"

    def __init__(self, clock: MutableClock, *, fail_once: str | None = None) -> None:
        self.clock = clock
        self.fail_once = fail_once
        self.failed = False
        self.calls: list[str] = []

    def search(self, queries: tuple[ResearchQuery, ...]) -> tuple[ResearchResult, ...]:
        assert len(queries) == 1
        query = queries[0]
        self.calls.append(query.query_id)
        if self.fail_once == query.query_id and not self.failed:
            self.failed = True
            raise RuntimeError("simulated provider interruption")
        url = f"https://example.com/{query.query_id.lower()}"
        return (
            ResearchResult(
                query_id=query.query_id,
                title=f"Result for {query.query_id}",
                locator=url,
                url=url,
                summary=f"Evidence candidate for {query.query}",
                source_tier="primary",
                retrieved_at=self.clock().isoformat().replace("+00:00", "Z"),
                published_at="2026-08-01",
            ),
        )


def _orientation_workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "workspace", title="Agent Research")
    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["intent"]["purpose"] = "研究企业 Agent 落地趋势"
    brief["intent"]["desired_outcome"] = "形成管理层决策依据"
    brief["audiences"][0]["role"] = "企业管理者"
    brief["audiences"][0]["needs"] = ["ROI", "风险"]
    brief["source_policy"]["external_research"] = True
    brief["source_policy"]["freshness_requirement"] = "2026 current"
    brief["source_policy"]["allowed_source_tiers"] = ["user", "primary", "secondary"]
    runtime.write_artifact(
        "project_brief",
        brief,
        expected_version=1,
        status="approved",
        created_by="research-test",
    )
    return workspace


def _targeted_workspace(tmp_path: Path) -> Path:
    root = find_repository_root()
    workspace = tmp_path / "targeted"
    shutil.copytree(root / "examples/minimal_project", workspace)
    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["source_policy"]["external_research"] = True
    brief["source_policy"]["freshness_requirement"] = "current"
    brief["source_policy"]["allowed_source_tiers"] = ["user", "primary", "secondary"]
    runtime.write_artifact(
        "project_brief",
        brief,
        expected_version=1,
        status="approved",
        created_by="research-test",
    )
    return workspace


def test_orientation_plan_is_stable_and_respects_brief_policy(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    first = plan_orientation_research(workspace)
    second = plan_orientation_research(workspace)

    assert first == second
    assert first.plan_id.startswith("RPL-")
    assert first.cycle_id == "RSC-001"
    assert first.cycle_kind == "orientation"
    assert first.outline_version is None
    assert [query.query_id for query in first.queries] == ["RQ-001", "RQ-002", "RQ-003"]
    assert all(query.preferred_source_tiers == ("primary", "secondary") for query in first.queries)
    assert all(query.freshness_requirement == "2026 current" for query in first.queries)

    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["source_policy"]["external_research"] = False
    runtime.write_artifact(
        "project_brief",
        brief,
        expected_version=2,
        status="approved",
        created_by="research-test",
    )
    with pytest.raises(ResearchPlanningError, match="disables external research"):
        plan_orientation_research(workspace)


def test_targeted_plan_binds_outline_version_and_slide_ids(tmp_path: Path) -> None:
    workspace = _targeted_workspace(tmp_path)
    state = read_json(workspace / "project_state.json")
    outline_entry = next(
        item for item in state["artifacts"] if item["artifact_type"] == "deck_outline"
    )

    plan = plan_targeted_research(workspace)

    assert plan.cycle_kind == "targeted"
    assert plan.outline_version == outline_entry["version"]
    assert plan.queries
    assert all(query.slide_id is not None for query in plan.queries)
    chosen = plan.queries[0].slide_id
    assert chosen is not None
    narrowed = plan_targeted_research(workspace, slide_ids=[chosen])
    assert [query.slide_id for query in narrowed.queries] == [chosen]
    with pytest.raises(ResearchPlanningError, match="unknown active slides"):
        plan_targeted_research(workspace, slide_ids=["S-999"])


def test_execution_persists_run_and_reuses_cache_across_plan_runs(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    first_plan = plan_orientation_research(
        workspace,
        limits=ResearchLimits(max_total_results=120),
    )

    first = runtime.execute(first_plan)

    assert first["status"] == "complete"
    assert provider.calls == ["RQ-001", "RQ-002", "RQ-003"]
    assert all(task["cache_status"] == "miss" for task in first["tasks"])
    assert runtime.load_run(first["run_id"]) == first

    second_plan = plan_orientation_research(
        workspace,
        limits=ResearchLimits(max_total_results=121),
    )
    second = runtime.execute(second_plan)

    assert second["run_id"] != first["run_id"]
    assert second["status"] == "complete"
    assert provider.calls == ["RQ-001", "RQ-002", "RQ-003"]
    assert all(task["cache_status"] == "hit" for task in second["tasks"])
    assert len(runtime.list_runs()) == 2


def test_completed_run_reexecution_is_byte_stable_without_refresh(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    first = runtime.execute(plan)
    run_path = workspace / ".slidethus/research/runs" / f"{first['run_id']}.json"
    before = run_path.read_bytes()

    clock.advance(days=2)
    second = runtime.execute(plan)

    assert second == first
    assert run_path.read_bytes() == before
    assert provider.calls == ["RQ-001", "RQ-002", "RQ-003"]


def test_expired_cache_refreshes_without_overwriting_history(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    first_plan = plan_orientation_research(
        workspace,
        limits=ResearchLimits(cache_ttl_seconds=60, max_total_results=120),
    )
    first = runtime.execute(first_plan)
    old_paths = [workspace / task["cache_snapshot_path"] for task in first["tasks"]]

    clock.advance(minutes=2)
    second_plan = plan_orientation_research(
        workspace,
        limits=ResearchLimits(cache_ttl_seconds=60, max_total_results=121),
    )
    second = runtime.execute(second_plan)

    assert len(provider.calls) == 6
    assert all(path.exists() for path in old_paths)
    assert all(task["cache_status"] == "miss" for task in second["tasks"])
    for task in second["tasks"]:
        cache_dir = workspace / ".slidethus/cache/research" / task["input_key"]
        snapshots = [path for path in cache_dir.glob("*.json") if path.name != "invalidated.json"]
        assert len(snapshots) == 2


def test_invalidation_bumps_generation_and_preserves_old_cache(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    first = runtime.execute(plan)
    old_snapshot = workspace / first["tasks"][0]["cache_snapshot_path"]
    old_bytes = old_snapshot.read_bytes()

    clock.advance(seconds=1)
    invalidated = runtime.invalidate(
        first["run_id"],
        query_ids=["RQ-001"],
        reason="source changed",
    )
    assert invalidated["tasks"][0]["status"] == "invalidated"
    assert invalidated["tasks"][1]["status"] == "complete"

    clock.advance(seconds=1)
    rerun = runtime.execute(plan)

    assert rerun["status"] == "complete"
    assert provider.calls == ["RQ-001", "RQ-002", "RQ-003", "RQ-001"]
    assert old_snapshot.read_bytes() == old_bytes
    new_snapshot = read_json(workspace / rerun["tasks"][0]["cache_snapshot_path"])
    assert new_snapshot["generation"] == 1


def test_provider_failure_is_checkpointed_and_resumable(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock, fail_once="RQ-002")
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, provider, clock=clock)

    with pytest.raises(ResearchProviderError, match="resumable"):
        runtime.execute(plan)

    run = runtime.load_run(runtime.prepare(plan)["run_id"])
    assert run["status"] == "partial"
    assert [task["status"] for task in run["tasks"]] == ["complete", "failed", "pending"]
    assert provider.calls == ["RQ-001", "RQ-002"]
    assert "simulated provider interruption" not in run["tasks"][1]["error"]
    assert "sensitive details omitted" in run["tasks"][1]["error"]

    resumed = runtime.execute(plan)

    assert resumed["status"] == "complete"
    assert provider.calls == ["RQ-001", "RQ-002", "RQ-002", "RQ-003"]
    assert resumed["tasks"][0]["attempts"] == 1
    assert resumed["tasks"][1]["attempts"] == 2


def test_offline_provider_blocks_without_fabricating_results(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, OfflineResearchProvider())

    run = runtime.execute(plan)

    assert run["status"] == "blocked"
    assert run["tasks"][0]["status"] == "blocked"
    assert run["tasks"][0]["result_count"] == 0
    assert run["tasks"][0]["cache_snapshot_path"] is None
    cache_root = workspace / ".slidethus/cache/research"
    assert not cache_root.exists() or not list(cache_root.rglob("*.json"))


def test_cache_tampering_is_detected_from_run_lineage(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    run = runtime.execute(plan)
    cache_path = workspace / run["tasks"][0]["cache_snapshot_path"]
    tampered = read_json(cache_path)
    tampered["results"][0]["summary"] = "tampered"
    cache_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ResearchCacheError, match="file hash mismatch"):
        runtime.load_run(run["run_id"])
    report = validate_workspace(workspace, check_hashes=True)
    assert not report.ok
    assert any(issue.code == "invalid_research_runtime" for issue in report.issues)


def test_invalid_provider_result_fails_without_cache_publication(tmp_path: Path) -> None:
    class InvalidProvider(RecordingProvider):
        def search(self, queries: tuple[ResearchQuery, ...]) -> tuple[ResearchResult, ...]:
            query = queries[0]
            self.calls.append(query.query_id)
            return (
                ResearchResult(
                    query_id=query.query_id,
                    title="Bad URL",
                    locator="javascript:alert(1)",
                    url="javascript:alert(1)",
                    summary="unsafe",
                    source_tier="primary",
                    retrieved_at=self.clock().isoformat().replace("+00:00", "Z"),
                ),
            )

    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    runtime = ResearchRuntime(workspace, InvalidProvider(clock), clock=clock)
    plan = plan_orientation_research(workspace)

    with pytest.raises(ResearchRuntimeError, match="unsafe URL"):
        runtime.execute(plan)

    cache_root = workspace / ".slidethus/cache/research"
    assert not cache_root.exists() or not list(cache_root.rglob("*.json"))
    prepared = runtime.prepare(plan)
    assert runtime.load_run(prepared["run_id"])["status"] == "failed"


def test_provider_version_and_cache_ttl_are_cache_identity_inputs(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider_v1 = RecordingProvider(clock)
    long_ttl = plan_orientation_research(
        workspace,
        limits=ResearchLimits(cache_ttl_seconds=3600),
    )
    ResearchRuntime(workspace, provider_v1, clock=clock).execute(long_ttl)
    assert len(provider_v1.calls) == 3

    short_ttl = plan_orientation_research(
        workspace,
        limits=ResearchLimits(cache_ttl_seconds=60),
    )
    ResearchRuntime(workspace, provider_v1, clock=clock).execute(short_ttl)
    assert len(provider_v1.calls) == 6

    class ProviderV2(RecordingProvider):
        version = "2.0.0"

    provider_v2 = ProviderV2(clock)
    ResearchRuntime(workspace, provider_v2, clock=clock).execute(long_ttl)
    assert len(provider_v2.calls) == 3


def test_runtime_freezes_provider_identity_for_the_complete_execution(
    tmp_path: Path,
) -> None:
    class IdentityChangingProvider(RecordingProvider):
        def search(self, queries: tuple[ResearchQuery, ...]) -> tuple[ResearchResult, ...]:
            results = super().search(queries)
            self.version = "9.9.9"
            return results

    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = IdentityChangingProvider(clock)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    plan = plan_orientation_research(workspace)

    run = runtime.execute(plan)

    assert run["status"] == "complete"
    assert run["provider"] == {"name": "fixture-search", "version": "1.0.0"}
    for task in run["tasks"]:
        cache = read_json(workspace / task["cache_snapshot_path"])
        assert cache["provider"] == run["provider"]
    assert validate_workspace(workspace, check_hashes=True).ok


def test_oversized_metadata_and_result_stream_fail_with_checkpoint(tmp_path: Path) -> None:
    class MetadataProvider(RecordingProvider):
        def search(self, queries: tuple[ResearchQuery, ...]) -> tuple[ResearchResult, ...]:
            query = queries[0]
            self.calls.append(query.query_id)
            return (
                ResearchResult(
                    query_id=query.query_id,
                    title="metadata",
                    locator="https://example.com/metadata",
                    url="https://example.com/metadata",
                    summary="bounded",
                    source_tier="primary",
                    retrieved_at=self.clock().isoformat().replace("+00:00", "Z"),
                    metadata={"payload": "x" * 100},
                ),
            )

    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    plan = plan_orientation_research(
        workspace,
        limits=ResearchLimits(max_metadata_bytes=32),
    )
    runtime = ResearchRuntime(workspace, MetadataProvider(clock), clock=clock)
    with pytest.raises(ResearchRuntimeError, match="max_metadata_bytes"):
        runtime.execute(plan)
    run = runtime.load_run(runtime.prepare(plan)["run_id"])
    assert run["status"] == "failed"
    assert run["tasks"][0]["status"] == "failed"

    class StreamingProvider(RecordingProvider):
        def search(self, queries: tuple[ResearchQuery, ...]):
            query = queries[0]
            self.calls.append(query.query_id)
            for index in range(1000):
                yield ResearchResult(
                    query_id=query.query_id,
                    title=f"result {index}",
                    locator=f"https://example.com/{index}",
                    url=f"https://example.com/{index}",
                    summary="bounded",
                    source_tier="primary",
                    retrieved_at=self.clock().isoformat().replace("+00:00", "Z"),
                )

    stream_plan = plan_orientation_research(
        workspace,
        limits=ResearchLimits(max_results_per_query=2),
    )
    streaming = ResearchRuntime(workspace, StreamingProvider(clock), clock=clock)
    with pytest.raises(ResearchRuntimeError, match="more than max_results_per_query"):
        streaming.execute(stream_plan)
    stream_run = streaming.load_run(streaming.prepare(stream_plan)["run_id"])
    assert stream_run["status"] == "failed"


def test_invalidation_marker_is_reconciled_after_interrupted_run_update(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    run = runtime.execute(plan)
    task = run["tasks"][0]
    marker = workspace / ".slidethus/cache/research" / task["input_key"] / "invalidated.json"
    clock.advance(seconds=1)
    marker.write_text(
        json.dumps(
            {
                "input_key": task["input_key"],
                "generation": 1,
                "invalidated_at": clock().isoformat().replace("+00:00", "Z"),
                "reason": "simulated crash after marker publish",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run_path = workspace / ".slidethus/research/runs" / f"{run['run_id']}.json"
    before_validation = run_path.read_bytes()
    report = validate_workspace(workspace, check_hashes=True)
    assert report.ok, report.issues
    assert run_path.read_bytes() == before_validation

    recovered = runtime.load_run(run["run_id"])
    assert recovered["status"] == "planned"
    assert recovered["tasks"][0]["status"] == "invalidated"
    assert recovered["tasks"][1]["status"] == "complete"


def test_cycle_identity_cannot_be_rebound_across_research_semantics(tmp_path: Path) -> None:
    workspace = _targeted_workspace(tmp_path)
    with pytest.raises(ResearchPlanningError, match="is orientation, not targeted"):
        plan_targeted_research(workspace, cycle_id="RSC-001")
    with pytest.raises(ResearchPlanningError, match="next available ID"):
        plan_targeted_research(workspace, cycle_id="RSC-999")


def test_orientation_planner_rejects_unresolved_placeholder_context(tmp_path: Path) -> None:
    workspace = init_workspace(tmp_path / "placeholder", title="Placeholder Research")
    runtime = ArtifactRuntime(workspace)
    brief = runtime.show_artifact("project_brief")
    brief["source_policy"]["external_research"] = True
    brief["source_policy"]["allowed_source_tiers"] = ["primary"]
    runtime.write_artifact(
        "project_brief",
        brief,
        expected_version=1,
        status="approved",
        created_by="research-test",
    )
    with pytest.raises(ResearchPlanningError, match="No non-empty research query"):
        plan_orientation_research(workspace)


def test_non_json_metadata_and_malformed_invalidation_fail_closed(tmp_path: Path) -> None:
    class NonJsonMetadataProvider(RecordingProvider):
        def search(self, queries: tuple[ResearchQuery, ...]) -> tuple[ResearchResult, ...]:
            query = queries[0]
            return (
                ResearchResult(
                    query_id=query.query_id,
                    title="non-json",
                    locator="https://example.com/non-json",
                    url="https://example.com/non-json",
                    summary="bounded",
                    source_tier="primary",
                    retrieved_at=self.clock().isoformat().replace("+00:00", "Z"),
                    metadata={"bad": object()},
                ),
            )

    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    plan = plan_orientation_research(workspace)
    bad_runtime = ResearchRuntime(workspace, NonJsonMetadataProvider(clock), clock=clock)
    with pytest.raises(ResearchRuntimeError, match="not JSON-serializable"):
        bad_runtime.execute(plan)
    failed = bad_runtime.load_run(bad_runtime.prepare(plan)["run_id"])
    assert failed["status"] == "failed"

    provider = RecordingProvider(clock)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    run = runtime.execute(plan)
    task = run["tasks"][0]
    marker = workspace / ".slidethus/cache/research" / task["input_key"] / "invalidated.json"
    marker.write_text(
        json.dumps(
            {
                "input_key": task["input_key"],
                "generation": 1,
                "invalidated_at": clock().isoformat().replace("+00:00", "Z"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ResearchCacheError, match="reason is missing"):
        runtime.load_run(run["run_id"])
    report = validate_workspace(workspace, check_hashes=True)
    assert not report.ok
    assert any(issue.code == "invalid_research_runtime" for issue in report.issues)


def test_research_run_tampering_is_rejected(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    prepared = runtime.prepare(plan)
    run_path = workspace / ".slidethus/research/runs" / f"{prepared['run_id']}.json"
    data = read_json(run_path)
    data["tasks"][0]["query"] = "changed behind runtime"
    run_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ResearchRuntimeError, match="plan_id mismatch"):
        runtime.load_run(prepared["run_id"])


def test_unknown_invalidation_query_is_rejected_without_mutation(tmp_path: Path) -> None:
    workspace = _orientation_workspace(tmp_path)
    clock = MutableClock()
    provider = RecordingProvider(clock)
    plan = plan_orientation_research(workspace)
    runtime = ResearchRuntime(workspace, provider, clock=clock)
    run = runtime.execute(plan)
    before = copy.deepcopy(runtime.load_run(run["run_id"]))

    with pytest.raises(ResearchRuntimeError, match="unknown queries"):
        runtime.invalidate(run["run_id"], query_ids=["RQ-999"], reason="bad request")

    assert runtime.load_run(run["run_id"]) == before
