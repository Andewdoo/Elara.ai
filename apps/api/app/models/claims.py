from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.types import JsonObject, utc_now


class AtomicClaim(Base):
    __tablename__ = "atomic_claims"
    __table_args__ = (
        CheckConstraint("importance_weight BETWEEN 1 AND 3", name="ck_atomic_claim_importance"),
        CheckConstraint(
            "support_score IS NULL OR support_score BETWEEN 0 AND 100",
            name="ck_atomic_claim_support_score",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR confidence_score BETWEEN 0 AND 100",
            name="ck_atomic_claim_confidence_score",
        ),
        CheckConstraint(
            "context_completeness IS NULL OR context_completeness BETWEEN 0 AND 100",
            name="ck_atomic_claim_context_completeness",
        ),
        Index("ix_atomic_claims_entities_gin", "entities", postgresql_using="gin"),
        Index("ix_atomic_claims_metrics_gin", "metrics", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    parent_claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("atomic_claims.id", ondelete="SET NULL")
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_claim: Mapped[str | None] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(100), nullable=False)
    importance_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    entities: Mapped[list[Any]] = mapped_column(JsonObject, nullable=False, default=list)
    time_period: Mapped[str | None] = mapped_column(Text)
    locations: Mapped[list[Any]] = mapped_column(JsonObject, nullable=False, default=list)
    metrics: Mapped[list[Any]] = mapped_column(JsonObject, nullable=False, default=list)
    comparison: Mapped[str | None] = mapped_column(Text)
    ambiguities: Mapped[list[Any]] = mapped_column(JsonObject, nullable=False, default=list)
    fact_checkable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    support_score: Mapped[int | None] = mapped_column(Integer)
    confidence_score: Mapped[int | None] = mapped_column(Integer)
    context_completeness: Mapped[int | None] = mapped_column(Integer)
    final_label: Mapped[str | None] = mapped_column(String(100))
    gates: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


Index("ix_atomic_claims_run_importance", AtomicClaim.run_id, AtomicClaim.importance_weight.desc())


class SearchQuery(Base):
    __tablename__ = "search_queries"
    __table_args__ = (
        CheckConstraint("priority IS NULL OR priority BETWEEN 0 AND 1", name="ck_search_queries_priority"),
        CheckConstraint(
            "discovery_phase IN ('authority_preflight', 'phase_one', 'phase_two')",
            name="ck_search_queries_discovery_phase",
        ),
        CheckConstraint(
            "execution_status IN ('planned', 'executed', 'cache_hit', 'not_needed')",
            name="ck_search_queries_execution_status",
        ),
        CheckConstraint(
            "network_attempt_count >= 0",
            name="ck_search_queries_network_attempt_count",
        ),
        Index("ix_search_queries_run_family", "run_id", "family"),
        Index("ix_search_queries_claim_family", "atomic_claim_id", "family"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False
    )
    atomic_claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("atomic_claims.id", ondelete="CASCADE")
    )
    family: Mapped[str] = mapped_column(String(100), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by_node: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    discovery_phase: Mapped[str] = mapped_column(String(20), nullable=False, default="phase_one")
    execution_status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    network_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skip_reason: Mapped[str | None] = mapped_column(String(100))
    policy_version: Mapped[str] = mapped_column(
        String(100), nullable=False, default="adaptive-search-v1"
    )
    authority_profile_version: Mapped[str | None] = mapped_column(String(100))
    authority_registry_version: Mapped[str | None] = mapped_column(String(100))
    source_role: Mapped[str | None] = mapped_column(String(100))
    domain_restriction: Mapped[str | None] = mapped_column(String(255))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
