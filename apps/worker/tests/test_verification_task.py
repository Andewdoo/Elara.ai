from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.exceptions import ResponseError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database.base import Base
from agents.schemas import CitationAuditOutput
from app.models import (
    AccessStatus,
    AgentEvent,
    InputType,
    ReportCitation,
    ResearchDepth,
    RunStatus,
    Source,
    SourcePassage,
    SourceSnapshot,
    SourceType,
    User,
    VerificationRun,
)
from app.redis_client import cancellation_key, progress_stream_key, publish_progress_event
from app.services.run_lifecycle import persist_progress
from app.services.reports import build_report
from elara_worker.errors import TransientFetchError, TransientProviderError
from elara_worker.tasks import verification as task_module
from elara_worker.tasks.verification import prepare_run, verify_run
from graph.state import (
    RecoverableError,
    ResearchDepth as GraphResearchDepth,
    VerificationState,
    WorkflowStage,
)


class FakeRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict[str, str]]] = {}
        self.stream_ids: dict[str, set[str]] = {}
        self.values: dict[str, str] = {}

    def xadd(self, key: str, fields: dict[str, str], **_: object) -> str:
        event_id = str(_.get("id", f"{len(self.streams.get(key, [])) + 1}-0"))
        ids = self.stream_ids.setdefault(key, set())
        if event_id in ids:
            raise ResponseError("ID is equal or smaller than the target stream top item")
        ids.add(event_id)
        events = self.streams.setdefault(key, [])
        events.append(fields)
        return event_id

    def expire(self, _key: str, _ttl: int) -> bool:
        return True

    def exists(self, key: str) -> int:
        return int(key in self.values)


def persist_audited_report(factory, run_id):
    with factory() as db:
        run = db.get(VerificationRun, run_id)
        assert run is not None
        now = datetime(2026, 7, 4, tzinfo=UTC)
        run.title = "Production verification report"
        run.verdict = "supported"
        run.evidence_support = 90
        run.verdict_confidence = 85
        run.source_independence = 80
        run.context_completeness = 90
        run.evidence_reviewed_at = now
        source = Source(
            canonical_url=f"https://example.test/{run_id}",
            domain="example.test",
            source_type=SourceType.PRIMARY,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(source)
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id,
            version_number=1,
            retrieved_at=now,
            access_status=AccessStatus.FETCHED,
        )
        db.add(snapshot)
        db.flush()
        passage = SourcePassage(
            snapshot_id=snapshot.id,
            source_id=source.id,
            text="The controlled filing supports the narrow claim.",
            text_hash=f"hash-{run_id}",
            extraction_certainty=Decimal("1"),
        )
        db.add(passage)
        db.flush()
        db.add(
            ReportCitation(
                run_id=run.id,
                report_section="summary",
                sentence_text="The controlled filing supports the narrow claim.",
                passage_id=passage.id,
                audit_status="passed",
                audit_note="Direct support.",
            )
        )
        db.commit()
        return str(passage.id)


def ready_state(run, passage_id: str) -> VerificationState:
    return VerificationState(
        run_id=run.id,
        user_id=run.user_id,
        research_depth=GraphResearchDepth.STANDARD,
        methodology_version="1.0",
        citation_audit=CitationAuditOutput.model_validate(
            {
                "sentence_audits": [
                    {
                        "sentence_ref": "summary-1",
                        "passage_id": passage_id,
                        "entailment": "entailed",
                        "support_explanation": "Direct support.",
                    }
                ],
                "needs_revision": False,
            }
        ),
        completed_stages=[WorkflowStage.CITATION_AUDIT],
    )


def make_run(
    submitted_text: str = "A durable claim",
) -> tuple[sessionmaker[Session], VerificationRun]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject=f"subject-{uuid4()}",
            email=f"{uuid4()}@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth=ResearchDepth.STANDARD,
            status=RunStatus.QUEUED,
            submitted_text=submitted_text,
            normalized_target={},
            workflow_version="step-5-test",
        )
        db.add(run)
        db.flush()
        db.add(
            AgentEvent(
                run_id=run.id,
                sequence=1,
                stage=RunStatus.QUEUED,
                event_type="run.queued",
                public_message="Verification queued for research.",
                payload={},
            )
        )
        db.commit()
        db.expunge(run)
        return factory, run


def test_task_contract_has_bounded_transient_retries():
    assert verify_run.name == "verification.verify_run"
    assert verify_run.max_retries == 2
    assert verify_run.autoretry_for == (TransientProviderError, TransientFetchError)


