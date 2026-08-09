import logging
import time
from uuid import UUID

from celery import Task
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import exists, select
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import VERIFICATION_QUEUES, celery_app
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
    RUN_STATUS_ORDER,
    TERMINAL_STATUSES,
    InvalidRunTransitionError,
    TerminalRunTransitionError,
    cancellation_requested,
    mirror_agent_event,
    persist_progress,
    persist_completed_run,
)
from elara_worker.errors import (
    TransientFetchError,
    TransientProviderError,
    is_retryable_workflow_error,
)
from graph.runtime import execute_verification_workflow
from graph.state import ResearchDepth as GraphResearchDepth, VerificationState
from observability import (
    build_run_metrics,
    emit_metrics,
    initialize_worker_sentry,
    queue_length,
    safe_trace,
)


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
                select(
                    exists().where(
                        AgentEvent.run_id == run_id, AgentEvent.event_type == event_type
                    )
                )
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
    internal_failure_detail: str | None = None,
) -> None:
    if _has_durable_event(factory, run_id, event_type):
        _backfill_progress(factory, redis_client, settings, run_id)
        return
    current = _load_run(factory, run_id)
    if stage not in {RunStatus.FAILED, RunStatus.CANCELLED} and RUN_STATUS_ORDER.get(
        stage, 0
    ) < RUN_STATUS_ORDER.get(current.status, 0):
        return
    with factory() as db:
        persist_progress(
            db,
            run_id=run_id,
            stage=stage,
            event_type=event_type,
            message=message,
            payload=payload,
            failure_code=failure_code,
            internal_failure_detail=internal_failure_detail,
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
    details: dict[str, object] | None = None,
    internal_failure_detail: str | None = None,
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
                payload=_public_failure_payload(code, details),
                failure_code=code,
                internal_failure_detail=internal_failure_detail,
            )
    except Exception:
        logger.error(
            "Unable to persist failure state for run %s", run_id, exc_info=False
        )


