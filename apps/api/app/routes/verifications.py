import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    AuthenticatedUser,
    get_authenticated_bearer,
    get_authenticated_session,
)
from app.config import Settings, get_settings
from app.database.session import get_db
from app.models.enums import RunStatus
from app.models.agent_event import AgentEvent
from app.models.verification_run import VerificationRun
from app.redis_client import get_redis_client, progress_stream_key, request_cancellation
from app.schemas.verifications import (
    VerificationCancelResponse,
    VerificationCreateRequest,
    VerificationCreateResponse,
    VerificationRunResponse,
)
from app.services.queueing import VerificationDispatcher, get_verification_dispatcher
from app.services.run_lifecycle import mirror_agent_event, mirror_progress, persist_progress
from app.services.run_events import (
    TERMINAL_STATUS_VALUES,
    encode_sse,
    public_event_data,
    terminal_database_event,
    validate_last_event_id,
)
from app.services.verifications import (
    ActiveRunLimitExceededError,
    ResearchDepthNotAllowedError,
    RunNotFoundError,
    create_queued_verification,
    get_authorized_run,
    request_run_cancellation,
)

router = APIRouter(prefix="/v1/verifications", tags=["verifications"])
logger = logging.getLogger(__name__)


class TestTransientStore:
    """Small no-network store for API boundary tests."""

    def __init__(self) -> None:
        self.values: set[str] = set()

    def xadd(self, _key: str, _fields: dict[str, str], **_: object) -> str:
        return "0-0"

    def expire(self, _key: str, _ttl: int) -> bool:
        return True

    def set(self, key: str, _value: str, **_: object) -> bool:
        self.values.add(key)
        return True

    def xread(self, _streams: dict[str, str], **_: object) -> list[object]:
        return []


def get_request_redis_client(settings: Settings = Depends(get_settings)) -> Redis:
    if settings.environment == "test":
        return TestTransientStore()  # type: ignore[return-value]
    return get_redis_client()


def _run_response(run: VerificationRun) -> VerificationRunResponse:
    return VerificationRunResponse(
        run_id=run.id,
        status=run.status,
        input_type=run.input_type,
        research_depth=run.research_depth,
        title=run.title,
        verdict=run.verdict,
        queued_at=run.queued_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        cancellation_requested_at=run.cancellation_requested_at,
        failure_code=run.failure_code,
        failure_message=run.failure_message,
        updated_at=run.updated_at,
    )


def _durable_terminal_event(db: Session, run: VerificationRun) -> dict[str, object]:
    event = db.scalar(
        select(AgentEvent)
        .where(AgentEvent.run_id == run.id, AgentEvent.stage == run.status)
        .order_by(AgentEvent.sequence.desc())
        .limit(1)
    )
    if event is not None:
        return public_event_data(
            {
                "run_id": str(run.id),
                "stage": run.status.value,
                "message": event.public_message,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
        )
    return terminal_database_event(
        run_id=run.id,
        status=run.status,
        message=run.failure_message or f"Verification {run.status.value.lower()}.",
        created_at=run.updated_at,
    )


@router.get("/{run_id}", response_model=VerificationRunResponse)
def get_verification(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> VerificationRunResponse:
    try:
        run = get_authorized_run(db, viewer_id=authenticated.user.id, run_id=run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _run_response(run)


@router.get("/{run_id}/events")
async def stream_verification_events(
    run_id: UUID,
    request: Request,
    authenticated: AuthenticatedUser = Depends(get_authenticated_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis_client: Redis = Depends(get_request_redis_client),
) -> StreamingResponse:
    forbidden_query_keys = {"token", "id_token", "access_token", "session", "auth"}
    if forbidden_query_keys.intersection(key.lower() for key in request.query_params):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication tokens are not accepted in the SSE URL",
        )
    try:
        cursor = validate_last_event_id(request.headers.get("last-event-id"))
        run = get_authorized_run(db, viewer_id=authenticated.user.id, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    stream_key = progress_stream_key(run_id)

    async def event_stream():
        nonlocal cursor
        if run.status.value in TERMINAL_STATUS_VALUES:
            yield encode_sse(cursor, _durable_terminal_event(db, run))
            return

        while True:
            if await request.is_disconnected():
                return
            try:
                batches = await asyncio.to_thread(
                    redis_client.xread,
                    {stream_key: cursor},
                    count=100,
                    block=settings.sse_heartbeat_seconds * 1_000,
                )
            except RedisError:
                logger.warning("Redis progress stream unavailable for run %s", run_id)
                yield "event: unavailable\ndata: {\"message\":\"Live progress is temporarily unavailable.\"}\n\n"
                return

            if not batches:
                db.expire(run, ["status", "failure_message", "updated_at"])
                if run.status.value in TERMINAL_STATUS_VALUES:
                    yield encode_sse(cursor, _durable_terminal_event(db, run))
                    return
                yield ": heartbeat\n\n"
                continue

            for _key, entries in batches:
                for event_id, fields in entries:
                    cursor = str(event_id)
                    data = public_event_data(fields)
                    yield encode_sse(cursor, data)
                    if data["stage"] in TERMINAL_STATUS_VALUES:
                        return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=VerificationCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_verification(
    request: VerificationCreateRequest,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis_client: Redis = Depends(get_request_redis_client),
    dispatcher: VerificationDispatcher = Depends(get_verification_dispatcher),
) -> VerificationCreateResponse:
    try:
        run = create_queued_verification(db, owner=authenticated.user, request=request, settings=settings)
    except ResearchDepthNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ActiveRunLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    try:
        mirror_agent_event(redis_client, settings=settings, event=run.events[0])
    except Exception:
        logger.warning("Unable to mirror queued progress for run %s", run.id)
    try:
        dispatcher.enqueue(run.id, run.research_depth)
    except Exception as exc:
        event = persist_progress(
            db,
            run_id=run.id,
            stage=RunStatus.FAILED,
            event_type="run.failed",
            message="Verification could not be queued. Please try again.",
            failure_code="QUEUE_UNAVAILABLE",
        )
        try:
            mirror_progress(redis_client, settings=settings, event=event)
        except Exception:
            logger.warning("Unable to mirror queue failure for run %s", run.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification queue is unavailable",
        ) from exc
    return VerificationCreateResponse(
        run_id=run.id,
        status=run.status,
        events_url=f"/v1/verifications/{run.id}/events",
    )


@router.post("/{run_id}/cancel", response_model=VerificationCancelResponse)
def cancel_verification(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis_client: Redis = Depends(get_request_redis_client),
) -> VerificationCancelResponse:
    try:
        run, event = request_run_cancellation(
            db, owner_id=authenticated.user.id, run_id=run_id
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if event is not None:
        try:
            request_cancellation(redis_client, settings=settings, run_id=run.id)
            mirror_agent_event(redis_client, settings=settings, event=event)
        except Exception:
            logger.warning(
                "Redis cancellation mirror failed for run %s; durable flag remains authoritative",
                run.id,
            )
    return VerificationCancelResponse(
        run_id=run.id,
        status=run.status,
        cancellation_requested_at=run.cancellation_requested_at,
    )
