from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceChunk:
    source_id: str
    locator: str
    text: str
    chunk_id: str = ""
    ordinal: int = 0
    content_hash: str = ""
    kind: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectedSourceFormat:
    family: str
    media_type: str
    suffix: str
    signature: str
    confidence: str

    @property
    def detection_method(self) -> str:
        """Return the stable admission method while preserving snapshot field compatibility."""

        return self.signature


@dataclass(frozen=True)
class SourceParseLimits:
    max_source_bytes: int = 50 * 1024 * 1024
    max_chunks: int = 5000
    max_chunk_chars: int = 12_000
    max_risks: int = 10_000
    max_pages: int = 500
    max_slides: int = 500
    max_sheets: int = 100
    max_rows: int = 100_000
    max_cells: int = 1_000_000
    max_archive_entries: int = 10_000
    max_archive_member_bytes: int = 64 * 1024 * 1024
    max_uncompressed_bytes: int = 512 * 1024 * 1024
    max_image_pixels: int = 100_000_000


@dataclass(frozen=True)
class SourceParseRequest:
    path: Path
    source_id: str
    limits: SourceParseLimits = field(default_factory=SourceParseLimits)


@dataclass(frozen=True)
class SourceRisk:
    risk_id: str
    category: str
    severity: str
    message: str
    locator: str | None = None


@dataclass(frozen=True)
class SourceParseResult:
    source_id: str
    parser_name: str
    parser_version: str
    detected_format: DetectedSourceFormat
    source_sha256: str
    size_bytes: int
    parsed_at: str
    chunks: tuple[SourceChunk, ...]
    parse_status: str = "parsed"
    warnings: tuple[str, ...] = ()
    risks: tuple[SourceRisk, ...] = ()


@dataclass(frozen=True)
class ResearchLimits:
    max_queries: int = 24
    max_query_chars: int = 600
    max_results_per_query: int = 12
    max_total_results: int = 120
    max_title_chars: int = 500
    max_summary_chars: int = 20_000
    max_metadata_bytes: int = 64 * 1024
    cache_ttl_seconds: int = 86_400


@dataclass(frozen=True)
class ResearchQuery:
    query_id: str
    query: str
    cycle_id: str
    cycle_kind: str
    outline_version: int | None = None
    freshness_requirement: str | None = None
    preferred_source_tiers: tuple[str, ...] = ()
    purpose: str = ""
    slide_id: str | None = None


@dataclass(frozen=True)
class ResearchPlan:
    plan_id: str
    project_id: str
    cycle_id: str
    cycle_kind: str
    outline_version: int | None
    queries: tuple[ResearchQuery, ...]
    limits: ResearchLimits = field(default_factory=ResearchLimits)


@dataclass(frozen=True)
class ResearchResult:
    query_id: str
    title: str
    locator: str
    summary: str
    source_tier: str
    retrieved_at: str
    url: str | None = None
    published_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceCandidate:
    candidate_id: str
    claim: str
    source_id: str | None
    locator: str | None
    support_type: str = "direct"
    origin_kind: str = "source_chunk"
    source_chunk_id: str | None = None
    research_run_id: str | None = None
    research_result_id: str | None = None
    freshness_date: str | None = None
    conflict_key: str | None = None
    stance: str | None = None
    tags: tuple[str, ...] = ()
    reasoning: str = ""


@dataclass(frozen=True)
class EvidencePolicyDecision:
    support_status: str
    use_policy: str
    strongest_authority: str
    weakest_authority: str
    freshness_status: str
    reason_codes: tuple[str, ...] = ()
    conflict_group: str | None = None


@dataclass(frozen=True)
class PlanningLimits:
    """Bound M3 provider proposals and deterministic planning artifacts."""

    max_blocking_questions: int = 3
    max_assumptions: int = 24
    max_sections: int = 12
    max_slides: int = 120
    max_blocks_per_slide: int = 12
    max_words_per_slide: int = 240
    max_provider_payload_bytes: int = 2 * 1024 * 1024
    max_change_targets: int = 64


@dataclass(frozen=True)
class ArtDirectionLimits:
    """Bound one provider proposal before P6 art-direction admission."""

    max_provider_payload_bytes: int = 256 * 1024
    max_design_read_chars: int = 600
    max_tone_terms: int = 12
    max_forbidden_patterns: int = 48
    max_component_variants: int = 24


@dataclass(frozen=True)
class ArtDirectionProposal:
    """Provider-neutral aesthetic proposal before deterministic freezing."""

    design_read: str
    dials: dict[str, int]
    direction: dict[str, Any]
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtDirectionSeedProposal:
    """Pre-layout visual direction proposed before Slide Specs own semantic Blocks."""

    design_read: str
    dials: dict[str, int]
    foundation: dict[str, Any]
    direction: dict[str, Any]
    direction_approval: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreLayoutArtDirection:
    """One frozen Seed reference plus bounded data for a planning-provider request."""

    reference: dict[str, Any]
    seed: dict[str, Any]


