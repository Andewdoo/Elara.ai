"""Idempotent retention cleanup with completed-report snapshot preservation."""

from datetime import timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import RunSource, RunStatus, SourceSnapshot, Upload, VerificationRun
from app.models.types import utc_now
from app.services.object_storage import ObjectStorage


def cleanup_expired_unclaimed_uploads(db: Session, *, storage: ObjectStorage) -> int:
    now = utc_now()
    rows = db.scalars(select(Upload).where(
        Upload.claimed_at.is_(None), Upload.deleted_at.is_(None), Upload.expires_at <= now
    )).all()
    removed = 0
    for row in rows:
        storage.delete_object(key=row.object_path)
        row.deleted_at = now
        removed += 1
    db.commit()
    return removed


def cleanup_orphan_snapshots(db: Session, *, storage: ObjectStorage, older_than_days: int) -> int:
    cutoff = utc_now() - timedelta(days=older_than_days)
    completed_reference = (
        select(RunSource.run_id).join(VerificationRun, VerificationRun.id == RunSource.run_id)
        .where(RunSource.snapshot_id == SourceSnapshot.id, VerificationRun.status == RunStatus.COMPLETED).exists()
    )
    any_reference = select(RunSource.run_id).where(RunSource.snapshot_id == SourceSnapshot.id).exists()
    rows = db.scalars(
        select(SourceSnapshot)
        .where(SourceSnapshot.created_at < cutoff, ~completed_reference, ~any_reference)
        .with_for_update(skip_locked=True)
    ).all()
    removed = 0
    for row in rows:
        protected = db.scalar(select(exists().where(
            RunSource.snapshot_id == row.id,
            RunSource.run_id == VerificationRun.id,
            VerificationRun.status == RunStatus.COMPLETED,
        )))
        if protected:
            continue
        if row.snapshot_path:
            storage.delete_object(key=row.snapshot_path)
        db.delete(row)
        removed += 1
    db.commit()
    return removed


__all__ = ["cleanup_expired_unclaimed_uploads", "cleanup_orphan_snapshots"]
