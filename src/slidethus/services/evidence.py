from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from slidethus.adapters.ingestion.common import SourceBlock, build_chunks
from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import EvidenceAdjudicationError, EvidenceMaterializationError
from slidethus.evidence_identity import candidate_id_for, claim_key, conflict_group_id
from slidethus.ingestion import build_source_risks
from slidethus.io_utils import (
    atomic_create_json,
    canonical_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
)
from slidethus.protocols import (
    DetectedSourceFormat,
    EvidenceCandidate,
    EvidencePolicyDecision,
    SourceParseLimits,
    SourceParseResult,
)
from slidethus.schema_registry import SchemaRegistry
from slidethus.services.research import inspect_research_run
from slidethus.source_snapshots import (
    build_source_snapshot,
    load_source_snapshot,
    snapshot_chunks,
    source_snapshot_key,
    validate_snapshot_data,
)

_CANDIDATE_ID = re.compile(r"^CND-[A-F0-9]{16}$")
_EVIDENCE_ID = re.compile(r"^EVD-[0-9]{3}$")
_SOURCE_ID = re.compile(r"^SRC-[0-9]{3}$")
_AUTHORITY_RANK = {"unknown": 0, "community": 1, "secondary": 2, "user": 3, "primary": 4}
_ENGINE_NAME = "deterministic-evidence-engine"
_ENGINE_VERSION = "1.2.0"
_WEB_MATERIALIZER = "research-result-materializer"
_WEB_MATERIALIZER_VERSION = "1.1.0"


@dataclass(frozen=True)
class ResearchMaterializationResult:
    run_id: str
    source_ids: tuple[str, ...]
    result_ids: tuple[str, ...]
    candidates: tuple[EvidenceCandidate, ...]
    source_ledger_changed: bool


@dataclass(frozen=True)
class EvidencePublishResult:
    changed: bool
    evidence_ids: tuple[str, ...]
    ledger: dict[str, Any]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()


def make_evidence_candidate(
    *,
    claim: str,
    source_id: str | None,
    locator: str | None,
    support_type: str = "direct",
    origin_kind: str = "source_chunk",
    source_chunk_id: str | None = None,
    research_run_id: str | None = None,
    research_result_id: str | None = None,
    freshness_date: str | None = None,
    conflict_key: str | None = None,
    stance: str | None = None,
    tags: Iterable[str] = (),
    reasoning: str = "",
) -> EvidenceCandidate:
    provisional = EvidenceCandidate(
        candidate_id="",
        claim=_normalize_text(claim),
        source_id=source_id,
        locator=_normalize_text(locator) or None,
        support_type=support_type,
        origin_kind=origin_kind,
        source_chunk_id=source_chunk_id,
        research_run_id=research_run_id,
        research_result_id=research_result_id,
        freshness_date=freshness_date,
        conflict_key=_normalize_text(conflict_key) or None,
        stance=_normalize_text(stance) or None,
        tags=tuple(dict.fromkeys(_normalize_text(tag) for tag in tags if _normalize_text(tag))),
        reasoning=_normalize_text(reasoning),
    )
    return EvidenceCandidate(**{**asdict(provisional), "candidate_id": candidate_id_for(provisional)})


def _candidate_binding(
    candidate: EvidenceCandidate,
    chunk: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "source_id": candidate.source_id,
        "locator": candidate.locator,
        "support_type": candidate.support_type,
        "origin_kind": candidate.origin_kind,
        "source_chunk_id": candidate.source_chunk_id,
        "content_hash": str(chunk["content_hash"]) if chunk is not None else None,
        "research_run_id": candidate.research_run_id,
        "research_result_id": candidate.research_result_id,
        "conflict_key": candidate.conflict_key,
        "stance": candidate.stance,
        "freshness_date": candidate.freshness_date,
    }


def _candidate_from_binding(claim: str, binding: dict[str, Any]) -> EvidenceCandidate:
    candidate = EvidenceCandidate(
        candidate_id=str(binding["candidate_id"]),
        claim=claim,
        source_id=binding.get("source_id"),
        locator=binding.get("locator"),
        support_type=str(binding["support_type"]),
        origin_kind=str(binding["origin_kind"]),
        source_chunk_id=binding.get("source_chunk_id"),
        research_run_id=binding.get("research_run_id"),
        research_result_id=binding.get("research_result_id"),
        freshness_date=binding.get("freshness_date"),
        conflict_key=binding.get("conflict_key"),
        stance=binding.get("stance"),
        tags=(),
        reasoning="",
    )
    if candidate.candidate_id != candidate_id_for(candidate):
        raise EvidenceAdjudicationError(
            f"Persisted candidate binding identity mismatch: {candidate.candidate_id}"
        )
    return candidate


def _source_refs_from_bindings(bindings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: dict[tuple[str, str, str], dict[str, Any]] = {}
    for binding in bindings:
        source_id = binding.get("source_id")
        locator = binding.get("locator")
        if source_id is None or locator is None:
            continue
        key = (str(source_id), str(locator), str(binding["support_type"]))
        refs[key] = {
            "source_id": str(source_id),
            "locator": str(locator),
            "support_type": str(binding["support_type"]),
            **(
                {
                    "chunk_id": str(binding["source_chunk_id"]),
                    "content_hash": str(binding["content_hash"]),
                }
                if binding.get("source_chunk_id") and binding.get("content_hash")
                else {}
            ),
        }
    return [refs[key] for key in sorted(refs)]


def canonical_web_url(raw: str) -> str:
    """Normalize one HTTP(S) URL for stable Source identity without fetching it."""

    value = _normalize_text(raw)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise EvidenceMaterializationError(f"Research Result has malformed URL: {raw}") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise EvidenceMaterializationError(f"Research Result has no admitted HTTP(S) URL: {raw}")
    if parsed.username is not None or parsed.password is not None:
        raise EvidenceMaterializationError("Research Result URL must not contain credentials")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, host, path, parsed.query, ""))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _date_text(value: str | None) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _source_sort_key(source: dict[str, Any]) -> int:
    return int(str(source["source_id"]).split("-")[-1])


def _next_source_number(sources: list[dict[str, Any]]) -> int:
    return max(
        (int(str(item["source_id"]).split("-")[-1]) for item in sources if _SOURCE_ID.fullmatch(str(item.get("source_id", "")))),
        default=0,
    ) + 1


def _next_evidence_number(claims: list[dict[str, Any]]) -> int:
    return max(
        (int(str(item["evidence_id"]).split("-")[-1]) for item in claims if _EVIDENCE_ID.fullmatch(str(item.get("evidence_id", "")))),
        default=0,
    ) + 1


def _authority_extrema(tiers: Iterable[str]) -> tuple[str, str, tuple[str, ...]]:
    normalized = tuple(dict.fromkeys(tier if tier in _AUTHORITY_RANK else "unknown" for tier in tiers))
    if not normalized:
        normalized = ("unknown",)
    strongest = max(normalized, key=lambda tier: _AUTHORITY_RANK[tier])
    weakest = min(normalized, key=lambda tier: _AUTHORITY_RANK[tier])
    return strongest, weakest, normalized


