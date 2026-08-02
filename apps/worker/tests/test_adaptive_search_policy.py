from agents.schemas import EvidenceIntent, ResearchObjectiveOutput, SearchQueryOutput
from research.search_policy import (
    CoverageBudgetExceededError,
    calculate_budget,
    canonical_query_text,
    policy_for_depth,
    select_initial_queries,
)


def _objective(ref: str, claim_ref: str, intent: EvidenceIntent) -> ResearchObjectiveOutput:
    return ResearchObjectiveOutput(
        objective_ref=ref,
        claim_ref=claim_ref,
        intent=intent,
        target=f"Find {intent.value} evidence for {claim_ref}",
    )


def _query(text: str, objective: ResearchObjectiveOutput, priority: float = 0.5):
    return SearchQueryOutput(
        query=text,
        objective_ref=objective.objective_ref,
        intent=objective.intent,
        priority=priority,
    )


def test_mandatory_primary_contradiction_and_attribution_paths_are_phase_one():
    objectives = [
        _objective("c1-primary", "claim-1", EvidenceIntent.PRIMARY),
        _objective("c1-counter", "claim-1", EvidenceIntent.CONTRADICTION),
        _objective("c2-primary", "claim-2", EvidenceIntent.PRIMARY),
        _objective("c2-counter", "claim-2", EvidenceIntent.CONTRADICTION),
        _objective("quote", "claim-1", EvidenceIntent.ATTRIBUTION),
        _objective("extra", "claim-1", EvidenceIntent.SUPPORT),
    ]
    queries = [
        _query("claim one primary", objectives[0], 0.9),
        _query("claim one contradiction", objectives[1], 0.8),
        _query("claim two primary", objectives[2], 0.7),
        _query("claim two contradiction", objectives[3], 0.6),
        _query('source for "exact words"', objectives[4], 0.5),
        *[
            _query(f"supplemental query {index}", objectives[5], 0.4 - index / 100)
            for index in range(20)
        ],
    ]
    policy = policy_for_depth("QUICK")
    budget = calculate_budget(
        policy,
        fact_checkable_claim_count=2,
        attribution_required=True,
    )

    phase_one, reserve = select_initial_queries(
        queries,
        objectives,
        fact_checkable_claim_refs={"claim-1", "claim-2"},
        attribution_required=True,
        exact_quote='"exact words"',
        policy=policy,
        budget=budget,
    )

    phase_one_text = {canonical_query_text(item.query) for item in phase_one}
    assert {
        "claim one primary",
        "claim one contradiction",
        "claim two primary",
        "claim two contradiction",
        'source for "exact words"',
    } <= phase_one_text
    assert len(phase_one) == 8
    assert len(phase_one) + len(reserve) == 22


def test_duplicate_normalized_query_text_is_never_selected_twice():
    objective = _objective("primary", "claim-1", EvidenceIntent.PRIMARY)
    duplicate = _query("  SAME   Query ", objective, 0.8)
    queries = [_query("same query", objective, 1), duplicate]
    policy = policy_for_depth("QUICK")
    budget = calculate_budget(
        policy,
        fact_checkable_claim_count=0,
        attribution_required=False,
    )

    phase_one, reserve = select_initial_queries(
        queries,
        [objective],
        fact_checkable_claim_refs=set(),
        attribution_required=False,
        exact_quote=None,
        policy=policy,
        budget=budget,
    )

    assert len(phase_one) == 1
    assert reserve == []


def test_every_depth_budget_is_bounded_and_future_over_ceiling_input_fails():
    expected = {
        "QUICK": (22, 25),
        "STANDARD": (48, 51),
        "DEEP": (100, 101),
    }
    for depth, (normal_total, ceiling) in expected.items():
        policy = policy_for_depth(depth)
        budget = calculate_budget(
            policy,
            fact_checkable_claim_count=1,
            attribution_required=False,
        )
        assert budget.effective_total_budget == normal_total
        assert budget.effective_total_budget <= ceiling

    try:
        calculate_budget(
            policy_for_depth("QUICK"),
            fact_checkable_claim_count=13,
            attribution_required=False,
        )
    except CoverageBudgetExceededError as exc:
        assert exc.mandatory_floor == 26
        assert exc.supported_ceiling == 25
    else:
        raise AssertionError("over-ceiling coverage must fail before search provider use")
