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


@dataclass(frozen=True)
class SourceParseLimits:
    max_source_bytes: int = 50 * 1024 * 1024
    max_chunks: int = 5000
    max_chunk_chars: int = 12_000


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
    warnings: tuple[str, ...] = ()
    risks: tuple[SourceRisk, ...] = ()


@dataclass(frozen=True)
class ResearchQuery:
    query_id: str
    query: str
    cycle_id: str
    cycle_kind: str
    outline_version: int | None = None
    freshness_requirement: str | None = None
    preferred_source_tiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchResult:
    query_id: str
    title: str
    locator: str
    summary: str
    source_tier: str
    retrieved_at: str


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
    def search(self, queries: Sequence[ResearchQuery]) -> Sequence[ResearchResult]: ...


class AssetProvider(Protocol):
    def acquire(self, request: dict[str, Any], output_dir: Path) -> dict[str, Any]: ...


class ReasoningProvider(Protocol):
    def generate_artifact(self, artifact_type: str, inputs: dict[str, Any]) -> dict[str, Any]: ...


class ChartProvider(Protocol):
    def build(self, specification: dict[str, Any], output_dir: Path) -> dict[str, Any]: ...


class DocumentRenderer(Protocol):
    def preview(self, document_path: Path, output_dir: Path) -> Sequence[Path]: ...


class RenderBackend(Protocol):
    name: str

    def render(self, request: RenderRequest) -> RenderResult: ...


class VisualReviewProvider(Protocol):
    def review(self, image_paths: Sequence[Path], context: dict[str, Any]) -> dict[str, Any]: ...
