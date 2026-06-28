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
        include=["elara_worker.tasks.verification"],
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
        broker_transport_options={"visibility_timeout": 7_200},
        timezone="UTC",
        enable_utc=True,
    )
    return application


celery_app = create_celery_app()
