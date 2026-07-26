from dataclasses import dataclass
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from celery import Celery
from fastapi import Depends
from redis.exceptions import RedisError

from app.celery_app import celery_app
from app.config import Settings, get_settings
from app.models.enums import ResearchDepth
from app.redis_client import get_redis_client, has_live_worker


TASK_NAME = "verification.verify_run"
QUEUE_BY_DEPTH = {
    ResearchDepth.QUICK: "verification.quick",
    ResearchDepth.STANDARD: "verification.standard",
    ResearchDepth.DEEP: "verification.deep",
}


class BrokerUnavailableError(RuntimeError):
    """The broker rejected an enqueue attempt; details stay server-side."""


class WorkerUnavailableError(RuntimeError):
    """No ready worker heartbeat is present for a new verification."""


class VerificationDispatcher(Protocol):
    def enqueue(self, run_id: UUID, research_depth: ResearchDepth) -> str: ...


@dataclass(frozen=True)
class CeleryVerificationDispatcher:
    application: Celery
    worker_ready: Callable[[], bool] | None = None

    def enqueue(self, run_id: UUID, research_depth: ResearchDepth) -> str:
        if self.worker_ready is not None:
            try:
                if not self.worker_ready():
                    raise WorkerUnavailableError("No worker heartbeat")
            except WorkerUnavailableError:
                raise
            except RedisError as exc:
                raise BrokerUnavailableError("Broker readiness probe failed") from exc
        try:
            result = self.application.send_task(
                TASK_NAME,
                args=[str(run_id)],
                queue=QUEUE_BY_DEPTH[research_depth],
            )
        except Exception as exc:
            raise BrokerUnavailableError("Broker enqueue failed") from exc
        return str(result.id)


@dataclass(frozen=True)
class NoopVerificationDispatcher:
    """Broker-free dispatcher used only under the explicit test environment."""

    def enqueue(self, run_id: UUID, research_depth: ResearchDepth) -> str:
        return f"test:{research_depth.value.lower()}:{run_id}"


def get_verification_dispatcher(
    settings: Settings = Depends(get_settings),
) -> VerificationDispatcher:
    if settings.environment == "test" and not settings.acceptance_test_mode:
        return NoopVerificationDispatcher()

    def worker_ready() -> bool:
        return has_live_worker(get_redis_client())

    return CeleryVerificationDispatcher(celery_app, worker_ready=worker_ready)
