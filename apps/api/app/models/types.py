from datetime import datetime, timezone

from sqlalchemy import JSON, Enum, String
from sqlalchemy.dialects.postgresql import CITEXT, JSONB

JsonObject = JSON().with_variant(JSONB(), "postgresql")
CaseInsensitiveText = String().with_variant(CITEXT(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enum_column(enum_class: type, name: str) -> Enum:
    return Enum(enum_class, name=name, validate_strings=True)
