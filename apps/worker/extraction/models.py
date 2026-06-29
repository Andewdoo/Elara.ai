from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    body: str
    title: str | None
    author: str | None
    publisher: str | None
    published_at: datetime | None
    updated_at: datetime | None
    headings: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()
    quotes: tuple[str, ...] = ()
    correction_notices: tuple[str, ...] = ()
    outbound_links: tuple[str, ...] = ()
    page_positions: tuple[str, ...] = ()
    parser_name: str = "unknown"
    parser_version: str = "unknown"
    quality: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


__all__ = ["ExtractedDocument"]
