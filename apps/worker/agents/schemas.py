"""Structured outputs exchanged by the controlled verification workflow.

These contracts capture language-understanding results only. Final scoring,
rejection gates, arithmetic, and completion decisions remain deterministic.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


UnitScore = Annotated[float, Field(ge=0.0, le=1.0)]


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InputKind(StrEnum):
    CLAIM = "claim"
    ARTICLE_URL = "article_url"
    ARTICLE_TEXT = "article_text"
    QUOTE = "quote"
    PARAPHRASE = "paraphrase"
    DOCUMENT = "document"


class ClaimKind(StrEnum):
    FACTUAL = "factual"
    NUMERICAL = "numerical"
    CAUSAL = "causal"
    QUOTATION = "quotation"
    ATTRIBUTION = "attribution"
    SCIENTIFIC = "scientific"
    LEGAL = "legal"
    PREDICTION = "prediction"
    OPINION = "opinion"
    ALLEGATION = "allegation"
    TESTIMONY = "testimony"
    RHETORICAL_FRAMING = "rhetorical_framing"


class FactCheckability(StrEnum):
    FACT_CHECKABLE = "fact_checkable"
    PARTIALLY_FACT_CHECKABLE = "partially_fact_checkable"
    NOT_FACT_CHECKABLE = "not_fact_checkable"


class Importance(StrEnum):
    ESSENTIAL = "essential"
    MAJOR = "major"
    MINOR = "minor"


class EvidenceIntent(StrEnum):
    PRIMARY = "primary"
    SUPPORT = "support"
    CONTRADICTION = "contradiction"
    CORRECTION = "correction"
    ATTRIBUTION = "attribution"
    DEFINITION = "definition"
    HISTORICAL_CONTEXT = "historical_context"
    SURROUNDING_CONTEXT = "surrounding_context"
    EXISTING_FACT_CHECK = "existing_fact_check"


class EvidenceStance(StrEnum):
    STRONGLY_CONTRADICTS = "strongly_contradicts"
    PARTIALLY_CONTRADICTS = "partially_contradicts"
    NEUTRAL = "neutral_or_irrelevant"
    PARTIALLY_SUPPORTS = "partially_supports"
    STRONGLY_SUPPORTS = "strongly_supports"


class ContextIssue(StrEnum):
    KEY_TERM_UNDEFINED = "key_term_undefined"
    DATE_RANGE_OMITTED = "date_range_omitted"
    BASELINE_OR_DENOMINATOR_OMITTED = "baseline_or_denominator_omitted"
    RELATIVE_WITHOUT_ABSOLUTE = "relative_without_absolute"
    CORRELATION_AS_CAUSATION = "correlation_as_causation"
    MATERIAL_QUALIFIER_OMITTED = "material_qualifier_omitted"
    INCOMPARABLE_GROUPS = "incomparable_groups"
    UNIT_OR_MEASURE_CHANGED = "unit_or_measure_changed"
    SURROUNDING_QUOTE_CHANGES_MEANING = "surrounding_quote_changes_meaning"
    CONDITIONAL_LANGUAGE_REMOVED = "conditional_language_removed"
    ADJACENT_SENTENCE_OMITTED = "adjacent_sentence_omitted"
    SCOPE_OMITTED = "scope_omitted"
    SPEAKER_QUOTING_ANOTHER = "speaker_quoting_another"
    NONLITERAL_PRESENTED_LITERALLY = "nonliteral_presented_literally"
    QUESTION_AS_ASSERTION = "question_as_assertion"
    TRANSLATION_QUALIFIER_REMOVED = "translation_qualifier_removed"
    EDIT_HIDES_CORRECTION = "edit_hides_correction"


class ConfidenceIssue(StrEnum):
    ESSENTIAL_TERM_AMBIGUOUS = "essential_term_ambiguous"
    SPEAKER_OR_DATE_UNRESOLVED = "speaker_or_date_unresolved"
    PRIMARY_EVIDENCE_UNAVAILABLE = "primary_evidence_unavailable"
    MAJOR_CONTRADICTION_UNRESOLVED = "major_contradiction_unresolved"
    SINGLE_INFORMATION_CLUSTER = "single_information_cluster"
    IMPORTANT_SOURCE_INACCESSIBLE = "important_source_inaccessible"
    TRANSLATION_UNCERTAIN = "translation_uncertain"
    EDITED_MEDIA_UNAUTHENTICATED = "edited_media_unauthenticated"
    DEVELOPING_EVENT_LOW = "developing_event_low"
    DEVELOPING_EVENT_HIGH = "developing_event_high"


class Entailment(StrEnum):
    ENTAILED = "entailed"
    PARTIAL = "partial"
    NOT_ENTAILED = "not_entailed"
    INSUFFICIENT = "insufficient_evidence"


class NamedEntity(AgentOutput):
    name: str = Field(min_length=1, max_length=500)
    entity_type: str = Field(min_length=1, max_length=100)


class MetricReference(AgentOutput):
    name: str = Field(min_length=1, max_length=300)
    unit: str | None = Field(default=None, max_length=100)
    period: str | None = Field(default=None, max_length=200)


class IntakeClassificationOutput(AgentOutput):
    input_kind: InputKind
    normalized_text: str = Field(min_length=1)
    detected_language: str = Field(min_length=2, max_length=100)
    fact_checkability: FactCheckability
    claim_kinds: list[ClaimKind] = Field(default_factory=list)
    entities: list[NamedEntity] = Field(default_factory=list)
    speaker: str | None = Field(default=None, max_length=500)
    venue: str | None = Field(default=None, max_length=500)
    dates: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    metrics: list[MetricReference] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list)
    comparisons: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    requires_attribution_check: bool = False
    public_warnings: list[str] = Field(default_factory=list)


class AtomicClaimOutput(AgentOutput):
    claim_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    text: str = Field(min_length=1)
    claim_kind: ClaimKind
    importance: Importance
    importance_weight: Literal[1, 2, 3]
    fact_checkability: FactCheckability
    original_text_span: str | None = None
    entities: list[NamedEntity] = Field(default_factory=list)
    time_period: str | None = Field(default=None, max_length=500)
    locations: list[str] = Field(default_factory=list)
    metrics: list[MetricReference] = Field(default_factory=list)
    comparison: str | None = None
    parent_claim_ref: str | None = Field(default=None, max_length=64)
    ambiguities: list[str] = Field(default_factory=list)
    verification_scope: str = Field(min_length=1)

    @model_validator(mode="after")
    def importance_matches_weight(self) -> "AtomicClaimOutput":
        expected = {
            Importance.ESSENTIAL: 3,
            Importance.MAJOR: 2,
            Importance.MINOR: 1,
        }[self.importance]
        if self.importance_weight != expected:
            raise ValueError("importance_weight must match importance")
        return self


class DecompositionDraftClaimOutput(AgentOutput):
    """Model-owned claim content before deterministic reference assignment."""

    text: str = Field(min_length=1)
    claim_kind: ClaimKind
    importance: Importance
    importance_weight: Literal[1, 2, 3]
    fact_checkability: FactCheckability
    original_text_span: str | None = None
    entities: list[NamedEntity] = Field(default_factory=list)
    time_period: str | None = Field(default=None, max_length=500)
    locations: list[str] = Field(default_factory=list)
    metrics: list[MetricReference] = Field(default_factory=list)
    comparison: str | None = None
    parent_claim_index: int | None = Field(default=None, ge=0, strict=True)
    ambiguities: list[str] = Field(default_factory=list)
    verification_scope: str = Field(min_length=1)

    @model_validator(mode="after")
    def importance_matches_weight(self) -> "DecompositionDraftClaimOutput":
        expected = {
            Importance.ESSENTIAL: 3,
            Importance.MAJOR: 2,
            Importance.MINOR: 1,
        }[self.importance]
        if self.importance_weight != expected:
            raise ValueError("importance_weight must match importance")
        return self


class DecompositionOutput(AgentOutput):
    atomic_claims: list[AtomicClaimOutput] = Field(min_length=1)
    unresolved_ambiguities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def claim_refs_are_unique(self) -> "DecompositionOutput":
        refs = [claim.claim_ref for claim in self.atomic_claims]
        if len(refs) != len(set(refs)):
            raise ValueError("claim_ref values must be unique")
        return self


class DecompositionDraftOutput(AgentOutput):
    """Strict model-facing decomposition contract without trusted identifiers."""

    atomic_claims: list[DecompositionDraftClaimOutput] = Field(min_length=1)
    unresolved_ambiguities: list[str] = Field(default_factory=list)


class ResearchObjectiveOutput(AgentOutput):
    objective_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    claim_ref: str = Field(min_length=1, max_length=64)
    intent: EvidenceIntent
    target: str = Field(min_length=1)
    required_source_role: str | None = Field(default=None, max_length=100)
    priority: UnitScore = 0.5
    preferred_source_types: list[str] = Field(default_factory=list)


class SearchQueryOutput(AgentOutput):
    query: str = Field(min_length=1, max_length=500)
    objective_ref: str = Field(min_length=1, max_length=64)
    intent: EvidenceIntent
    recency_hint: str | None = Field(default=None, max_length=100)
    domain_hints: list[str] = Field(default_factory=list)
    priority: UnitScore = 0.5


class PlanningDraftQueryOutput(AgentOutput):
    """A model-owned query scoped to its containing research objective."""

    query: str = Field(min_length=1, max_length=500)
    recency_hint: str | None = Field(default=None, max_length=100)
    domain_hints: list[str] = Field(default_factory=list)
    priority: UnitScore = 0.5


class PlanningDraftObjectiveOutput(AgentOutput):
    """A model-owned objective with no database-like objective reference."""

    claim_ref: str = Field(min_length=1, max_length=64)
    intent: EvidenceIntent
    target: str = Field(min_length=1)
    required_source_role: str | None = Field(default=None, max_length=100)
    priority: UnitScore = 0.5
    preferred_source_types: list[str] = Field(default_factory=list)
    queries: list[PlanningDraftQueryOutput] = Field(min_length=1)


class PlanningDraftOutput(AgentOutput):
    """The narrow schema DeepSeek may use to propose a research plan.

    Objective references and query intents are deterministic workflow values,
    deliberately absent from this model-facing contract.
    """

    objectives: list[PlanningDraftObjectiveOutput] = Field(min_length=1)
    primary_source_targets: list[str] = Field(default_factory=list)
    known_evidence_gaps: list[str] = Field(default_factory=list)


class PlanningOutput(AgentOutput):
    objectives: list[ResearchObjectiveOutput] = Field(min_length=1)
    queries: list[SearchQueryOutput] = Field(min_length=1)
    primary_source_targets: list[str] = Field(default_factory=list)
    known_evidence_gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def queries_reference_objectives(self) -> "PlanningOutput":
        objective_refs = {objective.objective_ref for objective in self.objectives}
        missing = {
            query.objective_ref
            for query in self.queries
            if query.objective_ref not in objective_refs
        }
        if missing:
            raise ValueError("queries must reference declared objectives")
        return self


class EvidenceQualityOutput(AgentOutput):
    relevance: UnitScore
    directness: UnitScore
    claim_specific_authority: UnitScore
    transparency: UnitScore
    temporal_fit: UnitScore
    extraction_certainty: UnitScore


class QuoteFidelityComponentsOutput(AgentOutput):
    wording: UnitScore
    speaker_identity: UnitScore
    completeness: UnitScore
    sequence_integrity: UnitScore
    translation_accuracy: UnitScore | None = None


class EvidenceClassificationItemOutput(AgentOutput):
    claim_ref: str = Field(min_length=1, max_length=64)
    passage_id: str = Field(min_length=1, max_length=128)
    stance: EvidenceStance
    quality: EvidenceQualityOutput
    explicit_support: str | None = None
    explicit_contradiction: str | None = None
    uncertainty: str | None = None
    omitted_context: list[str] = Field(default_factory=list)
    context_issues: list[ContextIssue] = Field(default_factory=list)
    confidence_issues: list[ConfidenceIssue] = Field(default_factory=list)
    quote_fidelity: QuoteFidelityComponentsOutput | None = None
    entity_match: bool
    time_period_match: bool
    quotation_or_number_located: bool | None = None
    recommended_rejection_reasons: list[str] = Field(default_factory=list)


class EvidenceClassificationTaskResultOutput(AgentOutput):
    """Language judgment keyed only by a declared classification task."""

    task_ref: str = Field(pattern=r"^classification-[a-f0-9]{24}$")
    stance: EvidenceStance
    quality: EvidenceQualityOutput
    explicit_support: str | None = None
    explicit_contradiction: str | None = None
    uncertainty: str | None = None
    omitted_context: list[str] = Field(default_factory=list)
    context_issues: list[ContextIssue] = Field(default_factory=list)
    confidence_issues: list[ConfidenceIssue] = Field(default_factory=list)
    quote_fidelity: QuoteFidelityComponentsOutput | None = None
    entity_match: bool
    time_period_match: bool
    quotation_or_number_located: bool | None = None
    recommended_rejection_reasons: list[str] = Field(default_factory=list)


class EvidenceClassificationOutput(AgentOutput):
    classifications: list[EvidenceClassificationTaskResultOutput] = Field(default_factory=list)


class CitedReportSentenceOutput(AgentOutput):
    sentence_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    text: str = Field(min_length=1)
    passage_ids: list[str] = Field(default_factory=list)


class SynthesisOutput(AgentOutput):
    title: str = Field(min_length=1, max_length=300)
    summary_sentences: list[CitedReportSentenceOutput] = Field(min_length=1)
    factual_sentences: list[CitedReportSentenceOutput] = Field(default_factory=list)
    strongest_credible_contradiction: CitedReportSentenceOutput | None = None
    attribution_findings: list[CitedReportSentenceOutput] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    inaccessible_source_notes: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    evidence_reviewed_at: datetime | None = None
    evidence_timestamp: str | None = None
    methodology_version: str | None = Field(default=None, max_length=100)
    workflow_version: str | None = Field(default=None, max_length=100)
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    parser_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def cited_report_sentence_refs_are_unique(self) -> "SynthesisOutput":
        sentences = [
            *self.summary_sentences,
            *self.factual_sentences,
            *self.attribution_findings,
        ]
        if self.strongest_credible_contradiction is not None:
            sentences.append(self.strongest_credible_contradiction)
        refs = [sentence.sentence_ref for sentence in sentences]
        if len(refs) != len(set(refs)):
            raise ValueError("sentence_ref values must be unique across the report")
        if any(not sentence.passage_ids for sentence in sentences):
            raise ValueError("every factual report sentence must cite at least one passage")
        return self


class SentenceCitationAuditOutput(AgentOutput):
    sentence_ref: str = Field(min_length=1, max_length=64)
    passage_id: str = Field(min_length=1, max_length=128)
    entailment: Entailment
    support_explanation: str = Field(min_length=1)
    suggested_revision: str | None = None


class CitationAuditOutput(AgentOutput):
    sentence_audits: list[SentenceCitationAuditOutput] = Field(default_factory=list)
    unsupported_sentence_refs: list[str] = Field(default_factory=list)
    missing_citation_sentence_refs: list[str] = Field(default_factory=list)
    needs_revision: bool


__all__ = [
    "AtomicClaimOutput",
    "CitationAuditOutput",
    "ConfidenceIssue",
    "ContextIssue",
    "CitedReportSentenceOutput",
    "DecompositionDraftClaimOutput",
    "DecompositionDraftOutput",
    "DecompositionOutput",
    "EvidenceClassificationOutput",
    "EvidenceClassificationTaskResultOutput",
    "EvidenceQualityOutput",
    "IntakeClassificationOutput",
    "PlanningDraftObjectiveOutput",
    "PlanningDraftOutput",
    "PlanningDraftQueryOutput",
    "PlanningOutput",
    "QuoteFidelityComponentsOutput",
    "SentenceCitationAuditOutput",
    "SynthesisOutput",
]
