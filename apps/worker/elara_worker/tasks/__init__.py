"""Celery task registrations."""

# Register the process-level readiness/heartbeat signal handlers before Celery
# imports individual task modules.
from elara_worker import worker_liveness as _worker_liveness  # noqa: F401
