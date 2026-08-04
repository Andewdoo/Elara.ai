import ipaddress
from datetime import datetime
from typing import Any, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator
from app.models.enums import EvidenceStance, ExportFormat, FeedbackCategory, InputType, ResearchDepth, RunStatus


class VerificationCreateRequest(BaseModel):
    input_type: InputType
    research_depth: ResearchDepth = ResearchDepth.STANDARD
    text: str | None = Field(default=None, max_length=50_000)
    article_title: str | None = Field(default=None, max_length=500)
    url: AnyHttpUrl | None = None
    quote: str | None = Field(default=None, max_length=10_000)
    speaker: str | None = Field(default=None, max_length=500)
    upload_id: UUID | None = None

    @field_validator("text", "article_title", "quote", "speaker", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_input_payload(self) -> Self:
        text_types = {InputType.CLAIM, InputType.ARTICLE_TEXT, InputType.PARAPHRASE}
        if self.input_type == InputType.ARTICLE_URL:
            raise ValueError("Article URL submissions are no longer supported; submit the article title instead")
        if self.input_type in text_types and not self.text:
            raise ValueError("text is required for this input type")
        if self.input_type == InputType.ARTICLE_TITLE and not self.article_title:
            raise ValueError("article_title is required for ARTICLE_TITLE")
        if self.input_type == InputType.QUOTE and not self.quote:
            raise ValueError("quote is required for QUOTE")
        if self.input_type == InputType.UPLOADED_DOCUMENT and not self.upload_id:
            raise ValueError("upload_id is required for UPLOADED_DOCUMENT")
        expected_field = {
            InputType.CLAIM: "text",
            InputType.ARTICLE_URL: "url",
            InputType.ARTICLE_TITLE: "article_title",
            InputType.ARTICLE_TEXT: "text",
            InputType.QUOTE: "quote",
            InputType.PARAPHRASE: "text",
            InputType.UPLOADED_DOCUMENT: "upload_id",
        }[self.input_type]
        supplied_targets = {
            name
            for name, value in {
                "text": self.text,
                "article_title": self.article_title,
                "url": self.url,
                "quote": self.quote,
                "upload_id": self.upload_id,
            }.items()
            if value is not None
        }
        if supplied_targets != {expected_field}:
            raise ValueError("provide only the payload field matching input_type")
        if self.url:
            parsed = urlsplit(str(self.url))
            if parsed.username or parsed.password:
                raise ValueError("URL credentials are not allowed")
            hostname = parsed.hostname
            if hostname == "localhost" or (hostname and hostname.endswith(".localhost")):
                raise ValueError("local URLs are not allowed")
            if hostname:
                try:
                    address = ipaddress.ip_address(hostname)
                except ValueError:
                    if "." not in hostname:
                        raise ValueError("single-label hostnames are not allowed")
                else:
                    if not address.is_global:
                        raise ValueError("non-public IP addresses are not allowed")
            if parsed.port not in {None, 80, 443}:
                raise ValueError("URL port is not allowed")
        return self


class VerificationCreateResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    events_url: str
    report_url: str | None = None


class UploadResponse(BaseModel):
    upload_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    content_hash: str


class VerificationCancelResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    cancellation_requested_at: datetime | None


class VerificationRunResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    input_type: InputType
    research_depth: ResearchDepth
    title: str | None
    verdict: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    cancellation_requested_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    updated_at: datetime
    saved_at: datetime | None
    is_owner: bool
    publication_state: str
    publication_review_reason: str | None


class HistoryItemResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    input_type: InputType
    research_depth: ResearchDepth
    title: str | None
    submitted_text_preview: str | None
    verdict: str | None
    verdict_confidence: int | None
    evidence_reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    saved_at: datetime | None


class HistoryResponse(BaseModel):
    items: list[HistoryItemResponse]
    total: int
    page: int
    page_size: int


class SavedReportResponse(BaseModel):
    run_id: UUID
    saved_at: datetime | None


class FeedbackCreateRequest(BaseModel):
    category: FeedbackCategory
    message: str = Field(min_length=3, max_length=10_000)
    source_url: AnyHttpUrl | None = None

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return value.strip()


class FeedbackResponse(BaseModel):
    feedback_id: UUID
    run_id: UUID
    category: FeedbackCategory
    message: str
    source_url: str | None
    status: str
    created_at: datetime


class FeedbackListResponse(BaseModel):
    items: list[FeedbackResponse]


class ExportCreateRequest(BaseModel):
    format: ExportFormat = ExportFormat.JSON


class ExportResponse(BaseModel):
    export_id: UUID
    run_id: UUID
    format: ExportFormat
    content_hash: str
    created_at: datetime
    download_url: str | None = None
    expires_at: datetime | None = None


class ExportListResponse(BaseModel):
    items: list[ExportResponse]


class DeleteReportResponse(BaseModel):
    run_id: UUID
    deleted: bool


class ShareCreateRequest(BaseModel):
    recipient_user_id: UUID
    scope: Literal["report", "report_sources", "report_sources_exports"] = "report"
    expires_in_hours: int = Field(default=24, ge=1, le=168)


class ShareResponse(BaseModel):
    share_id: UUID
    run_id: UUID
    recipient_user_id: UUID
    scope: str
    expires_at: datetime
    revoked_at: datetime | None


class PublicationReviewRequest(BaseModel):
    decision: Literal["approved", "rejected", "revision_required"]
    rationale: str = Field(min_length=3, max_length=2_000)


class FeedbackDecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected", "needs_information", "escalated"]
    rationale: str = Field(min_length=3, max_length=2_000)
    revised_run_id: UUID | None = None


class GovernanceDecisionResponse(BaseModel):
    decision_id: UUID
    decision: str
    created_at: datetime


class ProgressEvent(BaseModel):
    run_id: UUID
    stage: RunStatus
    message: str
    event_type: str
    completed_steps: int
    total_steps: int
    source_counts: dict[str, int] = Field(default_factory=dict)
    inaccessible_count: int = 0
    created_at: datetime


class ScoreBundle(BaseModel):
    evidence_support: int | None = None
    attribution_support: int | None = None
    quote_fidelity: int | None = None
    verdict_confidence: int | None = None
    source_independence: int | None = None
    context_completeness: int | None = None


class AtomicClaimResponse(BaseModel):
    id: UUID
    claim_text: str
    importance_weight: int
    claim_type: str
    final_label: str | None
    support_score: int | None
    confidence_score: int | None
    context_completeness: int | None
    ambiguities: list[str]
    gaps: list[str]


class EvidenceItemResponse(BaseModel):
    id: UUID
    atomic_claim_id: UUID
    passage_id: UUID
    stance: EvidenceStance
    base_quality: float
    dependency_multiplier: float
    adjusted_weight: float
    citation_status: str
    passage_text: str
    source_title: str | None
    source_url: str
    page_or_position: str | None


class ReportCitationResponse(BaseModel):
    id: UUID
    report_section: str
    sentence_text: str
    passage_id: UUID
    audit_status: str
    audit_note: str | None


class SourcePassageResponse(BaseModel):
    id: UUID
    text: str
    heading_path: str | None
    page_or_position: str | None
    paragraph_index: int | None
    speaker: str | None
    table_ref: str | None
    extraction_certainty: float
    metadata: dict[str, Any]
    citations: list[ReportCitationResponse]


class SourceResponse(BaseModel):
    id: UUID
    canonical_url: str
    domain: str
    title: str | None
    author: str | None
    publisher: str | None
    source_type: str
    content_type: str | None
    role: str
    retrieval_reason: str | None
    inaccessible_reason: str | None
    snapshot_id: UUID | None
    snapshot_version: int | None
    access_status: str
    retrieved_at: datetime | None
    published_at: datetime | None
    content_hash: str | None
    parser_name: str | None
    parser_version: str | None
    correction_status: str | None
    correction_history: list[dict[str, Any]]
    snapshot_metadata: dict[str, Any]
    failure_reason: str | None
    passages: list[SourcePassageResponse]


class SourcesResponse(BaseModel):
    sources: list[SourceResponse]


class SourceGraphNode(BaseModel):
    id: str
    type: str
    label: str
    data: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    relationship: str
    confidence: float
    data: dict[str, Any] = Field(default_factory=dict)


class SourceGraphResponse(BaseModel):
    nodes: list[SourceGraphNode]
    edges: list[SourceGraphEdge]


class CalculationResponse(BaseModel):
    id: UUID
    atomic_claim_id: UUID | None
    formula_name: str
    formula_text: str
    inputs: dict[str, Any]
    result: dict[str, Any]
    units: str | None
    decimal_context: dict[str, Any]
    audit_status: str


class ReportResponse(BaseModel):
    run_id: UUID
    verdict: str | None
    scores: ScoreBundle
    atomic_claims: list[AtomicClaimResponse]
    evidence: list[EvidenceItemResponse]
    source_graph: SourceGraphResponse
    calculations: list[CalculationResponse]
    methodology_version: str
    workflow_version: str
    model_versions: dict[str, Any]
    prompt_versions: dict[str, Any]
    parser_versions: dict[str, Any]
    retrieval_versions: dict[str, Any]
    score_roles: dict[str, str]
    report_sentences: list[ReportCitationResponse]
    evidence_reviewed_at: datetime
    generated_at: datetime
    limitations: list[str]
