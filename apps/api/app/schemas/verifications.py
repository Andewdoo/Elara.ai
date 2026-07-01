import ipaddress
from datetime import datetime
from typing import Any, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator
from app.models.enums import InputType, ResearchDepth, RunStatus


class VerificationCreateRequest(BaseModel):
    input_type: InputType
    research_depth: ResearchDepth = ResearchDepth.STANDARD
    text: str | None = Field(default=None, max_length=50_000)
    url: AnyHttpUrl | None = None
    quote: str | None = Field(default=None, max_length=10_000)
    speaker: str | None = Field(default=None, max_length=500)
    upload_id: UUID | None = None

    @field_validator("text", "quote", "speaker", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_input_payload(self) -> Self:
        text_types = {InputType.CLAIM, InputType.ARTICLE_TEXT, InputType.PARAPHRASE}
        if self.input_type in text_types and not self.text:
            raise ValueError("text is required for this input type")
        if self.input_type == InputType.ARTICLE_URL and not self.url:
            raise ValueError("url is required for ARTICLE_URL")
        if self.input_type == InputType.QUOTE and not self.quote:
            raise ValueError("quote is required for QUOTE")
        if self.input_type == InputType.UPLOADED_DOCUMENT and not self.upload_id:
            raise ValueError("upload_id is required for UPLOADED_DOCUMENT")
        expected_field = {
            InputType.CLAIM: "text",
            InputType.ARTICLE_URL: "url",
            InputType.ARTICLE_TEXT: "text",
            InputType.QUOTE: "quote",
            InputType.PARAPHRASE: "text",
            InputType.UPLOADED_DOCUMENT: "upload_id",
        }[self.input_type]
        supplied_targets = {
            name
            for name, value in {
                "text": self.text,
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


class ProgressEvent(BaseModel):
    run_id: UUID
    stage: RunStatus
    message: str
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
    stance: str
    base_quality: float
    dependency_multiplier: float
    adjusted_weight: float
    citation_status: str
    passage_text: str
    source_title: str | None
    source_url: str
    page_or_position: str | None


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
    evidence_reviewed_at: datetime
    limitations: list[str]
