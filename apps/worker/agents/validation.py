"""Pure, non-sensitive contracts for structured agent outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents.schemas import EvidenceIntent, FactCheckability, InputKind, PlanningOutput

if TYPE_CHECKING:
    from graph.state import VerificationState


@dataclass(frozen=True, slots=True)
class AgentContractViolation:
    """A stable validation result that is safe to persist in public events.

    ``field`` is always a validator-defined schema path. ``count`` is an
    aggregate only; raw claims, queries, provider output, and Pydantic errors
    are deliberately excluded.
    """

    code: str
    field: str
    count: int = 1


_QUERY_LIMITS = {"QUICK": 24, "STANDARD": 60, "DEEP": 120}
_SUMMARY_CODE_LIMIT = 8
_SUMMARY_CHARACTER_LIMIT = 256


def validate_research_plan(
    state: VerificationState, output: PlanningOutput
) -> tuple[AgentContractViolation, ...]:
    """Return every deterministic research-plan contract violation.

    This validator has no side effects and only returns static field names and
    aggregate counts so its output can be safely exposed in public progress
    events.
    """

    claim_refs = {claim.claim_ref for claim in state.claims}
    objective_refs = [objective.objective_ref for objective in output.objectives]
    objective_ref_set = set(objective_refs)
    planned_claim_refs = {objective.claim_ref for objective in output.objectives}
    objective_by_ref = {objective.objective_ref: objective for objective in output.objectives}
    violations: list[AgentContractViolation] = []

    duplicate_objective_count = len(objective_refs) - len(objective_ref_set)
    if duplicate_objective_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_DUPLICATE_OBJECTIVE_REF",
                field="objectives.objective_ref",
                count=duplicate_objective_count,
            )
        )

    unknown_claim_count = sum(
        objective.claim_ref not in claim_refs for objective in output.objectives
    )
    if unknown_claim_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_UNKNOWN_CLAIM_REF",
                field="objectives.claim_ref",
                count=unknown_claim_count,
            )
        )

    missing_coverage_count = len(claim_refs - planned_claim_refs)
    if missing_coverage_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_MISSING_CLAIM_COVERAGE",
                field="objectives.claim_ref",
                count=missing_coverage_count,
            )
        )

    extra_coverage_count = len(planned_claim_refs - claim_refs)
    if extra_coverage_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_EXTRA_CLAIM_COVERAGE",
                field="objectives.claim_ref",
                count=extra_coverage_count,
            )
        )

    query_limit = _QUERY_LIMITS[state.research_depth.value]
    query_limit_excess = len(output.queries) - query_limit
    if query_limit_excess > 0:
        violations.append(
            AgentContractViolation(
                code="PLAN_QUERY_LIMIT_EXCEEDED",
                field="queries",
                count=query_limit_excess,
            )
        )

    normalized_queries = [" ".join(query.query.casefold().split()) for query in output.queries]
    duplicate_query_count = len(normalized_queries) - len(set(normalized_queries))
    if duplicate_query_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_DUPLICATE_QUERY",
                field="queries.query",
                count=duplicate_query_count,
            )
        )

    intents_by_claim: dict[str, set[EvidenceIntent]] = {
        claim_ref: set() for claim_ref in claim_refs
    }
    for query in output.queries:
        objective = objective_by_ref.get(query.objective_ref)
        if objective is not None and objective.claim_ref in intents_by_claim:
            intents_by_claim[objective.claim_ref].add(query.intent)

    fact_checkable_claim_refs = {
        claim.claim_ref
        for claim in state.claims
        if claim.fact_checkability != FactCheckability.NOT_FACT_CHECKABLE
    }
    primary_missing_count = sum(
        EvidenceIntent.PRIMARY not in intents_by_claim[claim_ref]
        for claim_ref in fact_checkable_claim_refs
    )
    if primary_missing_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_PRIMARY_PATH_MISSING",
                field="queries.intent",
                count=primary_missing_count,
            )
        )

    contradiction_missing_count = sum(
        EvidenceIntent.CONTRADICTION not in intents_by_claim[claim_ref]
        for claim_ref in fact_checkable_claim_refs
    )
    if contradiction_missing_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_CONTRADICTION_PATH_MISSING",
                field="queries.intent",
                count=contradiction_missing_count,
            )
        )

    attribution_required = bool(
        state.normalized_input and state.normalized_input.requires_attribution_check
    ) or any(claim.claim_kind.value in {"quotation", "attribution"} for claim in state.claims)
    if attribution_required and not any(
        query.intent == EvidenceIntent.ATTRIBUTION for query in output.queries
    ):
        violations.append(
            AgentContractViolation(
                code="PLAN_ATTRIBUTION_PATH_MISSING",
                field="queries.intent",
            )
        )

    exact_quote_required = (
        state.normalized_input is not None
        and state.normalized_input.input_kind == InputKind.QUOTE
        and len(state.normalized_input.normalized_text) <= 300
    )
    if exact_quote_required and not any(
        state.normalized_input.normalized_text in query.query for query in output.queries
    ):
        violations.append(
            AgentContractViolation(
                code="PLAN_EXACT_QUOTE_PATH_MISSING",
                field="queries.query",
            )
        )

    unknown_objective_count = sum(
        query.objective_ref not in objective_ref_set for query in output.queries
    )
    if unknown_objective_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_UNKNOWN_OBJECTIVE_REF",
                field="queries.objective_ref",
                count=unknown_objective_count,
            )
        )

    intent_mismatch_count = sum(
        objective is not None and query.intent != objective.intent
        for query in output.queries
        if (objective := objective_by_ref.get(query.objective_ref)) is not None
    )
    if intent_mismatch_count:
        violations.append(
            AgentContractViolation(
                code="PLAN_INTENT_MISMATCH",
                field="queries.intent",
                count=intent_mismatch_count,
            )
        )

    return tuple(sorted(violations, key=lambda violation: (violation.code, violation.field)))


def summarize_violation_codes(
    violations: tuple[AgentContractViolation, ...],
) -> str:
    """Return a bounded, deterministic event-safe summary of violation codes."""

    summary = ",".join(
        violation.code for violation in violations[:_SUMMARY_CODE_LIMIT]
    )
    return summary[:_SUMMARY_CHARACTER_LIMIT]


__all__ = [
    "AgentContractViolation",
    "summarize_violation_codes",
    "validate_research_plan",
]
