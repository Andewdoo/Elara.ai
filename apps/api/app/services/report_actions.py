from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Export, ExportFormat, RunStatus, UserFeedback
from app.models.types import utc_now
from app.schemas.verifications import ExportResponse, FeedbackCreateRequest, FeedbackResponse
from app.services.object_storage import ObjectStorage
from app.services.reports import build_report
from app.services.verifications import get_authorized_run, get_owned_run

logger = logging.getLogger(__name__)


class ReportActionConflictError(ValueError):
    pass


class ExportNotFoundError(LookupError):
    pass


def set_saved(db: Session, *, owner_id: UUID, run_id: UUID, saved: bool):
    run = get_owned_run(db, owner_id=owner_id, run_id=run_id)
    if run.status != RunStatus.COMPLETED:
        raise ReportActionConflictError("Only completed reports can be saved")
    if saved and run.saved_at is None:
        run.saved_at = utc_now()
    elif not saved:
        run.saved_at = None
    db.commit()
    db.refresh(run)
    return run


def submit_feedback(
    db: Session, *, viewer_id: UUID, run_id: UUID, request: FeedbackCreateRequest
) -> UserFeedback:
    run = get_authorized_run(db, viewer_id=viewer_id, run_id=run_id)
    row = UserFeedback(
        run_id=run.id,
        user_id=viewer_id,
        category=request.category.value,
        message=request.message,
        source_url=str(request.source_url) if request.source_url else None,
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def feedback_response(row: UserFeedback) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=row.id,
        run_id=row.run_id,
        category=row.category,
        message=row.message,
        source_url=row.source_url,
        status=row.status,
        created_at=row.created_at,
    )


def list_feedback(db: Session, *, viewer_id: UUID, run_id: UUID) -> list[FeedbackResponse]:
    run = get_authorized_run(db, viewer_id=viewer_id, run_id=run_id)
    rows = db.scalars(
        select(UserFeedback)
        .where(UserFeedback.run_id == run.id, UserFeedback.user_id == viewer_id)
        .order_by(UserFeedback.created_at.desc(), UserFeedback.id)
    ).all()
    return [feedback_response(row) for row in rows]


def list_exports(db: Session, *, owner_id: UUID, run_id: UUID) -> list[ExportResponse]:
    run = get_owned_run(db, owner_id=owner_id, run_id=run_id)
    rows = db.scalars(
        select(Export)
        .where(Export.run_id == run.id)
        .order_by(Export.created_at.desc(), Export.id)
    ).all()
    return [export_response(row) for row in rows]


def create_json_export(
    db: Session,
    *,
    owner_id: UUID,
    run_id: UUID,
    storage: ObjectStorage,
) -> Export:
    run = get_owned_run(db, owner_id=owner_id, run_id=run_id)
    if run.status != RunStatus.COMPLETED:
        raise ReportActionConflictError("Only completed reports can be exported")
    payload = json.dumps(
        build_report(db, run=run).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    row = Export(
        run_id=run.id,
        export_type=ExportFormat.JSON.value,
        object_path="pending",
        content_hash=digest,
    )
    db.add(row)
    db.flush()
    row.object_path = f"exports/{run.user_id}/{run.id}/{row.id}.json"
    object_written = False
    try:
        storage.put_private_object(
            key=row.object_path, body=payload, content_type="application/json"
        )
        object_written = True
        db.commit()
    except Exception:
        db.rollback()
        if object_written:
            try:
                storage.delete_object(key=row.object_path)
            except Exception:
                logger.exception("Failed to clean up uncommitted export object %s", row.id)
        raise
    db.refresh(row)
    return row


def get_export_download(
    db: Session,
    *,
    viewer_id: UUID,
    run_id: UUID,
    export_id: UUID,
    storage: ObjectStorage,
    expires_in: int,
) -> ExportResponse:
    run = get_authorized_run(db, viewer_id=viewer_id, run_id=run_id)
    row = db.scalar(
        select(Export).where(Export.id == export_id, Export.run_id == run.id)
    )
    if row is None:
        raise ExportNotFoundError("Export not found")
    expires_at = utc_now() + timedelta(seconds=expires_in)
    return ExportResponse(
        export_id=row.id,
        run_id=row.run_id,
        format=row.export_type,
        content_hash=row.content_hash,
        created_at=row.created_at,
        download_url=storage.signed_download_url(
            key=row.object_path,
            filename=f"elara-report-{run.id}.json",
            content_type="application/json",
            expires_in=expires_in,
        ),
        expires_at=expires_at,
    )


def export_response(row: Export) -> ExportResponse:
    return ExportResponse(
        export_id=row.id,
        run_id=row.run_id,
        format=row.export_type,
        content_hash=row.content_hash,
        created_at=row.created_at,
    )


def delete_report(
    db: Session, *, owner_id: UUID, run_id: UUID, storage: ObjectStorage
) -> None:
    run = get_owned_run(db, owner_id=owner_id, run_id=run_id)
    if run.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
        raise ReportActionConflictError("Active verifications must be cancelled before deletion")
    exports = db.scalars(select(Export).where(Export.run_id == run.id)).all()
    for row in exports:
        storage.delete_object(key=row.object_path)
        db.delete(row)
    run.saved_at = None
    run.deleted_at = utc_now()
    db.commit()
