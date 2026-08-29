from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from slidethus.errors import ReviewSynthesisError, StageReviewError
from slidethus.io_utils import read_json
from slidethus.stage_ai_reviews import STAGES


def _identity(data: dict[str, Any], *, error_type: type[Exception]) -> tuple[str, str]:
    provider = data.get("provider")
    if not isinstance(provider, dict):
        raise error_type("Host review proposal requires provider{name, version}")
    name = str(provider.get("name", "")).strip()
    version = str(provider.get("version", "")).strip()
    if not name or not version:
        raise error_type("Host review proposal provider requires non-empty name/version")
    return name, version


class StageReviewProposalProvider:
    """Admit a Host AI-produced stage proposal bundle without bundling a model SDK."""

    def __init__(self, path: Path) -> None:
        data = read_json(path)
        if not isinstance(data, dict):
            raise StageReviewError("Stage review proposal bundle must be a JSON object")
        self.name, self.version = _identity(data, error_type=StageReviewError)
        stages = data.get("stages")
        if not isinstance(stages, dict):
            raise StageReviewError("Stage review proposal bundle requires stages{}")
        missing = [stage for stage in STAGES if stage not in stages]
        unknown = sorted(set(stages) - set(STAGES))
        if missing or unknown:
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if unknown:
                details.append("unknown=" + ",".join(unknown))
            raise StageReviewError("Stage review proposal stage set mismatch: " + "; ".join(details))
        for stage, proposal in stages.items():
            if not isinstance(proposal, dict) or not isinstance(proposal.get("issues", []), list):
                raise StageReviewError(f"Stage proposal {stage} must contain issues[]")
        self._stages = copy.deepcopy(stages)

    def review(self, context: dict[str, Any]) -> dict[str, Any]:
        stage = str(context.get("stage", ""))
        if stage not in self._stages:
            raise StageReviewError(f"No Host AI proposal for stage: {stage}")
        return copy.deepcopy(self._stages[stage])


class ReviewSynthesisProposalProvider:
    """Admit a Host AI-produced whole-attempt synthesis proposal."""

    def __init__(self, path: Path) -> None:
        data = read_json(path)
        if not isinstance(data, dict):
            raise ReviewSynthesisError("Review synthesis proposal must be a JSON object")
        self.name, self.version = _identity(data, error_type=ReviewSynthesisError)
        if not isinstance(data.get("clusters", []), list):
            raise ReviewSynthesisError("Review synthesis proposal requires clusters[]")
        if not isinstance(data.get("unclustered_issue_ids"), list):
            raise ReviewSynthesisError("Review synthesis proposal requires unclustered_issue_ids[]")
        self._proposal = {
            key: copy.deepcopy(value)
            for key, value in data.items()
            if key != "provider"
        }

    def synthesize(self, context: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(self._proposal)
