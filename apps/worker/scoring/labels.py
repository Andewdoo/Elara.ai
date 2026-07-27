"""Deterministic claim/article labels and methodology gates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from scoring.formulas import score


@dataclass(frozen=True, slots=True)
class InsufficientEvidence:
    total_below_minimum: bool = False
    no_essential_claim_adequate: bool = False
    single_uncheckable_interested_source: bool = False
    unresolved_key_facts: bool = False

    @property
    def triggered(self) -> bool:
        return any((self.total_below_minimum, self.no_essential_claim_adequate,
                    self.single_uncheckable_interested_source, self.unresolved_key_facts))

    @property
    def reasons(self) -> tuple[str, ...]:
        pairs = (("total_adjusted_evidence_below_minimum", self.total_below_minimum),
                 ("no_essential_claim_has_adequate_evidence", self.no_essential_claim_adequate),
                 ("single_interested_source_cannot_be_independently_checked", self.single_uncheckable_interested_source),
                 ("key_definitions_dates_or_identities_unresolved", self.unresolved_key_facts))
        return tuple(name for name, active in pairs if active)


def support_label(support: Decimal) -> str:
    value = score(support, "support")
    if value >= 90:
        return "Supported"
    if value >= 75:
        return "Mostly supported"
    if value >= 60:
        return "Leaning supported"
    if value >= 40:
        return "Mixed"
    if value >= 26:
        return "Leaning contradicted"
    if value >= 11:
        return "Mostly contradicted"
    return "Contradicted"


def confidence_label(confidence: Decimal) -> str:
    value = score(confidence, "confidence")
    if value >= 85:
        return "Very high"
    if value >= 70:
        return "High"
    if value >= 50:
        return "Moderate"
    if value >= 30:
        return "Low"
    return "Very low"


def final_claim_label(*, support: Decimal | None, confidence: Decimal,
                      context: Decimal, insufficient: InsufficientEvidence) -> str:
    if support is None or confidence < Decimal("35") or insufficient.triggered:
        return "Insufficient evidence"
    if support >= Decimal("70") and context < Decimal("50"):
        return "Technically supported but misleading"
    if support >= Decimal("90") and context >= Decimal("70"):
        return "Supported"
    return support_label(support)


def article_label(*, factual_accuracy: Decimal | None, insufficient: InsufficientEvidence,
                  strongly_refuted_essential_claim: bool,
                  verdict_confidence: Decimal = Decimal("100"),
                  context: Decimal = Decimal("100")) -> str:
    if factual_accuracy is None or verdict_confidence < Decimal("35") or insufficient.triggered:
        return "Insufficient evidence"
    if factual_accuracy >= Decimal("70") and context < Decimal("50"):
        return "Technically supported but misleading"
    label = support_label(factual_accuracy)
    if strongly_refuted_essential_claim and label == "Supported":
        return "Mostly supported"
    return label
