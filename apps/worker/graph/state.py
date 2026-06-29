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
    CITATION_AUDIT = "citation_audit"


class CandidateSource(StateModel):
    source_ref: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=4096)
    canonical_url: str | None = Field(default=None, max_length=4096)
    domain: str | None = Field(default=None, max_length=255)
    snippet: str | None = None
    objective_refs: list[str] = Field(default_factory=list)
    title: str | None = Field(default=None, max_length=1000)
    source_type: str = Field(default="UNKNOWN", max_length=100)
    selection_reason: str = Field(min_length=1)
    priority: UnitDecimal = Decimal("0")


class SnapshotRecord(StateModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    source_ref: str = Field(min_length=1, max_length=128)
    access_status: str = Field(min_length=1, max_length=100)
    retrieved_at: datetime
    content_hash: str | None = Field(default=None, max_length=128)
    parser_name: str | None = Field(default=None, max_length=100)
    parser_version: str | None = Field(default=None, max_length=100)
    failure_reason: str | None = None

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value


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
    embedding_model: str | None = Field(default=None, max_length=255)


class DependencyRecord(StateModel):
    parent_source_ref: str = Field(min_length=1, max_length=128)
    child_source_ref: str = Field(min_length=1, max_length=128)
    relationship: str = Field(min_length=1, max_length=100)
    confidence: UnitDecimal
    detection_method: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def no_self_edge(self) -> "DependencyRecord":
        if self.parent_source_ref == self.child_source_ref:
            raise ValueError("source dependencies cannot be self-referential")
        return self


class CalculationRecord(StateModel):
    calculation_ref: str = Field(min_length=1, max_length=128)
    formula_name: str = Field(min_length=1, max_length=100)
    formula_text: str = Field(min_length=1)
    inputs: dict[str, Any]
    result: dict[str, Any]
    units: str | None = Field(default=None, max_length=100)
    decimal_context: dict[str, Any]
    audit_status: str = Field(min_length=1, max_length=50)


class ScoreBundle(StateModel):
    evidence_support: ScoreValue | None = None
    verdict_confidence: ScoreValue | None = None
    source_independence: ScoreValue | None = None
    context_completeness: ScoreValue | None = None
    final_label: str | None = Field(default=None, max_length=100)
    methodology_version: str = Field(min_length=1, max_length=100)
    deterministic: Literal[True] = True


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
    workflow_version: str = Field(default="step-8", min_length=1, max_length=100)
    parser_versions: dict[str, str] = Field(default_factory=dict)
    claims: list[AtomicClaimOutput] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    objectives: list[ResearchObjectiveOutput] = Field(default_factory=list)
    queries: list[SearchQueryOutput] = Field(default_factory=list)
    primary_source_targets: list[str] = Field(default_factory=list)
    known_evidence_gaps: list[str] = Field(default_factory=list)
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    snapshots: list[SnapshotRecord] = Field(default_factory=list)
    passages: list[PassageRecord] = Field(default_factory=list)
    evidence: list[EvidenceClassificationItemOutput] = Field(default_factory=list)
    dependencies: list[DependencyRecord] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    scores: ScoreBundle | None = None
    report_draft: SynthesisOutput | None = None
    citation_audit: CitationAuditOutput | None = None
    evidence_reviewed_at: datetime | None = None
    recoverable_errors: list[RecoverableError] = Field(default_factory=list)
    model_calls: dict[str, CallMetadata] = Field(default_factory=dict)
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
    "CalculationRecord",
    "CandidateSource",
    "DependencyRecord",
    "PassageRecord",
    "RecoverableError",
    "ResearchDepth",
    "ScoreBundle",
    "SnapshotRecord",
    "VerificationState",
    "WorkflowStage",
]
