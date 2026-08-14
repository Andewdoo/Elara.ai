from sqlalchemy import func, select
from sqlalchemy.orm import Session
from uuid import UUID

from app.models import RunStatus, VerificationRun
from app.schemas.verifications import HistoryItemResponse, HistoryResponse, VerificationRunResponse

DEMO_RUN_LIMIT = 12
DEMO_VISIBILITY = "demo"


class DemoRunNotFoundError(LookupError):
    pass


def get_demo_run(db: Session, *, run_id: UUID) -> VerificationRun:
    run = db.scalar(
        select(VerificationRun).where(
            VerificationRun.id == run_id,
            VerificationRun.visibility == DEMO_VISIBILITY,
            VerificationRun.status == RunStatus.COMPLETED,
            VerificationRun.evidence_reviewed_at.is_not(None),
            VerificationRun.deleted_at.is_(None),
        )
    )
    if run is None:
        raise DemoRunNotFoundError("Demo report not found")
    return run


def demo_run_response(run: VerificationRun) -> VerificationRunResponse:
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
        failure_code=None,
        failure_message=None,
        updated_at=run.updated_at,
        saved_at=None,
        is_owner=False,
        publication_state=run.publication_state,
        publication_review_reason=run.publication_review_reason,
    )


def list_demo_runs(db: Session) -> HistoryResponse:
    """Return the fixed shared Demo collection, never a viewer's saved history."""
    filters = (
        VerificationRun.visibility == DEMO_VISIBILITY,
        VerificationRun.status == RunStatus.COMPLETED,
        VerificationRun.evidence_reviewed_at.is_not(None),
        VerificationRun.deleted_at.is_(None),
    )
    total = int(db.scalar(select(func.count()).select_from(VerificationRun).where(*filters)) or 0)
    rows = db.scalars(
        select(VerificationRun)
        .where(*filters)
        .order_by(VerificationRun.evidence_reviewed_at.desc(), VerificationRun.id)
        .limit(DEMO_RUN_LIMIT)
    ).all()
    return HistoryResponse(
        items=[
            HistoryItemResponse(
                run_id=row.id,
                status=row.status,
                input_type=row.input_type,
                research_depth=row.research_depth,
                title=row.title,
                submitted_text_preview=(row.submitted_text or "")[:240] or None,
                verdict=row.verdict,
                verdict_confidence=row.verdict_confidence,
                evidence_reviewed_at=row.evidence_reviewed_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
                saved_at=row.saved_at,
            )
            for row in rows
        ],
        total=total,
        page=1,
        page_size=DEMO_RUN_LIMIT,
    )