def test_task_invokes_full_verification_graph_after_durable_validation(monkeypatch: pytest.MonkeyPatch):
    factory, run = make_run()
    redis_client = FakeRedis()
    settings = Settings(environment="test")
    calls: list[object] = []

    @contextmanager
    def locked(_lock):
        yield True

    monkeypatch.setattr(task_module, "get_settings", lambda: settings)
    monkeypatch.setattr(task_module, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(task_module, "run_lock", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(task_module, "acquired_lock", locked)
    monkeypatch.setattr(
        task_module,
        "execute_verification_workflow",
        lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
    )

    result = verify_run.apply(args=[str(run.id)], throw=False)

    assert result.successful()
    assert len(calls) == 1
    with factory() as db:
        durable_run = db.get(VerificationRun, run.id)
    assert durable_run is not None and durable_run.status == RunStatus.VALIDATING


def test_production_task_completes_only_after_durable_audited_report_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
):
    factory, run = make_run()
    redis_client = FakeRedis()
    settings = Settings(environment="test")
    calls = 0

    @contextmanager
    def locked(_lock):
        yield True

    def execute(factory_arg, redis_arg, settings_arg, run_id, **_kwargs):
        nonlocal calls
        calls += 1
        stages = [
            (RunStatus.DECOMPOSING, "workflow.decomposition.completed"),
            (RunStatus.RESEARCHING, "workflow.discovery_source_selection.completed"),
            (RunStatus.EXTRACTING, "workflow.extraction.completed"),
            (RunStatus.ANALYZING_PROVENANCE, "workflow.provenance_dependency_analysis.completed"),
            (RunStatus.SCORING, "workflow.numerical_audit.completed"),
            (RunStatus.SYNTHESIZING, "workflow.synthesis.completed"),
            (RunStatus.AUDITING, "workflow.citation_audit.completed"),
        ]
        for stage, event_type in stages:
            task_module._record(
                factory_arg,
                redis_arg,
                settings_arg,
                run_id=run_id,
                stage=stage,
                event_type=event_type,
                message=f"Completed {stage.value.lower()}.",
            )
        return ready_state(run, persist_audited_report(factory_arg, run_id))

    monkeypatch.setattr(task_module, "get_settings", lambda: settings)
    monkeypatch.setattr(task_module, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(task_module, "run_lock", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(task_module, "acquired_lock", locked)
    monkeypatch.setattr(task_module, "execute_verification_workflow", execute)

    first = verify_run.apply(args=[str(run.id)], throw=False)
    second = verify_run.apply(args=[str(run.id)], throw=False)

    assert first.successful() and second.successful()
    assert calls == 1
    with factory() as db:
        durable = db.get(VerificationRun, run.id)
        events = db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence)
        ).all()
        citations = db.scalars(
            select(ReportCitation).where(ReportCitation.run_id == run.id)
        ).all()
        report = build_report(db, run=durable)
    assert durable is not None and durable.status == RunStatus.COMPLETED
    collapsed = list(dict.fromkeys(event.stage for event in events))
    assert collapsed == [
        RunStatus.QUEUED,
        RunStatus.VALIDATING,
        RunStatus.DECOMPOSING,
        RunStatus.RESEARCHING,
        RunStatus.EXTRACTING,
        RunStatus.ANALYZING_PROVENANCE,
        RunStatus.SCORING,
        RunStatus.SYNTHESIZING,
        RunStatus.AUDITING,
        RunStatus.COMPLETED,
    ]
    assert events[-1].event_type == "run.completed"
    assert len([event for event in events if event.event_type == "run.completed"]) == 1
    assert len(citations) == 1
    assert report.report_sentences[0].audit_status == "passed"
    stream = redis_client.streams[progress_stream_key(run.id)]
    assert stream[-1]["event_type"] == "run.completed"


def test_completion_cancellation_race_is_won_by_cancellation(
    monkeypatch: pytest.MonkeyPatch,
):
    factory, run = make_run()
    redis_client = FakeRedis()
    settings = Settings(environment="test")

    @contextmanager
    def locked(_lock):
        yield True

    def execute(factory_arg, redis_arg, settings_arg, run_id, **_kwargs):
        task_module._record(
            factory_arg,
            redis_arg,
            settings_arg,
            run_id=run_id,
            stage=RunStatus.AUDITING,
            event_type="workflow.citation_audit.completed",
            message="Completed citation audit.",
        )
        passage_id = persist_audited_report(factory_arg, run_id)
        with factory_arg() as db:
            durable = db.get(VerificationRun, run_id)
            assert durable is not None
            durable.cancellation_requested_at = datetime.now(UTC)
            db.commit()
        return ready_state(run, passage_id)

    monkeypatch.setattr(task_module, "get_settings", lambda: settings)
    monkeypatch.setattr(task_module, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(task_module, "run_lock", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(task_module, "acquired_lock", locked)
    monkeypatch.setattr(task_module, "execute_verification_workflow", execute)

    result = verify_run.apply(args=[str(run.id)], throw=False)

    assert result.successful()
    with factory() as db:
        durable = db.get(VerificationRun, run.id)
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.id)
        ).all()
    assert durable is not None and durable.status == RunStatus.CANCELLED
    assert not any(event.event_type == "run.completed" for event in events)


def test_synthetic_hosted_run_invalid_research_plan_is_durable_nonretryable_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    factory, run = make_run("Synthetic public claim: the city published its annual budget.")
    redis_client = FakeRedis()
    settings = Settings(environment="test")

    @contextmanager
    def locked(_lock):
        yield True

    stopped = VerificationState(
        run_id=run.id,
        user_id=run.user_id,
        research_depth=GraphResearchDepth.STANDARD,
        methodology_version="1.0",
        recoverable_errors=[
            RecoverableError(
                stage=WorkflowStage.PLANNER,
                code="INVALID_RESEARCH_PLAN",
                public_message="Research planning returned invalid references.",
            )
        ],
    )
    assert stopped.ready_for_completion is False
    assert stopped.recoverable_errors[-1].retryable is False
    monkeypatch.setattr(task_module, "get_settings", lambda: settings)
    monkeypatch.setattr(task_module, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(task_module, "run_lock", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(task_module, "acquired_lock", locked)
    monkeypatch.setattr(task_module, "execute_verification_workflow", lambda *_args, **_kwargs: stopped)

    result = verify_run.apply(args=[str(run.id)], throw=False)

    assert result.successful()
    with factory() as db:
        durable_run = db.get(VerificationRun, run.id)
        last_event = db.scalar(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence.desc())
            .limit(1)
        )
    assert durable_run is not None and durable_run.status == RunStatus.FAILED
    assert durable_run.failure_code == "INVALID_RESEARCH_PLAN"
    assert last_event is not None and last_event.event_type == "run.failed"
    with factory() as db:
        completed = db.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == run.id,
                AgentEvent.event_type == "run.completed",
            )
        )
    assert completed is None


