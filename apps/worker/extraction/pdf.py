from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
import re
from statistics import median

import fitz

from extraction.models import ExtractedBlock, ExtractedDocument


_SPEAKER = re.compile(r"^(?P<speaker>[A-Z][\w .'-]{0,79}):\s+(?P<text>.+)$")


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
        blocks: list[ExtractedBlock] = []
        heading_path: list[str] = []
        paragraph_index = 0
        table_index = 0
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
            page_headings = {
                str(span["text"]).strip()
                for span in spans
                if float(span.get("size", 0)) >= heading_threshold
            }
            headings.extend(page_headings)
            for raw_block in page.get_text("blocks", sort=True):
                block_text = "\n".join(
                    line.strip() for line in str(raw_block[4]).splitlines() if line.strip()
                )
                if not block_text:
                    continue
                if block_text in page_headings:
                    heading_path = [block_text]
                    blocks.append(
                        ExtractedBlock(
                            kind="heading",
                            text=block_text,
                            heading_path=tuple(heading_path),
                            page_or_position=f"page {number}",
                        )
                    )
                    continue
                paragraph_index += 1
                speaker_match = _SPEAKER.match(block_text)
                blocks.append(
                    ExtractedBlock(
                        kind="transcript_turn" if speaker_match else "paragraph",
                        text=block_text,
                        heading_path=tuple(heading_path),
                        page_or_position=f"page {number}",
                        paragraph_index=paragraph_index,
                        speaker=speaker_match.group("speaker") if speaker_match else None,
                    )
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
                    table_index += 1
                    headers = ["" if value is None else str(value).strip() for value in rows[0]] if rows else []
                    for row_index, row in enumerate(rows, start=1):
                        values = ["" if value is None else str(value).strip() for value in row]
                        if not any(values):
                            continue
                        if row_index > 1 and headers and len(headers) == len(values):
                            row_text = " | ".join(
                                f"{header}: {value}" if header else value
                                for header, value in zip(headers, values, strict=True)
                            )
                        else:
                            row_text = " | ".join(values)
                        blocks.append(
                            ExtractedBlock(
                                kind="table_row",
                                text=row_text,
                                heading_path=tuple(heading_path),
                                page_or_position=f"page {number}, table {table_index}, row {row_index}",
                                table_ref=f"page {number} table {table_index} row {row_index}",
                                metadata={"column_labels": headers},
                            )
                        )
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
            blocks=tuple(blocks),
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
