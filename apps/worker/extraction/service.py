from __future__ import annotations

from dataclasses import dataclass, replace

from extraction.html import extract_with_beautiful_soup, extract_with_trafilatura
from extraction.models import ExtractedDocument
from extraction.pdf import extract_pdf
from extraction.playwright import PlaywrightExtractionError, PlaywrightExtractor


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    document: ExtractedDocument | None
    fallback_attempted: bool = False
    fallback_reason: str | None = None
    failure_reason: str | None = None
    inaccessible_status: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None


class ExtractionService:
    def __init__(self, *, playwright_extractor: PlaywrightExtractor | None = None) -> None:
        self.playwright_extractor = playwright_extractor

    async def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        url: str,
        expected_terms: tuple[str, ...] = (),
        allow_browser_fallback: bool = False,
    ) -> ExtractedDocument | None:
        outcome = await self.extract_with_outcome(
            content,
            content_type=content_type,
            url=url,
            expected_terms=expected_terms,
            allow_browser_fallback=allow_browser_fallback,
        )
        return outcome.document

    async def extract_with_outcome(
        self,
        content: bytes,
        *,
        content_type: str,
        url: str,
        expected_terms: tuple[str, ...] = (),
        allow_browser_fallback: bool = False,
    ) -> ExtractionOutcome:
        # PDFs are routed to the page-aware parser after signature/type validation.
        if content_type == "application/pdf":
            try:
                result = extract_pdf(content)
            except (RuntimeError, TypeError, ValueError):
                result = None
            return ExtractionOutcome(
                _with_certainty(_assess(result, expected_terms)) if result is not None else None,
                failure_reason=("PDF parsing failed safely." if result is None else None),
                inaccessible_status=("UNSUPPORTED" if result is None else None),
            )
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
                    blocks=structure.blocks,
                    metadata={**structure.metadata, **result.metadata, "structure_parser": "beautifulsoup4"},
                )
            return ExtractionOutcome(_with_certainty(_assess(result, expected_terms)))
        result = extract_with_beautiful_soup(content, url=url)
        if result is not None:
            return ExtractionOutcome(_with_certainty(_assess(result, expected_terms)))
        barrier_status = _access_barrier_status(content)
        if barrier_status is not None:
            return ExtractionOutcome(
                None,
                failure_reason=(
                    "Source content is behind an access barrier."
                    if barrier_status == "PAYWALLED"
                    else "Source denied automated access."
                ),
                inaccessible_status=barrier_status,
            )
        fallback_reason = "static_extraction_failed_for_important_source"
        if not allow_browser_fallback:
            return ExtractionOutcome(
                None,
                failure_reason="Static extraction failed and browser fallback was not justified.",
                inaccessible_status="INACCESSIBLE",
            )
        if self.playwright_extractor is None:
            return ExtractionOutcome(
                None,
                fallback_attempted=True,
                fallback_reason=fallback_reason,
                failure_reason="Browser fallback is unavailable.",
                inaccessible_status="INACCESSIBLE",
                parser_name="playwright",
                parser_version="unknown",
            )
        try:
            result = await self.playwright_extractor.extract(
                url=url,
                fallback_reason=fallback_reason,
            )
        except PlaywrightExtractionError as exc:
            return ExtractionOutcome(
                None,
                fallback_attempted=True,
                fallback_reason=fallback_reason,
                failure_reason=str(exc),
                inaccessible_status=exc.access_status,
                parser_name="playwright",
                parser_version=self.playwright_extractor.parser_version,
            )
        return ExtractionOutcome(
            _with_certainty(_assess(result, expected_terms)),
            fallback_attempted=True,
            fallback_reason=fallback_reason,
            parser_name=result.parser_name,
            parser_version=result.parser_version,
        )


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


def _with_certainty(document: ExtractedDocument) -> ExtractedDocument:
    return replace(
        document,
        metadata={**document.metadata, "extraction_certainty": document.quality},
    )


def _terms(value: str) -> set[str]:
    return {
        "".join(character for character in token.casefold() if character.isalnum())
        for token in value.split()
        if len(token) > 2
    } - {""}


def _access_barrier_status(content: bytes) -> str | None:
    sample = content[:100_000].decode("utf-8", errors="ignore").casefold()
    if any(
        term in sample
        for term in ("subscribe to continue", "subscriber-only", "subscription required")
    ):
        return "PAYWALLED"
    if any(term in sample for term in ("access denied", "verify you are human", "captcha")):
        return "BOT_BLOCKED"
    return None


__all__ = ["ExtractionOutcome", "ExtractionService"]
