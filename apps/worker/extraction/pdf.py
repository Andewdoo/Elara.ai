from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
from statistics import median

import fitz

from extraction.models import ExtractedDocument


def extract_pdf(content: bytes) -> ExtractedDocument | None:
    if not content.startswith(b"%PDF-"):
        return None
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except (fitz.FileDataError, RuntimeError):
        return None
    try:
        pages: list[str] = []
        positions: list[str] = []
        links: list[str] = []
        headings: list[str] = []
        tables: list[str] = []
        for number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True).strip()
            if text:
                pages.append(text)
                positions.append(f"page {number}")
            page_dict = page.get_text("dict", sort=True)
            spans = [
                span
                for block in page_dict.get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text", "")).strip()
            ]
            sizes = [float(span.get("size", 0)) for span in spans if span.get("size")]
            heading_threshold = max(12.0, (median(sizes) + 1.5) if sizes else 12.0)
            headings.extend(
                str(span["text"]).strip()
                for span in spans
                if float(span.get("size", 0)) >= heading_threshold
            )
            try:
                found_tables = page.find_tables()
                for table in found_tables.tables:
                    rows = table.extract()
                    rendered = "\n".join(
                        " | ".join("" if value is None else str(value).strip() for value in row)
                        for row in rows
                    ).strip()
                    if rendered:
                        tables.append(f"page {number}\n{rendered}")
            except (AttributeError, RuntimeError, ValueError):
                pass
            links.extend(
                str(item["uri"])
                for item in page.get_links()
                if item.get("uri") and str(item["uri"]).startswith(("http://", "https://"))
            )
        body = "\n\n".join(pages)
        if len(body) < 50:
            return None
        metadata = document.metadata or {}
        return ExtractedDocument(
            body=body,
            title=metadata.get("title") or None,
            author=metadata.get("author") or None,
            publisher=None,
            published_at=_pdf_date(metadata.get("creationDate")),
            updated_at=_pdf_date(metadata.get("modDate")),
            headings=tuple(dict.fromkeys(headings)),
            tables=tuple(tables),
            outbound_links=tuple(dict.fromkeys(links)),
            page_positions=tuple(positions),
            parser_name="pymupdf",
            parser_version=version("pymupdf"),
            quality=round(min(1.0, 0.5 + len(body) / 10_000), 4),
            metadata={"page_count": document.page_count, "untrusted_evidence": True},
        )
    finally:
        document.close()


def _pdf_date(value: str | None) -> datetime | None:
    if not value:
        return None
    digits = "".join(character for character in value.removeprefix("D:") if character.isdigit())
    if len(digits) < 4:
        return None
    try:
        padded = (digits + "0101000000")[:14]
        return datetime.strptime(padded, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


__all__ = ["extract_pdf"]
