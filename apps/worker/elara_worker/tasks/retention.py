"""Scheduled, idempotent retention enforcement without content-bearing logs."""

import logging

from app.celery_app import celery_app
from app.config import get_settings
from app.database.session import get_session_factory
from app.services.object_storage import get_object_storage
from app.services.retention import cleanup_expired_unclaimed_uploads, cleanup_orphan_snapshots


logger = logging.getLogger(__name__)


@celery_app.task(name="governance.cleanup_retention")
def cleanup_retention() -> dict[str, int]:
    settings = get_settings()
    storage = get_object_storage()
    with get_session_factory()() as db:
        uploads = cleanup_expired_unclaimed_uploads(db, storage=storage)
        snapshots = cleanup_orphan_snapshots(
            db, storage=storage, older_than_days=settings.orphan_snapshot_retention_days
        )
    result = {"expired_upload_count": uploads, "orphan_snapshot_count": snapshots}
    logger.info("retention cleanup completed", extra={"retention_counts": result})
    return result


__all__ = ["cleanup_retention"]
