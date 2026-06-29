import logging
from uuid import UUID

from celery import Task
from redis import Redis
from sqlalchemy import exists, select
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.config import Settings, get_settings
from app.database.session import get_session_factory
from app.models.enums import RunStatus
from app.models.verification_run import VerificationRun
from app.redis_client import (
    acquired_lock,
    get_redis_client,
    has_cancellation_flag,
    run_lock,
)
from app.services.run_lifecycle import (
    TERMINAL_STATUSES,
    TerminalRunTransitionError,
    cancellation_requested,
    mirror_agent_event,
    persist_progress,
)
from elara_worker.errors import TransientFetchError, TransientProviderError
from graph.runtime import execute_planning_workflow


logger = logging.getLogger(__name__)


def _load_run(factory: sessionmaker[Session], run_id: UUID) -> VerificationRun:
    with factory() as db:
        run = db.scalar(select(VerificationRun).where(VerificationRun.id == run_id))
        if run is None:
            raise LookupError(f"Verification run {run_id} does not exist")
        db.expunge(run)
        return run


def _is_cancelled(
    factory: sessionmaker[Session], redis_client: Redis, run_id: UUID
) -> bool:
    try:
        if has_cancellation_flag(redis_client, run_id):
            return True
    except Exception:
        logger.warning("Redis cancellation lookup failed for run %s", run_id)
    with factory() as db:
        return cancellation_requested(db, run_id)


def _has_durable_event(
    factory: sessionmaker[Session], run_id: UUID, event_type: str
) -> bool:
    from app.models.agent_event import AgentEvent

    with factory() as db:
        return bool(
            db.scalar(
                select(exists().where(AgentEvent.run_id == run_id, AgentEvent.event_type == event_type))
            )
        )


def _backfill_progress(
    factory: sessionmaker[Session],
    redis_client: Redis,
    settings: Settings,
    run_id: UUID,
) -> None:
    from app.models.agent_event import AgentEvent

    with factory() as db:
        events = db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id)
            .order_by(AgentEvent.sequence)
        ).all()
    for event in events:
        try:
            mirror_agent_event(redis_client, settings=settings, event=event)
        except Exception:
            logger.warning("Unable to backfill progress for run %s", run_id)
            break


def _record(
    factory: sessionmaker[Session],
    redis_client: Redis,
    settings: Settings,
    *,
    run_id: UUID,
    stage: RunStatus,
    event_type: str,
    message: str,
    payload: dict[str, object] | None = None,
    failure_code: str | None = None,
) -> None:
    with factory() as db:
        persist_progress(
            db,
            run_id=run_id,
            stage=stage,
            event_type=event_type,
            message=message,
            payload=payload,
            failure_code=failure_code,
        )
    # Backfill in sequence order so a temporary Redis outage cannot create a
    # permanent hole before a later event.
    _backfill_progress(factory, redis_client, settings, run_id)


def _cancel_if_requested(
    factory: sessionmaker[Session],
    redis_client: Redis,
    settings: Settings,
    run_id: UUID,
) -> bool:
    if not _is_cancelled(factory, redis_client, run_id):
        return False
    run = _load_run(factory, run_id)
    if run.status not in TERMINAL_STATUSES:
        _record(
            factory,
            redis_client,
            settings,
            run_id=run_id,
            stage=RunStatus.CANCELLED,
            event_type="run.cancelled",
            message="Verification cancelled before the next expensive stage.",
        )
    return True


