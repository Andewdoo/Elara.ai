"""Atomic-claim decomposition prompt contract and deterministic normalizer."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from agents.schemas import (
    AtomicClaimOutput,
    DecompositionDraftOutput,
    DecompositionOutput,
)


PROMPT_VERSION = "decomposition-v2"
SYSTEM_PROMPT = """
Split the normalized target into independently testable atomic claims. Preserve
claim-specific entities, periods, locations, metrics, comparisons, and original
text spans. Rank each claim as essential, major, or minor using weights 3, 2, or 1.
Label opinions, predictions, allegations, testimony, attribution, rhetorical
framing, and partially fact-checkable claims explicitly. Return concise
verification scopes and unresolved ambiguities, never a verdict or reasoning
transcript. Return claims in their deterministic source order. If a claim has a
parent, set parent_claim_index to that claim's zero-based index in the ordered
claims list. Never create, return, infer, or reuse claim_ref or parent_claim_ref;
the workflow assigns those identifiers deterministically.
""".strip()


class DecompositionNormalizationError(ValueError):
    """A stable deterministic rejection for a model-produced claim draft."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


def normalize_decomposition(
    draft: DecompositionDraftOutput,
    *,
    normalized_text: str,
    claim_limit: int,
) -> DecompositionOutput:
    """Assign trusted refs and validate a model-owned decomposition draft."""
    claims = draft.atomic_claims
    if len(claims) > claim_limit:
        raise DecompositionNormalizationError(
            "DECOMPOSITION_CLAIM_LIMIT_EXCEEDED",
            "Claim decomposition exceeded the configured claim limit.",
        )

    normalized_claims = [_canonical_text(claim.text) for claim in claims]
    if len(normalized_claims) != len(set(normalized_claims)):
        raise DecompositionNormalizationError(
            "DECOMPOSITION_DUPLICATE_CLAIM",
            "Claim decomposition contains duplicate normalized claims.",
        )

    for claim in claims:
        if (
            claim.original_text_span is not None
            and claim.original_text_span not in normalized_text
        ):
            raise DecompositionNormalizationError(
                "DECOMPOSITION_INVALID_ORIGINAL_TEXT_SPAN",
                "Claim original_text_span must be an exact substring of normalized input.",
            )

    parent_indexes = [claim.parent_claim_index for claim in claims]
    for parent_index in parent_indexes:
        if parent_index is not None and parent_index >= len(claims):
            raise DecompositionNormalizationError(
                "DECOMPOSITION_PARENT_INDEX_INVALID",
                "Claim parent_claim_index must reference an ordered claim.",
            )
    if _has_parent_index_cycle(parent_indexes):
        raise DecompositionNormalizationError(
            "DECOMPOSITION_CLAIM_CYCLE",
            "Claim decomposition contains a parent cycle.",
        )

    claim_refs = [
        _claim_ref(index, claim.model_dump(mode="json", exclude={"parent_claim_index"}))
        for index, claim in enumerate(claims)
    ]
    atomic_claims = [
        AtomicClaimOutput.model_validate(
            {
                **claim.model_dump(mode="json", exclude={"parent_claim_index"}),
                "claim_ref": claim_refs[index],
                "parent_claim_ref": (
                    claim_refs[claim.parent_claim_index]
                    if claim.parent_claim_index is not None
                    else None
                ),
            }
        )
        for index, claim in enumerate(claims)
    ]
    return DecompositionOutput(
        atomic_claims=atomic_claims,
        unresolved_ambiguities=draft.unresolved_ambiguities,
    )


def _claim_ref(index: int, content: dict[str, Any]) -> str:
    digest = sha256(
        json.dumps(
            _canonical_content(content), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"claim-{index + 1}-{digest}"


def _canonical_content(value: Any) -> Any:
    if isinstance(value, str):
        return _canonical_text(value)
    if isinstance(value, dict):
        return {key: _canonical_content(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_content(item) for item in value]
    return value


def _canonical_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _has_parent_index_cycle(parent_indexes: list[int | None]) -> bool:
    for claim_index in range(len(parent_indexes)):
        seen: set[int] = set()
        current: int | None = claim_index
        while current is not None:
            if current in seen:
                return True
            seen.add(current)
            current = parent_indexes[current]
    return False
