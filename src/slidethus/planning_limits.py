from __future__ import annotations

from dataclasses import asdict

from slidethus.errors import PlanningLimitError
from slidethus.io_utils import canonical_json_bytes
from slidethus.protocols import PlanningLimits, PlanningProposal

_MAX_PROVIDER_PAYLOAD_BYTES = 10 * 1024 * 1024
_MAX_WORD_UNITS_PER_SLIDE = 10_000


def validate_planning_limits(limits: PlanningLimits) -> None:
    """Validate one complete M3 planning-limit contract before semantic mutation."""

    values = asdict(limits)
    if any(not isinstance(value, int) for value in values.values()):
        raise PlanningLimitError("Planning limits must be integers")
    bounded = {
        "max_blocking_questions": (1, 12),
        "max_assumptions": (1, 999),
        "max_sections": (1, 99),
        "max_slides": (1, 999),
        "max_blocks_per_slide": (1, 99),
        "max_words_per_slide": (1, _MAX_WORD_UNITS_PER_SLIDE),
        "max_provider_payload_bytes": (1, _MAX_PROVIDER_PAYLOAD_BYTES),
        "max_change_targets": (1, 999),
    }
    for name, (minimum, maximum) in bounded.items():
        value = int(values[name])
        if not minimum <= value <= maximum:
            raise PlanningLimitError(
                f"{name} must be between {minimum} and {maximum}, got {value}"
            )


def admit_planning_proposal(
    proposal: object,
    *,
    artifact_type: str,
    limits: PlanningLimits,
) -> PlanningProposal:
    """Validate and normalize a complete provider proposal within one payload budget."""

    validate_planning_limits(limits)
    if not isinstance(proposal, PlanningProposal):
        raise PlanningLimitError("Planning provider must return PlanningProposal")
    if proposal.artifact_type != artifact_type:
        raise PlanningLimitError(
            f"Planning provider returned {proposal.artifact_type}, expected {artifact_type}"
        )
    if not isinstance(proposal.content, dict):
        raise PlanningLimitError("Planning proposal content must be an object")

    def normalize_messages(values: object, field: str) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)) or not isinstance(values, tuple):
            raise PlanningLimitError(f"Planning proposal {field} must be a tuple of strings")
        if len(values) > limits.max_assumptions:
            raise PlanningLimitError(
                f"Planning proposal {field} exceeds max_assumptions={limits.max_assumptions}"
            )
        normalized: list[str] = []
        for item in values:
            if not isinstance(item, str):
                raise PlanningLimitError(f"Planning proposal {field} must contain strings")
            text = " ".join(item.replace("\u00a0", " ").split()).strip()
            if not text or len(text) > 4000:
                raise PlanningLimitError(
                    f"Planning proposal {field} entries must contain 1..4000 characters"
                )
            if text not in normalized:
                normalized.append(text)
        return tuple(normalized)

    warnings = normalize_messages(proposal.warnings, "warnings")
    assumptions = normalize_messages(proposal.assumptions, "assumptions")
    admitted = PlanningProposal(
        artifact_type=proposal.artifact_type,
        content=proposal.content,
        warnings=warnings,
        assumptions=assumptions,
    )
    try:
        payload_size = len(
            canonical_json_bytes(
                {
                    "artifact_type": admitted.artifact_type,
                    "content": admitted.content,
                    "warnings": admitted.warnings,
                    "assumptions": admitted.assumptions,
                }
            )
        )
    except (TypeError, ValueError) as exc:
        raise PlanningLimitError("Planning proposal is not JSON-serializable") from exc
    if payload_size > limits.max_provider_payload_bytes:
        raise PlanningLimitError(
            "Planning proposal exceeds max_provider_payload_bytes="
            f"{limits.max_provider_payload_bytes}"
        )
    return admitted
