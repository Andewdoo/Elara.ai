"""Traceable hybrid passage retrieval; scores rank evidence and never decide truth."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from agents.deepseek_client import DeepSeekClient, DeepSeekError
from app.models.sources import RunSource, SourcePassage


_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)
_QUOTED = re.compile(r"[\"\u201c](.+?)[\"\u201d]")
_NUMBER_OR_IDENTIFIER = re.compile(r"\b(?:\d[\d,.:/%-]*|[A-Z]{2,}[A-Z0-9._/-]*)\b")
_PROPER_NAME = re.compile(r"\b[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)+\b")


@dataclass(frozen=True, slots=True)
class PassageSearchResult:
    passage: SourcePassage
    score: Decimal
    lexical_score: Decimal
    vector_similarity: Decimal | None
    exact_match_score: Decimal
    metadata_fit: Decimal
    source_role_score: Decimal
    extraction_certainty: Decimal
    retrieval_only: bool = True


@dataclass(frozen=True, slots=True)
class PassageSearchResponse:
    results: list[PassageSearchResult]
    retrieval_mode: str
    embedding_model: str | None = None
    fallback_reason: str | None = None


class PassageRetriever:
    """Combine deterministic signals; downstream evidence checks remain authoritative."""

    def search(
        self,
        db: Session,
        *,
        run_id: UUID,
        query: str,
        query_vector: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
        limit: int = 20,
        candidate_limit: int = 200,
    ) -> list[PassageSearchResult]:
        if not query.strip():
            raise ValueError("passage retrieval query cannot be empty")
        if limit < 1 or candidate_limit < limit:
            raise ValueError("candidate_limit must be at least the positive result limit")
        statement = self._base_query(run_id)
        dialect = db.get_bind().dialect.name
        vector_sql = query_vector is not None and dialect == "postgresql"
        candidates: dict[UUID, tuple[SourcePassage, str, Decimal | None]] = {}
        if vector_sql:
            distance = SourcePassage.embedding.cosine_distance(query_vector).label("vector_distance")
            vector_rows = db.execute(
                statement.add_columns(distance)
                .where(SourcePassage.embedding.is_not(None))
                .order_by(distance)
                .limit(candidate_limit)
            ).all()
            for passage, role, raw_distance in vector_rows:
                similarity = _unit(Decimal("1") - Decimal(str(raw_distance)) / Decimal("2"))
                candidates[passage.id] = (passage, role, similarity)
            # Keep lexical-only passages eligible even when vectors exist. The
            # vector shortlist assists candidate discovery; it never gates it.
            lexical_rows = db.execute(
                self._postgresql_lexical_query(run_id, query).limit(candidate_limit)
            ).all()
            for passage, role, _rank in lexical_rows:
                candidates.setdefault(passage.id, (passage, role, None))
        else:
            rows = db.execute(statement.order_by(SourcePassage.created_at).limit(candidate_limit)).all()
            for passage, role in rows:
                similarity = (
                    _cosine_similarity(query_vector, list(passage.embedding))
                    if query_vector is not None and passage.embedding is not None
                    else None
                )
                candidates[passage.id] = (passage, role, similarity)
        results: list[PassageSearchResult] = []
        for passage, role, similarity in candidates.values():
            lexical = lexical_score(query, passage.text)
            exact = exact_match_score(query, passage.text)
            metadata_fit = _metadata_fit(metadata or {}, passage)
            role_score = _source_role_score(role)
            certainty = _unit(Decimal(str(passage.extraction_certainty)))
            weighted = [
                (lexical, Decimal("0.25")),
                (exact, Decimal("0.25")),
                (metadata_fit, Decimal("0.10")),
                (role_score, Decimal("0.10")),
                (certainty, Decimal("0.10")),
            ]
            if similarity is not None:
                weighted.append((similarity, Decimal("0.20")))
            total_weight = sum((weight for _, weight in weighted), Decimal("0"))
            score = sum((value * weight for value, weight in weighted), Decimal("0")) / total_weight
            results.append(
                PassageSearchResult(
                    passage=passage,
                    score=score.quantize(Decimal("0.000001")),
                    lexical_score=lexical,
                    vector_similarity=similarity,
                    exact_match_score=exact,
                    metadata_fit=metadata_fit,
                    source_role_score=role_score,
                    extraction_certainty=certainty,
                )
            )
        return sorted(results, key=lambda item: (-item.score, str(item.passage.id)))[:limit]

    @staticmethod
    def _base_query(run_id: UUID) -> Select:
        return (
            select(SourcePassage, RunSource.role)
            .join(
                RunSource,
                (RunSource.source_id == SourcePassage.source_id)
                & (RunSource.snapshot_id == SourcePassage.snapshot_id),
            )
            .where(RunSource.run_id == run_id)
        )

    @classmethod
    def _postgresql_lexical_query(cls, run_id: UUID, query: str) -> Select:
        query_ts = func.websearch_to_tsquery("simple", query)
        lexical_rank = func.ts_rank_cd(
            func.to_tsvector("simple", SourcePassage.text), query_ts
        ).label("lexical_rank")
        return (
            cls._base_query(run_id)
            .add_columns(lexical_rank)
            .order_by(lexical_rank.desc(), SourcePassage.created_at)
        )


class HybridPassageSearchService:
    """Generate a query vector through DeepSeek when available, then rank safely."""

    def __init__(
        self,
        client: DeepSeekClient,
        *,
        expected_dimension: int,
        retriever: PassageRetriever | None = None,
    ) -> None:
        if expected_dimension < 1:
            raise ValueError("expected_dimension must be positive")
        self.client = client
        self.expected_dimension = expected_dimension
        self.retriever = retriever or PassageRetriever()

    async def search(self, db: Session, **kwargs: Any) -> PassageSearchResponse:
        search_kwargs = dict(kwargs)
        # Query vectors are provider-owned here; callers cannot smuggle in a
        # vector from an unapproved embedding service through this interface.
        search_kwargs.pop("query_vector", None)
        query = search_kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("passage retrieval query cannot be empty")
        if not self.client.embedding_available:
            return PassageSearchResponse(
                results=self.retriever.search(db, **search_kwargs),
                retrieval_mode="lexical_metadata_fallback",
                fallback_reason="embedding_route_unavailable",
            )
        try:
            response = await self.client.generate_embeddings([query])
            vector = response.vectors[0]
            if len(vector) != self.expected_dimension:
                raise ValueError("query embedding dimension mismatch")
        except DeepSeekError as exc:
            return PassageSearchResponse(
                results=self.retriever.search(db, **search_kwargs),
                retrieval_mode="lexical_metadata_fallback",
                embedding_model=self.client.config.embedding_model,
                fallback_reason=exc.metadata.error_code or "embedding_provider_error",
            )
        except ValueError:
            return PassageSearchResponse(
                results=self.retriever.search(db, **search_kwargs),
                retrieval_mode="lexical_metadata_fallback",
                embedding_model=self.client.config.embedding_model,
                fallback_reason="embedding_dimension_mismatch",
            )
        return PassageSearchResponse(
            results=self.retriever.search(db, **{**search_kwargs, "query_vector": vector}),
            retrieval_mode="hybrid",
            embedding_model=response.metadata.model,
        )


def lexical_score(query: str, text: str) -> Decimal:
    query_terms = _terms(query)
    if not query_terms:
        return Decimal("0")
    text_terms = _terms(text)
    matched = sum(min(query_terms[term], text_terms.get(term, 0)) for term in query_terms)
    total = sum(query_terms.values())
    return _unit(Decimal(matched) / Decimal(total))


def exact_match_score(query: str, text: str) -> Decimal:
    needles = [value.strip().casefold() for value in _QUOTED.findall(query) if value.strip()]
    needles.extend(value.casefold() for value in _NUMBER_OR_IDENTIFIER.findall(query))
    needles.extend(value.casefold() for value in _PROPER_NAME.findall(query))
    if not needles:
        return Decimal("0")
    haystack = text.casefold()
    return Decimal(sum(needle in haystack for needle in needles)) / Decimal(len(needles))


def _metadata_fit(metadata: dict[str, Any], passage: SourcePassage) -> Decimal:
    wanted = [
        str(item).casefold()
        for value in metadata.values()
        for item in (value if isinstance(value, (list, tuple, set)) else [value])
        if item is not None and str(item).strip()
    ]
    if not wanted:
        return Decimal("0.5")
    searchable = " ".join(
        filter(
            None,
            [
                passage.heading_path,
                passage.text,
                passage.page_or_position,
                passage.speaker,
                passage.table_ref,
                " ".join(str(value) for value in passage.passage_metadata.values()),
            ],
        )
    ).casefold()
    return Decimal(sum(value in searchable for value in wanted)) / Decimal(len(wanted))


def _source_role_score(role: str) -> Decimal:
    return {
        "PRIMARY": Decimal("1"),
        "INDEPENDENT_ANALYSIS": Decimal("0.85"),
        "OFFICIAL_SELF_REPORT": Decimal("0.75"),
        "SECONDARY_REPORT": Decimal("0.60"),
        "DERIVATIVE_REPORT": Decimal("0.35"),
        "OPINION": Decimal("0.25"),
        "UNKNOWN": Decimal("0.50"),
    }.get(role, Decimal("0.50"))


def _terms(value: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _TOKEN.findall(value.casefold()):
        if len(token) < 2:
            continue
        counts[token] = counts.get(token, 0) + 1
    return counts


def _cosine_similarity(left: list[float], right: list[float]) -> Decimal | None:
    if len(left) != len(right) or not left:
        return None
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if norm == 0:
        return None
    return _unit(Decimal(str((dot / norm + 1) / 2)))


def _unit(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value))


__all__ = [
    "PassageRetriever",
    "HybridPassageSearchService",
    "PassageSearchResponse",
    "PassageSearchResult",
    "exact_match_score",
    "lexical_score",
]
