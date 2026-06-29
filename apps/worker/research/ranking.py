"""Deterministic usefulness ranking; never a credibility or truth score."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class RankingSignals:
    relevance: Decimal
    directness: Decimal
    temporal_fit: Decimal
    diversity: Decimal
    novelty: Decimal
    extractability: Decimal


def priority_score(signals: RankingSignals) -> Decimal:
    values = tuple(signals.__dict__.values()) if hasattr(signals, "__dict__") else (
        signals.relevance,
        signals.directness,
        signals.temporal_fit,
        signals.diversity,
        signals.novelty,
        signals.extractability,
    )
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("ranking signals must be between zero and one")
    return (
        Decimal("0.30") * signals.relevance
        + Decimal("0.20") * signals.directness
        + Decimal("0.15") * signals.temporal_fit
        + Decimal("0.15") * signals.diversity
        + Decimal("0.10") * signals.novelty
        + Decimal("0.10") * signals.extractability
    ).quantize(Decimal("0.0001"))


def lexical_overlap(query: str, title: str | None, snippet: str | None) -> Decimal:
    wanted = _terms(query)
    if not wanted:
        return Decimal("0")
    found = _terms(f"{title or ''} {snippet or ''}")
    return Decimal(len(wanted & found)) / Decimal(len(wanted))


def select_diverse(
    candidates: list,
    *,
    limit: int,
    per_domain: int = 2,
    reserved_intents: tuple[str, ...] = ("primary", "support", "contradiction"),
) -> list:
    selected: list = []
    domains: dict[str, int] = {}
    clusters: set[str] = set()
    ordered = sorted(candidates, key=lambda item: (-item.priority, item.source_ref))

    def add(candidate) -> bool:
        domain = candidate.domain or urlsplit(candidate.canonical_url or candidate.url).hostname or ""
        if domains.get(domain, 0) >= per_domain:
            return False
        cluster = _cluster_key(candidate)
        if cluster in clusters:
            return False
        selected.append(candidate)
        domains[domain] = domains.get(domain, 0) + 1
        clusters.add(cluster)
        return True

    for intent in reserved_intents:
        for candidate in ordered:
            if candidate not in selected and intent in candidate.evidence_intents and add(candidate):
                break
        if len(selected) >= limit:
            return selected
    for candidate in ordered:
        if candidate not in selected:
            add(candidate)
        if len(selected) >= limit:
            break
    return selected


def _terms(value: str) -> set[str]:
    return {part.casefold() for part in value.replace('"', " ").split() if len(part) > 2}


def _cluster_key(candidate) -> str:
    text = f"{candidate.title or ''} {candidate.snippet or ''}".casefold()
    normalized = " ".join("".join(character for character in part if character.isalnum()) for part in text.split())
    tokens = [token for token in normalized.split() if token][:20]
    return " ".join(tokens) or candidate.canonical_url or candidate.url


__all__ = ["RankingSignals", "lexical_overlap", "priority_score", "select_diverse"]
