from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.decomposition import DecompositionNormalizationError, normalize_decomposition
from agents.schemas import DecompositionDraftOutput
from graph.state import ResearchDepth, VerificationState


NORMALIZED_TEXT = "Company X doubled net income in Q1 2026. Revenue increased too."


def _claim(text: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "text": text,
        "claim_kind": "numerical",
        "importance": "essential",
        "importance_weight": 3,
        "fact_checkability": "fact_checkable",
        "verification_scope": "Compare the same metric and reporting period.",
    }
    value.update(overrides)
    return value


def _draft(*claims: dict[str, object], **overrides: object) -> DecompositionDraftOutput:
    return DecompositionDraftOutput.model_validate({"atomic_claims": list(claims), **overrides})


def test_draft_contract_forbids_model_created_references():
    with pytest.raises(ValidationError):
        _draft(_claim("Company X doubled net income in Q1 2026.", claim_ref="model-ref"))

    with pytest.raises(ValidationError):
        _draft(
            _claim(
                "Company X doubled net income in Q1 2026.",
                parent_claim_ref="model-parent-ref",
            )
        )


def test_normalization_assigns_stable_refs_and_converts_parent_indexes():
    draft = _draft(
        _claim("Company X doubled net income in Q1 2026."),
        _claim("Revenue increased too.", parent_claim_index=0),
    )

    first = normalize_decomposition(draft, normalized_text=NORMALIZED_TEXT, claim_limit=25)
    second = normalize_decomposition(draft, normalized_text=NORMALIZED_TEXT, claim_limit=25)

    assert first == second
    assert first.atomic_claims[0].claim_ref.startswith("claim-1-")
    assert first.atomic_claims[1].claim_ref.startswith("claim-2-")
    assert first.atomic_claims[1].parent_claim_ref == first.atomic_claims[0].claim_ref
    assert all(len(claim.claim_ref) <= 64 for claim in first.atomic_claims)


def test_normalization_scopes_draft_ambiguity_to_its_generated_claim_ref():
    draft = _draft(
        _claim("Company X doubled net income in Q1 2026."),
        _claim("Revenue increased too."),
        claim_ambiguities=[
            {"text": "The reporting-period comparison is unstated.", "owner_claim_index": 1}
        ],
    )

    first = normalize_decomposition(draft, normalized_text=NORMALIZED_TEXT, claim_limit=25)
    second = normalize_decomposition(draft, normalized_text=NORMALIZED_TEXT, claim_limit=25)

    assert first == second
    assert len(first.claim_ambiguities) == 1
    assert first.claim_ambiguities[0].text == "The reporting-period comparison is unstated."
    assert first.claim_ambiguities[0].claim_ref == first.atomic_claims[1].claim_ref
    assert first.atomic_claims[0].ambiguities == []
    assert first.atomic_claims[1].ambiguities == [
        "The reporting-period comparison is unstated."
    ]


def test_unowned_ambiguity_remains_a_limitation_without_claim_ownership():
    output = normalize_decomposition(
        _draft(
            _claim("Company X doubled net income in Q1 2026."),
            unresolved_ambiguities=["The source article does not identify its author."],
        ),
        normalized_text=NORMALIZED_TEXT,
        claim_limit=25,
    )
    state = VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="test",
        claims=output.atomic_claims,
        claim_ambiguities=output.claim_ambiguities,
        unresolved_ambiguities=output.unresolved_ambiguities,
    )

    assert state.claim_ambiguities == []
    assert state.unresolved_ambiguities == ["The source article does not identify its author."]


@pytest.mark.parametrize(
    ("draft", "claim_limit", "code"),
    [
        (
            _draft(_claim("Company X doubled net income in Q1 2026.", parent_claim_index=1)),
            25,
            "DECOMPOSITION_PARENT_INDEX_INVALID",
        ),
        (
            _draft(
                _claim("Company X doubled net income in Q1 2026.", parent_claim_index=1),
                _claim("Revenue increased too.", parent_claim_index=0),
            ),
            25,
            "DECOMPOSITION_CLAIM_CYCLE",
        ),
        (
            _draft(
                _claim("Company X doubled net income in Q1 2026."),
                _claim("  company x DOUBLED net income in q1 2026.  "),
            ),
            25,
            "DECOMPOSITION_DUPLICATE_CLAIM",
        ),
        (
            _draft(_claim("Company X doubled net income in Q1 2026.", original_text_span="not present")),
            25,
            "DECOMPOSITION_INVALID_ORIGINAL_TEXT_SPAN",
        ),
        (
            _draft(
                _claim("Company X doubled net income in Q1 2026."),
                _claim("Revenue increased too."),
            ),
            1,
            "DECOMPOSITION_CLAIM_LIMIT_EXCEEDED",
        ),
        (
            _draft(
                _claim("Company X doubled net income in Q1 2026."),
                claim_ambiguities=[{"text": "The period is unclear.", "owner_claim_index": 1}],
            ),
            25,
            "DECOMPOSITION_AMBIGUITY_OWNER_INDEX_INVALID",
        ),
    ],
)
def test_normalization_rejects_invalid_drafts_with_stable_codes(
    draft: DecompositionDraftOutput,
    claim_limit: int,
    code: str,
):
    with pytest.raises(DecompositionNormalizationError) as exc_info:
        normalize_decomposition(draft, normalized_text=NORMALIZED_TEXT, claim_limit=claim_limit)

    assert exc_info.value.code == code
