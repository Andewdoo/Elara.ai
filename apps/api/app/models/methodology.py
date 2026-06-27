from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.types import JsonObject


class MethodologyVersion(Base):
    __tablename__ = "methodology_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    scoring_config: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False)
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(JsonObject, nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


Index(
    "uq_methodology_versions_one_active",
    MethodologyVersion.active,
    unique=True,
    postgresql_where=text("active"),
    sqlite_where=text("active = 1"),
)
