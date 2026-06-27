from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import DependencyRelationship
from app.models.types import enum_column, utc_now


class InformationCluster(Base):
    __tablename__ = "information_clusters"
    __table_args__ = (Index("ix_information_clusters_run", "run_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    origin_type: Mapped[str | None] = mapped_column(String(100))
    representative_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SourceDependency(Base):
    __tablename__ = "source_dependencies"
    __table_args__ = (
        CheckConstraint("parent_source_id <> child_source_id", name="ck_source_dependencies_not_self"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_source_dependencies_confidence"),
        Index("ix_source_dependencies_run", "run_id"),
        Index("ix_source_dependencies_parent", "parent_source_id"),
        Index("ix_source_dependencies_child", "child_source_id"),
        Index("ix_source_dependencies_run_relationship", "run_id", "relationship"),
        UniqueConstraint(
            "run_id",
            "parent_source_id",
            "child_source_id",
            "relationship",
            name="uq_source_dependencies_edge",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    parent_source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    child_source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    relationship: Mapped[DependencyRelationship] = mapped_column(
        enum_column(DependencyRelationship, "dependency_relationship"), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    detection_method: Mapped[str] = mapped_column(String(100), nullable=False)
    information_cluster_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("information_clusters.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
