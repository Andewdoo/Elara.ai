from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import EvidenceStance
from app.models.types import enum_column, utc_now


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        CheckConstraint("stance_value BETWEEN -1 AND 1", name="ck_evidence_items_stance_value"),
        CheckConstraint("relevance BETWEEN 0 AND 1", name="ck_evidence_items_relevance"),
        CheckConstraint("directness BETWEEN 0 AND 1", name="ck_evidence_items_directness"),
        CheckConstraint("authority BETWEEN 0 AND 1", name="ck_evidence_items_authority"),
        CheckConstraint("transparency BETWEEN 0 AND 1", name="ck_evidence_items_transparency"),
        CheckConstraint("temporal_fit BETWEEN 0 AND 1", name="ck_evidence_items_temporal_fit"),
        CheckConstraint(
            "extraction_certainty BETWEEN 0 AND 1", name="ck_evidence_items_extraction_certainty"
        ),
        CheckConstraint("base_quality BETWEEN 0 AND 1", name="ck_evidence_items_base_quality"),
        CheckConstraint(
            "dependency_multiplier BETWEEN 0 AND 1", name="ck_evidence_items_dependency_multiplier"
        ),
        CheckConstraint("adjusted_weight BETWEEN 0 AND 1", name="ck_evidence_items_adjusted_weight"),
        Index("ix_evidence_items_claim", "atomic_claim_id"),
        Index("ix_evidence_items_passage", "passage_id"),
        Index("ix_evidence_items_stance", "stance"),
        UniqueConstraint("atomic_claim_id", "passage_id", name="uq_evidence_items_claim_passage"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    atomic_claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("atomic_claims.id", ondelete="CASCADE"), nullable=False
    )
    passage_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_passages.id", ondelete="CASCADE"), nullable=False
    )
    stance: Mapped[EvidenceStance] = mapped_column(
        enum_column(EvidenceStance, "evidence_stance"), nullable=False
    )
    stance_value: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    relevance: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    directness: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    authority: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    transparency: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    temporal_fit: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    extraction_certainty: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    base_quality: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    dependency_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    adjusted_weight: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    citation_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ReportCitation(Base):
    __tablename__ = "report_citations"
    __table_args__ = (
        Index("ix_report_citations_run_section", "run_id", "report_section"),
        Index("ix_report_citations_passage", "passage_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    atomic_claim_id: Mapped[UUID | None] = mapped_column(ForeignKey("atomic_claims.id"))
    report_section: Mapped[str] = mapped_column(String(100), nullable=False)
    sentence_text: Mapped[str] = mapped_column(Text, nullable=False)
    passage_id: Mapped[UUID] = mapped_column(ForeignKey("source_passages.id"), nullable=False)
    audit_status: Mapped[str] = mapped_column(String(50), nullable=False)
    audit_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
