from celery import Celery
from kombu import Queue

from app.config import get_settings


VERIFICATION_QUEUES = (
    "verification.quick",
    "verification.standard",
    "verification.deep",
)


def create_celery_app() -> Celery:
    settings = get_settings()
    application = Celery(
        "elara",
        broker=settings.effective_celery_broker_url,
        backend=settings.effective_celery_result_backend,
        include=["elara_worker.tasks.verification", "elara_worker.tasks.retention"],
    )
    application.conf.update(
        task_queues=tuple(Queue(name) for name in VERIFICATION_QUEUES),
        task_default_queue="verification.standard",
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=3_600,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        # Compose owns the small restart budget for the single-host demo;
        # Celery itself must not wait forever for an unavailable Redis broker.
        broker_connection_retry_on_startup=False,
        broker_connection_retry=False,
        broker_transport_options={"visibility_timeout": 7_200},
        task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
        task_time_limit=settings.celery_task_time_limit_seconds,
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "retention-cleanup-daily": {
                "task": "governance.cleanup_retention",
                "schedule": 86_400.0,
                "options": {"queue": "verification.standard"},
            }
        },
    )
    return application


celery_app = create_celery_app()
