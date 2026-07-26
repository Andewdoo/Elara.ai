from __future__ import annotations

from uuid import uuid4

from agents.schemas import (
    DecompositionOutput,
    PlanningOutput,
    ResearchObjectiveOutput,
    SearchQueryOutput,
)
from agents.validation import AgentContractViolation, validate_research_plan
from graph.state import ResearchDepth, VerificationState


def _state() -> VerificationState:
    claims = DecompositionOutput.model_validate(
        {
            "atomic_claims": [
                {
                    "claim_ref": "claim-1",
                    "text": "Raw claim text must remain out of diagnostics.",
                    "claim_kind": "factual",
                    "importance": "essential",
                    "importance_weight": 3,
                    "fact_checkability": "fact_checkable",
                    "verification_scope": "Check the record.",
                }
            ]
        }
    ).atomic_claims
    return VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="test",
        claims=claims,
    )


def _objective(*, claim_ref: str = "claim-1") -> ResearchObjectiveOutput:
    return ResearchObjectiveOutput(
        objective_ref="objective-1",
        claim_ref=claim_ref,
        intent="primary",
        target="Find the official record.",
    )


def _query(*, objective_ref: str = "objective-1", query: str = "sensitive query text") -> SearchQueryOutput:
    return SearchQueryOutput(
        query=query,
        objective_ref=objective_ref,
        intent="primary",
    )


def test_research_plan_validator_returns_every_violation_in_stable_code_order():
    state = _state()
    output = PlanningOutput.model_validate(
        {
            "objectives": [
                {
                    "objective_ref": "objective-1",
                    "claim_ref": "unknown-claim",
                    "intent": "primary",
                    "target": "Find an untrusted record.",
                }
            ],
            "queries": [
                {
                    "query": "Sensitive query text",
                    "objective_ref": "objective-1",
                    "intent": "primary",
                },
                {
                    "query": "  sensitive QUERY text  ",
                    "objective_ref": "objective-1",
                    "intent": "primary",
                },
            ],
        }
    )

    first = validate_research_plan(state, output)
    second = validate_research_plan(state, output)

    assert first == second
    assert tuple(item.code for item in first) == (
        "PLAN_CONTRADICTION_PATH_MISSING",
        "PLAN_DUPLICATE_QUERY",
        "PLAN_EXTRA_CLAIM_COVERAGE",
        "PLAN_MISSING_CLAIM_COVERAGE",
        "PLAN_PRIMARY_PATH_MISSING",
        "PLAN_UNKNOWN_CLAIM_REF",
    )
    assert first == tuple(sorted(first, key=lambda item: (item.code, item.field)))
    assert all(item.field in {"objectives.claim_ref", "queries.intent", "queries.query"} for item in first)
    assert all(isinstance(item.count, int) for item in first)


def test_research_plan_validator_keeps_legacy_unknown_objective_reference_check():
    state = _state()
    output = PlanningOutput.model_construct(
        objectives=[_objective()],
        queries=[_query(objective_ref="persisted-objective")],
        primary_source_targets=[],
        known_evidence_gaps=[],
    )

    violations = validate_research_plan(state, output)

    assert AgentContractViolation(
        code="PLAN_UNKNOWN_OBJECTIVE_REF",
        field="queries.objective_ref",
    ) in violations
