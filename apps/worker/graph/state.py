"""Typed, auditable state passed between verification workflow nodes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.deepseek_client import CallMetadata
from agents.schemas import (
    AtomicClaimOutput,
    ClaimAmbiguityOutput,
    CitationAuditOutput,
    EvidenceClassificationItemOutput,
    IntakeClassificationOutput,
    PlanningOutput,
    ResearchObjectiveOutput,
    SearchQueryOutput,
    SynthesisOutput,
)


UnitDecimal = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
ScoreValue = Annotated[int, Field(ge=0, le=100)]
AccessStatusValue = Literal[
    "PENDING", "FETCHED", "INACCESSIBLE", "PAYWALLED", "BOT_BLOCKED", "UNSUPPORTED", "FAILED"
]
SourceTypeValue = Literal[
    "PRIMARY",
    "OFFICIAL_SELF_REPORT",
    "INDEPENDENT_ANALYSIS",
    "SECONDARY_REPORT",
    "DERIVATIVE_REPORT",
    "OPINION",
    "UNKNOWN",
]
EvidenceIntentValue = Literal[
    "primary",
    "support",
    "contradiction",
    "correction",
    "attribution",
    "definition",
    "historical_context",
    "surrounding_context",
    "existing_fact_check",
]
DependencyRelationshipValue = Literal[
    "CITES",
    "REPUBLISHES",
    "QUOTES",
    "DERIVES_FROM",
    "USES_SAME_DATA",
    "POSSIBLE_DUPLICATE",
]
SearchDiscoveryPhaseValue = Literal["phase_one", "phase_two"]
SearchExecutionStatusValue = Literal["planned", "executed", "cache_hit", "not_needed"]
AuthoritySubjectValue = Literal[
    "compensation",
    "legal",
    "medical",
    "product",
    "corporate",
    "quotation",
    "public_record",
]
AuthorityGapReasonValue = Literal[
    "AUTHORITY_PROFILE_AMBIGUOUS",
    "NO_SEARCH_RESULTS",
    "NO_VERIFIED_RESULT",
    "PROVIDER_FAILURE",
    "PREFLIGHT_BUDGET_EXHAUSTED",
    "INACCESSIBLE_OR_BLOCKED",
    "NO_EXACT_CLAIM_EVIDENCE",
]
CandidateSearchPhaseValue = Literal[
    "submitted", "authority_preflight", "broad_phase_one", "broad_phase_two"
]


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchDepth(StrEnum):
    QUICK = "QUICK"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class WorkflowStage(StrEnum):
    INTAKE = "intake"
    DECOMPOSITION = "decomposition"
    PLANNER = "planner"
    DISCOVERY = "discovery_source_selection"
    RETRIEVAL = "secure_retrieval"
    EXTRACTION = "extraction"
    SEGMENTATION = "passage_segmentation_embedding"
    PROVENANCE = "provenance_dependency_analysis"
    EVIDENCE_CLASSIFICATION = "evidence_classification"
    SCORING = "deterministic_scoring"
    NUMERICAL_AUDIT = "numerical_audit"
    SYNTHESIS = "synthesis"
    CITATION_REVISION = "citation_revision"
    CITATION_AUDIT = "citation_audit"


class AuthorityRecordHolderRecord(StateModel):
    domain: str = Field(min_length=1, max_length=255)
    source_role: str = Field(min_length=1, max_length=100)
    entity: str = Field(min_length=1, max_length=300)
    jurisdictions: list[str] = Field(default_factory=list)
    query_terms: list[str] = Field(default_factory=list)
    document_terms: list[str] = Field(default_factory=list)
    source_type: SourceTypeValue


class AuthorityProfileRecord(StateModel):
    claim_ref: str = Field(min_length=1, max_length=64)
    subject: AuthoritySubjectValue
    entity: str | None = Field(default=None, max_length=300)
    jurisdiction: str | None = Field(default=None, max_length=200)
    timeframe: str | None = Field(default=None, max_length=500)
    metric_or_quotation: str | None = Field(default=None, max_length=180)
    expected_source_roles: list[str] = Field(min_length=1)
    record_holders: list[AuthorityRecordHolderRecord] = Field(min_length=1)
    profile_version: str = Field(min_length=1, max_length=100)
    registry_version: str = Field(min_length=1, max_length=100)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authority profile timestamps must be timezone-aware")
        return value


class AuthorityPreflightQueryRecord(StateModel):
    query_key: str = Field(min_length=1, max_length=700)
    claim_ref: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=500)
    domain_restriction: str = Field(min_length=1, max_length=255)
    source_role: str = Field(min_length=1, max_length=100)
    profile_version: str = Field(min_length=1, max_length=100)
    registry_version: str = Field(min_length=1, max_length=100)
    execution_status: SearchExecutionStatusValue = "planned"
    result_count: int | None = Field(default=None, ge=0)
    verified_candidate_count: int = Field(default=0, ge=0)
    network_attempt_count: int = Field(default=0, ge=0)
    executed_at: datetime | None = None
    skip_reason: str | None = Field(default=None, max_length=100)
    rejection_reason_codes: list[str] = Field(default_factory=list)

    @field_validator("executed_at")
    @classmethod
    def executed_at_is_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("authority preflight timestamps must be timezone-aware")
        return value


class AuthorityGapRecord(StateModel):
    code: Literal["APPLICABLE_AUTHORITATIVE_SOURCE_NOT_FOUND"]
    claim_ref: str = Field(min_length=1, max_length=64)
    profile_subject: AuthoritySubjectValue
    reason_code: AuthorityGapReasonValue
    preflight_queries: list[str] = Field(default_factory=list)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authority gap timestamps must be timezone-aware")
        return value


class CandidateSource(StateModel):
    source_ref: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=4096)
    canonical_url: str | None = Field(default=None, max_length=4096)
    domain: str | None = Field(default=None, max_length=255)
    snippet: str | None = None
    objective_refs: list[str] = Field(default_factory=list)
    evidence_intents: list[EvidenceIntentValue] = Field(default_factory=list)
    title: str | None = Field(default=None, max_length=1000)
    source_type: SourceTypeValue = "UNKNOWN"
    # This is deterministic intake provenance, not a claim about the source's
    # evidentiary weight.  It keeps a user-submitted URL distinct from the
    # supplementary Brave discovery candidates used to research the claim.
    source_origin: Literal[
        "submitted_url", "brave_discovery", "authority_preflight"
    ] = "brave_discovery"
    selection_reason: str = Field(min_length=1)
    priority: UnitDecimal = Decimal("0")
    search_phase: CandidateSearchPhaseValue = "broad_phase_one"
    authority_claim_ref: str | None = Field(default=None, max_length=64)
    authority_source_role: str | None = Field(default=None, max_length=100)
    authority_match_status: Literal[
        "not_evaluated", "verified_search_match", "verified_document_match", "rejected"
    ] = "not_evaluated"
    authority_match_reasons: list[str] = Field(default_factory=list)
    authority_profile_version: str | None = Field(default=None, max_length=100)
    authority_registry_version: str | None = Field(default=None, max_length=100)


class SnapshotRecord(StateModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    source_ref: str = Field(min_length=1, max_length=128)
    access_status: AccessStatusValue
    retrieved_at: datetime
    published_at: datetime | None = None
    updated_at: datetime | None = None
    content_hash: str | None = Field(default=None, max_length=128)
    content_type: str | None = Field(default=None, max_length=255)
    snapshot_path: str | None = None
    parser_name: str | None = Field(default=None, max_length=100)
    parser_version: str | None = Field(default=None, max_length=100)
    extraction_quality: UnitDecimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None

    @field_validator("retrieved_at", "published_at", "updated_at")
    @classmethod
    def retrieved_at_is_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("snapshot timestamps must be timezone-aware")
        return value


class ExtractedSourceRecord(StateModel):
    source_ref: str = Field(min_length=1, max_length=128)
    snapshot_id: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=1000)
    author: str | None = Field(default=None, max_length=1000)
    publisher: str | None = Field(default=None, max_length=1000)
    published_at: datetime | None = None
    updated_at: datetime | None = None
    headings: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    correction_notices: list[str] = Field(default_factory=list)
    outbound_links: list[str] = Field(default_factory=list)
    page_positions: list[str] = Field(default_factory=list)
    blocks: list["ExtractedBlockRecord"] = Field(default_factory=list)


class ExtractedBlockRecord(StateModel):
    kind: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1)
    heading_path: list[str] = Field(default_factory=list)
    page_or_position: str | None = Field(default=None, max_length=500)
    paragraph_index: int | None = Field(default=None, ge=0)
    speaker: str | None = None
    table_ref: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PassageRecord(StateModel):
    passage_id: str = Field(min_length=1, max_length=128)
    source_ref: str = Field(min_length=1, max_length=128)
    snapshot_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    text_hash: str = Field(min_length=1, max_length=128)
    page_or_position: str | None = Field(default=None, max_length=500)
    heading_path: str | None = None
    paragraph_index: int | None = Field(default=None, ge=0)
    speaker: str | None = None
    table_ref: str | None = Field(default=None, max_length=500)
    extraction_certainty: UnitDecimal
    embedding: list[float] | None = None
    embedding_model: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DependencyRecord(StateModel):
    parent_source_ref: str = Field(min_length=1, max_length=128)
    child_source_ref: str = Field(min_length=1, max_length=128)
    relationship: DependencyRelationshipValue
    confidence: UnitDecimal
    detection_method: str = Field(min_length=1, max_length=100)
    information_cluster_ref: str | None = Field(default=None, max_length=128)
    dependency_multiplier: UnitDecimal = Decimal("1.00")

    @model_validator(mode="after")
    def no_self_edge(self) -> "DependencyRecord":
        if self.parent_source_ref == self.child_source_ref:
            raise ValueError("source dependencies cannot be self-referential")
        return self


class InformationClusterRecord(StateModel):
    cluster_ref: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=500)
    origin_type: str = Field(min_length=1, max_length=100)
    representative_source_ref: str = Field(min_length=1, max_length=128)
    source_refs: list[str] = Field(min_length=1)

    @field_validator("source_refs")
    @classmethod
    def unique_members(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("information cluster members must be unique")
        return value


class CalculationRecord(StateModel):
    calculation_ref: str = Field(min_length=1, max_length=128)
    formula_name: str = Field(min_length=1, max_length=100)
    formula_text: str = Field(min_length=1)
    inputs: dict[str, Any]
    result: dict[str, Any]
    units: str | None = Field(default=None, max_length=100)
    decimal_context: dict[str, Any]
    audit_status: str = Field(min_length=1, max_length=50)
    claim_ref: str | None = Field(default=None, max_length=64)


class ScoredEvidenceRecord(StateModel):
    claim_ref: str = Field(min_length=1, max_length=64)
    passage_id: str = Field(min_length=1, max_length=128)
    stance_value: Decimal = Field(ge=Decimal("-1"), le=Decimal("1"))
    base_quality: UnitDecimal
    dependency_multiplier: UnitDecimal
    adjusted_weight: UnitDecimal
    rejection_reasons: list[str] = Field(default_factory=list)


class ClaimScoreRecord(StateModel):
    claim_ref: str = Field(min_length=1, max_length=64)
    supporting_weight: Decimal = Field(ge=0)
    contradicting_weight: Decimal = Field(ge=0)
    total_adjusted_evidence: Decimal = Field(ge=0)
    evidence_support: ScoreValue | None = None
    evidence_consistency: ScoreValue | None = None
    verdict_confidence: ScoreValue
    context_completeness: ScoreValue
    average_quality: ScoreValue
    adequate_evidence: bool
    final_label: str = Field(min_length=1, max_length=100)
    gates: dict[str, Any] = Field(default_factory=dict)


class ScoreBundle(StateModel):
    evidence_support: ScoreValue | None = None
    verdict_confidence: ScoreValue | None = None
    source_independence: ScoreValue | None = None
    context_completeness: ScoreValue | None = None
    evidence_consistency: ScoreValue | None = None
    quote_fidelity: ScoreValue | None = None
    article_factual_accuracy: ScoreValue | None = None
    final_label: str | None = Field(default=None, max_length=100)
    methodology_version: str = Field(min_length=1, max_length=100)
    deterministic: Literal[True] = True


class EmbeddingRunMetadata(StateModel):
    provider: Literal["deepseek"] = "deepseek"
    configured_model: str | None = Field(default=None, max_length=255)
    used_model: str | None = Field(default=None, max_length=255)
    status: Literal[
        "embedded",
        "unconfigured_fallback",
        "provider_fallback",
        "dimension_fallback",
        "no_passages",
    ]
    request_count: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=100)
    status_code: int | None = Field(default=None, ge=100, le=599)
    retryable: bool = False


class SearchQueryExecutionRecord(StateModel):
    query_key: str = Field(min_length=1, max_length=700)
    discovery_phase: SearchDiscoveryPhaseValue
    execution_status: SearchExecutionStatusValue = "planned"
    result_count: int | None = Field(default=None, ge=0)
    network_attempt_count: int = Field(default=0, ge=0)
    executed_at: datetime | None = None
    skip_reason: str | None = Field(default=None, max_length=100)

    @field_validator("executed_at")
    @classmethod
    def executed_at_is_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("search execution timestamps must be timezone-aware")
        return value


class DiscoveryGateRecord(StateModel):
    discovery_phase: SearchDiscoveryPhaseValue
    batch_number: int = Field(ge=1)
    passed: bool
    candidate_count: int = Field(ge=0)
    domain_count: int = Field(ge=0)
    minimum_candidate_count: int = Field(ge=1)
    minimum_domain_count: int = Field(ge=1)
    reason_codes: list[str] = Field(default_factory=list)
    missing_primary_claim_refs: list[str] = Field(default_factory=list)
    missing_contradiction_claim_refs: list[str] = Field(default_factory=list)
    attribution_covered: bool


class RecoverableError(StateModel):
    stage: WorkflowStage
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,99}$")
    public_message: str = Field(min_length=1, max_length=1000)
    recoverable: Literal[True] = True
    retryable: bool = False
    details: dict[str, str | int | bool | None] = Field(default_factory=dict)


class VerificationState(StateModel):
    """No prompts, raw provider responses, or chain-of-thought belong here."""

    run_id: UUID
    user_id: UUID
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    normalized_input: IntakeClassificationOutput | None = None
    research_depth: ResearchDepth
    methodology_version: str = Field(min_length=1, max_length=100)
    workflow_version: str = Field(default="step-10", min_length=1, max_length=100)
    parser_versions: dict[str, str] = Field(default_factory=dict)
    claims: list[AtomicClaimOutput] = Field(default_factory=list)
    # Typed claim ownership is required before a scoring gate may use an ambiguity.
    claim_ambiguities: list[ClaimAmbiguityOutput] = Field(default_factory=list)
    # Legacy/global strings stay durable report limitations and are never assigned
    # to a claim by the workflow state.
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    objectives: list[ResearchObjectiveOutput] = Field(default_factory=list)
    queries: list[SearchQueryOutput] = Field(default_factory=list)
    primary_source_targets: list[str] = Field(default_factory=list)
    known_evidence_gaps: list[str] = Field(default_factory=list)
    authority_profiles: list[AuthorityProfileRecord] = Field(default_factory=list)
    authority_preflight_queries: list[AuthorityPreflightQueryRecord] = Field(
        default_factory=list
    )
    authority_gaps: list[AuthorityGapRecord] = Field(default_factory=list)
    authority_profile_version: str | None = Field(default=None, max_length=100)
    authority_registry_version: str | None = Field(default=None, max_length=100)
    authority_preflight_budget: int = Field(default=0, ge=0)
    authority_preflight_used: int = Field(default=0, ge=0)
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    query_result_counts: dict[str, int] = Field(default_factory=dict)
    search_query_executions: list[SearchQueryExecutionRecord] = Field(default_factory=list)
    discovery_gate_outcomes: list[DiscoveryGateRecord] = Field(default_factory=list)
    search_policy_version: str = Field(default="adaptive-search-v1", min_length=1, max_length=100)
    search_phase_one_target: int | None = Field(default=None, ge=1)
    search_phase_two_target: int | None = Field(default=None, ge=0)
    search_mandatory_floor: int = Field(default=0, ge=0)
    search_effective_budget: int = Field(default=0, ge=0)
    snapshots: list[SnapshotRecord] = Field(default_factory=list)
    extracted_sources: list[ExtractedSourceRecord] = Field(default_factory=list)
    passages: list[PassageRecord] = Field(default_factory=list)
    evidence: list[EvidenceClassificationItemOutput] = Field(default_factory=list)
    information_clusters: list[InformationClusterRecord] = Field(default_factory=list)
    dependencies: list[DependencyRecord] = Field(default_factory=list)
    source_dependency_multipliers: dict[str, UnitDecimal] = Field(default_factory=dict)
    scored_evidence: list[ScoredEvidenceRecord] = Field(default_factory=list)
    claim_scores: list[ClaimScoreRecord] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    # Model- or parser-identified candidates remain untrusted dictionaries until
    # auditing.numerical validates them deterministically.
    numerical_candidates: list[dict[str, Any]] = Field(default_factory=list)
    scores: ScoreBundle | None = None
    report_draft: SynthesisOutput | None = None
    citation_audit: CitationAuditOutput | None = None
    citation_revision_count: int = Field(default=0, ge=0)
    evidence_reviewed_at: datetime | None = None
    recoverable_errors: list[RecoverableError] = Field(default_factory=list)
    model_calls: dict[str, CallMetadata] = Field(default_factory=dict)
    embedding_model_version: str | None = Field(default=None, max_length=255)
    passage_retrieval_mode: Literal["hybrid", "lexical_metadata_fallback"] = (
        "lexical_metadata_fallback"
    )
    embedding_run_metadata: EmbeddingRunMetadata | None = None
    completed_stages: list[WorkflowStage] = Field(default_factory=list)
    cancelled: bool = False

    @field_validator("started_at", "evidence_reviewed_at")
    @classmethod
    def workflow_timestamps_are_timezone_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("workflow timestamps must be timezone-aware")
        return value

    @property
    def plan(self) -> PlanningOutput | None:
        if not self.objectives or not self.queries:
            return None
        return PlanningOutput(
            objectives=self.objectives,
            queries=self.queries,
            primary_source_targets=self.primary_source_targets,
            known_evidence_gaps=self.known_evidence_gaps,
        )

    def with_error(self, error: RecoverableError) -> "VerificationState":
        return self.model_copy(update={"recoverable_errors": [*self.recoverable_errors, error]})

    @property
    def ready_for_completion(self) -> bool:
        """Deterministic gate: citation revision must finish before COMPLETED."""
        return bool(
            not self.cancelled
            and not self.recoverable_errors
            and self.citation_audit is not None
            and not self.citation_audit.needs_revision
            and WorkflowStage.CITATION_AUDIT in self.completed_stages
        )

    def complete(self, stage: WorkflowStage, **updates: object) -> "VerificationState":
        completed = self.completed_stages
        if stage not in completed:
            completed = [*completed, stage]
        return self.model_copy(update={**updates, "completed_stages": completed})


__all__ = [
    "AuthorityGapRecord",
    "AuthorityGapReasonValue",
    "AuthorityPreflightQueryRecord",
    "AuthorityProfileRecord",
    "AuthorityRecordHolderRecord",
    "AuthoritySubjectValue",
    "CandidateSearchPhaseValue",
    "CalculationRecord",
    "CandidateSource",
    "DependencyRecord",
    "EmbeddingRunMetadata",
    "EvidenceIntentValue",
    "DiscoveryGateRecord",
    "ExtractedBlockRecord",
    "ExtractedSourceRecord",
    "InformationClusterRecord",
    "PassageRecord",
    "RecoverableError",
    "ResearchDepth",
    "SearchQueryExecutionRecord",
    "ScoreBundle",
    "SnapshotRecord",
    "SourceTypeValue",
    "VerificationState",
    "WorkflowStage",
]
