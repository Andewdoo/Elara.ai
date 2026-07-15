"""Research-planning prompt contract and deterministic draft normalization."""

from __future__ import annotations

from collections.abc import Collection
from hashlib import sha256

from agents.schemas import (
    PlanningDraftOutput,
    PlanningOutput,
    ResearchObjectiveOutput,
    SearchQueryOutput,
)

PROMPT_VERSION = "planner-v1"
SYSTEM_PROMPT = """
Create auditable research objectives and targeted queries for each atomic claim.
Every fact-checkable claim needs primary-evidence and contradiction paths. Cover
support, corrections, attribution, definitions, existing fact checks, historical
context, and surrounding context where relevant. Preserve exact quotations in
attribution queries. Prefer original records and use neutral wording that does not
assume the submitted claim is true. Do not browse, score, or decide truth.
""".strip()


_OBJECTIVE_DIGEST_LENGTH = 16


class UnknownPlanningDraftClaimRefError(ValueError):
    """Raised when a draft selects a claim reference outside workflow state."""


def normalize_research_plan(
    draft: PlanningDraftOutput,
    *,
    allowed_claim_refs: Collection[str],
) -> PlanningOutput:
    """Convert a model-facing draft into the persisted planning contract.

    References are derived entirely in Python from canonical objective identity
    inputs.  The objective's position makes otherwise identical objectives
    stable and distinct; a suffix provides deterministic protection against a
    truncated-digest collision.
    """

    allowed_refs = frozenset(allowed_claim_refs)
    objective_refs: set[str] = set()
    objectives: list[ResearchObjectiveOutput] = []
    queries: list[SearchQueryOutput] = []

    for ordinal, objective in enumerate(draft.objectives, start=1):
        if objective.claim_ref not in allowed_refs:
            raise UnknownPlanningDraftClaimRefError("draft claim_ref is not allowed")

        objective_ref = _objective_ref(
            claim_ref=objective.claim_ref,
            intent=objective.intent.value,
            target=objective.target,
            ordinal=ordinal,
            existing_refs=objective_refs,
        )
        objective_refs.add(objective_ref)
        objectives.append(
            ResearchObjectiveOutput(
                objective_ref=objective_ref,
                claim_ref=objective.claim_ref,
                intent=objective.intent,
                target=objective.target,
                required_source_role=objective.required_source_role,
                priority=objective.priority,
                preferred_source_types=list(objective.preferred_source_types),
            )
        )
        queries.extend(
            SearchQueryOutput(
                query=query.query,
                objective_ref=objective_ref,
                intent=objective.intent,
                recency_hint=query.recency_hint,
                domain_hints=list(query.domain_hints),
                priority=query.priority,
            )
            for query in objective.queries
        )

    return PlanningOutput(
        objectives=objectives,
        queries=queries,
        primary_source_targets=list(draft.primary_source_targets),
        known_evidence_gaps=list(draft.known_evidence_gaps),
    )


def _objective_ref(
    *,
    claim_ref: str,
    intent: str,
    target: str,
    ordinal: int,
    existing_refs: Collection[str],
) -> str:
    canonical_identity = "\x1f".join(
        (_canonicalize(claim_ref), _canonicalize(intent), _canonicalize(target), str(ordinal))
    )
    digest = sha256(canonical_identity.encode("utf-8")).hexdigest()[:_OBJECTIVE_DIGEST_LENGTH]
    base_ref = f"obj-{digest}"
    candidate = base_ref
    collision_index = 2
    while candidate in existing_refs:
        candidate = f"{base_ref}-{collision_index}"
        collision_index += 1
    return candidate


def _canonicalize(value: str) -> str:
    return " ".join(value.casefold().split())


__all__ = [
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "UnknownPlanningDraftClaimRefError",
    "normalize_research_plan",
]
