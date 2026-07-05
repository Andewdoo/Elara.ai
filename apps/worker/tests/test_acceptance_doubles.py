import asyncio
from uuid import uuid4

import pytest

from acceptance.doubles import (
    ControlledSnapshotFetcher,
    DeterministicBraveDouble,
    DeterministicDeepSeekDouble,
)
from agents.deepseek_client import DeepSeekUnavailableError
from agents.schemas import (
    AtomicClaimOutput,
    ClaimKind,
    EvidenceIntent,
    FactCheckability,
    Importance,
    IntakeClassificationOutput,
    SearchQueryOutput,
)
from extraction.service import ExtractionService
from graph.state import ResearchDepth, VerificationState
from research.fetcher import SnapshotFileStore
from research.pipeline import RetrievalPipeline


def test_acceptance_provider_doubles_are_deterministic_and_credential_free():
    model = DeterministicDeepSeekDouble(
        "Company X doubled net income in Q1 2026.", embedding_dimension=8
    )
    first = asyncio.run(
        model.generate_structured(
            messages=[{"role": "user", "content": "controlled claim"}],
            output_schema=IntakeClassificationOutput,
            prompt_version="intake-v1",
            temperature=0,
        )
    )
    second = asyncio.run(
        model.generate_structured(
            messages=[{"role": "user", "content": "controlled claim"}],
            output_schema=IntakeClassificationOutput,
            prompt_version="intake-v1",
            temperature=0,
        )
    )
    search = asyncio.run(DeterministicBraveDouble().search("arbitrary query"))

    assert first.output == second.output
    assert first.metadata.model == "deepseek-acceptance-double"
    assert [row.url for row in search] == [
        "https://evidence.example.test/filing.html",
        "https://analysis.example.test/analysis.html",
    ]


def test_acceptance_deepseek_double_can_force_retryable_provider_failure():
    model = DeterministicDeepSeekDouble("[provider-failure]", embedding_dimension=8)

    with pytest.raises(DeepSeekUnavailableError) as caught:
        asyncio.run(
            model.generate_structured(
                messages=[{"role": "user", "content": "controlled claim"}],
                output_schema=IntakeClassificationOutput,
                prompt_version="intake-v1",
                temperature=0,
            )
        )

    assert caught.value.metadata.retryable is True


def test_controlled_brave_retrieval_persists_and_extracts_fixture_bytes(tmp_path):
    pipeline = RetrievalPipeline(
        search=DeterministicBraveDouble(),
        fetcher=ControlledSnapshotFetcher(SnapshotFileStore(tmp_path / "snapshots")),
        extractor=ExtractionService(),
    )
    state = VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.QUICK,
        methodology_version="1.0",
        claims=[
            AtomicClaimOutput(
                claim_ref="claim-1",
                text="Company X doubled net income in Q1 2026.",
                claim_kind=ClaimKind.NUMERICAL,
                importance=Importance.ESSENTIAL,
                importance_weight=3,
                fact_checkability=FactCheckability.FACT_CHECKABLE,
                verification_scope="Compare the Q1 values.",
            )
        ],
        queries=[
            SearchQueryOutput(
                query="Company X Q1 2026 net income filing",
                objective_ref="objective-primary",
                intent=EvidenceIntent.PRIMARY,
                priority=1,
            )
        ],
    )

    discovered = asyncio.run(pipeline.discover(state))
    retrieved = asyncio.run(pipeline.retrieve(discovered))
    extracted = asyncio.run(pipeline.extract(retrieved))

    assert len(discovered.candidate_sources) == 2
    assert all(snapshot.access_status == "FETCHED" for snapshot in retrieved.snapshots)
    assert len(extracted.extracted_sources) == 2
    assert all(snapshot.parser_name for snapshot in extracted.snapshots)
