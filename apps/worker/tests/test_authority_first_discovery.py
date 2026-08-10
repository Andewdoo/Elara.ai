from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agents.schemas import (
    AtomicClaimOutput,
    ClaimKind,
    EvidenceIntent,
    FactCheckability,
    Importance,
    MetricReference,
    NamedEntity,
    ResearchObjectiveOutput,
    SearchQueryOutput,
)
from extraction.service import ExtractionService
from graph.state import ResearchDepth, VerificationState
from graph.workflow import _deterministic_evidence_gaps
from research.authority import (
    AUTHORITY_GAP_CODE,
    AUTHORITY_PREFLIGHT_TOTAL_BUDGET,
)
from research.fetcher import FetchError, FetchResult
from research.pipeline import RetrievalPipeline
from research.search import SearchResult


def run(value):
    return asyncio.run(value)


@dataclass(frozen=True)
class AuthorityCase:
    subject: str
    text: str
    kind: ClaimKind
    entity: str
    location: str | None
    metric: str
    official_title: str
    official_snippet: str


CASES = (
    AuthorityCase(
        "compensation",
        "Ontario registered nurses had a starting wage of $39.07 per hour in 2025.",
        ClaimKind.NUMERICAL,
        "Ontario registered nurses",
        "Ontario",
        "starting wage",
        "2025 Ontario Nurses' Association collective agreement wage grid",
        "Registered nurse hourly wage, employment sector, full-time status, pay step, and salary rates.",
    ),
    AuthorityCase(
        "legal",
        "Ontario Regulation 123/2025 required the stated safety measure in 2025.",
        ClaimKind.LEGAL,
        "Government of Ontario",
        "Ontario",
        "regulation",
        "Ontario Regulation 123/2025 official law",
        "The 2025 regulation and enabling Act set the legal requirement.",
    ),
    AuthorityCase(
        "medical",
        "Health Canada guidance in 2025 recommended the stated vaccine dose.",
        ClaimKind.SCIENTIFIC,
        "Health Canada",
        "Canada",
        "vaccine dose",
        "Health Canada 2025 vaccine guidance and recommendation",
        "Public-health guidance describes the recommended vaccine dose and safety advice.",
    ),
    AuthorityCase(
        "product",
        "Apple's iPhone 16 technical specifications list the stated battery feature.",
        ClaimKind.FACTUAL,
        "Apple",
        None,
        "battery feature",
        "Apple iPhone 16 technical specifications",
        "Manufacturer specifications and support documentation list the battery feature.",
    ),
    AuthorityCase(
        "corporate",
        "Apple reported its 2025 annual revenue in a corporate filing.",
        ClaimKind.NUMERICAL,
        "Apple",
        None,
        "annual revenue",
        "Apple 2025 Form 10-K annual report filing",
        "The filing contains annual revenue, financial statements, and earnings.",
    ),
    AuthorityCase(
        "quotation",
        "President Biden stated in 2025 that the program was fully funded.",
        ClaimKind.QUOTATION,
        "President Biden",
        "United States",
        "stated",
        "2025 remarks and transcript by President Biden",
        "Official statement transcript: the program was fully funded.",
    ),
)


def _state(case: AuthorityCase, *, broad_intent: EvidenceIntent = EvidenceIntent.SUPPORT):
    objective = ResearchObjectiveOutput(
        objective_ref="objective-1",
        claim_ref="claim-1",
        intent=broad_intent,
        target="Find independent evidence.",
    )
    return VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        claims=[
            AtomicClaimOutput(
                claim_ref="claim-1",
                text=case.text,
                claim_kind=case.kind,
                importance=Importance.ESSENTIAL,
                importance_weight=3,
                fact_checkability=FactCheckability.FACT_CHECKABLE,
                entities=[NamedEntity(name=case.entity, entity_type="organization")],
                locations=[case.location] if case.location else [],
                time_period="2025" if "2025" in case.text else None,
                metrics=[MetricReference(name=case.metric)],
                verification_scope=case.text,
            )
        ],
        objectives=[objective],
        queries=[
            SearchQueryOutput(
                query=f"broad discovery for {case.subject}",
                objective_ref=objective.objective_ref,
                intent=broad_intent,
                priority=1,
            )
        ],
    )


