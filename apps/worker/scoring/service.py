"""Typed state adapter for deterministic formulas and methodology gates."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from agents.schemas import ClaimKind, ConfidenceIssue, ContextIssue, EvidenceStance, Importance
from graph.state import (
    CalculationRecord,
    ClaimScoreRecord,
    ScoredEvidenceRecord,
    ScoreBundle,
    VerificationState,
)
from research.extension_errors import WorkflowExtensionError
from scoring.formulas import (
    SCORING_VERSION,
    FORMULAS,
    EvidenceQuality,
    WeightedEvidence,
    article_factual_accuracy,
    context_completeness,
    decimal_context_record,
    evidence_balance,
    evidence_quality,
    quote_fidelity,
    rounded_score,
    source_independence,
    verdict_confidence,
    weighted_average,
)
from scoring.labels import InsufficientEvidence, article_label, final_claim_label


STANCE_VALUES = {
    EvidenceStance.STRONGLY_CONTRADICTS: Decimal("-1.00"),
    EvidenceStance.PARTIALLY_CONTRADICTS: Decimal("-0.50"),
    EvidenceStance.NEUTRAL: Decimal("0.00"),
    EvidenceStance.PARTIALLY_SUPPORTS: Decimal("0.50"),
    EvidenceStance.STRONGLY_SUPPORTS: Decimal("1.00"),
}

CONTEXT_PENALTIES = {
    ContextIssue.KEY_TERM_UNDEFINED: Decimal("20"),
    ContextIssue.DATE_RANGE_OMITTED: Decimal("15"),
    ContextIssue.BASELINE_OR_DENOMINATOR_OMITTED: Decimal("20"),
    ContextIssue.RELATIVE_WITHOUT_ABSOLUTE: Decimal("15"),
    ContextIssue.CORRELATION_AS_CAUSATION: Decimal("25"),
    ContextIssue.MATERIAL_QUALIFIER_OMITTED: Decimal("15"),
    ContextIssue.INCOMPARABLE_GROUPS: Decimal("20"),
    ContextIssue.UNIT_OR_MEASURE_CHANGED: Decimal("20"),
    ContextIssue.SURROUNDING_QUOTE_CHANGES_MEANING: Decimal("25"),
    ContextIssue.CONDITIONAL_LANGUAGE_REMOVED: Decimal("25"),
    ContextIssue.ADJACENT_SENTENCE_OMITTED: Decimal("20"),
    ContextIssue.SCOPE_OMITTED: Decimal("15"),
    ContextIssue.SPEAKER_QUOTING_ANOTHER: Decimal("25"),
    ContextIssue.NONLITERAL_PRESENTED_LITERALLY: Decimal("25"),
    ContextIssue.QUESTION_AS_ASSERTION: Decimal("20"),
    ContextIssue.TRANSLATION_QUALIFIER_REMOVED: Decimal("20"),
    ContextIssue.EDIT_HIDES_CORRECTION: Decimal("25"),
}

AMBIGUITY_NON_BLOCKING_MINIMUM_SUPPORT = Decimal("70")
AMBIGUITY_NON_BLOCKING_MAX_CONTRADICTION_RATIO = Decimal("0.15")
SPEAKER_OR_DATE_SENSITIVE_CLAIM_KINDS = frozenset(
    {ClaimKind.ATTRIBUTION, ClaimKind.QUOTATION}
)

CONFIDENCE_PENALTIES = {
    # An owned interpretation limitation remains visible, but its calibrated
    # confidence penalty is 30% lower than the previous 15-point penalty.
    ConfidenceIssue.ESSENTIAL_TERM_AMBIGUOUS: Decimal("10.5"),
    ConfidenceIssue.SPEAKER_OR_DATE_UNRESOLVED: Decimal("10"),
    # Keep the missing-primary limitation in the audit trail. The independent
    # primary_access confidence component still contributes 0 when unavailable.
    ConfidenceIssue.PRIMARY_EVIDENCE_UNAVAILABLE: Decimal("0"),
    ConfidenceIssue.MAJOR_CONTRADICTION_UNRESOLVED: Decimal("15"),
    ConfidenceIssue.SINGLE_INFORMATION_CLUSTER: Decimal("15"),
    ConfidenceIssue.IMPORTANT_SOURCE_INACCESSIBLE: Decimal("5"),
    ConfidenceIssue.TRANSLATION_UNCERTAIN: Decimal("10"),
    ConfidenceIssue.EDITED_MEDIA_UNAUTHENTICATED: Decimal("15"),
    ConfidenceIssue.DEVELOPING_EVENT_LOW: Decimal("5"),
    ConfidenceIssue.DEVELOPING_EVENT_HIGH: Decimal("7.5"),
}


class DeterministicScoringService:
    def __init__(self, *, minimum_adjusted_evidence: Decimal = Decimal("0.50")) -> None:
        if minimum_adjusted_evidence < 0:
            raise ValueError("minimum_adjusted_evidence cannot be negative")
        self.minimum = minimum_adjusted_evidence

    async def process(self, state: VerificationState) -> VerificationState:
        passages = {item.passage_id: item for item in state.passages}
        sources = {item.source_ref: item for item in state.candidate_sources}
        self._validate_inputs(state, passages, sources)
        accepted = [item for item in state.evidence if not item.recommended_rejection_reasons]
        scored: list[ScoredEvidenceRecord] = []
        calculations: list[CalculationRecord] = []
        by_claim: dict[str, list[tuple[ScoredEvidenceRecord, Decimal, object]]] = {}

        for item in state.evidence:
            passage = passages[item.passage_id]
            multiplier = state.source_dependency_multipliers.get(
                passage.source_ref, Decimal("1.00")
            )
            quality = evidence_quality(
                EvidenceQuality(
                    Decimal(str(item.quality.relevance)),
                    Decimal(str(item.quality.directness)),
                    Decimal(str(item.quality.claim_specific_authority)),
                    Decimal(str(item.quality.transparency)),
                    Decimal(str(item.quality.temporal_fit)),
                    Decimal(str(item.quality.extraction_certainty)),
                )
            )
            weight = quality * multiplier
            row = ScoredEvidenceRecord(
                claim_ref=item.claim_ref,
                passage_id=item.passage_id,
                stance_value=STANCE_VALUES[item.stance],
                base_quality=quality,
                dependency_multiplier=multiplier,
                adjusted_weight=weight,
                rejection_reasons=list(item.recommended_rejection_reasons),
            )
            scored.append(row)
            if not row.rejection_reasons:
                by_claim.setdefault(item.claim_ref, []).append((row, quality, item))
            calculations.extend(
                (
                    self._record(
                        "evidence_quality",
                        item.claim_ref,
                        {
                            "passage_id": item.passage_id,
                            "R": str(item.quality.relevance),
                            "D": str(item.quality.directness),
                            "A": str(item.quality.claim_specific_authority),
                            "T": str(item.quality.transparency),
                            "F": str(item.quality.temporal_fit),
                            "X": str(item.quality.extraction_certainty),
                        },
                        {"quality": str(quality)},
                        "ratio",
                    ),
                    self._record(
                        "adjusted_evidence_weight",
                        item.claim_ref,
                        {
                            "passage_id": item.passage_id,
                            "quality": str(quality),
                            "dependency_multiplier": str(multiplier),
                        },
                        {"adjusted_weight": str(weight)},
                        "weight",
                    ),
                )
            )

        independence = self._independence(state, accepted, passages, sources)
        claim_scores: list[ClaimScoreRecord] = []
        exact_support: dict[str, Decimal] = {}
        exact_context: dict[str, Decimal] = {}
        exact_confidence: dict[str, Decimal] = {}
        claim_quote_scores: dict[str, Decimal] = {}
        claim_confidence_issues: dict[str, set[ConfidenceIssue]] = {}

        for claim in state.claims:
            items = by_claim.get(claim.claim_ref, [])
            balance = evidence_balance(
                WeightedEvidence(row.stance_value, row.base_quality, row.dependency_multiplier)
                for row, _, _ in items
            )
            support = balance.support
            if support is not None:
                exact_support[claim.claim_ref] = support
            consistency = balance.consistency or Decimal("0")
            average_quality = weighted_average(
                (quality * 100, row.adjusted_weight) for row, quality, _ in items
            ) or Decimal("0")
            adequate = balance.total >= self.minimum
            claim_source_refs = {passages[row.passage_id].source_ref for row, _, _ in items}
            claim_independence = self._independence(
                state,
                [item for _, _, item in items],
                passages,
                sources,
            )
            primary = Decimal("100") if any(
                sources.get(ref) and sources[ref].source_type == "PRIMARY"
                for ref in claim_source_refs
            ) else Decimal("0")
            context_issues = {issue for _, _, item in items for issue in item.context_issues}
            context_penalties = [CONTEXT_PENALTIES[issue] for issue in sorted(context_issues)]
            context = context_completeness(context_penalties)
            exact_context[claim.claim_ref] = context
            confidence_issues = {
                issue for _, _, item in items for issue in item.confidence_issues
            }
            owned_ambiguity_count = self._owned_ambiguity_count(state, claim)
            has_owned_ambiguity = owned_ambiguity_count > 0
            if has_owned_ambiguity:
                confidence_issues.add(ConfidenceIssue.ESSENTIAL_TERM_AMBIGUOUS)
            if primary == 0 and self._primary_expected(state, claim.claim_ref):
                confidence_issues.add(ConfidenceIssue.PRIMARY_EVIDENCE_UNAVAILABLE)
            if self._one_origin(state, claim_source_refs):
                confidence_issues.add(ConfidenceIssue.SINGLE_INFORMATION_CLUSTER)
            if self._has_inaccessible_source(state, claim.claim_ref):
                confidence_issues.add(ConfidenceIssue.IMPORTANT_SOURCE_INACCESSIBLE)
            claim_confidence_issues[claim.claim_ref] = confidence_issues
            penalties = [CONFIDENCE_PENALTIES[issue] for issue in sorted(confidence_issues)]
            confidence = verdict_confidence(
                coverage=Decimal("100") if adequate else Decimal("0"),
                average_quality=average_quality,
                independence=claim_independence,
                consistency=consistency,
                primary_access=primary,
                penalties=penalties,
            )
            exact_confidence[claim.claim_ref] = confidence
            one_interested_source = len(claim_source_refs) == 1 and all(
                sources[ref].source_type == "OFFICIAL_SELF_REPORT"
                for ref in claim_source_refs
            )
            # An ambiguity is non-blocking when this owning claim is well
            # supported by adequate evidence and any contradiction is limited.
            # This preserves a disclosed qualification for broad terms without
            # treating a small, relevant counterpoint as missing evidence.
            # Unowned/global ambiguity strings never enter a claim-level gate.
            contradiction_ratio = (
                balance.contradicting / balance.supporting
                if balance.supporting > 0
                else Decimal("1")
            )
            limited_contradiction = (
                contradiction_ratio <= AMBIGUITY_NON_BLOCKING_MAX_CONTRADICTION_RATIO
            )
            ambiguity_non_blocking = (
                has_owned_ambiguity
                and adequate
                and support is not None
                and support >= AMBIGUITY_NON_BLOCKING_MINIMUM_SUPPORT
                and limited_contradiction
            )
            ambiguity_blocks_key_facts = has_owned_ambiguity and not ambiguity_non_blocking
            speaker_or_date_blocks_key_facts = (
                ConfidenceIssue.SPEAKER_OR_DATE_UNRESOLVED in confidence_issues
                and (
                    claim.claim_kind in SPEAKER_OR_DATE_SENSITIVE_CLAIM_KINDS
                    or claim.time_period is not None
                )
            )
            unresolved_key_facts = (
                ambiguity_blocks_key_facts
                or speaker_or_date_blocks_key_facts
            )
            insufficient = InsufficientEvidence(
                total_below_minimum=not adequate,
                single_uncheckable_interested_source=one_interested_source,
                unresolved_key_facts=unresolved_key_facts,
            )
            label = final_claim_label(
                support=support,
                confidence=confidence,
                context=context,
                insufficient=insufficient,
            )
            quote_inputs = [
                (row, item.quote_fidelity)
                for row, _, item in items
                if item.quote_fidelity is not None and row.adjusted_weight > 0
            ]
            if quote_inputs:
                quote_values = []
                for row, components in quote_inputs:
                    value = quote_fidelity(
                        wording=Decimal(str(components.wording)) * 100,
                        speaker_identity=Decimal(str(components.speaker_identity)) * 100,
                        completeness=Decimal(str(components.completeness)) * 100,
                        sequence_integrity=Decimal(str(components.sequence_integrity)) * 100,
                        translation_accuracy=(
                            Decimal(str(components.translation_accuracy)) * 100
                            if components.translation_accuracy is not None
                            else None
                        ),
                    )
                    quote_values.append((value, row.adjusted_weight))
                quote_score = weighted_average(quote_values)
                if quote_score is not None:
                    claim_quote_scores[claim.claim_ref] = quote_score
                    calculations.append(
                        self._record(
                            "quote_fidelity",
                            claim.claim_ref,
                            {
                                "passages": [
                                    {
                                        "passage_id": row.passage_id,
                                        "components": components.model_dump(mode="json"),
                                        "adjusted_weight": str(row.adjusted_weight),
                                    }
                                    for row, components in quote_inputs
                                ]
                            },
                            {"score": str(quote_score)},
                            "score_0_100",
                        )
                    )

            claim_scores.append(
                ClaimScoreRecord(
                    claim_ref=claim.claim_ref,
                    supporting_weight=balance.supporting,
                    contradicting_weight=balance.contradicting,
                    total_adjusted_evidence=balance.total,
                    evidence_support=rounded_score(support) if support is not None else None,
                    evidence_consistency=(
                        rounded_score(balance.consistency)
                        if balance.consistency is not None
                        else None
                    ),
                    verdict_confidence=rounded_score(confidence),
                    context_completeness=rounded_score(context),
                    average_quality=rounded_score(average_quality),
                    adequate_evidence=adequate,
                    final_label=label,
                    gates={
                        "insufficient_evidence": list(insufficient.reasons),
                        "context_issues": sorted(issue.value for issue in context_issues),
                        "confidence_issues": sorted(issue.value for issue in confidence_issues),
                    },
                )
            )
            base_inputs = {"P": str(balance.supporting), "N": str(balance.contradicting)}
            calculations.extend(
                (
                    self._record("supporting_weight", claim.claim_ref, {"evidence": [row.passage_id for row, _, _ in items]}, {"P": str(balance.supporting)}, "weight"),
                    self._record("contradicting_weight", claim.claim_ref, {"evidence": [row.passage_id for row, _, _ in items]}, {"N": str(balance.contradicting)}, "weight"),
                    self._record("evidence_support", claim.claim_ref, base_inputs, {"score": str(support) if support is not None else None}, "score_0_100", "insufficient" if support is None else "passed"),
                    self._record("evidence_consistency", claim.claim_ref, base_inputs, {"score": str(balance.consistency) if balance.consistency is not None else None}, "score_0_100", "insufficient" if balance.consistency is None else "passed"),
                    self._record("source_independence", claim.claim_ref, self._independence_inputs(state, [item for _, _, item in items], passages, sources), {"score": str(claim_independence)}, "score_0_100"),
                    self._record("verdict_confidence", claim.claim_ref, {"coverage": "100" if adequate else "0", "average_quality": str(average_quality), "independence": str(claim_independence), "consistency": str(consistency), "primary_access": str(primary), "penalties": {issue.value: str(CONFIDENCE_PENALTIES[issue]) for issue in sorted(confidence_issues)}}, {"score": str(confidence)}, "score_0_100"),
                    self._record("context_completeness", claim.claim_ref, {"material_penalties": {issue.value: str(CONTEXT_PENALTIES[issue]) for issue in sorted(context_issues)}}, {"score": str(context)}, "score_0_100"),
                    self._record("final_label", claim.claim_ref, {"support": str(support) if support is not None else None, "confidence": str(confidence), "context": str(context), "insufficient_evidence_reasons": list(insufficient.reasons), "scoring_version": SCORING_VERSION}, {"label": label}, "label", "gated" if support is None or insufficient.triggered or confidence < 35 else "passed"),
                )
            )
            if has_owned_ambiguity:
                calculations.append(
                    self._record(
                        "ambiguity_gate",
                        claim.claim_ref,
                        {
                            "scoring_version": SCORING_VERSION,
                            "owned_ambiguity_count": owned_ambiguity_count,
                            "accepted_adjusted_evidence": str(balance.total),
                            "minimum_adjusted_evidence": str(self.minimum),
                            "accepted_supporting_weight": str(balance.supporting),
                            "accepted_contradicting_weight": str(balance.contradicting),
                            "contradiction_ratio": str(contradiction_ratio),
                        },
                        {
                            "adequate_accepted_evidence": adequate,
                            "has_accepted_support": balance.supporting > 0,
                            "no_accepted_material_contradiction": limited_contradiction,
                            "non_blocking": ambiguity_non_blocking,
                            "unresolved_key_facts": unresolved_key_facts,
                        },
                        "gate_decision",
                        "non_blocking" if ambiguity_non_blocking else "gated",
                    )
                )

        factual_claims = [
            (exact_support[row.claim_ref], claim.importance_weight)
            for row in claim_scores
            for claim in state.claims
            if row.claim_ref == claim.claim_ref
            and row.claim_ref in exact_support
            and claim.fact_checkability.value != "not_fact_checkable"
        ]
        factual_accuracy = article_factual_accuracy(factual_claims)
        attribution_claims = [
            (exact_support[row.claim_ref], claim.importance_weight)
            for row in claim_scores
            for claim in state.claims
            if row.claim_ref == claim.claim_ref
            and row.claim_ref in exact_support
            and claim.claim_kind == ClaimKind.ATTRIBUTION
        ]
        attribution_support = article_factual_accuracy(attribution_claims)
        essential = [
            row
            for row in claim_scores
            for claim in state.claims
            if row.claim_ref == claim.claim_ref and claim.importance == Importance.ESSENTIAL
        ]
        coverage_claims = [
            (row, claim)
            for row in claim_scores
            for claim in state.claims
            if row.claim_ref == claim.claim_ref
            and (
                claim.importance == Importance.ESSENTIAL
                or not any(c.importance == Importance.ESSENTIAL for c in state.claims)
            )
            and claim.fact_checkability.value != "not_fact_checkable"
        ]
        coverage_denominator = sum((Decimal(claim.importance_weight) for _, claim in coverage_claims), Decimal("0"))
        coverage = (
            100 * sum((Decimal(claim.importance_weight) for row, claim in coverage_claims if row.adequate_evidence), Decimal("0")) / coverage_denominator
            if coverage_denominator
            else Decimal("0")
        )
        all_items = [entry for values in by_claim.values() for entry in values]
        overall_quality = weighted_average((quality * 100, row.adjusted_weight) for row, quality, _ in all_items) or Decimal("0")
        overall_balance = evidence_balance(WeightedEvidence(row.stance_value, row.base_quality, row.dependency_multiplier) for row, _, _ in all_items)
        overall_consistency = overall_balance.consistency or Decimal("0")
        accepted_refs = {passages[item.passage_id].source_ref for item in accepted}
        primary_access = Decimal("100") if any(sources.get(ref) and sources[ref].source_type == "PRIMARY" for ref in accepted_refs) else Decimal("0")
        # Claim-owned interpretation limits remain visible on their claim only.
        # They must not turn a separate essential claim or the whole article into
        # insufficient evidence; speaker/date limits remain article-level gates.
        global_issues = {
            issue
            for issues in claim_confidence_issues.values()
            for issue in issues
            if issue != ConfidenceIssue.ESSENTIAL_TERM_AMBIGUOUS
        }
        overall_confidence = verdict_confidence(
            coverage=coverage,
            average_quality=overall_quality,
            independence=independence,
            consistency=overall_consistency,
            primary_access=primary_access,
            penalties=[CONFIDENCE_PENALTIES[issue] for issue in sorted(global_issues)],
        )
        overall_context = weighted_average(
            (exact_context[row.claim_ref], next(c.importance_weight for c in state.claims if c.claim_ref == row.claim_ref))
            for row in claim_scores
        ) or Decimal("100")
        quote_score = weighted_average(
            (value, next(c.importance_weight for c in state.claims if c.claim_ref == claim_ref))
            for claim_ref, value in claim_quote_scores.items()
        )
        speaker_or_date_blocks_article = any(
            ConfidenceIssue.SPEAKER_OR_DATE_UNRESOLVED
            in claim_confidence_issues.get(claim.claim_ref, set())
            and (
                claim.claim_kind in SPEAKER_OR_DATE_SENSITIVE_CLAIM_KINDS
                or claim.time_period is not None
            )
            for claim in state.claims
        )
        overall_insufficient = InsufficientEvidence(
            total_below_minimum=overall_balance.total < self.minimum,
            no_essential_claim_adequate=bool(essential) and not any(row.adequate_evidence for row in essential),
            single_uncheckable_interested_source=(len(accepted_refs) == 1 and all(sources[ref].source_type == "OFFICIAL_SELF_REPORT" for ref in accepted_refs)),
            unresolved_key_facts=speaker_or_date_blocks_article,
        )
        strong_refutation = any(
            row.claim_ref in exact_support
            and exact_support[row.claim_ref] <= Decimal("10")
            and exact_confidence[row.claim_ref] >= Decimal("70")
            for row in essential
        )
        final = article_label(
            factual_accuracy=factual_accuracy,
            insufficient=overall_insufficient,
            strongly_refuted_essential_claim=strong_refutation,
            verdict_confidence=overall_confidence,
            context=overall_context,
        )
        calculations.extend(
            (
                self._record("source_independence", None, self._independence_inputs(state, accepted, passages, sources), {"score": str(independence)}, "score_0_100"),
                self._record("verdict_confidence", None, {"coverage": str(coverage), "average_quality": str(overall_quality), "independence": str(independence), "consistency": str(overall_consistency), "primary_access": str(primary_access), "penalties": {issue.value: str(CONFIDENCE_PENALTIES[issue]) for issue in sorted(global_issues)}}, {"score": str(overall_confidence)}, "score_0_100"),
                self._record("article_factual_accuracy", None, {"claims": [{"support": str(s), "importance_weight": w} for s, w in factual_claims]}, {"score": str(factual_accuracy) if factual_accuracy is not None else None, "essential_claim_gate": strong_refutation}, "score_0_100", "insufficient" if factual_accuracy is None else "passed"),
                self._record("final_label", None, {"factual_accuracy": str(factual_accuracy) if factual_accuracy is not None else None, "verdict_confidence": str(overall_confidence), "context": str(overall_context), "insufficient_evidence_reasons": list(overall_insufficient.reasons), "strongly_refuted_essential_claim": strong_refutation, "scoring_version": SCORING_VERSION}, {"label": final}, "label", "gated" if overall_insufficient.triggered or strong_refutation or overall_confidence < 35 else "passed"),
            )
        )
        calculations.append(
            self._record(
                "research_coverage",
                None,
                {
                    "claims": [
                        {
                            "claim_ref": claim.claim_ref,
                            "importance_weight": claim.importance_weight,
                            "adequate_evidence": row.adequate_evidence,
                        }
                        for row, claim in coverage_claims
                    ],
                    "confidence_issues": sorted(issue.value for issue in global_issues),
                },
                {
                    "adequate_evidence": str(coverage),
                    "insufficient_evidence": str(Decimal("100") - coverage),
                    "inaccessible_source_impact": str(
                        CONFIDENCE_PENALTIES[ConfidenceIssue.IMPORTANT_SOURCE_INACCESSIBLE]
                        if ConfidenceIssue.IMPORTANT_SOURCE_INACCESSIBLE in global_issues
                        else Decimal("0")
                    ),
                },
                "score_0_100",
            )
        )
        calculations.append(
            self._record(
                "context_completeness",
                None,
                {
                    "claims": [
                        {
                            "claim_ref": row.claim_ref,
                            "context": str(exact_context[row.claim_ref]),
                            "importance_weight": next(
                                claim.importance_weight
                                for claim in state.claims
                                if claim.claim_ref == row.claim_ref
                            ),
                        }
                        for row in claim_scores
                    ]
                },
                {"score": str(overall_context)},
                "score_0_100",
            )
        )
        if quote_score is not None:
            calculations.append(
                self._record(
                    "quote_fidelity",
                    None,
                    {
                        "claims": [
                            {
                                "claim_ref": claim_ref,
                                "score": str(value),
                                "importance_weight": next(
                                    claim.importance_weight
                                    for claim in state.claims
                                    if claim.claim_ref == claim_ref
                                ),
                            }
                            for claim_ref, value in claim_quote_scores.items()
                        ]
                    },
                    {"score": str(quote_score)},
                    "score_0_100",
                )
            )
        if attribution_support is not None:
            calculations.append(
                self._record(
                    "attribution_support",
                    None,
                    {
                        "claims": [
                            {"support": str(support), "importance_weight": weight}
                            for support, weight in attribution_claims
                        ]
                    },
                    {"score": str(attribution_support)},
                    "score_0_100",
                )
            )
        scores = ScoreBundle(
            evidence_support=rounded_score(factual_accuracy) if factual_accuracy is not None else None,
            article_factual_accuracy=rounded_score(factual_accuracy) if factual_accuracy is not None else None,
            verdict_confidence=rounded_score(overall_confidence),
            source_independence=rounded_score(independence),
            context_completeness=rounded_score(overall_context),
            evidence_consistency=rounded_score(overall_consistency) if overall_balance.consistency is not None else None,
            quote_fidelity=rounded_score(quote_score) if quote_score is not None else None,
            final_label=final,
            methodology_version=state.methodology_version,
        )
        return state.model_copy(update={"scored_evidence": scored, "claim_scores": claim_scores, "calculations": calculations, "scores": scores})

    @staticmethod
    def _validate_inputs(state, passages, sources) -> None:
        if not state.claims:
            raise WorkflowExtensionError(
                code="SCORING_CLAIMS_REQUIRED",
                public_message="Deterministic scoring requires at least one atomic claim.",
            )
        if not state.evidence:
            raise WorkflowExtensionError(
                code="SCORING_EVIDENCE_REQUIRED",
                public_message="Deterministic scoring requires classified evidence.",
            )
        claim_refs = {claim.claim_ref for claim in state.claims}
        missing_claims = sum(1 for item in state.evidence if item.claim_ref not in claim_refs)
        missing_passages = sum(1 for item in state.evidence if item.passage_id not in passages)
        unknown_sources = sum(
            1
            for item in state.evidence
            if item.passage_id in passages and passages[item.passage_id].source_ref not in sources
        )
        if missing_claims or missing_passages or unknown_sources:
            raise WorkflowExtensionError(
                code="INVALID_SCORING_EVIDENCE_INPUT",
                public_message="Classified evidence did not match the available scoring inputs.",
                details={
                    "missing_claim_count": missing_claims,
                    "missing_passage_count": missing_passages,
                    "unknown_source_count": unknown_sources,
                },
            )
        missing_multipliers = set(sources) - set(state.source_dependency_multipliers)
        invalid_multipliers = sum(
            1
            for value in state.source_dependency_multipliers.values()
            if value not in {Decimal("1.00"), Decimal("0.35"), Decimal("0.10"), Decimal("0.00")}
        )
        if missing_multipliers or invalid_multipliers:
            raise WorkflowExtensionError(
                code="SCORING_DEPENDENCY_MULTIPLIERS_REQUIRED",
                public_message="Deterministic scoring requires valid provenance dependency multipliers.",
                details={
                    "missing_multiplier_count": len(missing_multipliers),
                    "invalid_multiplier_count": invalid_multipliers,
                },
            )

    @staticmethod
    def _primary_expected(state: VerificationState, claim_ref: str) -> bool:
        objective_refs = {item.objective_ref for item in state.objectives if item.claim_ref == claim_ref}
        return bool(state.primary_source_targets or any(query.objective_ref in objective_refs and query.intent.value == "primary" for query in state.queries))

    @staticmethod
    def _owned_ambiguity_count(state: VerificationState, claim) -> int:
        """Count only limitations that are explicitly attached to this claim."""
        owned = set(claim.ambiguities)
        owned.update(
            ambiguity.text
            for ambiguity in state.claim_ambiguities
            if ambiguity.claim_ref == claim.claim_ref
        )
        return len(owned)

    @staticmethod
    def _has_inaccessible_source(state: VerificationState, claim_ref: str) -> bool:
        objective_refs = {item.objective_ref for item in state.objectives if item.claim_ref == claim_ref}
        relevant_sources = {item.source_ref for item in state.candidate_sources if set(item.objective_refs) & objective_refs}
        return any(snapshot.source_ref in relevant_sources and snapshot.access_status != "FETCHED" for snapshot in state.snapshots)

    @staticmethod
    def _one_origin(state: VerificationState, refs: set[str]) -> bool:
        if not refs:
            return False
        cluster_members = {ref: cluster.cluster_ref for cluster in state.information_clusters for ref in cluster.source_refs}
        origins = {cluster_members.get(ref, f"source:{ref}") for ref in refs}
        return len(origins) == 1

    def _independence_inputs(self, state, accepted, passages, sources):
        refs = {passages[item.passage_id].source_ref for item in accepted}
        cluster_members = {ref: cluster.cluster_ref for cluster in state.information_clusters for ref in cluster.source_refs}
        origins = {cluster_members.get(ref, f"source:{ref}") for ref in refs}
        independent = sum(1 for ref in refs if state.source_dependency_multipliers.get(ref, Decimal("1")) == Decimal("1"))
        primary = sum(1 for ref in refs if sources.get(ref) and sources[ref].source_type == "PRIMARY")
        organizations = len({(sources[ref].domain or ref).lower() for ref in refs if ref in sources})
        data_chains = {cluster_members.get(ref, f"source:{ref}") for ref in refs}
        return {
            "origin_diversity": str(min(Decimal("100"), Decimal(len(origins)) * 50)),
            "primary_diversity": str(min(Decimal("100"), Decimal(primary) * 50)),
            "organizational_diversity": str(min(Decimal("100"), Decimal(organizations) * 50)),
            "method_diversity": str(min(Decimal("100"), Decimal(max(len(data_chains), independent)) * 50)),
        }

    def _independence(self, state, accepted, passages, sources):
        values = self._independence_inputs(state, accepted, passages, sources)
        return source_independence(**{key: Decimal(value) for key, value in values.items()})

    @staticmethod
    def _record(name, claim_ref, inputs, result, units, audit_status="passed"):
        return CalculationRecord(
            calculation_ref=str(uuid4()),
            formula_name=name,
            formula_text=FORMULAS[name],
            inputs=inputs,
            result=result,
            units=units,
            decimal_context=decimal_context_record(),
            audit_status=audit_status,
            claim_ref=claim_ref,
        )


__all__ = [
    "CONFIDENCE_PENALTIES",
    "CONTEXT_PENALTIES",
    "DeterministicScoringService",
    "STANCE_VALUES",
]
