"""Pure Decimal implementations of the published Elara scoring formulas."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from typing import Iterable, Mapping


DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_UP)
SCORING_VERSION = "1.3-qualified-ambiguity"
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def decimal_context_record() -> dict[str, object]:
    return {"precision": DECIMAL_CONTEXT.prec, "rounding": DECIMAL_CONTEXT.rounding}


def _decimal(value: Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _bounded(value: Decimal | int | str, low: Decimal, high: Decimal, name: str) -> Decimal:
    result = _decimal(value)
    if not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return result


def unit(value: Decimal | int | str, name: str = "value") -> Decimal:
    return _bounded(value, ZERO, ONE, name)


def score(value: Decimal | int | str, name: str = "value") -> Decimal:
    return _bounded(value, ZERO, HUNDRED, name)


def clamp_score(value: Decimal | int | str) -> Decimal:
    return min(HUNDRED, max(ZERO, _decimal(value)))


def rounded_score(value: Decimal | int | str) -> int:
    return int(clamp_score(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class EvidenceQuality:
    relevance: Decimal
    directness: Decimal
    authority: Decimal
    transparency: Decimal
    temporal_fit: Decimal
    extraction_certainty: Decimal

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, unit(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class WeightedEvidence:
    stance: Decimal
    quality: Decimal
    dependency_multiplier: Decimal

    def __post_init__(self) -> None:
        stance = _bounded(self.stance, Decimal("-1"), ONE, "stance")
        object.__setattr__(self, "stance", stance)
        object.__setattr__(self, "quality", unit(self.quality, "quality"))
        object.__setattr__(self, "dependency_multiplier", unit(self.dependency_multiplier, "dependency_multiplier"))

    @property
    def adjusted_weight(self) -> Decimal:
        return adjusted_evidence_weight(self.quality, self.dependency_multiplier)


@dataclass(frozen=True, slots=True)
class EvidenceBalance:
    supporting: Decimal
    contradicting: Decimal

    @property
    def total(self) -> Decimal:
        return self.supporting + self.contradicting

    @property
    def support(self) -> Decimal | None:
        return evidence_support(self.supporting, self.contradicting)

    @property
    def consistency(self) -> Decimal | None:
        return evidence_consistency(self.supporting, self.contradicting)


def evidence_quality(value: EvidenceQuality) -> Decimal:
    with localcontext(DECIMAL_CONTEXT):
        return (
            Decimal("0.25") * value.relevance
            + Decimal("0.20") * value.directness
            + Decimal("0.20") * value.authority
            + Decimal("0.15") * value.transparency
            + Decimal("0.10") * value.temporal_fit
            + Decimal("0.10") * value.extraction_certainty
        )


def adjusted_evidence_weight(quality: Decimal, dependency_multiplier: Decimal) -> Decimal:
    with localcontext(DECIMAL_CONTEXT):
        return unit(quality, "quality") * unit(dependency_multiplier, "dependency_multiplier")


def evidence_balance(items: Iterable[WeightedEvidence]) -> EvidenceBalance:
    supporting = ZERO
    contradicting = ZERO
    with localcontext(DECIMAL_CONTEXT):
        for item in items:
            supporting += max(item.stance, ZERO) * item.adjusted_weight
            contradicting += max(-item.stance, ZERO) * item.adjusted_weight
    return EvidenceBalance(supporting, contradicting)


def evidence_support(supporting: Decimal, contradicting: Decimal) -> Decimal | None:
    total = _decimal(supporting) + _decimal(contradicting)
    if total == ZERO:
        return None
    with localcontext(DECIMAL_CONTEXT):
        return HUNDRED * _decimal(supporting) / total


def evidence_consistency(supporting: Decimal, contradicting: Decimal) -> Decimal | None:
    total = _decimal(supporting) + _decimal(contradicting)
    if total == ZERO:
        return None
    with localcontext(DECIMAL_CONTEXT):
        return HUNDRED * abs(_decimal(supporting) - _decimal(contradicting)) / total


def verdict_confidence(*, coverage: Decimal, average_quality: Decimal, independence: Decimal,
                       consistency: Decimal, primary_access: Decimal,
                       penalties: Iterable[Decimal] = ()) -> Decimal:
    values = [score(value, name) for name, value in (("coverage", coverage), ("average_quality", average_quality),
              ("independence", independence), ("consistency", consistency), ("primary_access", primary_access))]
    deductions = sum((_decimal(value) for value in penalties), ZERO)
    if deductions < ZERO:
        raise ValueError("penalties cannot be negative")
    with localcontext(DECIMAL_CONTEXT):
        base = sum((weight * value for weight, value in zip(
            (Decimal("0.30"), Decimal("0.25"), Decimal("0.20"), Decimal("0.15"), Decimal("0.10")), values)), ZERO)
        return clamp_score(base - deductions)


def source_independence(*, origin_diversity: Decimal, primary_diversity: Decimal,
                        organizational_diversity: Decimal, method_diversity: Decimal) -> Decimal:
    values = [score(value, name) for name, value in (("origin_diversity", origin_diversity),
              ("primary_diversity", primary_diversity), ("organizational_diversity", organizational_diversity),
              ("method_diversity", method_diversity))]
    with localcontext(DECIMAL_CONTEXT):
        return sum((weight * value for weight, value in zip(
            (Decimal("0.40"), Decimal("0.25"), Decimal("0.20"), Decimal("0.15")), values)), ZERO)


def quote_fidelity(*, wording: Decimal, speaker_identity: Decimal, completeness: Decimal,
                   sequence_integrity: Decimal, translation_accuracy: Decimal | None = None) -> Decimal:
    components = [(Decimal("0.35"), score(wording, "wording")),
                  (Decimal("0.20"), score(speaker_identity, "speaker_identity")),
                  (Decimal("0.20"), score(completeness, "completeness")),
                  (Decimal("0.15"), score(sequence_integrity, "sequence_integrity"))]
    if translation_accuracy is not None:
        components.append((Decimal("0.10"), score(translation_accuracy, "translation_accuracy")))
    with localcontext(DECIMAL_CONTEXT):
        weight_total = sum((weight for weight, _ in components), ZERO)
        return sum((weight * value for weight, value in components), ZERO) / weight_total


def context_completeness(material_penalties: Iterable[Decimal]) -> Decimal:
    penalties = [_decimal(value) for value in material_penalties]
    if any(value < ZERO for value in penalties):
        raise ValueError("material penalties cannot be negative")
    return clamp_score(HUNDRED - sum(penalties, ZERO))


def article_factual_accuracy(claims: Iterable[tuple[Decimal, int]]) -> Decimal | None:
    accepted = [(score(support, "claim support"), _decimal(weight)) for support, weight in claims]
    if not accepted:
        return None
    if any(weight <= ZERO for _, weight in accepted):
        raise ValueError("importance weights must be positive")
    with localcontext(DECIMAL_CONTEXT):
        denominator = sum((weight for _, weight in accepted), ZERO)
        return sum((support * weight for support, weight in accepted), ZERO) / denominator


def weighted_average(values: Iterable[tuple[Decimal, Decimal | int]]) -> Decimal | None:
    items = [(_decimal(value), _decimal(weight)) for value, weight in values]
    if not items or sum((weight for _, weight in items), ZERO) == ZERO:
        return None
    return sum((value * weight for value, weight in items), ZERO) / sum((weight for _, weight in items), ZERO)


FORMULAS: Mapping[str, str] = {
    "evidence_quality": "q_i = 0.25R + 0.20D + 0.20A + 0.15T + 0.10F + 0.10X",
    "adjusted_evidence_weight": "w_i = q_i * dependency_multiplier",
    "supporting_weight": "P = sum(max(stance_i, 0) * w_i)",
    "contradicting_weight": "N = sum(max(-stance_i, 0) * w_i)",
    "evidence_support": "100 * P / (P + N)",
    "evidence_consistency": "100 * abs(P - N) / (P + N)",
    "verdict_confidence": "clamp(0.30COV + 0.25QUAL + 0.20IND + 0.15CONS + 0.10PRI - penalties, 0, 100)",
    "source_independence": "0.40O + 0.25P + 0.20G + 0.15M",
    "quote_fidelity": "weighted mean(0.35 wording, 0.20 speaker, 0.20 completeness, 0.15 sequence, 0.10 translation when applicable)",
    "context_completeness": "clamp(100 - sum(material penalties), 0, 100)",
    "article_factual_accuracy": "sum(atomic_claim_support * importance_weight) / sum(importance_weight)",
    "attribution_support": "sum(attribution_claim_support * importance_weight) / sum(importance_weight)",
    "research_coverage": "importance-weighted adequate evidence percentage; insufficient = 100 - adequate; inaccessible impact = deterministic confidence penalty",
    "ambiguity_gate": "owned ambiguity blocks unresolved key facts unless accepted adjusted evidence >= minimum, P > 0, and N = 0",
    "final_label": "apply insufficient-evidence gate, confidence < 35 gate, context override, support thresholds, and essential-claim gate",
}
