"""Small, transient Celery worker readiness signal for the single-host demo."""

from __future__ import annotations

import logging
from typing import Any

from celery.signals import heartbeat_sent, task_prerun, worker_ready
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.redis_client import get_redis_client, worker_liveness_key


logger = logging.getLogger(__name__)


def refresh_worker_liveness(
    *_: Any,
    settings: Settings | None = None,
    redis_client: Any | None = None,
    **__: Any,
) -> bool:
    """Refresh the worker heartbeat, returning False when Redis is unavailable.

    The value is deliberately only a short-lived operational hint. Run status,
    events, and report artifacts remain durable PostgreSQL records.
    """
    settings = settings or get_settings()
    try:
        (redis_client or get_redis_client()).set(
            worker_liveness_key(),
            "ready",
            ex=settings.worker_liveness_ttl_seconds,
        )
    except RedisError:
        logger.warning("Unable to refresh worker liveness signal")
        return False
    return True


worker_ready.connect(refresh_worker_liveness, weak=False)
heartbeat_sent.connect(refresh_worker_liveness, weak=False)
task_prerun.connect(refresh_worker_liveness, weak=False)
