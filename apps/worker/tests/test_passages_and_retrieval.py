from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.deepseek_client import DeepSeekClient, DeepSeekConfig
from app.database.base import Base
from app.database.constants import PASSAGE_EMBEDDING_DIMENSION
from app.models.enums import AccessStatus, InputType, RunStatus, SourceType
from app.models.sources import RunSource, Source, SourcePassage, SourceSnapshot
from app.models.user import User
from app.models.verification_run import VerificationRun
from extraction.passages import PassageEmbeddingService, PassageSegmenter, hash_passage_text
from extraction.html import extract_with_beautiful_soup
from graph.runtime import SqlWorkflowStateWriter
from graph.state import (
    EmbeddingRunMetadata,
    ExtractedBlockRecord,
    ExtractedSourceRecord,
    ResearchDepth,
    SnapshotRecord,
    VerificationState,
    WorkflowStage,
)
from research.passage_retrieval import (
    HybridPassageSearchService,
    PassageRetriever,
    exact_match_score,
    rank_classification_candidates,
)


def _state(*, blocks: list[ExtractedBlockRecord], body: str = "body") -> VerificationState:
    snapshot_id = str(uuid4())
    return VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        snapshots=[
            SnapshotRecord(
                snapshot_id=snapshot_id,
                source_ref="source-1",
                access_status="FETCHED",
                retrieved_at=datetime(2026, 6, 29, tzinfo=UTC),
                extraction_quality=Decimal("0.93"),
            )
        ],
        extracted_sources=[
            ExtractedSourceRecord(
                source_ref="source-1",
                snapshot_id=snapshot_id,
                body=body,
                blocks=blocks,
            )
        ],
    )


def test_html_extraction_captures_heading_transcript_and_labeled_table_rows():
    filler = "Evidence context remains attached to the paragraph. " * 5
    document = extract_with_beautiful_soup(
        f"""
        <html><head><title>Report</title></head><body><article>
          <h1>Annual Results</h1>
          <p>ALICE: Revenue increased in the reporting period. {filler}</p>
          <table><tr><th>Metric</th><th>2026</th></tr><tr><td>Revenue</td><td>42</td></tr></table>
        </article></body></html>
        """.encode(),
        url="https://example.test/report",
    )

    assert document is not None
    assert any(block.kind == "transcript_turn" and block.speaker == "ALICE" for block in document.blocks)
    row = next(block for block in document.blocks if block.table_ref == "table 1 row 2")
    assert row.text == "Metric: Revenue | 2026: 42"
    assert row.heading_path == ("Annual Results",)


def test_segmenter_preserves_structure_exact_text_hash_and_limited_overlap():
    long_text = " ".join(f"Sentence {index} has evidence." for index in range(100))
    state = _state(
        blocks=[
            ExtractedBlockRecord(kind="heading", text="Results", heading_path=["Report", "Results"]),
            ExtractedBlockRecord(
                kind="transcript_turn",
                text="ALICE: The identifier ABC-42 rose to 17.5%.",
                heading_path=["Report", "Results"],
                page_or_position="page 3",
                paragraph_index=7,
                speaker="ALICE",
            ),
            ExtractedBlockRecord(
                kind="table_row",
                text="Metric: Revenue | 2026: 42",
                heading_path=["Report", "Results"],
                page_or_position="page 4, table 1, row 2",
                table_ref="page 4 table 1 row 2",
                metadata={"column_labels": ["Metric", "2026"]},
            ),
            ExtractedBlockRecord(kind="paragraph", text=long_text, paragraph_index=8),
        ]
    )

    passages = PassageSegmenter(max_chars=400, overlap_chars=60).segment(state)
    repeated = PassageSegmenter(max_chars=400, overlap_chars=60).segment(state)

    transcript = passages[0]
    assert transcript.text == "ALICE: The identifier ABC-42 rose to 17.5%."
    assert transcript.text_hash == hash_passage_text(transcript.text)
    assert [item.passage_id for item in passages] == [item.passage_id for item in repeated]
    assert transcript.heading_path == "Report > Results"
    assert transcript.page_or_position == "page 3"
    assert transcript.paragraph_index == 7
    assert transcript.speaker == "ALICE"
    table = passages[1]
    assert table.table_ref == "page 4 table 1 row 2"
    assert table.metadata["column_labels"] == ["Metric", "2026"]
    assert any(item.metadata["has_boundary_overlap"] for item in passages[3:])
    assert all(len(item.text) <= 400 for item in passages)


def test_quote_passage_retains_exact_quote_with_speaker_and_surrounding_context():
    state = _state(
        blocks=[
            ExtractedBlockRecord(
                kind="transcript_turn",
                text="ALICE: This is the surrounding introduction.",
                speaker="ALICE",
            ),
            ExtractedBlockRecord(kind="quote", text="Revenue increased by 12 percent."),
            ExtractedBlockRecord(kind="paragraph", text="The filing then explains the comparison period."),
        ]
    )

    quote = PassageSegmenter().segment(state)[1]

    assert quote.speaker == "ALICE"
    assert quote.metadata["exact_quote"] == "Revenue increased by 12 percent."
    assert quote.metadata["quote_context_attached"] is True
    assert "surrounding introduction" in quote.text
    assert "comparison period" in quote.text