def prepare_run(
    factory: sessionmaker[Session],
    redis_client: Redis,
    settings: Settings,
    run_id: UUID,
) -> None:
    """Validate durable input and establish the handoff boundary for Step 8.

    This task intentionally does not synthesize a result. The controlled LangGraph
    stages are added later and must call ``_cancel_if_requested`` before every
    provider, search, fetch, extraction, and browser-rendering stage.
    """
    _backfill_progress(factory, redis_client, settings, run_id)
    run = _load_run(factory, run_id)
    if run.status in TERMINAL_STATUSES:
        return
    if run.status == RunStatus.VALIDATING:
        if _cancel_if_requested(factory, redis_client, settings, run_id):
            return
        if not _has_durable_event(factory, run_id, "run.validated"):
            _record(
                factory,
                redis_client,
                settings,
                run_id=run_id,
                stage=RunStatus.VALIDATING,
                event_type="run.validated",
                message="Verification target validated and ready for research.",
                payload={"completed_steps": 0, "total_steps": 13},
            )
        return
    if run.status != RunStatus.QUEUED:
        # A redelivered task must never rewind durable workflow progress.
        return
    if not any((run.submitted_text, run.submitted_url, run.upload_object_path)):
        _record(
            factory,
            redis_client,
            settings,
            run_id=run_id,
            stage=RunStatus.FAILED,
            event_type="run.failed",
            message="Verification input is unavailable.",
            failure_code="INVALID_RUN_INPUT",
        )
        return
    if _cancel_if_requested(factory, redis_client, settings, run_id):
        return
    _record(
        factory,
        redis_client,
        settings,
        run_id=run_id,
        stage=RunStatus.VALIDATING,
        event_type="run.validating",
        message="Validating the submitted verification target.",
        payload={"completed_steps": 0, "total_steps": 13},
    )
    if _cancel_if_requested(factory, redis_client, settings, run_id):
        return
    _record(
        factory,
        redis_client,
        settings,
        run_id=run_id,
        stage=RunStatus.VALIDATING,
        event_type="run.validated",
        message="Verification target validated and ready for research.",
        payload={"completed_steps": 0, "total_steps": 13},
    )


def _mark_failure_safely(
    factory: sessionmaker[Session],
    redis_client: Redis,
    settings: Settings,
    run_id: UUID,
    *,
    code: str,
    message: str,
) -> None:
    try:
        run = _load_run(factory, run_id)
        if run.status not in TERMINAL_STATUSES:
            _record(
                factory,
                redis_client,
                settings,
                run_id=run_id,
                stage=RunStatus.FAILED,
                event_type="run.failed",
                message=message,
                failure_code=code,
            )
    except Exception:
        logger.exception("Unable to persist failure state for run %s", run_id)


@celery_app.task(
    name="verification.verify_run",
    bind=True,
    autoretry_for=(TransientProviderError, TransientFetchError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
)
def verify_run(self: Task, run_id: str) -> None:
    parsed_run_id = UUID(run_id)
    settings = get_settings()
    redis_client = get_redis_client()
    factory = get_session_factory()
    try:
        with acquired_lock(run_lock(redis_client, settings=settings, run_id=parsed_run_id)) as acquired:
            if not acquired:
                logger.info("Run %s is already owned by another worker", parsed_run_id)
                return
            prepare_run(factory, redis_client, settings, parsed_run_id)
            if _cancel_if_requested(factory, redis_client, settings, parsed_run_id):
                return
            result = execute_planning_workflow(
                factory,
                redis_client,
                settings,
                parsed_run_id,
                record=_record,
                is_cancelled=_is_cancelled,
            )
            if result is not None and any(error.retryable for error in result.recoverable_errors):
                raise TransientProviderError("A recoverable language-analysis step failed")
            if result is not None and result.recoverable_errors:
                error = result.recoverable_errors[-1]
                _mark_failure_safely(
                    factory,
                    redis_client,
                    settings,
                    parsed_run_id,
                    code=error.code,
                    message=error.public_message,
                )
    except TerminalRunTransitionError:
        # Cancellation can win the race after the pre-stage check. The durable
        # terminal status is authoritative and is a successful no-op here.
        return
    except (TransientProviderError, TransientFetchError) as exc:
        if self.request.retries >= 2:
            code = (
                "PROVIDER_UNAVAILABLE"
                if isinstance(exc, TransientProviderError)
                else "FETCH_UNAVAILABLE"
            )
            _mark_failure_safely(
                factory,
                redis_client,
                settings,
                parsed_run_id,
                code=code,
                message="A temporary research service remained unavailable after retries.",
            )
        raise
    except Exception:
        _mark_failure_safely(
            factory,
            redis_client,
            settings,
            parsed_run_id,
            code="WORKER_ERROR",
            message="Verification stopped because the worker encountered an error.",
        )
        raise
