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
from app.models.records import UserFeedback
from app.models.verification_run import VerificationRun
from app.redis_client import get_redis_client, progress_stream_key, request_cancellation
from app.schemas.verifications import (
    DeleteReportResponse,
    ExportCreateRequest,
    ExportListResponse,
    ExportResponse,
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackListResponse,
    FeedbackDecisionRequest,
    GovernanceDecisionResponse,
    PublicationReviewRequest,
    ShareCreateRequest,
    ShareResponse,
    SavedReportResponse,
    VerificationCancelResponse,
    VerificationCreateRequest,
    VerificationCreateResponse,
    ProgressEvent,
    VerificationRunResponse,
    SourceGraphResponse,
    ReportResponse,
    SourcesResponse,
)
from app.services.queueing import (
    BrokerUnavailableError,
    VerificationDispatcher,
    WorkerUnavailableError,
    get_verification_dispatcher,
)
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
    UploadNotFoundError,
    create_queued_verification,
    create_retry_verification,
    get_authorized_run,
    request_run_cancellation,
)
from app.services.object_storage import ObjectStorage, get_object_storage
from app.services.report_actions import (
    ExportNotFoundError,
    ReportActionConflictError,
    create_json_export,
    delete_report,
    export_response,
    feedback_response,
    list_exports,
    list_feedback,
    get_export_download,
    set_saved,
    submit_feedback,
)
from app.services.source_graph import build_source_graph
from app.services.reports import build_report
from app.services.rate_limits import (
    RateLimitExceededError,
    RateLimitUnavailableError,
    enforce_verification_rate_limit,
    enforce_action_rate_limit,
)
from app.services.sources import build_sources
from app.services.governance import (
    GovernanceConflictError,
    adjudicate_feedback,
    decide_publication,
    revoke_share,
    share_report,
)

router = APIRouter(prefix="/v1/verifications", tags=["verifications"])
logger = logging.getLogger(__name__)


def _enforce_action_or_raise(
    redis_client: Redis, settings: Settings, user_id: UUID, action: str
) -> None:
    try:
        enforce_action_rate_limit(
            redis_client, settings=settings, user_id=str(user_id), action=action
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Action rate limit reached",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except RateLimitUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Action admission control is unavailable",
        ) from exc


class TestTransientStore:
    """Small no-network store for API boundary tests."""

    def __init__(self) -> None:
        self.values: set[str] = set()

    def xadd(self, _key: str, _fields: dict[str, str], **_: object) -> str:
        return "0-0"

    def set(self, key: str, _value: str, **_: object) -> bool:
        self.values.add(key)
        return True

    def xread(self, _streams: dict[str, str], **_: object) -> list[object]:
        return []

    def incr(self, key: str) -> int:
        return 1

    def ttl(self, _key: str) -> int:
        return 3_600

    def expire(self, _key: str, _seconds: int) -> bool:
        return True


def get_request_redis_client(settings: Settings = Depends(get_settings)) -> Redis:
    if settings.environment == "test" and not settings.acceptance_test_mode:
        return TestTransientStore()  # type: ignore[return-value]
    return get_redis_client()


def _run_response(run: VerificationRun, *, viewer_id: UUID) -> VerificationRunResponse:
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
        saved_at=run.saved_at,
        is_owner=run.user_id == viewer_id,
        publication_state=run.publication_state,
        publication_review_reason=run.publication_review_reason,
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
    return _run_response(run, viewer_id=authenticated.user.id)


