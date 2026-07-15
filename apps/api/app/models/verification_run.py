from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import InputType, ResearchDepth, RunStatus
from app.models.types import JsonObject, utc_now


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (
        CheckConstraint(
            "evidence_support IS NULL OR evidence_support BETWEEN 0 AND 100",
            name="ck_verification_runs_evidence_support",
        ),
        CheckConstraint(
            "verdict_confidence IS NULL OR verdict_confidence BETWEEN 0 AND 100",
            name="ck_verification_runs_verdict_confidence",
        ),
        CheckConstraint(
            "source_independence IS NULL OR source_independence BETWEEN 0 AND 100",
            name="ck_verification_runs_source_independence",
        ),
        CheckConstraint(
            "context_completeness IS NULL OR context_completeness BETWEEN 0 AND 100",
            name="ck_verification_runs_context_completeness",
        ),
        Index("ix_verification_runs_status_queued", "status", "queued_at"),
        Index("ix_verification_runs_visibility", "visibility"),
        Index("ix_verification_runs_owner_saved", "user_id", "saved_at"),
        Index(
            "ix_verification_runs_share_token",
            "share_token_hash",
            postgresql_where="share_token_hash IS NOT NULL",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    input_type: Mapped[InputType] = mapped_column(Enum(InputType, name="input_type"), nullable=False)
    research_depth: Mapped[ResearchDepth] = mapped_column(
        Enum(ResearchDepth, name="research_depth"), nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="run_status"), nullable=False)
    submitted_text: Mapped[str | None] = mapped_column(Text)
    submitted_url: Mapped[str | None] = mapped_column(Text)
    upload_object_path: Mapped[str | None] = mapped_column(Text)
    normalized_target: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False, default=dict)
    title: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[str | None] = mapped_column(String(100))
    evidence_support: Mapped[int | None] = mapped_column(Integer)
    verdict_confidence: Mapped[int | None] = mapped_column(Integer)
    source_independence: Mapped[int | None] = mapped_column(Integer)
    context_completeness: Mapped[int | None] = mapped_column(Integer)
    methodology_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("methodology_versions.id", ondelete="RESTRICT")
    )
    workflow_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False, default=dict)
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False, default=dict)
    parser_versions: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False, default=dict)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(Text)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_status: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    legal_hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_state: Mapped[str] = mapped_column(String(30), nullable=False, default="unreviewed")
    publication_review_reason: Mapped[str | None] = mapped_column(String(255))
    publication_reviewed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    publication_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="private")
    share_token_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    user: Mapped["User"] = relationship(  # noqa: F821
        back_populates="verification_runs",
        foreign_keys=[user_id],
    )
    events: Mapped[list["AgentEvent"]] = relationship(  # noqa: F821
        back_populates="run", cascade="all, delete-orphan", order_by="AgentEvent.sequence"
    )


Index(
    "ix_verification_runs_owner_created",
    VerificationRun.user_id,
    VerificationRun.created_at.desc(),
)
