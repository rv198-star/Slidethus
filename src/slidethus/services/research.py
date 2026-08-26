from __future__ import annotations

from collections.abc import Sequence

from slidethus.protocols import ResearchProvider, ResearchQuery, ResearchResult


def run_research(provider: ResearchProvider, queries: Sequence[ResearchQuery]) -> Sequence[ResearchResult]:
    """Execute provider-neutral research. Evidence conversion belongs to M2."""

    return provider.search(queries)
