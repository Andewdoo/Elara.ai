from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.agent_event import AgentEvent
from app.models.enums import InputType, RunStatus
from app.models.types import utc_now
from app.models.user import User
from app.models.verification_run import VerificationRun
from app.schemas.verifications import VerificationCreateRequest


class RunNotFoundError(LookupError):
    pass


class ResearchDepthNotAllowedError(PermissionError):
    pass


class ActiveRunLimitExceededError(PermissionError):
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
    run = VerificationRun(
        user_id=owner.id,
        input_type=request.input_type,
        research_depth=request.research_depth,
        status=RunStatus.QUEUED,
        submitted_text=submitted_text,
        submitted_url=str(request.url) if request.url else None,
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
        )
    )
    if run is None:
        raise RunNotFoundError("Verification run not found")
    return run
