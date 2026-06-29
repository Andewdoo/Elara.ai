from __future__ import annotations

from dataclasses import replace

from extraction.html import extract_with_beautiful_soup, extract_with_trafilatura
from extraction.models import ExtractedDocument
from extraction.pdf import extract_pdf
from extraction.playwright import extract_with_playwright_placeholder


class ExtractionService:
    async def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        url: str,
        expected_terms: tuple[str, ...] = (),
    ) -> ExtractedDocument | None:
        # PDFs are routed to the page-aware parser after signature/type validation.
        if content_type == "application/pdf":
            result = extract_pdf(content)
            return _assess(result, expected_terms) if result is not None else None
        result = extract_with_trafilatura(content, url=url)
        if result is not None:
            structure = extract_with_beautiful_soup(content, url=url)
            if structure is not None:
                result = replace(
                    result,
                    title=result.title or structure.title,
                    author=result.author or structure.author,
                    publisher=result.publisher or structure.publisher,
                    published_at=result.published_at or structure.published_at,
                    updated_at=result.updated_at or structure.updated_at,
                    headings=structure.headings,
                    tables=structure.tables,
                    quotes=structure.quotes,
                    correction_notices=structure.correction_notices,
                    outbound_links=structure.outbound_links,
                    metadata={**structure.metadata, **result.metadata, "structure_parser": "beautifulsoup4"},
                )
            return _assess(result, expected_terms)
        result = extract_with_beautiful_soup(content, url=url)
        if result is not None:
            return _assess(result, expected_terms)
        result = await extract_with_playwright_placeholder(url=url)
        if result is not None:
            return _assess(result, expected_terms)
        return None


def _assess(document: ExtractedDocument, expected_terms: tuple[str, ...]) -> ExtractedDocument:
    body_terms = _terms(document.body)
    title_terms = _terms(document.title or "")
    wanted = set().union(*(_terms(value) for value in expected_terms)) if expected_terms else set()
    lines = [line.strip() for line in document.body.splitlines() if line.strip()]
    duplicate_ratio = 1 - (len(set(lines)) / len(lines)) if lines else 1.0
    checks = {
        "minimum_readable_text": len(document.body) >= 200,
        "title_body_consistent": not title_terms or bool(title_terms & body_terms),
        "duplicate_line_ratio": round(duplicate_ratio, 4),
        "expected_term_overlap": round(len(wanted & body_terms) / len(wanted), 4) if wanted else None,
        "truncation_detected": document.body.rstrip().endswith(("...", "…")),
        "hidden_element_count": int(document.metadata.get("hidden_element_count", 0)),
        "malformed_table_count": int(document.metadata.get("malformed_table_count", 0)),
    }
    expected_fit = checks["expected_term_overlap"]
    check_score = sum(
        (
            float(checks["minimum_readable_text"]),
            float(checks["title_body_consistent"]),
            float(duplicate_ratio <= 0.35),
            float(not checks["truncation_detected"]),
            float(checks["malformed_table_count"] == 0),
            float(expected_fit is None or expected_fit >= 0.05),
        )
    ) / 6
    quality = round(min(1.0, max(0.0, 0.6 * document.quality + 0.4 * check_score)), 4)
    return replace(document, quality=quality, metadata={**document.metadata, "quality_checks": checks})


def _terms(value: str) -> set[str]:
    return {
        "".join(character for character in token.casefold() if character.isalnum())
        for token in value.split()
        if len(token) > 2
    } - {""}


__all__ = ["ExtractionService"]