class FixtureSearch:
    def __init__(self, case: AuthorityCase, *, official: bool = True) -> None:
        self.case = case
        self.official = official
        self.queries: list[str] = []

    async def search(self, query: str, *, count: int = 10):
        del count
        self.queries.append(query)
        if query.startswith("site:"):
            if not self.official:
                return []
            domain = query.split()[0].removeprefix("site:")
            return [
                SearchResult(
                    f"https://{domain}/official-record",
                    self.case.official_title,
                    self.case.official_snippet,
                    1,
                )
            ]
        return [
            SearchResult(
                "https://independent.example/analysis",
                "Independent analysis",
                f"Independent support and contradiction context for {self.case.subject}.",
                1,
            )
        ]

    async def aclose(self):
        return None


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.subject)
def test_profile_specific_preflight_runs_before_broad_discovery(case: AuthorityCase):
    search = FixtureSearch(case)
    result = run(
        RetrievalPipeline(search=search, fetcher=object()).discover(  # type: ignore[arg-type]
            _state(case)
        )
    )

    broad_index = search.queries.index(f"broad discovery for {case.subject}")
    assert broad_index > 0
    assert all(query.startswith("site:") for query in search.queries[:broad_index])
    assert result.authority_profiles[0].subject == case.subject
    assert result.authority_preflight_used <= AUTHORITY_PREFLIGHT_TOTAL_BUDGET
    assert result.authority_preflight_budget == AUTHORITY_PREFLIGHT_TOTAL_BUDGET
    assert any(
        source.source_origin == "authority_preflight"
        and source.authority_match_status == "verified_search_match"
        for source in result.candidate_sources
    )
    assert any(
        source.source_origin == "brave_discovery"
        for source in result.candidate_sources
    )
    assert all("site:" in record.query for record in result.authority_preflight_queries)


def test_missing_official_record_records_gap_and_falls_back_without_spending_broad_budget():
    case = CASES[0]
    search = FixtureSearch(case, official=False)
    result = run(
        RetrievalPipeline(search=search, fetcher=object()).discover(  # type: ignore[arg-type]
            _state(case)
        )
    )

    assert result.search_effective_budget == 48
    assert result.authority_preflight_used == 2
    assert len(result.search_query_executions) == 1
    assert result.search_query_executions[0].execution_status == "executed"
    assert result.candidate_sources[0].source_origin == "brave_discovery"
    assert result.authority_gaps[0].code == AUTHORITY_GAP_CODE
    assert result.authority_gaps[0].reason_code == "NO_SEARCH_RESULTS"
    assert AUTHORITY_GAP_CODE in result.known_evidence_gaps


def test_primary_intent_does_not_make_an_unregistered_broad_result_authoritative():
    case = CASES[0]
    result = run(
        RetrievalPipeline(search=FixtureSearch(case, official=False), fetcher=object()).discover(  # type: ignore[arg-type]
            _state(case, broad_intent=EvidenceIntent.PRIMARY)
        )
    )

    broad = next(
        source for source in result.candidate_sources if source.source_origin == "brave_discovery"
    )
    assert broad.evidence_intents == ["primary"]
    assert broad.source_type == "UNKNOWN"
    assert broad.authority_match_status == "not_evaluated"


class MixedFetcher:
    def __init__(self, *, block_official: bool = False, irrelevant_official: bool = False) -> None:
        self.block_official = block_official
        self.irrelevant_official = irrelevant_official

    async def fetch(self, url: str) -> FetchResult:
        if self.block_official and "independent.example" not in url:
            raise FetchError("blocked official fixture", access_status="BOT_BLOCKED")
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            content_length=512,
            content_hash="d" * 64,
            storage_path="broad.html" if "independent.example" in url else "official.html",
            redirect_chain=(),
            origin_fetched_at="2026-08-09T00:00:00+00:00",
        )

    def read_content(self, path: str, *, expected_hash: str) -> bytes:
        del expected_hash
        if path == "official.html" and self.irrelevant_official:
            body = "Ontario Nurses' Association community event and newsletter. " * 20
        elif path == "official.html":
            body = (
                "Ontario Nurses' Association 2025 collective agreement wage grid. "
                "Registered nurse full-time hourly starting wage, employment sector, and pay step. "
            ) * 12
        else:
            body = "Independent analysis of the Ontario registered nurse wage claim in 2025. " * 20
        return f"<html><body><article><h1>Evidence</h1><p>{body}</p></article></body></html>".encode()


def test_blocked_official_source_records_gap_while_broad_fallback_remains_usable():
    case = CASES[0]
    discovered = run(
        RetrievalPipeline(search=FixtureSearch(case), fetcher=object()).discover(  # type: ignore[arg-type]
            _state(case)
        )
    )
    retrieved = run(
        RetrievalPipeline(
            search=object(),  # type: ignore[arg-type]
            fetcher=MixedFetcher(block_official=True),
        ).retrieve(discovered)
    )

    assert any(snapshot.access_status == "FETCHED" for snapshot in retrieved.snapshots)
    assert retrieved.authority_gaps[0].reason_code == "INACCESSIBLE_OR_BLOCKED"
    assert AUTHORITY_GAP_CODE in retrieved.known_evidence_gaps


