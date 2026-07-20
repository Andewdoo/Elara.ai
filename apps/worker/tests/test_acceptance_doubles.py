import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from acceptance.doubles import (
    ControlledSnapshotFetcher,
    DeterministicBraveDouble,
    DeterministicDeepSeekDouble,
    WHO_PANDEMIC_CLAIM,
)
from app.config import Settings
from app.database.base import Base
from app.models import InputType, ResearchDepth as DurableResearchDepth, RunStatus, User, VerificationRun
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
from graph.runtime import execute_verification_workflow
from graph.state import WorkflowStage
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


def _who_fixture_run() -> tuple[sessionmaker[Session], VerificationRun]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(
            auth_provider="firebase",
            auth_subject="who-fixture-owner",
            email="who-fixture@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(user)
        db.flush()
        run = VerificationRun(
            user_id=user.id,
            input_type=InputType.CLAIM,
            research_depth=DurableResearchDepth.STANDARD,
            status=RunStatus.VALIDATING,
            submitted_text=WHO_PANDEMIC_CLAIM,
            normalized_target={},
            workflow_version="prompt-13-who-fixture",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
    return factory, run


def _who_fixture_adapters(tmp_path, *, include_required_evidence: bool):
    return (
        DeterministicDeepSeekDouble(WHO_PANDEMIC_CLAIM, embedding_dimension=8),
        RetrievalPipeline(
            search=DeterministicBraveDouble(
                fixture="who_pandemic", include_required_evidence=include_required_evidence
            ),
            fetcher=ControlledSnapshotFetcher(SnapshotFileStore(tmp_path / "snapshots")),
            extractor=ExtractionService(),
        ),
    )


def test_who_dated_claim_fixture_reaches_classification_and_deterministic_scoring(tmp_path):
    factory, run = _who_fixture_run()
    model, pipeline = _who_fixture_adapters(tmp_path, include_required_evidence=True)
    events: list[dict[str, object]] = []

    result = execute_verification_workflow(
        factory,
        object(),
        Settings(environment="test", passage_embedding_dimension=8),
        run.id,
        record=lambda *_args, **kwargs: events.append(kwargs),
        is_cancelled=lambda *_args: False,
        model=model,
        retrieval_pipeline=pipeline,
    )

    assert result is not None
    assert WorkflowStage.EVIDENCE_CLASSIFICATION in result.completed_stages
    assert WorkflowStage.SCORING in result.completed_stages
    assert result.scores is not None
    assert len({item.claim_ref for item in result.evidence}) == 1
    with factory() as db:
        durable = db.get(VerificationRun, run.id)
        assert durable is not None
        plan = durable.normalized_target["research_plan"]
    assert "Official WHO record dated March 11, 2020" in plan["primary_source_targets"]
    assert any(
        "WHO" in item["target"] and "March 11, 2020" in item["target"]
        for item in plan["objectives"]
    )
    assert any(event["event_type"] == "workflow.deterministic_scoring.completed" for event in events)


def test_who_dated_claim_fixture_missing_required_evidence_stops_with_typed_failure(tmp_path):
    factory, run = _who_fixture_run()
    model, pipeline = _who_fixture_adapters(tmp_path, include_required_evidence=False)

    result = execute_verification_workflow(
        factory,
        object(),
        Settings(environment="test", passage_embedding_dimension=8),
        run.id,
        record=lambda *_args, **_kwargs: None,
        is_cancelled=lambda *_args: False,
        model=model,
        retrieval_pipeline=pipeline,
    )

    assert result is not None
    assert result.ready_for_completion is False
    assert [(item.code, item.retryable) for item in result.recoverable_errors] == [
        ("NO_DISCOVERY_RESULTS", False)
    ]
