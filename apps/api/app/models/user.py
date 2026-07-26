from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.types import CaseInsensitiveText, JsonObject, utc_now


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_provider", "auth_subject", name="uq_users_auth_identity"),
        Index("ix_users_active", "id", postgresql_where="deleted_at IS NULL"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(CaseInsensitiveText, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    plan_tier: Mapped[str] = mapped_column(String(50), nullable=False, default="free")
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    usage_limits: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    verification_runs: Mapped[list["VerificationRun"]] = relationship(  # noqa: F821
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="VerificationRun.user_id",
    )
