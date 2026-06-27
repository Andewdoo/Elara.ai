from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.constants import PASSAGE_EMBEDDING_DIMENSION
from app.models.enums import AccessStatus, SourceType
from app.models.types import JsonObject, enum_column, utc_now


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_domain", "domain"),
        Index("ix_sources_source_type", "source_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(
        enum_column(SourceType, "source_type"), nullable=False, default=SourceType.UNKNOWN
    )
    content_type: Mapped[str | None] = mapped_column(String(255))
    robots_or_policy_status: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_source_snapshots_version_positive"),
        CheckConstraint(
            "extraction_quality IS NULL OR extraction_quality BETWEEN 0 AND 1",
            name="ck_source_snapshots_extraction_quality",
        ),
        UniqueConstraint("id", "source_id", name="uq_source_snapshots_id_source"),
        UniqueConstraint("source_id", "version_number", name="uq_source_snapshots_source_version"),
        Index("ix_source_snapshots_content_hash", "content_hash"),
        Index("ix_source_snapshots_access_status", "access_status"),
        Index("ix_source_snapshots_source_content_hash", "source_id", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_status: Mapped[AccessStatus] = mapped_column(
        enum_column(AccessStatus, "access_status"), nullable=False
    )
    content_hash: Mapped[str | None] = mapped_column(String(128))
    snapshot_path: Mapped[str | None] = mapped_column(Text)
    parser_name: Mapped[str | None] = mapped_column(String(100))
    parser_version: Mapped[str | None] = mapped_column(String(100))
    extraction_quality: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    correction_status: Mapped[str | None] = mapped_column(String(100))
    snapshot_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JsonObject, nullable=False, default=dict
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


Index("ix_source_snapshots_source_retrieved", SourceSnapshot.source_id, SourceSnapshot.retrieved_at.desc())


class RunSource(Base):
    __tablename__ = "run_sources"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "source_id", name="pk_run_sources"),
        ForeignKeyConstraint(
            ["snapshot_id", "source_id"],
            ["source_snapshots.id", "source_snapshots.source_id"],
            name="fk_run_sources_snapshot_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint("priority_score IS NULL OR priority_score BETWEEN 0 AND 1", name="ck_run_sources_priority"),
        Index("ix_run_sources_snapshot", "snapshot_id"),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("verification_runs.id", ondelete="CASCADE"))
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    snapshot_id: Mapped[UUID | None] = mapped_column()
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    retrieval_reason: Mapped[str | None] = mapped_column(Text)
    priority_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    selected_rank: Mapped[int | None] = mapped_column(Integer)
    inaccessible_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SourcePassage(Base):
    __tablename__ = "source_passages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "source_id"],
            ["source_snapshots.id", "source_snapshots.source_id"],
            name="fk_source_passages_snapshot_source",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "extraction_certainty BETWEEN 0 AND 1", name="ck_source_passages_extraction_certainty"
        ),
        Index("ix_source_passages_source", "source_id"),
        Index("ix_source_passages_snapshot", "snapshot_id"),
        Index("ix_source_passages_text_hash", "text_hash"),
        UniqueConstraint("snapshot_id", "text_hash", name="uq_source_passages_snapshot_text_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(nullable=False)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    heading_path: Mapped[str | None] = mapped_column(Text)
    page_or_position: Mapped[str | None] = mapped_column(String(255))
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(Text)
    table_ref: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(PASSAGE_EMBEDDING_DIMENSION).with_variant(JSON(), "sqlite")
    )
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    extraction_certainty: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    passage_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JsonObject, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
