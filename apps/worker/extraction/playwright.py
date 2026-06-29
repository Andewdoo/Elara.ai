"""Explicit future fallback boundary; no browser session or credentials are created yet."""

from __future__ import annotations

from extraction.models import ExtractedDocument


async def extract_with_playwright_placeholder(*, url: str) -> ExtractedDocument | None:
    del url
    return None


__all__ = ["extract_with_playwright_placeholder"]
