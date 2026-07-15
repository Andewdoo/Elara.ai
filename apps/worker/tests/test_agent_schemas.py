import pytest
from pydantic import ValidationError

from agents.schemas import (
    AtomicClaimOutput,
    ClaimKind,
    DecompositionOutput,
    FactCheckability,
    Importance,
    PlanningOutput,
    SynthesisOutput,
)


def atomic_claim(**overrides):
    values = {
        "claim_ref": "claim-1",
        "text": "The reported value doubled.",
        "claim_kind": ClaimKind.NUMERICAL,
        "importance": Importance.ESSENTIAL,
        "importance_weight": 3,
        "fact_checkability": FactCheckability.FACT_CHECKABLE,
        "verification_scope": "Compare the same metric and reporting period.",
    }
    values.update(overrides)
    return AtomicClaimOutput.model_validate(values)


def test_decomposition_rejects_inconsistent_weights_and_duplicate_refs():
    with pytest.raises(ValidationError):
        atomic_claim(importance_weight=1)

    with pytest.raises(ValidationError):
        DecompositionOutput(atomic_claims=[atomic_claim(), atomic_claim()])


def test_planner_unknown_objective_ref_is_blocked_by_pydantic_before_workflow():
    """The workflow's redundant unknown-objective guard is unreachable."""
    with pytest.raises(ValidationError):
        PlanningOutput.model_validate(
            {
                "objectives": [
                    {
                        "objective_ref": "objective-1",
                        "claim_ref": "claim-1",
                        "intent": "primary",
                        "target": "Locate the original filing.",
                    }
                ],
                "queries": [
                    {
                        "query": "original quarterly filing",
                        "objective_ref": "missing-objective",
                        "intent": "primary",
                    }
                ],
            }
        )


def test_synthesis_requires_citations_for_every_factual_sentence():
    with pytest.raises(ValidationError):
        SynthesisOutput.model_validate(
            {
                "title": "Assessment",
                "summary_sentences": [
                    {
                        "sentence_ref": "summary-1",
                        "text": "The available record supports the narrow claim.",
                        "passage_ids": [],
                    }
                ],
            }
        )

    output = SynthesisOutput.model_validate(
        {
            "title": "Assessment",
            "summary_sentences": [
                {
                    "sentence_ref": "summary-1",
                    "text": "The available record supports the narrow claim.",
                    "passage_ids": ["passage-1"],
                }
            ],
            "strongest_credible_contradiction": {
                "sentence_ref": "contradiction-1",
                "text": "A later filing reports a different period.",
                "passage_ids": ["passage-2"],
            },
        }
    )

    assert output.summary_sentences[0].passage_ids == ["passage-1"]
