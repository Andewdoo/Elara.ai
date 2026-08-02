"""Deterministic two-phase Brave Search budget and coverage policy."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

from agents.schemas import EvidenceIntent, SearchQueryOutput


POLICY_VERSION = "adaptive-search-v1"


@dataclass(frozen=True, slots=True)
class DepthSearchPolicy:
    research_depth: str
    phase_one_target: int
    phase_two_additional_target: int
    supported_ceiling: int
    reserve_batch_size: int
    minimum_candidate_count: int
    minimum_domain_count: int
    policy_version: str = POLICY_VERSION

    @property
    def normal_total_maximum(self) -> int:
        return self.phase_one_target + self.phase_two_additional_target


@dataclass(frozen=True, slots=True)
class SearchBudget:
    mandatory_floor: int
    effective_total_budget: int


@dataclass(frozen=True, slots=True)
class DiscoveryGateDecision:
    passed: bool
    reason_codes: tuple[str, ...]
    candidate_count: int
    domain_count: int
    missing_primary_claim_refs: tuple[str, ...]
    missing_contradiction_claim_refs: tuple[str, ...]
    attribution_covered: bool


class CoverageBudgetExceededError(ValueError):
    def __init__(self, *, mandatory_floor: int, supported_ceiling: int) -> None:
        super().__init__("mandatory search coverage exceeds the supported ceiling")
        self.mandatory_floor = mandatory_floor
        self.supported_ceiling = supported_ceiling


class ObjectiveLike(Protocol):
    objective_ref: str
    claim_ref: str
    intent: EvidenceIntent


class CandidateLike(Protocol):
    canonical_url: str | None
    url: str
    domain: str | None
    objective_refs: list[str]
    source_origin: str


_DEFAULTS = {
    "QUICK": DepthSearchPolicy("QUICK", 8, 14, 25, 4, 3, 2),
    "STANDARD": DepthSearchPolicy("STANDARD", 18, 30, 51, 6, 5, 3),
    "DEEP": DepthSearchPolicy("DEEP", 36, 64, 101, 8, 8, 4),
}


def policy_for_depth(
    research_depth: str,
    *,
    phase_one_target: int | None = None,
    phase_two_additional_target: int | None = None,
    policy_version: str = POLICY_VERSION,
) -> DepthSearchPolicy:
    default = _DEFAULTS[research_depth]
    return DepthSearchPolicy(
        research_depth=research_depth,
        phase_one_target=phase_one_target or default.phase_one_target,
        phase_two_additional_target=(
            phase_two_additional_target
            if phase_two_additional_target is not None
            else default.phase_two_additional_target
        ),
        supported_ceiling=default.supported_ceiling,
        reserve_batch_size=default.reserve_batch_size,
        minimum_candidate_count=default.minimum_candidate_count,
        minimum_domain_count=default.minimum_domain_count,
        policy_version=policy_version,
    )


def calculate_budget(
    policy: DepthSearchPolicy,
    *,
    fact_checkable_claim_count: int,
    attribution_required: bool,
) -> SearchBudget:
    mandatory_floor = 2 * fact_checkable_claim_count + int(attribution_required)
    if mandatory_floor > policy.supported_ceiling:
        raise CoverageBudgetExceededError(
            mandatory_floor=mandatory_floor,
            supported_ceiling=policy.supported_ceiling,
        )
    return SearchBudget(
        mandatory_floor=mandatory_floor,
        effective_total_budget=max(policy.normal_total_maximum, mandatory_floor),
    )


def canonical_query_text(value: str) -> str:
    return " ".join(value.casefold().split())


def query_state_key(query: SearchQueryOutput) -> str:
    return f"{query.objective_ref}:{query.query}"


def select_initial_queries(
    queries: Sequence[SearchQueryOutput],
    objectives: Sequence[ObjectiveLike],
    *,
    fact_checkable_claim_refs: Collection[str],
    attribution_required: bool,
    exact_quote: str | None,
    policy: DepthSearchPolicy,
    budget: SearchBudget,
) -> tuple[list[SearchQueryOutput], list[SearchQueryOutput]]:
    """Partition a validated plan into deterministic phase-one and reserve pools."""

    objective_by_ref = {item.objective_ref: item for item in objectives}
    ordered = sorted(
        enumerate(queries),
        key=lambda item: (
            -float(item[1].priority),
            canonical_query_text(item[1].query),
            item[0],
        ),
    )
    selected: list[SearchQueryOutput] = []
    selected_text: set[str] = set()

    def add_best(*, claim_ref: str | None, intent: EvidenceIntent) -> None:
        candidates = [
            query
            for _, query in ordered
            if query.intent == intent
            and (
                claim_ref is None
                or (
                    (objective := objective_by_ref.get(query.objective_ref)) is not None
                    and objective.claim_ref == claim_ref
                )
            )
            and canonical_query_text(query.query) not in selected_text
        ]
        if exact_quote and intent == EvidenceIntent.ATTRIBUTION:
            candidates.sort(key=lambda query: exact_quote not in query.query)
        if candidates:
            selected.append(candidates[0])
            selected_text.add(canonical_query_text(candidates[0].query))

    for claim_ref in sorted(fact_checkable_claim_refs):
        add_best(claim_ref=claim_ref, intent=EvidenceIntent.PRIMARY)
        add_best(claim_ref=claim_ref, intent=EvidenceIntent.CONTRADICTION)
    if attribution_required:
        add_best(claim_ref=None, intent=EvidenceIntent.ATTRIBUTION)

    phase_one_limit = min(
        budget.effective_total_budget,
        max(policy.phase_one_target, budget.mandatory_floor),
    )
    for _, query in ordered:
        normalized = canonical_query_text(query.query)
        if len(selected) >= phase_one_limit:
            break
        if normalized not in selected_text:
            selected.append(query)
            selected_text.add(normalized)

    reserve = [
        query
        for _, query in ordered
        if canonical_query_text(query.query) not in selected_text
    ][: max(0, budget.effective_total_budget - len(selected))]
    return selected, reserve


def select_reserve_batch(
    reserve_queries: Sequence[SearchQueryOutput],
    *,
    already_executed_keys: Collection[str],
    batch_size: int,
    remaining_budget: int,
) -> list[SearchQueryOutput]:
    limit = min(batch_size, max(0, remaining_budget))
    return [
        query
        for query in reserve_queries
        if query_state_key(query) not in already_executed_keys
    ][:limit]


def evaluate_discovery_gate(
    candidates: Sequence[CandidateLike],
    objectives: Sequence[ObjectiveLike],
    *,
    fact_checkable_claim_refs: Collection[str],
    attribution_required: bool,
    policy: DepthSearchPolicy,
) -> DiscoveryGateDecision:
    brave_candidates = [item for item in candidates if item.source_origin == "brave_discovery"]
    objective_by_ref = {item.objective_ref: item for item in objectives}
    coverage = {
        (objective.claim_ref, objective.intent)
        for candidate in brave_candidates
        for objective_ref in candidate.objective_refs
        if (objective := objective_by_ref.get(objective_ref)) is not None
    }
    missing_primary = tuple(
        sorted(
            claim_ref
            for claim_ref in fact_checkable_claim_refs
            if (claim_ref, EvidenceIntent.PRIMARY) not in coverage
        )
    )
    missing_contradiction = tuple(
        sorted(
            claim_ref
            for claim_ref in fact_checkable_claim_refs
            if (claim_ref, EvidenceIntent.CONTRADICTION) not in coverage
        )
    )
    attribution_covered = (
        not attribution_required
        or any(intent == EvidenceIntent.ATTRIBUTION for _, intent in coverage)
    )
    urls = {item.canonical_url or item.url for item in brave_candidates}
    domains = {item.domain for item in brave_candidates if item.domain}
    reasons: list[str] = []
    if missing_primary:
        reasons.append("MISSING_PRIMARY_COVERAGE")
    if missing_contradiction:
        reasons.append("MISSING_CONTRADICTION_COVERAGE")
    if not attribution_covered:
        reasons.append("MISSING_ATTRIBUTION_COVERAGE")
    if len(urls) < policy.minimum_candidate_count:
        reasons.append("CANDIDATE_COUNT_BELOW_MINIMUM")
    if len(domains) < policy.minimum_domain_count:
        reasons.append("DOMAIN_COUNT_BELOW_MINIMUM")
    return DiscoveryGateDecision(
        passed=not reasons,
        reason_codes=tuple(reasons),
        candidate_count=len(urls),
        domain_count=len(domains),
        missing_primary_claim_refs=missing_primary,
        missing_contradiction_claim_refs=missing_contradiction,
        attribution_covered=attribution_covered,
    )


__all__ = [
    "CoverageBudgetExceededError",
    "DepthSearchPolicy",
    "DiscoveryGateDecision",
    "POLICY_VERSION",
    "SearchBudget",
    "calculate_budget",
    "canonical_query_text",
    "evaluate_discovery_gate",
    "policy_for_depth",
    "query_state_key",
    "select_initial_queries",
    "select_reserve_batch",
]
