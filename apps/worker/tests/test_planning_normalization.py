from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

import agents.planning as planning
from agents.planning import UnknownPlanningDraftClaimRefError, normalize_research_plan
from agents.schemas import PlanningDraftOutput
from agents.validation import validate_research_plan
from graph.state import ResearchDepth, VerificationState


def _draft() -> PlanningDraftOutput:
    return PlanningDraftOutput.model_validate(
        {
            "objectives": [
                {
                    "claim_ref": "claim-1",
                    "intent": "primary",
                    "target": "  Locate   the original filing. ",
                    "queries": [{"query": "Company X filing", "priority": 1}],
                },
                {
                    "claim_ref": "claim-1",
                    "intent": "contradiction",
                    "target": "Locate later corrections.",
                    "queries": [{"query": "Company X correction"}],
                },
            ]
        }
    )


def _state(*, claims: list[dict[str, str]] | None = None) -> VerificationState:
    return VerificationState.model_validate(
        {
            "run_id": uuid4(),
            "user_id": uuid4(),
            "research_depth": ResearchDepth.STANDARD,
            "methodology_version": "test",
            "claims": claims
            or [
                {
                    "claim_ref": "claim-1",
                    "text": "A fact-checkable claim.",
                    "claim_kind": "factual",
                    "importance": "essential",
                    "importance_weight": 3,
                    "fact_checkability": "fact_checkable",
                    "verification_scope": "Check the record.",
                }
            ],
        }
    )


def test_draft_schema_rejects_model_owned_objective_ref_and_query_intent():
    with pytest.raises(ValidationError):
        PlanningDraftOutput.model_validate(
            {
                "objectives": [
                    {
                        "objective_ref": "model-provided-ref",
                        "claim_ref": "claim-1",
                        "intent": "primary",
                        "target": "Find a primary record.",
                        "queries": [{"query": "Company X filing", "objective_ref": "model-provided-ref"}],
                    }
                ]
            }
        )

    with pytest.raises(ValidationError):
        PlanningDraftOutput.model_validate(
            {
                "objectives": [
                    {
                        "claim_ref": "claim-1",
                        "intent": "primary",
                        "target": "Find a primary record.",
                        "queries": [{"query": "Company X filing", "intent": "support"}],
                    }
                ]
            }
        )


def test_normalization_is_stable_idempotent_and_inherits_parent_relationships():
    draft = _draft()

    first = normalize_research_plan(draft, allowed_claim_refs=["claim-1"])
    second = normalize_research_plan(draft, allowed_claim_refs=["claim-1"])

    assert first == second
    assert all(objective.objective_ref.startswith("obj-") for objective in first.objectives)
    assert [query.objective_ref for query in first.queries] == [
        objective.objective_ref for objective in first.objectives
    ]
    assert [query.intent for query in first.queries] == [
        objective.intent for objective in first.objectives
    ]


def test_normalization_handles_truncated_digest_collisions_deterministically(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(planning, "_OBJECTIVE_DIGEST_LENGTH", 0)

    output = normalize_research_plan(_draft(), allowed_claim_refs=["claim-1"])

    assert [objective.objective_ref for objective in output.objectives] == ["obj-", "obj--2"]


def test_normalization_rejects_a_claim_not_selected_from_allowed_refs():
    draft = _draft()
    draft.objectives[0].claim_ref = "unknown-claim"

    with pytest.raises(UnknownPlanningDraftClaimRefError):
        normalize_research_plan(draft, allowed_claim_refs=["claim-1"])


def test_post_normalization_validator_rejects_duplicate_queries_and_missing_coverage():
    duplicate = _draft()
    duplicate.objectives[1].queries[0].query = "  COMPANY x FILING "
    duplicate.objectives[0].queries[0].query = "company x filing"
    duplicate_output = normalize_research_plan(duplicate, allowed_claim_refs=["claim-1"])

    duplicate_codes = {
        violation.code for violation in validate_research_plan(_state(), duplicate_output)
    }
    assert "PLAN_DUPLICATE_QUERY" in duplicate_codes

    missing_coverage = _draft()
    missing_output = normalize_research_plan(
        missing_coverage, allowed_claim_refs=["claim-1", "claim-2"]
    )
    coverage_state = _state(
        claims=[
            *_state().claims[0:1],
            {
                "claim_ref": "claim-2",
                "text": "A second fact-checkable claim.",
                "claim_kind": "factual",
                "importance": "major",
                "importance_weight": 2,
                "fact_checkability": "fact_checkable",
                "verification_scope": "Check the second record.",
            },
        ]
    )

    coverage_codes = {
        violation.code
        for violation in validate_research_plan(coverage_state, missing_output)
    }
    assert "PLAN_MISSING_CLAIM_COVERAGE" in coverage_codes