def test_irrelevant_official_document_is_downgraded_and_gap_is_retained():
    case = CASES[0]
    fetcher = MixedFetcher(irrelevant_official=True)
    pipeline = RetrievalPipeline(
        search=FixtureSearch(case),
        fetcher=fetcher,
        extractor=ExtractionService(),
    )
    discovered = run(pipeline.discover(_state(case)))
    retrieved = run(pipeline.retrieve(discovered))
    extracted = run(pipeline.extract(retrieved))

    official = next(
        source
        for source in extracted.candidate_sources
        if source.source_origin == "authority_preflight"
    )
    assert official.source_type == "UNKNOWN"
    assert official.authority_match_status == "rejected"
    assert extracted.authority_gaps[0].reason_code == "NO_EXACT_CLAIM_EVIDENCE"
    assert any(source.source_origin == "brave_discovery" for source in extracted.candidate_sources)


def test_matching_official_document_keeps_verified_role_and_broad_corroboration():
    case = CASES[0]
    fetcher = MixedFetcher()
    pipeline = RetrievalPipeline(
        search=FixtureSearch(case),
        fetcher=fetcher,
        extractor=ExtractionService(),
    )
    extracted = run(pipeline.extract(run(pipeline.retrieve(run(pipeline.discover(_state(case)))))))

    official = next(
        source
        for source in extracted.candidate_sources
        if source.source_origin == "authority_preflight"
    )
    broad = next(
        source
        for source in extracted.candidate_sources
        if source.source_origin == "brave_discovery"
    )
    official_snapshot = next(
        snapshot for snapshot in extracted.snapshots if snapshot.source_ref == official.source_ref
    )
    assert official.source_type == "PRIMARY"
    assert official.authority_match_status == "verified_document_match"
    assert official_snapshot.metadata["authority_match_status"] == "verified_document_match"
    assert extracted.authority_gaps == []
    assert broad.source_type == "UNKNOWN"


def test_ambiguous_profile_records_specific_gap_and_runs_broad_search():
    case = AuthorityCase(
        "product",
        "Acme Model Z technical specifications list a proprietary battery feature.",
        ClaimKind.FACTUAL,
        "Acme",
        None,
        "battery feature",
        "unused",
        "unused",
    )
    search = FixtureSearch(case)
    result = run(
        RetrievalPipeline(search=search, fetcher=object()).discover(  # type: ignore[arg-type]
            _state(case)
        )
    )

    assert search.queries == ["broad discovery for product"]
    assert result.authority_profiles == []
    assert result.authority_gaps[0].reason_code == "AUTHORITY_PROFILE_AMBIGUOUS"
    assert result.candidate_sources[0].source_origin == "brave_discovery"


def test_authority_provenance_is_versioned_and_timestamped():
    result = run(
        RetrievalPipeline(search=FixtureSearch(CASES[0]), fetcher=object()).discover(  # type: ignore[arg-type]
            _state(CASES[0])
        )
    )
    profile = result.authority_profiles[0]
    query = result.authority_preflight_queries[0]
    source = next(
        item for item in result.candidate_sources if item.source_origin == "authority_preflight"
    )

    assert profile.created_at.tzinfo is not None
    assert query.executed_at is not None and query.executed_at.tzinfo is not None
    assert query.profile_version == profile.profile_version
    assert query.registry_version == profile.registry_version
    assert source.authority_profile_version == profile.profile_version
    assert source.authority_registry_version == profile.registry_version
    assert source.search_phase == "authority_preflight"
    assert datetime.now(UTC) >= query.executed_at


def test_authority_fallback_gap_is_exposed_by_deterministic_report_provenance():
    state = run(
        RetrievalPipeline(
            search=FixtureSearch(CASES[0], official=False),
            fetcher=object(),  # type: ignore[arg-type]
        ).discover(_state(CASES[0]))
    )

    gaps = _deterministic_evidence_gaps(state, approved_passage_ids=set())

    assert gaps[0].startswith(f"{AUTHORITY_GAP_CODE} for claim claim-1")
    assert "no search results" in gaps[0]


def test_untrusted_profile_text_cannot_weaken_registered_site_restriction():
    state = _state(CASES[3])
    claim = state.claims[0].model_copy(
        update={
            "entities": [
                NamedEntity(
                    name='Apple" OR site:attacker.example',
                    entity_type="organization",
                )
            ]
        }
    )
    result = run(
        RetrievalPipeline(
            search=FixtureSearch(CASES[3], official=False),
            fetcher=object(),  # type: ignore[arg-type]
        ).discover(state.model_copy(update={"claims": [claim]}))
    )

    query = result.authority_preflight_queries[0].query
    assert query.startswith("site:apple.com ")
    assert query.count("site:") == 1
    assert " OR " not in query
