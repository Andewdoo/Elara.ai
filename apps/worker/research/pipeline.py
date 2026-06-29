"""Typed Step 9 LangGraph extensions for discovery, fetching, and extraction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4

from extraction.service import ExtractionService
from graph.state import CandidateSource, ExtractedSourceRecord, SnapshotRecord, VerificationState
from research.cache import RetrievalRateLimiter
from research.fetcher import FetchError, SecureFetcher
from research.ranking import RankingSignals, lexical_overlap, priority_score, select_diverse
from research.search import BraveSearchClient, SearchProviderError
from research.url_guard import UnsafeUrlError, canonicalize_url


_LIMITS = {"QUICK": 5, "STANDARD": 10, "DEEP": 20}


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
        for query in sorted(state.queries, key=lambda item: -item.priority):
            try:
                results = await self.search.search(query.query, count=10)
            except SearchProviderError:
                raise
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
        selected = select_diverse(list(by_url.values()), limit=_LIMITS[state.research_depth.value])
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
                        metadata={"untrusted_evidence": True},
                    )
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
            try:
                if not snapshot.content_hash:
                    raise ValueError("fetched snapshot is missing its content hash")
                content = self.fetcher.read_content(
                    snapshot.snapshot_path, expected_hash=snapshot.content_hash
                )
                source = sources[snapshot.source_ref]
                expected_terms = tuple(
                    claims[objectives[objective_ref]]
                    for objective_ref in source.objective_refs
                    if objective_ref in objectives and objectives[objective_ref] in claims
                )
                document = await self.extractor.extract(
                    content,
                    content_type=snapshot.content_type or "",
                    url=source.canonical_url or source.url,
                    expected_terms=expected_terms,
                )
            except Exception:
                # Parser and storage errors caused by untrusted source bytes are
                # source-level failures, not permission to abort the whole run.
                document = None
            if document is None:
                snapshots.append(
                    snapshot.model_copy(
                        update={
                            "access_status": "INACCESSIBLE",
                            "failure_reason": "No safe extractor produced sufficient readable content.",
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
                )
            )
        parser_versions = dict(state.parser_versions)
        for snapshot in snapshots:
            if snapshot.parser_name and snapshot.parser_version:
                parser_versions[snapshot.parser_name] = snapshot.parser_version
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


__all__ = ["RetrievalPipeline"]