def _public_failure_payload(
    code: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Keep terminal events actionable without retaining operational detail.

    Workflow extension details are scalar by contract, but scalar text can still
    be an URL, a provider response, or an internal exception.  The public
    durable event needs only the stable failure code and bounded counts.  Raw
    diagnostics stay in server-side logs/monitoring.
    """
    safe_structured_subtypes = {
        "response_json",
        "choices_envelope",
        "message_content_type",
        "content_json",
        "usage_metadata",
        "output_schema",
    }
    payload: dict[str, object] = {"code": code}
    for key, value in (details or {}).items():
        if key == "structured_failure_subtype" and value in safe_structured_subtypes:
            payload[key] = value
            continue
        if (
            key.endswith("_count")
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        ):
            payload[key] = value
    return payload


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
    initialize_worker_sentry(settings)
    redis_client = get_redis_client()
    factory = get_session_factory()
    started = time.perf_counter()
    result: VerificationState | None = None
    try:
        with acquired_lock(
            run_lock(redis_client, settings=settings, run_id=parsed_run_id)
        ) as acquired:
            if not acquired:
                logger.info("Run %s is already owned by another worker", parsed_run_id)
                return
            prepare_run(factory, redis_client, settings, parsed_run_id)
            if _cancel_if_requested(factory, redis_client, settings, parsed_run_id):
                return
            durable_before_work = _load_run(factory, parsed_run_id)
            if (
                durable_before_work.status in TERMINAL_STATUSES
                or durable_before_work.publication_state
                in {"review_required", "approved", "rejected", "revision_required"}
            ):
                return
            with safe_trace(
                "verification.run",
                metadata={
                    "run_id": str(parsed_run_id),
                    "workflow_version": settings.workflow_version,
                    "retry_count": self.request.retries,
                    "environment": settings.environment,
                },
            ) as trace:
                workflow_kwargs = {}
                if settings.acceptance_test_mode:
                    from acceptance.doubles import build_acceptance_adapters

                    durable_run = _load_run(factory, parsed_run_id)
                    model, retrieval_pipeline = build_acceptance_adapters(
                        settings,
                        durable_run.submitted_text or durable_run.submitted_url or "",
                    )
                    workflow_kwargs = {
                        "model": model,
                        "retrieval_pipeline": retrieval_pipeline,
                    }
                result = execute_verification_workflow(
                    factory,
                    redis_client,
                    settings,
                    parsed_run_id,
                    record=_record,
                    is_cancelled=_is_cancelled,
                    retrieve=True,
                    **workflow_kwargs,
                )
                if result is not None:
                    trace.add_outputs(
                        {
                            "completed_stage_count": len(result.completed_stages),
                            "recoverable_error_count": len(result.recoverable_errors),
                            "cancelled": result.cancelled,
                        }
                    )
            retryable_error = next(
                (
                    item
                    for item in reversed(
                        result.recoverable_errors if result is not None else []
                    )
                    if is_retryable_workflow_error(
                        code=item.code,
                        retryable=item.retryable,
                        details=item.details,
                    )
                ),
                None,
            )
            if retryable_error is not None:
                error = retryable_error
                if error.details.get("failure_kind") == "fetch":
                    raise TransientFetchError("A recoverable retrieval step failed")
                raise TransientProviderError("A recoverable provider step failed")
            if result is not None and result.recoverable_errors:
                error = result.recoverable_errors[-1]
                _mark_failure_safely(
                    factory,
                    redis_client,
                    settings,
                    parsed_run_id,
                    code=error.code,
                    message=error.public_message,
                    details=error.details,
                )
            elif result is not None and result.ready_for_completion:
                if result.citation_audit is None:
                    raise RuntimeError(
                        "completion gate accepted a missing citation audit"
                    )
                expected_citations = len(result.citation_audit.sentence_audits)
                with factory() as db:
                    persist_completed_run(
                        db,
                        run_id=parsed_run_id,
                        expected_citation_count=expected_citations,
                    )
                _backfill_progress(factory, redis_client, settings, parsed_run_id)
            elif result is not None and not result.cancelled:
                _mark_failure_safely(
                    factory,
                    redis_client,
                    settings,
                    parsed_run_id,
                    code="COMPLETION_GATE_REJECTED",
                    message="Verification stopped before a citation-audited report was ready.",
                )
    except TerminalRunTransitionError:
        # Cancellation can win the race after the pre-stage check. The durable
        # terminal status is authoritative and is a successful no-op here.
        _cancel_if_requested(factory, redis_client, settings, parsed_run_id)
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
    except RedisError:
        _mark_failure_safely(
            factory,
            redis_client,
            settings,
            parsed_run_id,
            code="WORKER_UNAVAILABLE",
            message="Verification worker temporarily lost its queue connection.",
        )
        raise
    except InvalidRunTransitionError:
        _mark_failure_safely(
            factory,
            redis_client,
            settings,
            parsed_run_id,
            code="COMPLETION_GATE_REJECTED",
            message="Verification stopped before durable citation-audited artifacts were ready.",
        )
    except Exception as exc:
        logger.exception(
            "Verification worker encountered an unexpected error for run %s "
            "(exception_type=%s, retry_count=%s)",
            parsed_run_id,
            type(exc).__name__,
            self.request.retries,
        )
        _mark_failure_safely(
            factory,
            redis_client,
            settings,
            parsed_run_id,
            code="WORKER_ERROR",
            message="Verification stopped because the worker encountered an error.",
            internal_failure_detail=f"unexpected_exception:{type(exc).__name__}",
        )
        raise
    finally:
        try:
            metric_state = result
            if metric_state is None:
                durable = _load_run(factory, parsed_run_id)
                metric_state = VerificationState(
                    run_id=durable.id,
                    user_id=durable.user_id,
                    research_depth=GraphResearchDepth(durable.research_depth.value),
                    methodology_version="1.0",
                    workflow_version=durable.workflow_version,
                    cancelled=durable.status == RunStatus.CANCELLED,
                )
            points = build_run_metrics(
                metric_state,
                duration_seconds=time.perf_counter() - started,
                retry_count=self.request.retries,
                queue_depth=queue_length(redis_client, VERIFICATION_QUEUES),
                input_cost_per_million=settings.deepseek_input_cost_per_million_tokens,
                output_cost_per_million=settings.deepseek_output_cost_per_million_tokens,
                search_cost_per_request=settings.search_cost_per_request,
            )
            emit_metrics(redis_client, points)
        except Exception:
            logger.warning("Unable to finalize metrics for run %s", parsed_run_id)
