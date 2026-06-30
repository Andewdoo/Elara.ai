from __future__ import annotations

import re
from datetime import UTC, datetime
from importlib.metadata import version
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup, Comment

from extraction.models import ExtractedBlock, ExtractedDocument


_SPACE = re.compile(r"[ \t\r\f\v]+")
_SPEAKER = re.compile(r"^(?P<speaker>[A-Z][\w .'-]{0,79}):\s+(?P<text>.+)$")
_BARRIER_TERMS = ("enable javascript", "access denied", "verify you are human", "subscribe to continue")


def extract_with_trafilatura(content: bytes, *, url: str) -> ExtractedDocument | None:
    text = trafilatura.extract(
        content,
        url=url,
        include_comments=False,
        include_links=False,
        include_tables=True,
        favor_precision=True,
    )
    if not text or not _acceptable(text):
        return None
    metadata = trafilatura.extract_metadata(content, default_url=url)
    return ExtractedDocument(
        body=_normalize(text),
        title=getattr(metadata, "title", None),
        author=getattr(metadata, "author", None),
        publisher=getattr(metadata, "sitename", None),
        published_at=_parse_date(getattr(metadata, "date", None)),
        updated_at=None,
        parser_name="trafilatura",
        parser_version=version("trafilatura"),
        quality=_quality(text),
        metadata={"untrusted_evidence": True},
    )


def extract_with_beautiful_soup(content: bytes, *, url: str) -> ExtractedDocument | None:
    soup = BeautifulSoup(content, "html.parser")
    hidden_count = len(soup.select("[hidden], [aria-hidden='true'], [style*='display:none'], [style*='display: none']"))
    for item in soup(["script", "style", "nav", "footer", "aside", "form", "noscript", "svg"]):
        item.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    root = soup.find("article") or soup.find("main") or soup.body
    if root is None:
        return None
    blocks = [
        _normalize(item.get_text(" ", strip=True))
        for item in root.find_all(["h1", "h2", "h3", "p", "li", "blockquote", "pre"])
    ]
    text = "\n\n".join(dict.fromkeys(block for block in blocks if block))
    if not _acceptable(text):
        return None
    headings = tuple(
        _normalize(item.get_text(" ", strip=True)) for item in root.find_all(["h1", "h2", "h3"])
    )
    tables = tuple(_table_text(table) for table in root.find_all("table"))
    links = tuple(
        dict.fromkeys(
            urljoin(url, str(anchor["href"]))
            for anchor in root.find_all("a", href=True)
            if not str(anchor["href"]).startswith(("#", "javascript:", "mailto:"))
        )
    )
    title = _meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else None)
    author = _meta(soup, "author")
    publisher = _meta(soup, "og:site_name")
    quotes = tuple(_normalize(item.get_text(" ", strip=True)) for item in root.find_all("blockquote"))
    corrections = tuple(
        block for block in blocks if any(term in block.casefold() for term in ("correction", "retraction", "editor's note"))
    )
    structured_blocks = _structured_blocks(root)
    return ExtractedDocument(
        body=text,
        title=title,
        author=author,
        publisher=publisher,
        published_at=_parse_date(_meta(soup, "article:published_time")),
        updated_at=_parse_date(_meta(soup, "article:modified_time")),
        headings=headings,
        tables=tuple(value for value in tables if value),
        quotes=quotes,
        correction_notices=corrections,
        outbound_links=links,
        blocks=structured_blocks,
        parser_name="beautifulsoup4",
        parser_version=version("beautifulsoup4"),
        quality=_quality(text),
        metadata={
            "untrusted_evidence": True,
            "hidden_element_count": hidden_count,
            "malformed_table_count": sum(not _table_is_rectangular(table) for table in root.find_all("table")),
        },
    )


def _acceptable(text: str) -> bool:
    normalized = _normalize(text)
    return len(normalized) >= 200 and not any(term in normalized[:1000].casefold() for term in _BARRIER_TERMS)


def _quality(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    unique_ratio = len(set(lines)) / len(lines)
    length_score = min(len(text) / 2_000, 1.0)
    return round(max(0.0, min(1.0, 0.65 * length_score + 0.35 * unique_ratio)), 4)


def _normalize(value: str) -> str:
    return "\n".join(_SPACE.sub(" ", line).strip() for line in value.splitlines() if line.strip())


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return str(node.get("content")) if node and node.get("content") else None


def _table_text(table) -> str:
    rows = []
    for row in table.find_all("tr"):
        values = [_normalize(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        if values:
            rows.append(" | ".join(values))
    return "\n".join(rows)


def _table_is_rectangular(table) -> bool:
    widths = [len(row.find_all(["th", "td"])) for row in table.find_all("tr")]
    widths = [width for width in widths if width]
    return not widths or len(set(widths)) == 1


def _structured_blocks(root) -> tuple[ExtractedBlock, ...]:
    heading_stack: list[str] = []
    paragraph_index = 0
    table_index = 0
    result: list[ExtractedBlock] = []
    selected = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "table"]
    for node in root.find_all(selected):
        if node.name != "table" and node.find_parent("table") is not None:
            continue
        if node.find_parent(selected) is not None:
            continue
        if node.name and node.name.startswith("h"):
            text = _normalize(node.get_text(" ", strip=True))
            if not text:
                continue
            level = int(node.name[1])
            heading_stack = heading_stack[: level - 1]
            while len(heading_stack) < level - 1:
                heading_stack.append("")
            heading_stack.append(text)
            result.append(
                ExtractedBlock(
                    kind="heading",
                    text=text,
                    heading_path=tuple(value for value in heading_stack if value),
                    page_or_position=f"heading {len(result) + 1}",
                )
            )
            continue
        if node.name == "table":
            table_index += 1
            rows = node.find_all("tr")
            header_cells = rows[0].find_all(["th", "td"]) if rows else []
            headers = [_normalize(cell.get_text(" ", strip=True)) for cell in header_cells]
            for row_index, row in enumerate(rows, start=1):
                values = [_normalize(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
                if not any(values):
                    continue
                if row_index > 1 and headers and len(headers) == len(values):
                    text = " | ".join(
                        f"{header}: {value}" if header else value
                        for header, value in zip(headers, values, strict=True)
                    )
                else:
                    text = " | ".join(values)
                result.append(
                    ExtractedBlock(
                        kind="table_row",
                        text=text,
                        heading_path=tuple(value for value in heading_stack if value),
                        page_or_position=f"table {table_index}, row {row_index}",
                        table_ref=f"table {table_index} row {row_index}",
                        metadata={"column_labels": headers},
                    )
                )
            continue
        text = _normalize(node.get_text(" ", strip=True))
        if not text:
            continue
        paragraph_index += 1
        speaker_match = _SPEAKER.match(text)
        result.append(
            ExtractedBlock(
                kind="transcript_turn" if speaker_match else ("quote" if node.name == "blockquote" else "paragraph"),
                text=text,
                heading_path=tuple(value for value in heading_stack if value),
                page_or_position=f"paragraph {paragraph_index}",
                paragraph_index=paragraph_index,
                speaker=speaker_match.group("speaker") if speaker_match else None,
                metadata=(
                    {"quote_citation": str(node.get("cite"))}
                    if node.name == "blockquote" and node.get("cite")
                    else {}
                ),
            )
        )
    return tuple(result)


def _parse_date(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


__all__ = ["extract_with_beautiful_soup", "extract_with_trafilatura"]
