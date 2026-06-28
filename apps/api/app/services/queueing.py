from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from celery import Celery
from fastapi import Depends

from app.celery_app import celery_app
from app.config import Settings, get_settings
from app.models.enums import ResearchDepth


TASK_NAME = "verification.verify_run"
QUEUE_BY_DEPTH = {
    ResearchDepth.QUICK: "verification.quick",
    ResearchDepth.STANDARD: "verification.standard",
    ResearchDepth.DEEP: "verification.deep",
}


class VerificationDispatcher(Protocol):
    def enqueue(self, run_id: UUID, research_depth: ResearchDepth) -> str: ...


@dataclass(frozen=True)
class CeleryVerificationDispatcher:
    application: Celery

    def enqueue(self, run_id: UUID, research_depth: ResearchDepth) -> str:
        result = self.application.send_task(
            TASK_NAME,
            args=[str(run_id)],
            queue=QUEUE_BY_DEPTH[research_depth],
        )
        return str(result.id)


@dataclass(frozen=True)
class NoopVerificationDispatcher:
    """Broker-free dispatcher used only under the explicit test environment."""

    def enqueue(self, run_id: UUID, research_depth: ResearchDepth) -> str:
        return f"test:{research_depth.value.lower()}:{run_id}"


def get_verification_dispatcher(
    settings: Settings = Depends(get_settings),
) -> VerificationDispatcher:
    if settings.environment == "test":
        return NoopVerificationDispatcher()
    return CeleryVerificationDispatcher(celery_app)