def test_embeddings_use_configured_deepseek_route_and_fallback_when_unavailable():
    captured_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "model": "approved-embedding-v1",
                "data": [{"index": 0, "embedding": [1.0, 0.0, 0.5]}],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            },
        )

    state = _state(blocks=[ExtractedBlockRecord(kind="paragraph", text="Evidence passage")])
    passages = PassageSegmenter().segment(state)

    async def exercise(configured: bool):
        transport = httpx.MockTransport(handler)
        http = httpx.AsyncClient(transport=transport)
        client = DeepSeekClient(
            DeepSeekConfig(
                api_key="secret",
                base_url="https://deepseek.example.test/v1",
                chat_model="chat",
                reasoning_model="reasoner",
                embedding_model="approved-embedding-v1" if configured else None,
            ),
            http_client=http,
        )
        try:
            return await PassageEmbeddingService(client, expected_dimension=3).apply(state, passages)
        finally:
            await http.aclose()

    embedded = asyncio.run(exercise(True))
    fallback = asyncio.run(exercise(False))

    assert captured_paths == ["/v1/embeddings"]
    assert embedded.passage_retrieval_mode == "hybrid"
    assert embedded.passages[0].embedding == [1.0, 0.0, 0.5]
    assert embedded.passages[0].embedding_model == "approved-embedding-v1"
    assert embedded.embedding_run_metadata is not None
    assert embedded.embedding_run_metadata.status == "embedded"
    assert embedded.embedding_run_metadata.prompt_tokens == 3
    assert fallback.passage_retrieval_mode == "lexical_metadata_fallback"
    assert fallback.passages[0].embedding is None
    assert fallback.embedding_run_metadata is not None
    assert fallback.embedding_run_metadata.status == "unconfigured_fallback"


def test_pgvector_cosine_operator_is_used_for_vector_candidate_search():
    statement = select(SourcePassage.id).order_by(
        SourcePassage.embedding.cosine_distance([0.0] * PASSAGE_EMBEDDING_DIMENSION)
    )

    compiled = str(statement.compile(dialect=postgresql_dialect()))

    assert "<=>" in compiled
    lexical = str(
        PassageRetriever._postgresql_lexical_query(uuid4(), '"Revenue" 2026').compile(
            dialect=postgresql_dialect()
        )
    )
    assert "to_tsvector" in lexical
    assert "websearch_to_tsquery" in lexical


def test_classification_candidates_are_bounded_by_research_depth_and_deterministic():
    claims = [
        SimpleNamespace(claim_ref=f"claim-{index}", text=f"Claim {index} value {index}")
        for index in range(1, 26)
    ]
    passages = [
        SimpleNamespace(
            passage_id=f"passage-{index}",
            text=f"Passage {index} confirms value {index}",
            extraction_certainty=Decimal("0.95"),
        )
        for index in range(1, 26)
    ]

    quick = rank_classification_candidates(claims, passages, research_depth="QUICK")
    standard = rank_classification_candidates(claims, passages, research_depth="STANDARD")
    deep = rank_classification_candidates(claims, passages, research_depth="DEEP")

    assert len(quick) == 5
    assert len(standard) == 10
    assert len(deep) == 20
    assert quick == rank_classification_candidates(claims, passages, research_depth="QUICK")
    assert len({(item.claim_ref, item.passage_id) for item in deep}) == len(deep)


def test_embedding_provider_failure_is_a_durable_lexical_fallback():
    state = _state(blocks=[ExtractedBlockRecord(kind="paragraph", text="Evidence passage")])
    passages = PassageSegmenter().segment(state)

    async def exercise():
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(503, json={}))
        )
        client = DeepSeekClient(
            DeepSeekConfig(
                api_key="secret",
                base_url="https://deepseek.example.test/v1",
                chat_model="chat",
                reasoning_model="reasoner",
                embedding_model="approved-embedding-v1",
            ),
            http_client=http,
        )
        try:
            return await PassageEmbeddingService(client, expected_dimension=3).apply(
                state, passages
            )
        finally:
            await http.aclose()

    result = asyncio.run(exercise())

    assert result.passage_retrieval_mode == "lexical_metadata_fallback"
    assert result.embedding_run_metadata is not None
    assert result.embedding_run_metadata.status == "provider_fallback"
    assert result.embedding_run_metadata.status_code == 503
    assert result.embedding_run_metadata.error_code == "provider_unavailable"
    assert result.embedding_run_metadata.retryable is True
    assert result.embedding_run_metadata.request_count == 1


