import pytest
from pydantic import ValidationError

from agents.batching import chunked
from agents.citation_audit import build_citation_audit_tasks
from agents.evidence_classification import classification_task_ref
from agents.schemas import (
    AtomicClaimOutput,
    ClaimKind,
    CitationAuditBatchOutput,
    DecompositionOutput,
    FactCheckability,
    Importance,
    PlanningOutput,
    SynthesisDraftOutput,
    SynthesisOutput,
    iter_auditable_sentences,
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
    assert [section for section, _ in iter_auditable_sentences(output)] == [
        "summary",
        "strongest_contradiction",
    ]


def test_model_synthesis_draft_rejects_free_form_factual_gap_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SynthesisDraftOutput.model_validate(
            {
                "summary_sentences": [
                    {
                        "sentence_ref": "summary-1",
                        "text": "The supplied passage supports the narrow claim.",
                        "passage_ids": ["passage-1"],
                    }
                ],
                "limitations": ["A separate source confirmed the claim."],
            }
        )


def test_citation_audit_batch_output_rejects_run_level_decisions():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CitationAuditBatchOutput.model_validate(
            {"sentence_audits": [], "needs_revision": False}
        )


def test_batch_helpers_preserve_order_and_bounds():
    values = list(range(10))

    batches = chunked(values, 4)

    assert [len(batch) for batch in batches] == [4, 4, 2]
    assert [item for batch in batches for item in batch] == values
    assert chunked([], 4) == []


def test_stable_classification_and_citation_pair_references_are_unchanged():
    report = SynthesisOutput.model_validate(
        {
            "title": "Assessment",
            "summary_sentences": [
                {
                    "sentence_ref": "summary-1",
                    "text": "The filing reports the value.",
                    "passage_ids": ["passage-2", "passage-1"],
                }
            ],
        }
    )
    passage = type("Passage", (), {"text": "Source passage"})

    tasks = build_citation_audit_tasks(
        report,
        {"passage-1": passage(), "passage-2": passage()},
    )

    assert classification_task_ref("claim-1", "passage-1") == (
        "classification-d1b91dcb0727cb47d7ef5348"
    )
    assert [(task.sentence_ref, task.passage_id) for task in tasks] == [
        ("summary-1", "passage-2"),
        ("summary-1", "passage-1"),
    ]

    with pytest.raises(ValidationError, match="sentence_ref values must be unique"):
        SynthesisDraftOutput.model_validate(
            {
                "summary_sentences": [
                    {
                        "sentence_ref": "summary-1",
                        "text": "The supplied passage supports the narrow claim.",
                        "passage_ids": ["passage-1"],
                    }
                ],
                "factual_sentences": [
                    {
                        "sentence_ref": "summary-1",
                        "text": "The same passage contains a second finding.",
                        "passage_ids": ["passage-1"],
                    }
                ],
            }
        )