@dataclass(frozen=True)
class BriefCompletionHints:
    """Explicit user/host hints admitted by deterministic Brief completion."""

    request_text: str = ""
    purpose: str | None = None
    desired_outcome: str | None = None
    call_to_action: str | None = None
    delivery_context: str | None = None
    presentation_mode: str | None = None
    audience_role: str | None = None
    audience_needs: tuple[str, ...] = ()
    audience_objections: tuple[str, ...] = ()
    decision_power: str | None = None
    knowledge_level: str | None = None
    page_target: int | None = None
    duration_minutes: float | None = None
    output_formats: tuple[str, ...] = ()
    editability_target: str | None = None
    approval_mode: str | None = None
    quality_profile: str | None = None


@dataclass(frozen=True)
class PlanningProposal:
    """One provider proposal before deterministic identity/lineage admission."""

    artifact_type: str
    content: dict[str, Any]
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    art_direction_seed: dict[str, Any] | None = None


@dataclass(frozen=True)
class RenderRequest:
    workspace: Path
    target_format: str
    target_editability_level: str
    output_dir: Path


@dataclass(frozen=True)
class RenderResult:
    status: str
    output_paths: tuple[Path, ...]
    preview_paths: tuple[Path, ...] = ()
    actual_editability_level: str = "not_measured"
    font_substitutions: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()


class SourceParser(Protocol):
    name: str
    version: str
    priority: int

    def supports(self, detected_format: DetectedSourceFormat) -> bool: ...

    def parse(
        self,
        request: SourceParseRequest,
        detected_format: DetectedSourceFormat,
    ) -> SourceParseResult: ...


class ResearchProvider(Protocol):
    name: str
    version: str

    def search(self, queries: Sequence[ResearchQuery]) -> Sequence[ResearchResult]: ...


class AssetProvider(Protocol):
    def acquire(self, request: dict[str, Any], output_dir: Path) -> dict[str, Any]: ...


class ReasoningProvider(Protocol):
    def generate_artifact(self, artifact_type: str, inputs: dict[str, Any]) -> dict[str, Any]: ...


class PlanningProvider(Protocol):
    """Provider-neutral structured proposal port for M3 planning."""

    name: str
    version: str

    def propose(
        self,
        artifact_type: str,
        context: dict[str, Any],
        limits: PlanningLimits,
    ) -> PlanningProposal: ...


class ArtDirectionProvider(Protocol):
    """Provider-neutral P6 port for bounded art-direction proposals."""

    name: str
    version: str
    mode: str

    def propose_seed(
        self,
        context: dict[str, Any],
        limits: ArtDirectionLimits,
    ) -> ArtDirectionSeedProposal: ...

    def propose(
        self,
        context: dict[str, Any],
        limits: ArtDirectionLimits,
    ) -> ArtDirectionProposal: ...

    def resource_identity(self) -> dict[str, Any] | None: ...


class ChartProvider(Protocol):
    def build(self, specification: dict[str, Any], output_dir: Path) -> dict[str, Any]: ...


class DocumentRenderer(Protocol):
    def preview(self, document_path: Path, output_dir: Path) -> Sequence[Path]: ...


class RenderBackend(Protocol):
    name: str

    def render(self, request: RenderRequest) -> RenderResult: ...


class SemanticReviewProvider(Protocol):
    """Provider-neutral semantic review port for M5 open-issue and scorecard proposals."""

    name: str
    version: str

    def review(self, context: dict[str, Any]) -> dict[str, Any]: ...


class VisualReviewProvider(Protocol):
    """Provider-neutral full-page visual review port for real rendered page images."""

    name: str
    version: str

    def review(self, image_paths: Sequence[Path], context: dict[str, Any]) -> dict[str, Any]: ...


class StageReviewProvider(Protocol):
    """Host-supplied AI reviewer for one retrospective production-stage lens."""

    name: str
    version: str

    def review(self, context: dict[str, Any]) -> dict[str, Any]: ...


class ReviewSynthesisProvider(Protocol):
    """Host-supplied AI attribution/clustering provider over a completed review set."""

    name: str
    version: str

    def synthesize(self, context: dict[str, Any]) -> dict[str, Any]: ...


class WorkflowCostMeter(Protocol):
    """Host-supplied cumulative external-provider cost meter for M6 budgets."""

    name: str
    version: str

    def current_cost_usd(self) -> float: ...
