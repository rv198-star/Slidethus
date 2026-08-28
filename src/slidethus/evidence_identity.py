from __future__ import annotations

import unicodedata
from typing import Any

from slidethus.errors import EvidenceAdjudicationError
from slidethus.io_utils import sha256_bytes, sha256_json
from slidethus.protocols import EvidenceCandidate

_DASHES = frozenset("-‐‑‒–—―﹘﹣－−")
_APOSTROPHES = frozenset("'’ʼ")
_SEMANTIC_PUNCTUATION = frozenset("%‰‱/+±=<>≤≥×÷#@&")
_NUMERIC_PUNCTUATION = frozenset(".,:")


def _neighbor(text: str, index: int, step: int) -> str:
    position = index + step
    while 0 <= position < len(text):
        char = text[position]
        if not char.isspace() and not unicodedata.category(char).startswith("Z"):
            return char
        position += step
    return ""


def normalize_claim(text: str) -> str:
    """Return a conservative exact-dedupe form without erasing units or operators.

    Presentation punctuation and separators collapse to spaces, while punctuation
    that changes numerical or symbolic meaning (for example ``%``, ``/``, decimal
    points, ratios and numeric ranges) remains part of the identity.
    """

    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    output: list[str] = []

    def append_space() -> None:
        if output and output[-1] != " ":
            output.append(" ")

    for index, char in enumerate(normalized):
        category = unicodedata.category(char)
        previous = _neighbor(normalized, index, -1)
        following = _neighbor(normalized, index, 1)

        if char.isspace() or category.startswith("Z"):
            append_space()
            continue
        if char in _DASHES:
            immediate_previous = normalized[index - 1] if index > 0 else ""
            numeric_range = previous.isdigit() and following.isdigit()
            unary_number = following.isdigit() and (
                not immediate_previous
                or immediate_previous.isspace()
                or immediate_previous in "([=<>+*/:"
            )
            if numeric_range or unary_number:
                output.append("-")
            else:
                append_space()
            continue
        if char in _SEMANTIC_PUNCTUATION:
            output.append("-" if char == "−" else char)
            continue
        if char in _NUMERIC_PUNCTUATION:
            if previous.isdigit() and following.isdigit():
                output.append(char)
            else:
                append_space()
            continue
        if char in _APOSTROPHES:
            if previous.isalnum() and following.isalnum():
                output.append("'")
            else:
                append_space()
            continue
        if category.startswith("P"):
            append_space()
            continue
        output.append(char)

    return " ".join("".join(output).split())


def claim_key(claim: str) -> str:
    normalized = normalize_claim(claim)
    if not normalized:
        raise EvidenceAdjudicationError("Evidence claim is empty after normalization")
    return "CLK-" + sha256_bytes(normalized.encode("utf-8"))[:16].upper()


def candidate_identity_payload(candidate: EvidenceCandidate) -> dict[str, Any]:
    return {
        "claim_key": claim_key(candidate.claim),
        "source_id": candidate.source_id,
        "locator": candidate.locator,
        "support_type": candidate.support_type,
        "origin_kind": candidate.origin_kind,
        "source_chunk_id": candidate.source_chunk_id,
        "research_run_id": candidate.research_run_id,
        "research_result_id": candidate.research_result_id,
        "conflict_key": candidate.conflict_key,
        "stance": candidate.stance,
    }


def candidate_id_for(candidate: EvidenceCandidate) -> str:
    return "CND-" + sha256_json(candidate_identity_payload(candidate))[:16].upper()


def conflict_group_id(key: str) -> str:
    normalized = " ".join(str(key).split()).strip().casefold()
    if not normalized:
        raise EvidenceAdjudicationError("Conflict key must not be blank")
    return "CFG-" + sha256_bytes(normalized.encode("utf-8"))[:16].upper()