def test_task_rejects_exhausted_citation_revision(monkeypatch: pytest.MonkeyPatch):
    factory, run = make_run()
    redis_client = FakeRedis()

    @contextmanager
    def locked(_lock):
        yield True

    stopped = VerificationState(
        run_id=run.id,
        user_id=run.user_id,
        research_depth=GraphResearchDepth.STANDARD,
        methodology_version="1.0",
        recoverable_errors=[
            RecoverableError(
                stage=WorkflowStage.CITATION_REVISION,
                code="CITATION_REVISION_EXHAUSTED",
                public_message=(
                    "The report could not be fully supported after bounded citation revision."
                ),
            )
        ],
    )
    monkeypatch.setattr(task_module, "get_settings", lambda: Settings(environment="test"))
    monkeypatch.setattr(task_module, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(task_module, "run_lock", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(task_module, "acquired_lock", locked)
    monkeypatch.setattr(
        task_module, "execute_verification_workflow", lambda *_args, **_kwargs: stopped
    )

    result = verify_run.apply(args=[str(run.id)], throw=False)

    assert result.successful()
    with factory() as db:
        durable = db.get(VerificationRun, run.id)
        completed = db.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == run.id,
                AgentEvent.event_type == "run.completed",
            )
        )
    assert durable is not None and durable.status == RunStatus.FAILED
    assert durable.failure_code == "CITATION_REVISION_EXHAUSTED"
    assert completed is None


