from contextlib import contextmanager
from uuid import uuid4

import pytest
from redis.exceptions import ResponseError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database.base import Base
from app.models import AgentEvent, InputType, ResearchDepth, RunStatus, User, VerificationRun
from app.redis_client import cancellation_key, progress_stream_key, publish_progress_event
from app.services.run_lifecycle import persist_progress
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


def make_run() -> tuple[sessionmaker[Session], VerificationRun]:
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
            submitted_text="A durable claim",
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


def test_task_invokes_planning_graph_after_durable_validation(monkeypatch: pytest.MonkeyPatch):
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
        "execute_planning_workflow",
        lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
    )

    result = verify_run.apply(args=[str(run.id)], throw=False)

    assert result.successful()
    assert len(calls) == 1
    with factory() as db:
        durable_run = db.get(VerificationRun, run.id)
    assert durable_run is not None and durable_run.status == RunStatus.VALIDATING


def test_task_marks_nonretryable_workflow_stop_failed(monkeypatch: pytest.MonkeyPatch):
    factory, run = make_run()
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
    monkeypatch.setattr(task_module, "get_settings", lambda: settings)
    monkeypatch.setattr(task_module, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(task_module, "run_lock", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(task_module, "acquired_lock", locked)
    monkeypatch.setattr(task_module, "execute_planning_workflow", lambda *_args, **_kwargs: stopped)

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