def _freshness_decision(
    dates: Iterable[str | None],
    cutoff: str | None,
) -> tuple[str, str | None, tuple[str, ...]]:
    values = [parsed for parsed in (_parse_date(value) for value in dates) if parsed is not None]
    if cutoff is None:
        evaluated = max(values).isoformat() if values else None
        return "not_required", evaluated, ("freshness_not_required",)
    cutoff_date = _parse_date(cutoff)
    if cutoff_date is None:
        return "unknown", max(values).isoformat() if values else None, ("freshness_cutoff_unparseable",)
    if not values:
        return "unknown", None, ("freshness_date_missing",)
    if any(value >= cutoff_date for value in values):
        return "current", max(values).isoformat(), ("freshness_at_or_after_cutoff",)
    return "stale", max(values).isoformat(), ("freshness_before_cutoff",)


class EvidenceEngine:
    """Deterministic candidate materialization and fail-closed Evidence adjudication."""

    def __init__(
        self,
        workspace: Path,
        *,
        runtime: ArtifactRuntime | None = None,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runtime = runtime or ArtifactRuntime(self.workspace)
        self.schemas = schema_registry or SchemaRegistry()
        self.project_id = str(self.runtime.show_artifact("project_state")["project_id"])

    @staticmethod
    def _current_high_risk_count(snapshot: dict[str, Any]) -> int:
        """Count persisted and currently detectable high risks without rewriting snapshots."""

        findings: set[tuple[str, str, str, str | None]] = {
            (
                str(item.get("category", "")),
                str(item.get("severity", "")),
                str(item.get("message", "")),
                str(item.get("locator")) if item.get("locator") is not None else None,
            )
            for item in snapshot.get("risks", [])
        }
        recomputed = build_source_risks(
            snapshot_chunks(snapshot),
            str(snapshot["source_id"]),
            max_risks=int(snapshot.get("limits", {}).get("max_risks", 10_000)),
        )
        findings.update(
            (risk.category, risk.severity, risk.message, risk.locator)
            for risk in recomputed
        )
        return sum(1 for _category, severity, _message, _locator in findings if severity == "high")

    def current_high_risk_source_counts(self) -> dict[str, int]:
        """Return current-policy high-risk counts for all ingested Sources."""

        ledger = self.runtime.show_artifact("source_ledger")
        counts: dict[str, int] = {}
        for source in ledger.get("sources", []):
            if not source.get("ingestion"):
                continue
            source_id = str(source["source_id"])
            snapshot = load_source_snapshot(
                self.workspace,
                self.project_id,
                source,
                self.schemas.schema_dir,
            )
            count = self._current_high_risk_count(snapshot)
            if count:
                counts[source_id] = count
        return counts

    def candidates_from_source(self, source_id: str) -> tuple[EvidenceCandidate, ...]:
        """Create one conservative candidate per persisted Production Source Chunk."""

        ledger = self.runtime.show_artifact("source_ledger")
        source = next(
            (item for item in ledger.get("sources", []) if item.get("source_id") == source_id),
            None,
        )
        if source is None:
            raise EvidenceMaterializationError(f"Unknown source ID: {source_id}")
        if not source.get("ingestion"):
            raise EvidenceMaterializationError(
                f"Source {source_id} has no Production snapshot; deterministic candidate extraction is unavailable"
            )
        snapshot = load_source_snapshot(
            self.workspace,
            self.project_id,
            source,
            self.schemas.schema_dir,
        )
        candidates = []
        for item in snapshot.get("chunks", []):
            metadata = dict(item.get("metadata", {}))
            chunk_text = _normalize_text(item.get("text"))
            heading_text = _normalize_text(metadata.get("title"))
            if (
                metadata.get("heading_level") is not None
                and heading_text
                and claim_key(chunk_text) == claim_key(heading_text)
            ):
                continue
            result_id = metadata.get("research_result_id")
            run_id = metadata.get("research_run_id")
            research_summary = bool(metadata.get("remote_body_fetched") is False and result_id)
            candidates.append(
                make_evidence_candidate(
                    claim=chunk_text,
                    source_id=source_id,
                    locator=str(item["locator"]),
                    support_type="indirect" if research_summary else "direct",
                    origin_kind="research_summary" if research_summary else "source_chunk",
                    source_chunk_id=str(item["chunk_id"]),
                    research_run_id=str(run_id) if run_id else None,
                    research_result_id=str(result_id) if result_id else None,
                    freshness_date=(
                        _date_text(metadata.get("published_at"))
                        or source.get("freshness_date")
                    ),
                    tags=(str(item.get("kind", "text")),),
                    reasoning=(
                        "Provider summary materialized without fetching remote body."
                        if research_summary
                        else "Persisted Source Chunk."
                    ),
                )
            )
        return tuple(candidates)

    def _research_results(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any], ...]:
        run = inspect_research_run(self.workspace, run_id)
        if run.get("status") != "complete":
            raise EvidenceMaterializationError(
                f"Research Run must be complete before materialization: {run_id} status={run.get('status')}"
            )
        results: list[dict[str, Any]] = []
        for task in run.get("tasks", []):
            raw_path = task.get("cache_snapshot_path")
            if not raw_path:
                raise EvidenceMaterializationError(
                    f"Completed research task has no cache snapshot: {task.get('task_id')}"
                )
            snapshot = read_json(self.workspace / str(raw_path))
            for item in snapshot.get("results", []):
                results.append(
                    {
                        **dict(item),
                        "query_id": task["query_id"],
                        "run_id": run_id,
                        "provider": dict(run["provider"]),
                    }
                )
        return run, *results

    def _existing_materialized_records(
        self,
        source: dict[str, Any] | None,
        canonical_url: str,
    ) -> dict[str, dict[str, Any]]:
        """Recover current materializer-owned result records for one canonical URL."""

        if source is None:
            return {}
        ingestion = source.get("ingestion", {})
        if ingestion.get("parser_name") != _WEB_MATERIALIZER:
            raise EvidenceMaterializationError(
                f"Web Source is not owned by the Research Result materializer: {source.get('source_id')}"
            )
        snapshot = load_source_snapshot(
            self.workspace,
            self.project_id,
            source,
            self.schemas.schema_dir,
        )
        records: dict[str, dict[str, Any]] = {}
        for chunk in snapshot.get("chunks", []):
            metadata = dict(chunk.get("metadata", {}))
            result_id = _normalize_text(metadata.get("research_result_id"))
            if not result_id:
                raise EvidenceMaterializationError(
                    f"Materialized Web Source has a Chunk without research_result_id: {source.get('source_id')}"
                )
            if metadata.get("remote_body_fetched") is not False:
                raise EvidenceMaterializationError(
                    f"Materialized Web Source has incompatible coverage semantics: {source.get('source_id')}"
                )
            if canonical_web_url(str(metadata.get("canonical_url", ""))) != canonical_url:
                raise EvidenceMaterializationError(
                    f"Materialized Web Source canonical URL drift: {source.get('source_id')}"
                )
            records[result_id] = {
                "result_id": result_id,
                "query_id": str(metadata.get("query_id", "")),
                "title": str(metadata.get("title", source.get("title", ""))),
                "summary": str(chunk.get("text", "")),
                "locator": str(metadata.get("remote_locator", canonical_url)),
                "url": canonical_url,
                "source_tier": str(metadata.get("source_tier", "unknown")),
                "retrieved_at": str(metadata.get("retrieved_at", source.get("retrieved_at", ""))),
                "published_at": metadata.get("published_at"),
                "metadata": dict(metadata.get("provider_metadata", {})),
                "provider": dict(metadata.get("provider", {})),
                "run_id": str(metadata.get("research_run_id", "")),
            }
        return records

    def materialize_research_run(self, run_id: str) -> ResearchMaterializationResult:
        """Materialize verified Research cache facts as partial Web Source snapshots."""

        packed = self._research_results(run_id)
        results = list(packed[1:])
        if not results:
            raise EvidenceMaterializationError(f"Research Run has no results to materialize: {run_id}")

        grouped: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            canonical = canonical_web_url(str(result.get("url") or result.get("locator") or ""))
            result["canonical_url"] = canonical
            grouped.setdefault(canonical, []).append(result)

        ledger, source_ledger_version = self.runtime.read_artifact_snapshot("source_ledger")
        sources = list(ledger.get("sources", []))
        url_to_source: dict[str, dict[str, Any]] = {}
        for source in sources:
            if source.get("kind") != "web":
                continue
            try:
                canonical = canonical_web_url(str(source.get("path_or_url", "")))
            except EvidenceMaterializationError:
                continue
            if canonical in url_to_source and url_to_source[canonical]["source_id"] != source["source_id"]:
                raise EvidenceMaterializationError(
                    f"Web Source URL is aliased by multiple Source IDs: {canonical}"
                )
            url_to_source[canonical] = source

        next_number = _next_source_number(sources)
        assigned: dict[str, str] = {}
        for canonical in sorted(grouped):
            existing = url_to_source.get(canonical)
            if existing is not None:
                ingestion = existing.get("ingestion")
                if not ingestion or ingestion.get("parser_name") != _WEB_MATERIALIZER:
                    raise EvidenceMaterializationError(
                        "Research Result cannot overwrite an existing Web Source owned by another ingestion path: "
                        f"{canonical} ({existing.get('source_id')})"
                    )
                assigned[canonical] = str(existing["source_id"])
                continue
            if next_number > 999:
                raise EvidenceMaterializationError("Source ID space is exhausted")
            assigned[canonical] = f"SRC-{next_number:03d}"
            next_number += 1

        candidate_sources = copy.deepcopy(sources)
        source_by_id = {str(item["source_id"]): item for item in candidate_sources}
        source_ids: list[str] = []
        result_ids: list[str] = []
        candidates: list[EvidenceCandidate] = []
        source_ledger_changed = False
        limits = SourceParseLimits()

        for canonical in sorted(grouped):
            source_id = assigned[canonical]
            group = sorted(grouped[canonical], key=lambda item: str(item["result_id"]))
            existing = source_by_id.get(source_id)
            records_by_id = self._existing_materialized_records(existing, canonical)
            current_result_ids: set[str] = set()
            for item in group:
                result_id = str(item["result_id"])
                current_result_ids.add(result_id)
                records_by_id[result_id] = {
                    "result_id": result_id,
                    "query_id": item["query_id"],
                    "title": item["title"],
                    "summary": item["summary"],
                    "locator": item["locator"],
                    "url": canonical,
                    "source_tier": item["source_tier"],
                    "retrieved_at": item["retrieved_at"],
                    "published_at": item.get("published_at"),
                    "metadata": item.get("metadata", {}),
                    "provider": item["provider"],
                    "run_id": run_id,
                }
            payload_records = [records_by_id[result_id] for result_id in sorted(records_by_id)]
            payload = canonical_json_bytes(payload_records)
            blocks = [
                SourceBlock(
                    locator=f"research result {item['result_id']}",
                    text=str(item["summary"]),
                    kind="research_summary",
                    metadata={
                        "title": item["title"],
                        "canonical_url": canonical,
                        "remote_locator": item["locator"],
                        "query_id": item["query_id"],
                        "research_run_id": item["run_id"],
                        "research_result_id": item["result_id"],
                        "provider": item["provider"],
                        "provider_metadata": item.get("metadata", {}),
                        "source_tier": item["source_tier"],
                        "retrieved_at": item["retrieved_at"],
                        "published_at": item.get("published_at"),
                        "remote_body_fetched": False,
                    },
                )
                for item in payload_records
            ]
            chunks = build_chunks(
                source_id,
                blocks,
                max_chunk_chars=limits.max_chunk_chars,
                max_chunks=limits.max_chunks,
            )
            retrieved_at = max(str(item["retrieved_at"]) for item in payload_records)
            risks = build_source_risks(
                chunks,
                source_id,
                max_risks=limits.max_risks,
            )
            result = SourceParseResult(
                source_id=source_id,
                parser_name=_WEB_MATERIALIZER,
                parser_version=_WEB_MATERIALIZER_VERSION,
                detected_format=DetectedSourceFormat(
                    family="web_research_summary",
                    media_type="text/x-slidethus-research-summary",
                    suffix="",
                    signature="research-provider-result",
                    confidence="high",
                ),
                source_sha256=sha256_bytes(payload),
                size_bytes=len(payload),
                parsed_at=retrieved_at,
                chunks=chunks,
                parse_status="partial",
                warnings=(
                    "Research provider summary only; remote page body was not fetched or independently verified.",
                ),
                risks=risks,
            )
            snapshot = build_source_snapshot(self.project_id, result, limits)
            errors = validate_snapshot_data(snapshot, self.schemas.schema_dir)
            if errors:
                raise EvidenceMaterializationError(
                    "Research materialization produced an invalid Source Snapshot: " + "; ".join(errors)
                )
            key = source_snapshot_key(result, limits)
            relative_path = Path(".slidethus/cache/ingestion") / f"{key}.json"
            absolute_path = self.workspace / relative_path
            created = atomic_create_json(absolute_path, snapshot)
            if not created and read_json(absolute_path) != snapshot:
                raise EvidenceMaterializationError(
                    f"Immutable Web Source snapshot path contains different content: {relative_path}"
                )
            snapshot_hash = sha256_file(absolute_path)
            tiers = [str(item.get("source_tier", "unknown")) for item in payload_records]
            _strongest, weakest, _all_tiers = _authority_extrema(tiers)
            published_dates = [
                value
                for value in (_date_text(item.get("published_at")) for item in payload_records)
                if value
            ]
            freshness_date = max(published_dates) if published_dates else None
            record = {
                "source_id": source_id,
                "kind": "web",
                "title": str(group[0]["title"]),
                "path_or_url": canonical,
                "ownership": "public_reference",
                "confidentiality": "public",
                "authority_tier": weakest,
                "freshness_date": freshness_date,
                "retrieved_at": retrieved_at,
                "content_hash": f"sha256:{result.source_sha256}",
                "media_type": result.detected_format.media_type,
                "size_bytes": result.size_bytes,
                "ingestion": {
                    "parser_name": result.parser_name,
                    "parser_version": result.parser_version,
                    "detected_family": result.detected_format.family,
                    "snapshot_path": relative_path.as_posix(),
                    "snapshot_sha256": snapshot_hash,
                    "chunk_count": len(snapshot["chunks"]),
                    "warning_count": len(snapshot["warnings"]),
                    "risk_count": len(snapshot["risks"]),
                    "limits": asdict(limits),
                    "ingested_at": snapshot["created_at"],
                },
                "parse_status": "partial",
                "allowed_use": "citation_only",
                "notes": [
                    "Materialized from M2.3 Research Result lineage; remote body was not fetched.",
                    "Research runs: "
                    + ", ".join(sorted({str(item["run_id"]) for item in payload_records}))
                    + ".",
                    "Only provider-returned title/summary/URL/metadata are represented in this Source Snapshot.",
                    "content_hash identifies the materialized Research Result payload, not the remote Web page body.",
                ],
            }
            if existing != record:
                source_ledger_changed = True
                source_by_id[source_id] = record
            source_ids.append(source_id)
            for chunk in chunks:
                metadata = chunk.metadata
                if (
                    str(metadata.get("research_run_id")) != run_id
                    or str(metadata.get("research_result_id")) not in current_result_ids
                ):
                    continue
                candidate = make_evidence_candidate(
                    claim=chunk.text,
                    source_id=source_id,
                    locator=chunk.locator,
                    support_type="indirect",
                    origin_kind="research_summary",
                    source_chunk_id=chunk.chunk_id,
                    research_run_id=run_id,
                    research_result_id=str(metadata["research_result_id"]),
                    freshness_date=_date_text(metadata.get("published_at")),
                    tags=("research", "summary"),
                    reasoning="Research provider summary; remote body not fetched.",
                )
                candidates.append(candidate)
                result_ids.append(str(metadata["research_result_id"]))

        if source_ledger_changed:
            updated_sources = sorted(source_by_id.values(), key=_source_sort_key)
            candidate_ledger = copy.deepcopy(ledger)
            candidate_ledger["sources"] = updated_sources
            self.runtime.write_artifact(
                "source_ledger",
                candidate_ledger,
                expected_version=source_ledger_version,
                status="approved",
                created_by="evidence-engine-research-materializer",
            )

        return ResearchMaterializationResult(
            run_id=run_id,
            source_ids=tuple(dict.fromkeys(source_ids)),
            result_ids=tuple(dict.fromkeys(result_ids)),
            candidates=tuple(candidates),
            source_ledger_changed=source_ledger_changed,
        )

    def _validate_candidate(self, candidate: EvidenceCandidate) -> None:
        if not _CANDIDATE_ID.fullmatch(candidate.candidate_id):
            raise EvidenceAdjudicationError(f"Invalid candidate ID: {candidate.candidate_id}")
        if candidate.candidate_id != candidate_id_for(candidate):
            raise EvidenceAdjudicationError(
                f"Candidate identity mismatch: {candidate.candidate_id}"
            )
        if not _normalize_text(candidate.claim):
            raise EvidenceAdjudicationError("Evidence candidate claim must not be blank")
        if candidate.support_type not in {"direct", "indirect", "context"}:
            raise EvidenceAdjudicationError(
                f"Invalid support_type on {candidate.candidate_id}: {candidate.support_type}"
            )
        if candidate.source_id is None:
            if candidate.origin_kind not in {"inference", "assumption"}:
                raise EvidenceAdjudicationError(
                    f"Source-less candidate must be inference/assumption: {candidate.candidate_id}"
                )
        elif not _SOURCE_ID.fullmatch(candidate.source_id):
            raise EvidenceAdjudicationError(f"Invalid source ID on {candidate.candidate_id}")
        if candidate.conflict_key and candidate.stance not in {"supports", "opposes", "neutral"}:
            raise EvidenceAdjudicationError(
                f"Explicit conflict candidate requires supports/opposes/neutral stance: {candidate.candidate_id}"
            )

    def _source_context(
        self,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, dict[str, Any]]],
        set[str],
    ]:
        ledger = self.runtime.show_artifact("source_ledger")
        source_map = {str(item["source_id"]): item for item in ledger.get("sources", [])}
        locator_map: dict[str, dict[str, dict[str, Any]]] = {}
        high_risk_source_ids: set[str] = set()
        for source_id, source in source_map.items():
            if not source.get("ingestion"):
                continue
            snapshot = load_source_snapshot(
                self.workspace,
                self.project_id,
                source,
                self.schemas.schema_dir,
            )
            locator_map[source_id] = {
                str(item["locator"]): dict(item)
                for item in snapshot.get("chunks", [])
            }
            if self._current_high_risk_count(snapshot):
                high_risk_source_ids.add(source_id)
        return source_map, locator_map, high_risk_source_ids

    def _decision(
        self,
        *,
        candidates: list[EvidenceCandidate],
        refs: list[dict[str, Any]],
        sources: dict[str, dict[str, Any]],
        high_risk_source_ids: set[str],
        conflict_group: str | None,
        freshness_cutoff: str | None,
        existing_support_status: str | None = None,
    ) -> tuple[EvidencePolicyDecision, dict[str, Any], dict[str, Any], str | None]:
        reason_codes: list[str] = []
        origins = {candidate.origin_kind for candidate in candidates}
        if conflict_group is not None:
            support_status = "disputed"
            reason_codes.append("explicit_conflict_group")
        elif origins == {"inference"} and existing_support_status not in {"verified", "provisional"}:
            support_status = "inference"
            reason_codes.append("explicit_inference")
        elif origins == {"assumption"} and existing_support_status not in {"verified", "provisional"}:
            support_status = "assumption"
            reason_codes.append("explicit_assumption")
        elif not refs:
            support_status = "unsupported"
            reason_codes.append("no_source_reference")
        else:
            referenced_sources = [sources[str(ref["source_id"])] for ref in refs]
            uses_high_risk_source = any(
                str(ref["source_id"]) in high_risk_source_ids for ref in refs
            )
            has_direct_full = any(
                ref["support_type"] == "direct"
                and source.get("parse_status") == "parsed"
                and source.get("kind") != "web"
                for ref, source in zip(refs, referenced_sources, strict=True)
            )
            if has_direct_full and not uses_high_risk_source:
                support_status = "verified"
                reason_codes.append("direct_parsed_source")
            else:
                support_status = "provisional"
                reason_codes.append(
                    "high_risk_source_requires_qualification"
                    if uses_high_risk_source
                    else "partial_or_indirect_source"
                )

        referenced_sources = [sources[str(ref["source_id"])] for ref in refs] if refs else []
        strongest, weakest, tiers = _authority_extrema(
            source.get("authority_tier", "unknown") for source in referenced_sources
        )
        authority_reason = ["authority_from_source_ledger"]
        if weakest in {"community", "unknown"}:
            authority_reason.append("low_authority_present")
            reason_codes.append("low_authority_present")
        authority = {
            "strongest_tier": strongest,
            "weakest_tier": weakest,
            "source_tiers": list(tiers),
            "reason_codes": authority_reason,
        }

        freshness_dates = [candidate.freshness_date for candidate in candidates]
        freshness_dates.extend(source.get("freshness_date") for source in referenced_sources)
        freshness_status, evaluated_date, freshness_reasons = _freshness_decision(
            freshness_dates,
            freshness_cutoff,
        )
        reason_codes.extend(freshness_reasons)
        freshness = {
            "status": freshness_status,
            "cutoff_date": _date_text(freshness_cutoff),
            "evaluated_date": evaluated_date,
            "reason_codes": list(freshness_reasons),
        }

        forbidden_source = any(
            source.get("allowed_use") in {"do_not_use", "metadata_only"}
            for source in referenced_sources
        )
        internal_source = any(
            source.get("allowed_use") == "internal_only"
            or source.get("confidentiality") in {"internal", "confidential", "restricted"}
            for source in referenced_sources
        )
        if forbidden_source:
            use_policy = "do_not_use"
            reason_codes.append("source_policy_forbids_factual_use")
        elif support_status in {"unsupported", "disputed"}:
            use_policy = "do_not_use"
            reason_codes.append("support_status_blocks_use")
        elif internal_source:
            use_policy = "internal_only"
            reason_codes.append("source_restricted_to_internal_use")
        elif (
            support_status in {"provisional", "inference", "assumption"}
            or freshness_status in {"stale", "unknown"}
            or weakest in {"community", "unknown"}
        ):
            use_policy = "allowed_with_qualification"
            reason_codes.append("qualification_required")
        else:
            use_policy = "allowed_with_citation"
            reason_codes.append("citation_required")

        decision = EvidencePolicyDecision(
            support_status=support_status,
            use_policy=use_policy,
            strongest_authority=strongest,
            weakest_authority=weakest,
            freshness_status=freshness_status,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            conflict_group=conflict_group,
        )
        freshness_date = evaluated_date
        return decision, authority, freshness, freshness_date

    def _reconcile_existing_claims(
        self,
        claims: list[dict[str, Any]],
        *,
        sources: dict[str, dict[str, Any]],
        locator_map: dict[str, dict[str, dict[str, Any]]],
        high_risk_source_ids: set[str],
        freshness_cutoff: str | None,
    ) -> list[dict[str, Any]]:
        """Downgrade Production claims whose current Source lineage no longer supports them."""

        reconciled: list[dict[str, Any]] = []
        for original in claims:
            record = copy.deepcopy(original)
            if record.get("adjudication", {}).get("engine") != _ENGINE_NAME:
                reconciled.append(record)
                continue
            expected_key = str(record.get("claim_key") or claim_key(str(record.get("claim", ""))))
            persisted_bindings = record.get("candidate_bindings")
            if persisted_bindings is not None:
                valid_bindings: list[dict[str, Any]] = []
                invalidated = False
                for raw_binding in persisted_bindings:
                    binding = copy.deepcopy(raw_binding)
                    candidate = _candidate_from_binding(str(record.get("claim", "")), binding)
                    source_id = candidate.source_id
                    if source_id is None:
                        valid_bindings.append(binding)
                        continue
                    source = sources.get(source_id)
                    if source is None:
                        invalidated = True
                        continue
                    if not source.get("ingestion"):
                        valid_bindings.append(binding)
                        continue
                    chunk = locator_map.get(source_id, {}).get(str(candidate.locator or ""))
                    if chunk is None:
                        invalidated = True
                        continue
                    if (
                        binding.get("source_chunk_id") != chunk.get("chunk_id")
                        or binding.get("content_hash") != chunk.get("content_hash")
                    ):
                        invalidated = True
                        continue
                    if candidate.origin_kind in {"source_chunk", "research_summary"} and (
                        claim_key(str(chunk.get("text", ""))) != expected_key
                    ):
                        invalidated = True
                        continue
                    valid_bindings.append(binding)

                candidates = [
                    _candidate_from_binding(str(record.get("claim", "")), binding)
                    for binding in valid_bindings
                ]
                refs = _source_refs_from_bindings(valid_bindings)
                declared_groups = {
                    conflict_group_id(str(binding["conflict_key"]))
                    for binding in valid_bindings
                    if binding.get("conflict_key")
                }
                if len(declared_groups) > 1:
                    raise EvidenceAdjudicationError(
                        f"One exact claim cannot belong to multiple conflict groups: {expected_key}"
                    )
                declared_group = next(iter(declared_groups), None)
                stances = sorted(
                    {
                        str(binding["stance"])
                        for binding in valid_bindings
                        if binding.get("stance")
                    }
                )
                disputed = {"supports", "opposes"}.issubset(set(stances))
                decision, authority, freshness, freshness_date = self._decision(
                    candidates=candidates,
                    refs=refs,
                    sources=sources,
                    high_risk_source_ids=high_risk_source_ids,
                    conflict_group=declared_group if disputed else None,
                    freshness_cutoff=freshness_cutoff,
                    existing_support_status=str(record.get("support_status", "")),
                )
                record["candidate_bindings"] = valid_bindings
                record["candidate_refs"] = sorted(
                    str(binding["candidate_id"]) for binding in valid_bindings
                )
                record["source_refs"] = refs
                record["conflict_group"] = declared_group
                record["conflict_stances"] = stances
                record["support_status"] = decision.support_status
                record["use_policy"] = decision.use_policy
                record["authority_decision"] = authority
                record["freshness_decision"] = freshness
                record["freshness_date"] = freshness_date
                generated_prefix = "Explicit conflict group "
                notes = [
                    note
                    for note in record.get("conflict_notes", [])
                    if not str(note).startswith(generated_prefix)
                ]
                if disputed and declared_group:
                    notes.append(
                        f"Explicit conflict group {declared_group} contains opposing candidate stances."
                    )
                record["conflict_notes"] = notes
                reasons = list(decision.reason_codes)
                if invalidated:
                    reasons.append("source_lineage_invalidated")
                adjudication = dict(record.get("adjudication", {}))
                adjudication.update(
                    {
                        "engine": _ENGINE_NAME,
                        "version": _ENGINE_VERSION,
                        "reason_codes": list(dict.fromkeys(reasons)),
                    }
                )
                record["adjudication"] = adjudication
                record["reasoning"] = "; ".join(adjudication["reason_codes"])
                reconciled.append(record)
                continue
            valid_refs: list[dict[str, Any]] = []
            invalidated = False
            for ref in record.get("source_refs", []):
                source_id = str(ref.get("source_id", ""))
                source = sources.get(source_id)
                if source is None:
                    invalidated = True
                    continue
                if not source.get("ingestion"):
                    valid_refs.append(copy.deepcopy(ref))
                    continue
                chunk = locator_map.get(source_id, {}).get(str(ref.get("locator", "")))
                if chunk is None:
                    invalidated = True
                    continue
                bound_chunk_id = ref.get("chunk_id")
                bound_content_hash = ref.get("content_hash")
                if bound_chunk_id and bound_content_hash:
                    if (
                        bound_chunk_id != chunk.get("chunk_id")
                        or bound_content_hash != chunk.get("content_hash")
                    ):
                        invalidated = True
                        continue
                elif ref.get("support_type") != "context":
                    try:
                        current_key = claim_key(str(chunk.get("text", "")))
                    except EvidenceAdjudicationError:
                        invalidated = True
                        continue
                    if current_key != expected_key:
                        invalidated = True
                        continue
                valid_refs.append(copy.deepcopy(ref))
            if not invalidated:
                reconciled.append(record)
                continue

            record["source_refs"] = valid_refs
            record["candidate_refs"] = []
            if valid_refs:
                decision, authority, freshness, freshness_date = self._decision(
                    candidates=[],
                    refs=valid_refs,
                    sources=sources,
                    high_risk_source_ids=high_risk_source_ids,
                    conflict_group=(
                        str(record.get("conflict_group"))
                        if record.get("support_status") == "disputed" and record.get("conflict_group")
                        else None
                    ),
                    freshness_cutoff=freshness_cutoff,
                    existing_support_status=str(record.get("support_status", "")),
                )
                record["support_status"] = decision.support_status
                record["use_policy"] = decision.use_policy
                record["authority_decision"] = authority
                record["freshness_decision"] = freshness
                record["freshness_date"] = freshness_date
                reason_codes = list(decision.reason_codes)
            else:
                previous_status = str(record.get("support_status", ""))
                if previous_status in {"inference", "assumption"}:
                    record["support_status"] = previous_status
                    record["use_policy"] = "allowed_with_qualification"
                else:
                    record["support_status"] = "unsupported"
                    record["use_policy"] = "do_not_use"
                strongest, weakest, tiers = _authority_extrema(())
                record["authority_decision"] = {
                    "strongest_tier": strongest,
                    "weakest_tier": weakest,
                    "source_tiers": list(tiers),
                    "reason_codes": ["no_current_source_support"],
                }
                freshness_status, evaluated_date, freshness_reasons = _freshness_decision(
                    (), freshness_cutoff
                )
                record["freshness_decision"] = {
                    "status": freshness_status,
                    "cutoff_date": _date_text(freshness_cutoff),
                    "evaluated_date": evaluated_date,
                    "reason_codes": list(freshness_reasons),
                }
                record["freshness_date"] = evaluated_date
                record["conflict_group"] = None
                record["conflict_stances"] = []
                reason_codes = [
                    "source_lineage_invalidated",
                    "no_current_source_support",
                    "support_status_blocks_use",
                ]
            if "source_lineage_invalidated" not in reason_codes:
                reason_codes.append("source_lineage_invalidated")
            adjudication = dict(record.get("adjudication", {}))
            adjudication["engine"] = _ENGINE_NAME
            adjudication["version"] = _ENGINE_VERSION
            adjudication["reason_codes"] = list(dict.fromkeys(reason_codes))
            record["adjudication"] = adjudication
            record["reasoning"] = "; ".join(adjudication["reason_codes"])
            reconciled.append(record)
        return reconciled

    def reconcile_current_evidence(
        self,
        *,
        freshness_cutoff: str | None = None,
    ) -> EvidencePublishResult:
        """Re-evaluate current Production claims against current Source lineage and policy."""

        sources, locator_map, high_risk_source_ids = self._source_context()
        ledger, evidence_ledger_version = self.runtime.read_artifact_snapshot(
            "evidence_ledger"
        )
        existing_claims = list(ledger.get("claims", []))
        reconciled_claims = self._reconcile_existing_claims(
            existing_claims,
            sources=sources,
            locator_map=locator_map,
            high_risk_source_ids=high_risk_source_ids,
            freshness_cutoff=freshness_cutoff,
        )
        candidate_ledger = copy.deepcopy(ledger)
        candidate_ledger["claims"] = reconciled_claims
        if candidate_ledger == ledger:
            return EvidencePublishResult(
                changed=False,
                evidence_ids=(),
                ledger=copy.deepcopy(ledger),
            )
        before = {
            str(item.get("evidence_id")): item for item in existing_claims
        }
        touched = tuple(
            str(item["evidence_id"])
            for item in reconciled_claims
            if before.get(str(item.get("evidence_id"))) != item
        )
        self.runtime.write_artifact(
            "evidence_ledger",
            candidate_ledger,
            expected_version=evidence_ledger_version,
            status="approved",
            created_by="deterministic-evidence-engine-reconcile",
        )
        return EvidencePublishResult(
            changed=True,
            evidence_ids=touched,
            ledger=self.runtime.show_artifact("evidence_ledger"),
        )

    def adjudicate(
        self,
        candidates: Iterable[EvidenceCandidate],
        *,
        freshness_cutoff: str | None = None,
        allow_high_risk_source_evidence: bool = False,
    ) -> EvidencePublishResult:
        """Exact-dedupe candidates, adjudicate policy, and version the Evidence Ledger."""

        candidate_list = list(candidates)
        if not candidate_list:
            raise EvidenceAdjudicationError("No Evidence candidates were supplied")
        for candidate in candidate_list:
            self._validate_candidate(candidate)

        sources, locator_map, high_risk_source_ids = self._source_context()
        for candidate in candidate_list:
            if candidate.source_id is None:
                continue
            source = sources.get(candidate.source_id)
            if source is None:
                raise EvidenceAdjudicationError(
                    f"Candidate {candidate.candidate_id} references unknown source {candidate.source_id}"
                )
            if (
                candidate.source_id in high_risk_source_ids
                and not allow_high_risk_source_evidence
            ):
                raise EvidenceAdjudicationError(
                    f"Source {candidate.source_id} has high-severity risk findings; "
                    "explicit high-risk Evidence approval is required"
                )
            if source.get("ingestion"):
                admitted = locator_map.get(candidate.source_id, {})
                chunk = admitted.get(str(candidate.locator))
                if chunk is None:
                    raise EvidenceAdjudicationError(
                        f"Candidate {candidate.candidate_id} locator is not present in Source Snapshot"
                    )
                if candidate.source_chunk_id and candidate.source_chunk_id != chunk.get("chunk_id"):
                    raise EvidenceAdjudicationError(
                        f"Candidate {candidate.candidate_id} source_chunk_id does not match current Source Snapshot"
                    )
                if candidate.origin_kind in {"source_chunk", "research_summary"} and (
                    claim_key(candidate.claim) != claim_key(str(chunk.get("text", "")))
                ):
                    raise EvidenceAdjudicationError(
                        f"Candidate {candidate.candidate_id} claim does not match current Source Chunk content"
                    )

        by_claim_key: dict[str, list[EvidenceCandidate]] = {}
        for candidate in candidate_list:
            by_claim_key.setdefault(claim_key(candidate.claim), []).append(candidate)

        ledger, evidence_ledger_version = self.runtime.read_artifact_snapshot("evidence_ledger")
        existing_claims = self._reconcile_existing_claims(
            list(ledger.get("claims", [])),
            sources=sources,
            locator_map=locator_map,
            high_risk_source_ids=high_risk_source_ids,
            freshness_cutoff=freshness_cutoff,
        )
        key_to_existing: dict[str, dict[str, Any]] = {}
        for item in existing_claims:
            key = str(item.get("claim_key") or claim_key(str(item["claim"])))
            if key in key_to_existing and key_to_existing[key]["evidence_id"] != item["evidence_id"]:
                raise EvidenceAdjudicationError(
                    f"Existing Evidence Ledger contains exact-normalized duplicate claims: {key}"
                )
            key_to_existing[key] = item

        conflict_stances_by_group: dict[str, set[str]] = {}
        for item in existing_claims:
            group_id = item.get("conflict_group")
            if group_id:
                conflict_stances_by_group.setdefault(str(group_id), set()).update(
                    str(stance) for stance in item.get("conflict_stances", [])
                )
        for candidate in candidate_list:
            if candidate.conflict_key:
                group_id = conflict_group_id(candidate.conflict_key)
                if candidate.stance:
                    conflict_stances_by_group.setdefault(group_id, set()).add(candidate.stance)
        disputed_groups = {
            group_id
            for group_id, stances in conflict_stances_by_group.items()
            if {"supports", "opposes"}.issubset(stances)
        }
        for item in existing_claims:
            group_id = item.get("conflict_group")
            if (
                not group_id
                or group_id in disputed_groups
                or item.get("support_status") != "disputed"
            ):
                continue
            decision, authority, freshness, freshness_date = self._decision(
                candidates=[],
                refs=list(item.get("source_refs", [])),
                sources=sources,
                high_risk_source_ids=high_risk_source_ids,
                conflict_group=None,
                freshness_cutoff=freshness_cutoff,
            )
            item["support_status"] = decision.support_status
            item["use_policy"] = decision.use_policy
            item["authority_decision"] = authority
            item["freshness_decision"] = freshness
            item["freshness_date"] = freshness_date
            generated_note = f"Explicit conflict group {group_id} contains opposing candidate stances."
            item["conflict_notes"] = [
                note for note in item.get("conflict_notes", []) if note != generated_note
            ]
            reasons = list(decision.reason_codes)
            reasons.append("conflict_group_no_longer_opposed")
            adjudication = dict(item.get("adjudication", {}))
            adjudication.update(
                {
                    "engine": _ENGINE_NAME,
                    "version": _ENGINE_VERSION,
                    "reason_codes": list(dict.fromkeys(reasons)),
                }
            )
            item["adjudication"] = adjudication
            item["reasoning"] = "; ".join(adjudication["reason_codes"])

        next_number = _next_evidence_number(existing_claims)
        updated_by_id = {str(item["evidence_id"]): copy.deepcopy(item) for item in existing_claims}
        touched_ids: list[str] = []

        for key in sorted(by_claim_key):
            group = sorted(by_claim_key[key], key=lambda item: item.candidate_id)
            existing = key_to_existing.get(key)
            if existing is not None:
                evidence_id = str(existing["evidence_id"])
            else:
                if next_number > 999:
                    raise EvidenceAdjudicationError("Evidence ID space is exhausted")
                evidence_id = f"EVD-{next_number:03d}"
                next_number += 1

            bindings_by_id = {
                str(binding["candidate_id"]): copy.deepcopy(binding)
                for binding in (existing or {}).get("candidate_bindings", [])
            }
            for candidate in group:
                chunk = (
                    locator_map.get(str(candidate.source_id), {}).get(str(candidate.locator))
                    if candidate.source_id is not None and candidate.locator is not None
                    else None
                )
                bindings_by_id[candidate.candidate_id] = _candidate_binding(candidate, chunk)
            candidate_bindings = [
                bindings_by_id[candidate_id] for candidate_id in sorted(bindings_by_id)
            ]
            all_candidates = [
                _candidate_from_binding(
                    str((existing or {}).get("claim") or group[0].claim),
                    binding,
                )
                for binding in candidate_bindings
            ]

            refs_by_key = {
                (str(ref["source_id"]), str(ref["locator"]), str(ref["support_type"])): copy.deepcopy(ref)
                for ref in (
                    (existing or {}).get("source_refs", [])
                    if not (existing or {}).get("candidate_bindings")
                    else []
                )
            }
            for ref in _source_refs_from_bindings(candidate_bindings):
                ref_key = (str(ref["source_id"]), str(ref["locator"]), str(ref["support_type"]))
                refs_by_key[ref_key] = ref
            refs = [refs_by_key[ref_key] for ref_key in sorted(refs_by_key)]

            declared_groups = {
                conflict_group_id(str(binding["conflict_key"]))
                for binding in candidate_bindings
                if binding.get("conflict_key")
            }
            existing_group = (existing or {}).get("conflict_group")
            if existing_group and not candidate_bindings:
                declared_groups.add(str(existing_group))
            if len(declared_groups) > 1:
                raise EvidenceAdjudicationError(
                    f"One exact claim cannot belong to multiple conflict groups: {key}"
                )
            conflict_group = next(iter(declared_groups), None)
            conflict_stances = sorted(
                {
                    str(binding["stance"])
                    for binding in candidate_bindings
                    if binding.get("stance")
                }
                or set((existing or {}).get("conflict_stances", []))
            )
            decision, authority, freshness, freshness_date = self._decision(
                candidates=all_candidates or group,
                refs=refs,
                sources=sources,
                high_risk_source_ids=high_risk_source_ids,
                conflict_group=(
                    conflict_group if conflict_group in disputed_groups else None
                ),
                freshness_cutoff=freshness_cutoff,
                existing_support_status=(existing or {}).get("support_status"),
            )
            candidate_refs = sorted(
                str(binding["candidate_id"]) for binding in candidate_bindings
            ) or sorted(
                set((existing or {}).get("candidate_refs", []))
                | {candidate.candidate_id for candidate in group}
            )
            tags = sorted(
                set(str(tag) for tag in (existing or {}).get("tags", []))
                | {tag for candidate in group for tag in candidate.tags}
            )
            conflict_notes = list((existing or {}).get("conflict_notes", []))
            if conflict_group in disputed_groups:
                note = f"Explicit conflict group {conflict_group} contains opposing candidate stances."
                if note not in conflict_notes:
                    conflict_notes.append(note)
            claim_record = {
                "evidence_id": evidence_id,
                "claim_key": key,
                "candidate_refs": candidate_refs,
                "candidate_bindings": candidate_bindings,
                "claim": str((existing or {}).get("claim") or group[0].claim),
                "support_status": decision.support_status,
                "source_refs": refs,
                "freshness_date": freshness_date,
                "authority_decision": authority,
                "freshness_decision": freshness,
                "conflict_group": conflict_group,
                "conflict_stances": conflict_stances,
                "adjudication": {
                    "engine": _ENGINE_NAME,
                    "version": _ENGINE_VERSION,
                    "reason_codes": list(decision.reason_codes),
                },
                "conflict_notes": conflict_notes,
                "use_policy": decision.use_policy,
                "reasoning": "; ".join(decision.reason_codes),
                "tags": tags,
            }
            updated_by_id[evidence_id] = claim_record
            touched_ids.append(evidence_id)

        for record in updated_by_id.values():
            group_id = record.get("conflict_group")
            if group_id not in disputed_groups:
                continue
            record["support_status"] = "disputed"
            record["use_policy"] = "do_not_use"
            note = f"Explicit conflict group {group_id} contains opposing candidate stances."
            notes = list(record.get("conflict_notes", []))
            if note not in notes:
                notes.append(note)
            record["conflict_notes"] = notes
            adjudication = dict(record.get("adjudication", {}))
            reasons = list(adjudication.get("reason_codes", []))
            for reason in ("explicit_conflict_group", "support_status_blocks_use"):
                if reason not in reasons:
                    reasons.append(reason)
            if adjudication:
                adjudication["reason_codes"] = reasons
                record["adjudication"] = adjudication
            record["reasoning"] = "; ".join(reasons) if reasons else record.get("reasoning", "")

        candidate_ledger = copy.deepcopy(ledger)
        candidate_ledger["claims"] = sorted(
            updated_by_id.values(),
            key=lambda item: int(str(item["evidence_id"]).split("-")[-1]),
        )
        changed = candidate_ledger != ledger
        if changed:
            self.runtime.write_artifact(
                "evidence_ledger",
                candidate_ledger,
                expected_version=evidence_ledger_version,
                status="approved",
                created_by="deterministic-evidence-engine",
            )
            candidate_ledger = self.runtime.show_artifact("evidence_ledger")
        return EvidencePublishResult(
            changed=changed,
            evidence_ids=tuple(touched_ids),
            ledger=copy.deepcopy(candidate_ledger),
        )

    def materialize_and_adjudicate_research(
        self,
        run_id: str,
        *,
        freshness_cutoff: str | None = None,
        complete_cycle: bool = True,
        allow_high_risk_source_evidence: bool = False,
    ) -> tuple[ResearchMaterializationResult, EvidencePublishResult]:
        materialized = self.materialize_research_run(run_id)
        published = self.adjudicate(
            materialized.candidates,
            freshness_cutoff=freshness_cutoff,
            allow_high_risk_source_evidence=allow_high_risk_source_evidence,
        )
        if complete_cycle:
            completed_ledger = self.complete_research_cycle(run_id)
            published = EvidencePublishResult(
                changed=published.changed or completed_ledger != published.ledger,
                evidence_ids=published.evidence_ids,
                ledger=completed_ledger,
            )
        return materialized, published

    def complete_research_cycle(self, run_id: str) -> dict[str, Any]:
        """Complete one semantic research cycle only after Run results are materialized and usable."""

        run = inspect_research_run(self.workspace, run_id)
        if run.get("status") != "complete":
            raise EvidenceAdjudicationError(
                f"Research Run is not complete: {run_id} status={run.get('status')}"
            )
        expected_results = {
            str(result_id)
            for task in run.get("tasks", [])
            for result_id in task.get("result_ids", [])
        }
        if not expected_results:
            raise EvidenceAdjudicationError("Research Run has no results to complete")

        source_ledger = self.runtime.show_artifact("source_ledger")
        result_to_source: dict[str, tuple[str, EvidenceCandidate]] = {}
        for source in source_ledger.get("sources", []):
            if source.get("kind") != "web" or not source.get("ingestion"):
                continue
            snapshot = load_source_snapshot(
                self.workspace,
                self.project_id,
                source,
                self.schemas.schema_dir,
            )
            for item in snapshot.get("chunks", []):
                metadata = item.get("metadata", {})
                if metadata.get("research_run_id") != run_id:
                    continue
                result_id = str(metadata.get("research_result_id", ""))
                if not result_id:
                    continue
                candidate = make_evidence_candidate(
                    claim=str(item["text"]),
                    source_id=str(source["source_id"]),
                    locator=str(item["locator"]),
                    support_type="indirect",
                    origin_kind="research_summary",
                    source_chunk_id=str(item["chunk_id"]),
                    research_run_id=run_id,
                    research_result_id=result_id,
                    freshness_date=_date_text(metadata.get("published_at")),
                    tags=("research", "summary"),
                    reasoning="Research provider summary; remote body not fetched.",
                )
                result_to_source[result_id] = (str(source["source_id"]), candidate)
        if set(result_to_source) != expected_results:
            missing = sorted(expected_results - set(result_to_source))
            raise EvidenceAdjudicationError(
                "Research Run results are not fully materialized: " + ", ".join(missing)
            )

        evidence, evidence_ledger_version = self.runtime.read_artifact_snapshot("evidence_ledger")
        claims_by_candidate = {
            candidate_ref: claim
            for claim in evidence.get("claims", [])
            for candidate_ref in claim.get("candidate_refs", [])
        }
        blocked: list[str] = []
        for result_id, (_source_id, candidate) in result_to_source.items():
            claim = claims_by_candidate.get(candidate.candidate_id)
            if claim is None or claim.get("use_policy") == "do_not_use":
                blocked.append(result_id)
        if blocked:
            raise EvidenceAdjudicationError(
                "Research results lack usable adjudicated Evidence: " + ", ".join(sorted(blocked))
            )

        cycle_id = str(run["cycle_id"])
        cycles = list(evidence.get("research_cycles", []))
        cycle = next((item for item in cycles if item.get("cycle_id") == cycle_id), None)
        if cycle is not None:
            if cycle.get("kind") != run.get("cycle_kind"):
                raise EvidenceAdjudicationError("Research cycle kind does not match Run")
            if cycle.get("outline_version") != run.get("outline_version"):
                raise EvidenceAdjudicationError("Research cycle outline version does not match Run")
            updated_cycle = copy.deepcopy(cycle)
        else:
            updated_cycle = {
                "cycle_id": cycle_id,
                "kind": run["cycle_kind"],
                "status": "pending",
                "basis": "none_required",
                "outline_version": run.get("outline_version"),
                "source_ids": [],
                "query_count": 0,
                "waiver_reason": None,
                "notes": [],
            }
            cycles.append(updated_cycle)

        research_source_ids = sorted({source_id for source_id, _candidate in result_to_source.values()})
        existing_source_ids = list(updated_cycle.get("source_ids", []))
        all_source_ids = sorted(set(existing_source_ids) | set(research_source_ids))
        all_run_ids = sorted(set(updated_cycle.get("run_ids", [])) | {run_id})
        query_count = 0
        for referenced_run_id in all_run_ids:
            referenced_run = inspect_research_run(self.workspace, referenced_run_id)
            if referenced_run.get("status") != "complete":
                raise EvidenceAdjudicationError(
                    f"Research cycle cannot complete with non-complete Run: {referenced_run_id}"
                )
            if (
                referenced_run.get("cycle_id") != cycle_id
                or referenced_run.get("cycle_kind") != run.get("cycle_kind")
                or referenced_run.get("outline_version") != run.get("outline_version")
            ):
                raise EvidenceAdjudicationError(
                    f"Research cycle Run lineage is inconsistent: {referenced_run_id}"
                )
            query_count += len(referenced_run.get("tasks", []))

        source_map = {str(item["source_id"]): item for item in source_ledger.get("sources", [])}
        has_user_materials = any(
            source_map.get(source_id, {}).get("kind") != "web"
            for source_id in all_source_ids
        )
        updated_cycle.update(
            {
                "status": "complete",
                "basis": "mixed" if has_user_materials else "external_research",
                "source_ids": all_source_ids,
                "run_ids": all_run_ids,
                "query_count": query_count,
                "waiver_reason": None,
            }
        )
        note = (
            f"Research Run {run_id} completed; all {len(expected_results)} result(s) were materialized "
            "as partial Web Sources and adjudicated before semantic cycle completion."
        )
        notes = list(updated_cycle.get("notes", []))
        if note not in notes:
            notes.append(note)
        updated_cycle["notes"] = notes

        candidate_ledger = copy.deepcopy(evidence)
        candidate_ledger["research_cycles"] = [
            updated_cycle if item.get("cycle_id") == cycle_id else item
            for item in cycles
        ]
        if cycle is None and not any(
            item.get("cycle_id") == cycle_id for item in candidate_ledger["research_cycles"]
        ):
            candidate_ledger["research_cycles"].append(updated_cycle)
        candidate_ledger["research_cycles"] = sorted(
            candidate_ledger["research_cycles"],
            key=lambda item: int(str(item["cycle_id"]).split("-")[-1]),
        )
        if candidate_ledger == evidence:
            return copy.deepcopy(evidence)
        self.runtime.write_artifact(
            "evidence_ledger",
            candidate_ledger,
            expected_version=evidence_ledger_version,
            status="approved",
            created_by="deterministic-evidence-engine",
        )
        return self.runtime.show_artifact("evidence_ledger")