@pytest.mark.parametrize(
    ("error", "failure_code"),
    [
        (TransientProviderError("provider detail"), "PROVIDER_UNAVAILABLE"),
        (TransientFetchError("fetch detail"), "FETCH_UNAVAILABLE"),
    ],
)
def test_transient_failures_retry_twice_then_use_public_code(
    monkeypatch: pytest.MonkeyPatch, error: Exception, failure_code: str
):
    attempts: list[int] = []
    failures: list[dict[str, object]] = []

    @contextmanager
    def locked(_lock):
        yield True

    def fail_prepare(*_args, **_kwargs):
        attempts.append(1)
        raise error

    monkeypatch.setattr(task_module, "get_settings", lambda: Settings(environment="test"))
    monkeypatch.setattr(task_module, "get_redis_client", lambda: object())
    monkeypatch.setattr(task_module, "get_session_factory", lambda: object())
    monkeypatch.setattr(task_module, "run_lock", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(task_module, "acquired_lock", locked)
    monkeypatch.setattr(task_module, "prepare_run", fail_prepare)
    monkeypatch.setattr(
        task_module,
        "_mark_failure_safely",
        lambda *_args, **kwargs: failures.append(kwargs),
    )

    result = verify_run.apply(args=[str(uuid4())], throw=False)

    assert result.failed()
    assert len(attempts) == 3
    assert failures == [
        {
            "code": failure_code,
            "message": "A temporary research service remained unavailable after retries.",
        }
    ]


def test_prepare_run_loads_postgres_and_mirrors_public_progress():
    factory, run = make_run()
    redis_client = FakeRedis()
    settings = Settings(environment="test")

    prepare_run(factory, redis_client, settings, run.id)

    with factory() as db:
        durable_run = db.get(VerificationRun, run.id)
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.sequence)
        ).all()
    assert durable_run is not None and durable_run.status == RunStatus.VALIDATING
    assert durable_run.started_at is not None
    assert [event.event_type for event in events] == [
        "run.queued",
        "run.validating",
        "run.validated",
    ]
    stream_events = redis_client.streams[progress_stream_key(run.id)]
    assert [event["event_type"] for event in stream_events] == [
        "run.queued",
        "run.validating",
        "run.validated",
    ]
    assert all("reasoning" not in event["payload"].lower() for event in stream_events)


def test_prepare_run_is_idempotent_after_validation():
    factory, run = make_run()
    redis_client = FakeRedis()
    settings = Settings(environment="test")

    prepare_run(factory, redis_client, settings, run.id)
    prepare_run(factory, redis_client, settings, run.id)

    with factory() as db:
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.sequence)
        ).all()
    assert [event.event_type for event in events] == [
        "run.queued",
        "run.validating",
        "run.validated",
    ]


def test_resume_backfills_a_durable_event_missing_from_redis():
    factory, run = make_run()
    redis_client = FakeRedis()
    settings = Settings(environment="test")
    publish_progress_event(
        redis_client,
        settings=settings,
        run_id=run.id,
        sequence=1,
        stage="QUEUED",
        event_type="run.queued",
        message="Verification queued for research.",
        payload={},
        created_at="2026-06-27T00:00:00+00:00",
    )
    with factory() as db:
        persist_progress(
            db,
            run_id=run.id,
            stage=RunStatus.VALIDATING,
            event_type="run.validating",
            message="Validating input.",
        )

    prepare_run(factory, redis_client, settings, run.id)

    stream = redis_client.streams[progress_stream_key(run.id)]
    assert [event["sequence"] for event in stream] == ["1", "2", "3"]


def test_redelivery_never_rewinds_a_later_durable_stage():
    factory, run = make_run()
    with factory() as db:
        durable_run = db.get(VerificationRun, run.id)
        assert durable_run is not None
        durable_run.status = RunStatus.RESEARCHING
        db.commit()

    prepare_run(factory, FakeRedis(), Settings(environment="test"), run.id)

    with factory() as db:
        durable_run = db.get(VerificationRun, run.id)
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.sequence)
        ).all()
    assert durable_run is not None and durable_run.status == RunStatus.RESEARCHING
    assert [event.event_type for event in events] == ["run.queued"]


def test_prepare_run_observes_cancellation_before_work_starts():
    factory, run = make_run()
    redis_client = FakeRedis()
    redis_client.values[cancellation_key(run.id)] = "1"

    prepare_run(factory, redis_client, Settings(environment="test"), run.id)

    with factory() as db:
        durable_run = db.get(VerificationRun, run.id)
        last_event = db.scalar(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence.desc())
            .limit(1)
        )
    assert durable_run is not None and durable_run.status == RunStatus.CANCELLED
    assert last_event is not None and last_event.event_type == "run.cancelled"
