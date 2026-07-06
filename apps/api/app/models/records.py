from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.types import JsonObject, utc_now


class Calculation(Base):
    __tablename__ = "calculations"
    __table_args__ = (
        Index("ix_calculations_run_formula", "run_id", "formula_name"),
        Index("ix_calculations_claim", "atomic_claim_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    atomic_claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("atomic_claims.id", ondelete="CASCADE")
    )
    formula_name: Mapped[str] = mapped_column(String(100), nullable=False)
    formula_text: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False)
    units: Mapped[str | None] = mapped_column(String(100))
    decimal_context: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False)
    audit_status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    __table_args__ = (
        CheckConstraint(
            "category IN ('CORRECTION', 'MISSED_EVIDENCE', 'APPEAL', 'BROKEN_CITATION')",
            name="ck_user_feedback_category",
        ),
        Index("ix_user_feedback_status", "status"),
        Index("ix_user_feedback_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


Index("ix_user_feedback_run_created", UserFeedback.run_id, UserFeedback.created_at.desc())


class Export(Base):
    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint("export_type IN ('JSON')", name="ck_exports_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    export_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


Index("ix_exports_run_type_created", Export.run_id, Export.export_type, Export.created_at.desc())


class ReportShare(Base):
    __tablename__ = "report_shares"
    __table_args__ = (
        UniqueConstraint("run_id", "recipient_user_id", name="uq_report_shares_recipient"),
        CheckConstraint("scope IN ('report', 'report_sources', 'report_sources_exports')", name="ck_report_shares_scope"),
        Index("ix_report_shares_recipient_active", "recipient_user_id", "revoked_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False)
    recipient_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class GovernanceDecision(Base):
    __tablename__ = "governance_decisions"
    __table_args__ = (Index("ix_governance_decisions_feedback_created", "feedback_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    feedback_id: Mapped[UUID] = mapped_column(ForeignKey("user_feedback.id", ondelete="RESTRICT"), nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    prior_status: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    revised_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("verification_runs.id", ondelete="RESTRICT"))
    public_notice_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