@router.get("/{run_id}/progress", response_model=list[ProgressEvent])
def get_verification_progress_history(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> list[ProgressEvent]:
    """Return the durable, public run events used to render research progress."""
    try:
        run = get_authorized_run(db, viewer_id=authenticated.user.id, run_id=run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    events = db.scalars(
        select(AgentEvent)
        .where(AgentEvent.run_id == run.id)
        .order_by(AgentEvent.sequence.asc())
    ).all()
    return [
        ProgressEvent(
            **public_event_data(
                {
                    "run_id": str(run.id),
                    "stage": event.stage.value,
                    "message": event.public_message,
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
            )
        )
        for event in events
    ]


@router.get("/{run_id}/source-graph", response_model=SourceGraphResponse)
def get_verification_source_graph(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> SourceGraphResponse:
    try:
        run = get_authorized_run(db, viewer_id=authenticated.user.id, run_id=run_id, required_scope="sources")
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return build_source_graph(db, run_id=run.id)


@router.get("/{run_id}/sources", response_model=SourcesResponse)
def get_verification_sources(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> SourcesResponse:
    try:
        run = get_authorized_run(db, viewer_id=authenticated.user.id, run_id=run_id, required_scope="sources")
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return build_sources(db, run_id=run.id)


@router.get("/{run_id}/report", response_model=ReportResponse)
def get_verification_report(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> ReportResponse:
    try:
        run = get_authorized_run(db, viewer_id=authenticated.user.id, run_id=run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if run.status != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Report is unavailable until durable citation-audited completion",
        )
    return build_report(db, run=run)


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
        if run.status.value in TERMINAL_STATUS_VALUES or run.publication_state == "review_required":
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
                db.expire(run, ["status", "failure_message", "updated_at", "publication_state"])
                if run.status.value in TERMINAL_STATUS_VALUES or run.publication_state == "review_required":
                    yield encode_sse(cursor, _durable_terminal_event(db, run))
                    return
                yield ": heartbeat\n\n"
                continue

            for _key, entries in batches:
                for event_id, fields in entries:
                    cursor = str(event_id)
                    data = public_event_data(fields)
                    yield encode_sse(cursor, data)
                    if data["stage"] in TERMINAL_STATUS_VALUES or data.get("event_type") == "publication.review_required":
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
    payload: VerificationCreateRequest,
    request: Request,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis_client: Redis = Depends(get_request_redis_client),
    dispatcher: VerificationDispatcher = Depends(get_verification_dispatcher),
) -> VerificationCreateResponse:
    try:
        enforce_verification_rate_limit(
            redis_client,
            settings=settings,
            user_id=str(authenticated.user.id),
            ip_address=request.client.host if request.client else "unknown",
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except RateLimitUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification admission control is temporarily unavailable",
        ) from exc
    try:
        run = create_queued_verification(db, owner=authenticated.user, request=payload, settings=settings)
    except ResearchDepthNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ActiveRunLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except UploadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        mirror_agent_event(redis_client, settings=settings, event=run.events[0])
    except Exception:
        logger.warning("Unable to mirror queued progress for run %s", run.id)
    try:
        dispatcher.enqueue(run.id, run.research_depth)
    except WorkerUnavailableError as exc:
        event = persist_progress(
            db,
            run_id=run.id,
            stage=RunStatus.FAILED,
            event_type="run.failed",
            message="Verification worker is temporarily unavailable. Please try again.",
            payload={"worker_ready_count": 0},
            failure_code="WORKER_UNAVAILABLE",
        )
        try:
            mirror_progress(redis_client, settings=settings, event=event)
        except Exception:
            logger.warning("Unable to mirror worker failure for run %s", run.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification worker is unavailable",
        ) from exc
    except BrokerUnavailableError as exc:
        event = persist_progress(
            db,
            run_id=run.id,
            stage=RunStatus.FAILED,
            event_type="run.failed",
            message="Verification queue is temporarily unavailable. Please try again.",
            payload={"broker_connection_attempt_count": 1},
            failure_code="BROKER_UNAVAILABLE",
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


@router.post("/{run_id}/retry", response_model=VerificationCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_verification(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis_client: Redis = Depends(get_request_redis_client),
    dispatcher: VerificationDispatcher = Depends(get_verification_dispatcher),
) -> VerificationCreateResponse:
    _enforce_action_or_raise(redis_client, settings, authenticated.user.id, "retry")
    try:
        run = create_retry_verification(
            db, owner=authenticated.user, run_id=run_id, settings=settings
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ActiveRunLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ResearchDepthNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    try:
        mirror_agent_event(redis_client, settings=settings, event=run.events[0])
    except Exception:
        logger.warning("Unable to mirror retry progress for run %s", run.id)
    try:
        dispatcher.enqueue(run.id, run.research_depth)
    except WorkerUnavailableError as exc:
        event = persist_progress(
            db,
            run_id=run.id,
            stage=RunStatus.FAILED,
            event_type="run.failed",
            message="Verification worker is temporarily unavailable. Please try again.",
            payload={"worker_ready_count": 0},
            failure_code="WORKER_UNAVAILABLE",
        )
        try:
            mirror_progress(redis_client, settings=settings, event=event)
        except Exception:
            logger.warning("Unable to mirror worker failure for retry run %s", run.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification worker is unavailable",
        ) from exc
    except BrokerUnavailableError as exc:
        event = persist_progress(
            db,
            run_id=run.id,
            stage=RunStatus.FAILED,
            event_type="run.failed",
            message="Verification queue is temporarily unavailable. Please try again.",
            payload={"broker_connection_attempt_count": 1},
            failure_code="BROKER_UNAVAILABLE",
        )
        try:
            mirror_progress(redis_client, settings=settings, event=event)
        except Exception:
            logger.warning("Unable to mirror broker failure for retry run %s", run.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification queue is unavailable",
        ) from exc
    return VerificationCreateResponse(
        run_id=run.id,
        status=run.status,
        events_url=f"/v1/verifications/{run.id}/events",
    )


@router.post("/{run_id}/save", response_model=SavedReportResponse)
def save_report(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> SavedReportResponse:
    try:
        run = set_saved(db, owner_id=authenticated.user.id, run_id=run_id, saved=True)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReportActionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SavedReportResponse(run_id=run.id, saved_at=run.saved_at)


@router.delete("/{run_id}/save", response_model=SavedReportResponse)
def unsave_report(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> SavedReportResponse:
    try:
        run = set_saved(db, owner_id=authenticated.user.id, run_id=run_id, saved=False)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReportActionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SavedReportResponse(run_id=run.id, saved_at=run.saved_at)


@router.post(
    "/{run_id}/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED
)
def create_feedback(
    run_id: UUID,
    request: FeedbackCreateRequest,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis_client: Redis = Depends(get_request_redis_client),
) -> FeedbackResponse:
    _enforce_action_or_raise(redis_client, settings, authenticated.user.id, "feedback")
    try:
        row = submit_feedback(
            db, viewer_id=authenticated.user.id, run_id=run_id, request=request
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return feedback_response(row)


@router.get("/{run_id}/feedback", response_model=FeedbackListResponse)
def get_feedback_history(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> FeedbackListResponse:
    try:
        return FeedbackListResponse(
            items=list_feedback(db, viewer_id=authenticated.user.id, run_id=run_id)
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{run_id}/exports", response_model=ExportResponse, status_code=status.HTTP_201_CREATED
)
def create_export(
    run_id: UUID,
    request: ExportCreateRequest,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_object_storage),
    settings: Settings = Depends(get_settings),
    redis_client: Redis = Depends(get_request_redis_client),
) -> ExportResponse:
    _enforce_action_or_raise(redis_client, settings, authenticated.user.id, "export")
    try:
        row = create_json_export(
            db, owner_id=authenticated.user.id, run_id=run_id, storage=storage
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReportActionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Private export storage failed for run %s", run_id, exc_info=False)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export storage is temporarily unavailable",
        ) from exc
    return export_response(row)


@router.get("/{run_id}/exports", response_model=ExportListResponse)
def get_export_history(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> ExportListResponse:
    try:
        return ExportListResponse(
            items=list_exports(db, owner_id=authenticated.user.id, run_id=run_id)
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{run_id}/exports/{export_id}", response_model=ExportResponse)
def get_export(
    run_id: UUID,
    export_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_object_storage),
    redis_client: Redis = Depends(get_request_redis_client),
) -> ExportResponse:
    _enforce_action_or_raise(redis_client, settings, authenticated.user.id, "signed_url")
    try:
        return get_export_download(
            db,
            viewer_id=authenticated.user.id,
            run_id=run_id,
            export_id=export_id,
            storage=storage,
            expires_in=settings.export_signed_url_ttl_seconds,
        )
    except (RunNotFoundError, ExportNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Signed export URL creation failed for run %s", run_id, exc_info=False)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export download is temporarily unavailable",
        ) from exc


@router.delete("/{run_id}", response_model=DeleteReportResponse)
def remove_report(
    run_id: UUID,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_object_storage),
) -> DeleteReportResponse:
    try:
        delete_report(db, owner_id=authenticated.user.id, run_id=run_id, storage=storage)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReportActionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.error("Report object cleanup failed for run %s", run_id, exc_info=False)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report deletion is temporarily unavailable",
        ) from exc
    return DeleteReportResponse(run_id=run_id, deleted=True)


@router.post("/{run_id}/shares", response_model=ShareResponse, status_code=status.HTTP_201_CREATED)
def create_share(run_id: UUID, request: ShareCreateRequest,
                 authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
                 db: Session = Depends(get_db)) -> ShareResponse:
    try:
        row = share_report(db, owner_id=authenticated.user.id, run_id=run_id,
                           recipient_id=request.recipient_user_id, scope=request.scope,
                           expires_in_hours=request.expires_in_hours)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GovernanceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ShareResponse(share_id=row.id, run_id=row.run_id, recipient_user_id=row.recipient_user_id,
                         scope=row.scope, expires_at=row.expires_at, revoked_at=row.revoked_at)


@router.delete("/{run_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_share(run_id: UUID, share_id: UUID,
                 authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
                 db: Session = Depends(get_db)) -> None:
    try:
        revoke_share(db, owner_id=authenticated.user.id, run_id=run_id, share_id=share_id)
    except (RunNotFoundError, LookupError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{run_id}/publication-review", response_model=VerificationRunResponse)
def review_publication(run_id: UUID, request: PublicationReviewRequest,
                       authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
                       db: Session = Depends(get_db)) -> VerificationRunResponse:
    try:
        run = decide_publication(db, reviewer=authenticated.user, run_id=run_id,
                                 decision=request.decision, rationale=request.rationale)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GovernanceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run_response(run, viewer_id=authenticated.user.id)


@router.post("/{run_id}/feedback/{feedback_id}/decision", response_model=GovernanceDecisionResponse)
def decide_feedback(run_id: UUID, feedback_id: UUID, request: FeedbackDecisionRequest,
                    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
                    db: Session = Depends(get_db)) -> GovernanceDecisionResponse:
    try:
        feedback = db.get(UserFeedback, feedback_id)
        if feedback is None or feedback.run_id != run_id:
            raise LookupError("Feedback not found")
        row = adjudicate_feedback(db, reviewer=authenticated.user, feedback_id=feedback_id,
                                  decision=request.decision, rationale=request.rationale,
                                  revised_run_id=request.revised_run_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GovernanceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GovernanceDecisionResponse(decision_id=row.id, decision=row.decision, created_at=row.created_at)
