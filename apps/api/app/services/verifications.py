from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.agent_event import AgentEvent
from app.models.enums import InputType, RunStatus
from app.models.types import utc_now
from app.models.user import User
from app.models.verification_run import VerificationRun
from app.models.upload import Upload
from app.schemas.verifications import VerificationCreateRequest


class RunNotFoundError(LookupError):
    pass


class ResearchDepthNotAllowedError(PermissionError):
    pass


class ActiveRunLimitExceededError(PermissionError):
    pass


class UploadNotFoundError(LookupError):
    pass


ACTIVE_RUN_STATUSES = {
    status for status in RunStatus if status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
}


def enforce_verification_limits(
    db: Session,
    *,
    owner: User,
    request: VerificationCreateRequest,
) -> None:
    allowed_depths = owner.usage_limits.get("allowed_research_depths")
    if isinstance(allowed_depths, list):
        normalized_depths = {str(value).upper() for value in allowed_depths}
        if request.research_depth.value not in normalized_depths:
            raise ResearchDepthNotAllowedError("Research depth is not available for this account")

    max_active_runs = owner.usage_limits.get("max_active_runs")
    if isinstance(max_active_runs, int) and not isinstance(max_active_runs, bool) and max_active_runs >= 0:
        active_count = db.scalar(
            select(func.count())
            .select_from(VerificationRun)
            .where(
                VerificationRun.user_id == owner.id,
                VerificationRun.deleted_at.is_(None),
                VerificationRun.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
        if (active_count or 0) >= max_active_runs:
            raise ActiveRunLimitExceededError("Active verification limit reached")


def create_queued_verification(
    db: Session,
    *,
    owner: User,
    request: VerificationCreateRequest,
    settings: Settings,
) -> VerificationRun:
    enforce_verification_limits(db, owner=owner, request=request)
    now = utc_now()
    submitted_text = request.quote if request.input_type == InputType.QUOTE else request.text
    normalized_target = {
        key: value
        for key, value in {
            "quote": request.quote,
            "speaker": request.speaker,
            "upload_id": str(request.upload_id) if request.upload_id else None,
        }.items()
        if value is not None
    }
    upload = None
    if request.upload_id is not None:
        upload = db.scalar(
            select(Upload)
            .where(
                Upload.id == request.upload_id,
                Upload.user_id == owner.id,
                Upload.claimed_at.is_(None),
            )
            .with_for_update()
        )
        if upload is None:
            raise UploadNotFoundError("Upload not found")
        upload.claimed_at = now
    run = VerificationRun(
        user_id=owner.id,
        input_type=request.input_type,
        research_depth=request.research_depth,
        status=RunStatus.QUEUED,
        submitted_text=submitted_text,
        submitted_url=str(request.url) if request.url else None,
        upload_object_path=upload.object_path if upload is not None else None,
        normalized_target=normalized_target,
        workflow_version=settings.workflow_version,
        queued_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(run)
        db.flush()
        db.add(
            AgentEvent(
                run_id=run.id,
                sequence=1,
                stage=RunStatus.QUEUED,
                event_type="run.queued",
                public_message="Verification queued for research.",
                payload={"research_depth": request.research_depth.value},
                created_at=now,
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    db.refresh(run)
    return run


def get_owned_run(db: Session, *, owner_id: UUID, run_id: UUID) -> VerificationRun:
    run = db.scalar(
        select(VerificationRun).where(
            VerificationRun.id == run_id,
            VerificationRun.user_id == owner_id,
            VerificationRun.deleted_at.is_(None),
        )
    )
    if run is None:
        raise RunNotFoundError("Verification run not found")
    return run


def get_authorized_run(db: Session, *, viewer_id: UUID, run_id: UUID) -> VerificationRun:
    """Authorize an owner or a run explicitly shared to all authenticated users."""
    run = db.scalar(
        select(VerificationRun).where(
            VerificationRun.id == run_id,
            VerificationRun.deleted_at.is_(None),
            or_(VerificationRun.user_id == viewer_id, VerificationRun.visibility == "public"),
        )
    )
    if run is None:
        # Keep cross-user existence private.
        raise RunNotFoundError("Verification run not found")
    return run


def request_run_cancellation(
    db: Session, *, owner_id: UUID, run_id: UUID
) -> tuple[VerificationRun, AgentEvent | None]:
    run = db.scalar(
        select(VerificationRun)
        .where(
            VerificationRun.id == run_id,
            VerificationRun.user_id == owner_id,
            VerificationRun.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if run is None:
        raise RunNotFoundError("Verification run not found")
    if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
        return run, None
    if run.cancellation_requested_at is not None:
        return run, None

    now = utc_now()
    run.cancellation_requested_at = run.cancellation_requested_at or now
    queued = run.status == RunStatus.QUEUED
    if queued:
        run.status = RunStatus.CANCELLED
    sequence = int(
        db.scalar(select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run_id)) or 0
    ) + 1
    event = AgentEvent(
        run_id=run.id,
        sequence=sequence,
        stage=run.status,
        event_type="run.cancelled" if queued else "run.cancellation_requested",
        public_message=(
            "Verification cancelled before research began."
            if queued
            else "Cancellation requested; the worker will stop before the next expensive stage."
        ),
        payload={},
        created_at=now,
    )
    db.add(event)
    db.commit()
    db.refresh(run)
    return run, event