def test_hybrid_search_generates_query_vector_only_through_deepseek_client():
    captured: dict[str, object] = {}

    class CapturingRetriever:
        def search(self, _db, **kwargs):
            captured.update(kwargs)
            return []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "approved-embedding-v1",
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
            },
        )

    async def exercise():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(
            DeepSeekConfig(
                api_key="secret",
                base_url="https://deepseek.example.test/v1",
                chat_model="chat",
                reasoning_model="reasoner",
                embedding_model="approved-embedding-v1",
            ),
            http_client=http,
        )
        try:
            service = HybridPassageSearchService(
                client,
                expected_dimension=3,
                retriever=CapturingRetriever(),  # type: ignore[arg-type]
            )
            return await service.search(
                object(),  # type: ignore[arg-type]
                run_id=uuid4(),
                query="Revenue in 2026",
                query_vector=[9.0, 9.0, 9.0],
            )
        finally:
            await http.aclose()

    response = asyncio.run(exercise())

    assert response.retrieval_mode == "hybrid"
    assert captured["query_vector"] == [0.1, 0.2, 0.3]


def test_passages_persist_model_version_and_hybrid_retrieval_only_ranks_candidates():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 6, 29, tzinfo=UTC)
    snapshot_id = uuid4()
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="passage-owner",
            email="passages@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth="STANDARD",
            status=RunStatus.EXTRACTING,
            submitted_text="Revenue was 42 in 2026",
            normalized_target={},
            workflow_version="step-10-test",
        )
        source = Source(
            canonical_url="https://example.test/report",
            domain="example.test",
            source_type=SourceType.PRIMARY,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add_all([run, source])
        db.flush()
        snapshot = SourceSnapshot(
            id=snapshot_id,
            source_id=source.id,
            version_number=1,
            retrieved_at=now,
            access_status=AccessStatus.FETCHED,
            content_hash="snapshot-hash",
            extraction_quality=Decimal("0.95"),
            snapshot_metadata={},
        )
        db.add(snapshot)
        db.flush()
        db.add(
            RunSource(
                run_id=run.id,
                source_id=source.id,
                snapshot_id=snapshot.id,
                role="PRIMARY",
                retrieval_reason="direct record",
            )
        )
        db.commit()
        run_id, user_id = run.id, owner.id

    state = VerificationState(
        run_id=run_id,
        user_id=user_id,
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        snapshots=[
            SnapshotRecord(
                snapshot_id=str(snapshot_id),
                source_ref="source-1",
                access_status="FETCHED",
                retrieved_at=now,
                extraction_quality=Decimal("0.95"),
            )
        ],
        extracted_sources=[
            ExtractedSourceRecord(
                source_ref="source-1",
                snapshot_id=str(snapshot_id),
                body="Revenue was 42 in 2026.",
                blocks=[
                    ExtractedBlockRecord(
                        kind="table_row",
                        text="Metric: Revenue | 2026: 42",
                        heading_path=["Annual results"],
                        table_ref="table 1 row 2",
                    ),
                    ExtractedBlockRecord(kind="paragraph", text="Unrelated background material."),
                ],
            )
        ],
        embedding_model_version="approved-embedding-v1",
        passage_retrieval_mode="hybrid",
        embedding_run_metadata=EmbeddingRunMetadata(
            configured_model="approved-embedding-v1",
            used_model="approved-embedding-v1",
            status="embedded",
            request_count=1,
            latency_ms=12,
            prompt_tokens=8,
            total_tokens=8,
        ),
    )
    passages = PassageSegmenter().segment(state)
    passages[0] = passages[0].model_copy(
        update={"embedding": [1.0, 0.0, 0.0], "embedding_model": "approved-embedding-v1"}
    )
    passages[1] = passages[1].model_copy(
        update={"embedding": [0.0, 1.0, 0.0], "embedding_model": "approved-embedding-v1"}
    )
    state = state.model_copy(update={"passages": passages}).complete(WorkflowStage.SEGMENTATION)
    asyncio.run(SqlWorkflowStateWriter(factory).save(stage=WorkflowStage.SEGMENTATION, state=state))

    with factory() as db:
        run = db.get(VerificationRun, run_id)
        assert run.model_versions["embedding"] == {
            "provider": "deepseek",
            "configured_model": "approved-embedding-v1",
            "used_model": "approved-embedding-v1",
            "status": "embedded",
            "request_count": 1,
            "latency_ms": 12,
            "prompt_tokens": 8,
            "total_tokens": 8,
            "error_code": None,
            "status_code": None,
            "retryable": False,
            "retrieval_mode": "hybrid",
        }
        stored = db.scalars(select(SourcePassage)).all()
        assert len(stored) == 2
        results = PassageRetriever().search(
            db,
            run_id=run_id,
            query='"Revenue" ABC-42 2026 42',
            query_vector=[1.0, 0.0, 0.0],
            metadata={"heading": "Annual results", "document_type": "table"},
            limit=2,
        )

    assert results[0].passage.table_ref == "table 1 row 2"
    assert results[0].vector_similarity == Decimal("1")
    assert results[0].retrieval_only is True
    assert exact_match_score('identifier ABC-42 and value 42', "ABC-42 equals 42") == Decimal("1")
