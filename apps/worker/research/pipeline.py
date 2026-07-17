"""Typed Step 9 LangGraph extensions for discovery, fetching, and extraction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import time
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree.ElementTree import ParseError

import fitz

from extraction.service import ExtractionService
from graph.state import CandidateSource, ExtractedBlockRecord, ExtractedSourceRecord, SnapshotRecord, VerificationState
from research.cache import RetrievalRateLimiter
from research.extension_errors import WorkflowExtensionError
from research.fetcher import FetchError, SecureFetcher
from research.ranking import (
    RESEARCH_DEPTH_LIMITS,
    RankingSignals,
    lexical_overlap,
    priority_score,
    select_diverse,
)
from research.search import BraveSearchClient, SearchProviderError
from research.url_guard import UnsafeUrlError, canonicalize_url


_UNTRUSTED_SOURCE_EXTRACTION_ERRORS = (UnicodeError, ParseError, fitz.FileDataError)


class RetrievalPipeline:
    def __init__(
        self,
        *,
        search: BraveSearchClient,
        fetcher: SecureFetcher,
        extractor: ExtractionService | None = None,
        rate_limiter: RetrievalRateLimiter | None = None,
    ) -> None:
        self.search = search
        self.fetcher = fetcher
        self.extractor = extractor or ExtractionService()
        self.rate_limiter = rate_limiter

    async def discover(self, state: VerificationState) -> VerificationState:
        by_url: dict[str, CandidateSource] = {}
        result_counts: dict[str, int] = {}
        last_provider_error: SearchProviderError | None = None
        for query in sorted(state.queries, key=lambda item: -item.priority):
            try:
                results = await self.search.search(query.query, count=10)
            except SearchProviderError as exc:
                last_provider_error = exc
                result_counts[f"{query.objective_ref}:{query.query}"] = 0
                continue
            result_counts[f"{query.objective_ref}:{query.query}"] = len(results)
            for result in results:
                try:
                    canonical = canonicalize_url(result.url)
                except UnsafeUrlError:
                    continue
                domain = urlsplit(canonical).hostname or ""
                relevance = lexical_overlap(query.query, result.title, result.snippet)
                intent = query.intent.value
                directness = Decimal("1") if intent == "primary" else Decimal("0.6")
                same_domain_count = sum(item.domain == domain for item in by_url.values())
                same_title_count = sum(
                    (item.title or "").casefold() == (result.title or "").casefold()
                    for item in by_url.values()
                    if result.title
                )
                signals = RankingSignals(
                    relevance=relevance,
                    directness=directness,
                    temporal_fit=Decimal("0.7" if result.published_at else "0.5"),
                    diversity=Decimal("1" if same_domain_count == 0 else "0.5"),
                    novelty=Decimal("1" if same_title_count == 0 else "0.25"),
                    extractability=Decimal("0.8"),
                )
                score = priority_score(signals)
                existing = by_url.get(canonical)
                objective_refs = sorted(
                    set((existing.objective_refs if existing else []) + [query.objective_ref])
                )
                evidence_intents = sorted(
                    set((existing.evidence_intents if existing else []) + [intent])
                )
                if existing is None or score > existing.priority:
                    by_url[canonical] = CandidateSource(
                        source_ref=f"source-{len(by_url) + 1}",
                        url=result.url,
                        canonical_url=canonical,
                        domain=domain,
                        snippet=result.snippet,
                        objective_refs=objective_refs,
                        evidence_intents=evidence_intents,
                        title=result.title,
                        source_type="PRIMARY" if intent == "primary" else "UNKNOWN",
                        selection_reason=f"Brave result for {intent} objective {query.objective_ref}",
                        priority=score,
                    )
                else:
                    by_url[canonical] = existing.model_copy(
                        update={
                            "objective_refs": objective_refs,
                            "evidence_intents": evidence_intents,
                        }
                    )
        if not by_url and last_provider_error is not None:
            raise last_provider_error
        if not by_url:
            raise WorkflowExtensionError(
                code="NO_DISCOVERY_RESULTS",
                public_message="The configured search policy returned no evidence candidates.",
                details={
                    "provider": "brave",
                    "query_count": len(state.queries),
                    "search_result_count": sum(result_counts.values()),
                },
            )
        selected = select_diverse(
            list(by_url.values()), limit=RESEARCH_DEPTH_LIMITS[state.research_depth.value]
        )
        # Keep source refs stable after ranking/deduplication.
        selected = [item.model_copy(update={"source_ref": f"source-{index}"}) for index, item in enumerate(selected, 1)]
        return state.model_copy(
            update={"candidate_sources": selected, "query_result_counts": result_counts}
        )

    async def retrieve(self, state: VerificationState) -> VerificationState:
        snapshots: list[SnapshotRecord] = []
        for source in state.candidate_sources:
            snapshot_id = str(uuid4())
            retrieved_at = datetime.now(UTC)
            fetch_started = time.perf_counter()
            try:
                if self.rate_limiter and not self.rate_limiter.allow(
                    user_id=str(state.user_id), domain=source.domain or "unknown"
                ):
                    raise FetchError("retrieval rate limit reached", access_status="INACCESSIBLE")
                result = await self.fetcher.fetch(source.canonical_url or source.url)
                snapshots.append(
                    SnapshotRecord(
                        snapshot_id=snapshot_id,
                        source_ref=source.source_ref,
                        access_status="FETCHED",
                        retrieved_at=retrieved_at,
                        content_hash=result.content_hash,
                        content_type=result.content_type,
                        snapshot_path=result.storage_path,
                        metadata={
                            "final_url": result.final_url,
                            "redirect_chain": list(result.redirect_chain),
                            "content_length": result.content_length,
                            "origin_fetched_at": result.origin_fetched_at,
                            "cache_hit": result.cache_hit,
                            "fetch_latency_ms": round((time.perf_counter() - fetch_started) * 1000, 3),
                            "untrusted_evidence": True,
                        },
                    )
                )
            except FetchError as exc:
                if exc.retryable:
                    raise
                snapshots.append(
                    SnapshotRecord(
                        snapshot_id=snapshot_id,
                        source_ref=source.source_ref,
                        access_status=exc.access_status,
                        retrieved_at=retrieved_at,
                        failure_reason=str(exc),
                        metadata={
                            "untrusted_evidence": True,
                            "fetch_latency_ms": round((time.perf_counter() - fetch_started) * 1000, 3),
                        },
                    )
                )
        accessible_count = sum(snapshot.access_status == "FETCHED" for snapshot in snapshots)
        if not accessible_count:
            raise WorkflowExtensionError(
                code="NO_ACCESSIBLE_SOURCES",
                public_message="No selected evidence source could be retrieved safely.",
                details={
                    "candidate_count": len(state.candidate_sources),
                    "snapshot_count": len(snapshots),
                },
            )
        return state.model_copy(update={"snapshots": snapshots})

    async def extract(self, state: VerificationState) -> VerificationState:
        snapshots: list[SnapshotRecord] = []
        extracted: list[ExtractedSourceRecord] = []
        sources = {source.source_ref: source for source in state.candidate_sources}
        claims = {claim.claim_ref: claim.text for claim in state.claims}
        objectives = {objective.objective_ref: objective.claim_ref for objective in state.objectives}
        for snapshot in state.snapshots:
            if snapshot.access_status != "FETCHED" or not snapshot.snapshot_path:
                snapshots.append(snapshot)
                continue
            if not snapshot.content_hash:
                raise WorkflowExtensionError(
                    code="SNAPSHOT_HASH_MISSING",
                    public_message="A retrieved evidence snapshot is incomplete.",
                    details={"snapshot_id": snapshot.snapshot_id},
                )
            source = sources[snapshot.source_ref]
            try:
                content = self.fetcher.read_content(
                    snapshot.snapshot_path, expected_hash=snapshot.content_hash
                )
                expected_terms = tuple(
                    claims[objectives[objective_ref]]
                    for objective_ref in source.objective_refs
                    if objective_ref in objectives and objectives[objective_ref] in claims
                )
                outcome = await self.extractor.extract_with_outcome(
                    content,
                    content_type=snapshot.content_type or "",
                    url=str(snapshot.metadata.get("final_url") or source.canonical_url or source.url),
                    expected_terms=expected_terms,
                    allow_browser_fallback=_browser_fallback_is_justified(source),
                )
            except _UNTRUSTED_SOURCE_EXTRACTION_ERRORS:
                # Malformed untrusted source bytes can make a parser reject this
                # source. Storage, state, and invariant failures intentionally
                # propagate to the worker's internal-error path instead.
                outcome = None
            document = outcome.document if outcome is not None else None
            if document is None:
                failure_reason = (
                    outcome.failure_reason
                    if outcome is not None and outcome.failure_reason
                    else "No safe extractor produced sufficient readable content."
                )
                inaccessible_status = (
                    outcome.inaccessible_status
                    if outcome is not None and outcome.inaccessible_status
                    else "INACCESSIBLE"
                )
                extraction_metadata = {
                    "fallback_attempted": bool(outcome and outcome.fallback_attempted),
                    "fallback_reason": outcome.fallback_reason if outcome else None,
                    "extraction_certainty": None,
                    "inaccessible_status": inaccessible_status,
                    "parser_name": outcome.parser_name if outcome else None,
                    "parser_version": outcome.parser_version if outcome else None,
                }
                snapshots.append(
                    snapshot.model_copy(
                        update={
                            "access_status": inaccessible_status,
                            "failure_reason": failure_reason,
                            "parser_name": outcome.parser_name if outcome else None,
                            "parser_version": outcome.parser_version if outcome else None,
                            "metadata": {**snapshot.metadata, "extraction": extraction_metadata},
                        }
                    )
                )
                continue
            snapshots.append(
                snapshot.model_copy(
                    update={
                        "parser_name": document.parser_name,
                        "parser_version": document.parser_version,
                        "published_at": document.published_at,
                        "updated_at": document.updated_at,
                        "extraction_quality": Decimal(str(document.quality)),
                        "metadata": {
                            **snapshot.metadata,
                            **document.metadata,
                            "extraction": {
                                "title": document.title,
                                "author": document.author,
                                "publisher": document.publisher,
                                "headings": list(document.headings),
                                "table_count": len(document.tables),
                                "quote_count": len(document.quotes),
                                "correction_notices": list(document.correction_notices),
                                "outbound_links": list(document.outbound_links),
                                "page_positions": list(document.page_positions),
                                "fallback_attempted": bool(outcome and outcome.fallback_attempted),
                                "fallback_reason": outcome.fallback_reason if outcome else None,
                                "extraction_certainty": document.metadata.get(
                                    "extraction_certainty", document.quality
                                ),
                                "inaccessible_status": None,
                                "parser_name": document.parser_name,
                                "parser_version": document.parser_version,
                            },
                        },
                    }
                )
            )
            extracted.append(
                ExtractedSourceRecord(
                    source_ref=snapshot.source_ref,
                    snapshot_id=snapshot.snapshot_id,
                    body=document.body,
                    title=document.title,
                    author=document.author,
                    publisher=document.publisher,
                    published_at=document.published_at,
                    updated_at=document.updated_at,
                    headings=list(document.headings),
                    tables=list(document.tables),
                    quotes=list(document.quotes),
                    correction_notices=list(document.correction_notices),
                    outbound_links=list(document.outbound_links),
                    page_positions=list(document.page_positions),
                    blocks=[
                        ExtractedBlockRecord(
                            kind=block.kind,
                            text=block.text,
                            heading_path=list(block.heading_path),
                            page_or_position=block.page_or_position,
                            paragraph_index=block.paragraph_index,
                            speaker=block.speaker,
                            table_ref=block.table_ref,
                            metadata=block.metadata,
                        )
                        for block in document.blocks
                    ],
                )
            )
        parser_versions = dict(state.parser_versions)
        for snapshot in snapshots:
            if snapshot.parser_name and snapshot.parser_version:
                parser_versions[snapshot.parser_name] = snapshot.parser_version
        if not extracted:
            raise WorkflowExtensionError(
                code="NO_EXTRACTED_SOURCES",
                public_message="No retrieved evidence source contained usable extractable content.",
                details={
                    "fetched_snapshot_count": sum(
                        snapshot.access_status == "FETCHED" for snapshot in state.snapshots
                    ),
                    "snapshot_count": len(state.snapshots),
                },
            )
        return state.model_copy(
            update={
                "snapshots": snapshots,
                "extracted_sources": extracted,
                "parser_versions": parser_versions,
            }
        )

    async def aclose(self) -> None:
        await self.search.aclose()
        await self.fetcher.aclose()


def _browser_fallback_is_justified(source: CandidateSource) -> bool:
    return bool(
        source.priority >= Decimal("0.7500")
        or source.source_type in {"PRIMARY", "OFFICIAL_SELF_REPORT"}
        or {"primary", "correction"}.intersection(source.evidence_intents)
    )

__all__ = ["RetrievalPipeline"]
