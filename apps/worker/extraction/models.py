from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    """A source-native unit retained for traceable passage segmentation."""

    kind: str
    text: str
    heading_path: tuple[str, ...] = ()
    page_or_position: str | None = None
    paragraph_index: int | None = None
    speaker: str | None = None
    table_ref: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


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
    blocks: tuple[ExtractedBlock, ...] = ()
    parser_name: str = "unknown"
    parser_version: str = "unknown"
    quality: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


__all__ = ["ExtractedBlock", "ExtractedDocument"]
