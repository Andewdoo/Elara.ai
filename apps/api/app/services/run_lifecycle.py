from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.agent_event import AgentEvent
from app.models.enums import RunStatus
from app.models.evidence import ReportCitation
from app.models.types import utc_now
from app.models.verification_run import VerificationRun
from app.redis_client import publish_progress_event


TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
RUN_STATUS_ORDER = {
    RunStatus.QUEUED: 0,
    RunStatus.VALIDATING: 1,
    RunStatus.DECOMPOSING: 2,
    RunStatus.RESEARCHING: 3,
    RunStatus.EXTRACTING: 4,
    RunStatus.ANALYZING_PROVENANCE: 5,
    RunStatus.SCORING: 6,
    RunStatus.SYNTHESIZING: 7,
    RunStatus.AUDITING: 8,
    RunStatus.COMPLETED: 9,
}
PRIVATE_EVENT_KEYS = {
    "analysis",
    "chain_of_thought",
    "internal_reasoning",
    "private_reasoning",
    "prompt",
    "raw_model_output",
    "raw_prompt",
    "raw_provider_response",
    "raw_response",
    "reasoning",
    "reasoning_trace",
    "thinking",
    "thoughts",
}


class InvalidRunTransitionError(RuntimeError):
    pass


class TerminalRunTransitionError(InvalidRunTransitionError):
    pass


@dataclass(frozen=True)
class DurableProgressEvent:
    run_id: UUID
    sequence: int
    stage: RunStatus
    event_type: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


def _next_sequence(db: Session, run_id: UUID) -> int:
    current = db.scalar(select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run_id))
    return int(current or 0) + 1


def _load_locked_run(db: Session, run_id: UUID) -> VerificationRun:
    run = db.scalar(
        select(VerificationRun).where(VerificationRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError(f"Verification run {run_id} does not exist")
    return run


def _validate_public_payload(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key in PRIVATE_EVENT_KEYS:
                raise ValueError(f"Private field {key!r} is not allowed in public events")
            _validate_public_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_public_payload(child)


def _validate_transition(current: RunStatus, target: RunStatus) -> None:
    if current in TERMINAL_STATUSES:
        raise TerminalRunTransitionError(f"Run is already terminal with status {current}")
    if target in {RunStatus.FAILED, RunStatus.CANCELLED}:
        return
    if RUN_STATUS_ORDER[target] < RUN_STATUS_ORDER[current]:
        raise InvalidRunTransitionError(f"Cannot move run backward from {current} to {target}")


def persist_progress(
    db: Session,
    *,
    run_id: UUID,
    stage: RunStatus,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
    failure_code: str | None = None,
) -> DurableProgressEvent:
    now = utc_now()
    run = _load_locked_run(db, run_id)
    _validate_transition(run.status, stage)
    public_payload = payload or {}
    _validate_public_payload(public_payload)

    run.status = stage
    run.updated_at = now
    if stage == RunStatus.VALIDATING and run.started_at is None:
        run.started_at = now
    elif stage == RunStatus.COMPLETED:
        run.completed_at = now
        run.evidence_reviewed_at = run.evidence_reviewed_at or now
    elif stage == RunStatus.FAILED:
        run.failed_at = now
        run.failure_code = failure_code or "WORKER_ERROR"
        run.failure_message = message
    elif stage == RunStatus.CANCELLED:
        run.cancellation_requested_at = run.cancellation_requested_at or now

    event = AgentEvent(
        run_id=run_id,
        sequence=_next_sequence(db, run_id),
        stage=stage,
        event_type=event_type,
        public_message=message,
        payload=public_payload,
        created_at=now,
    )
    db.add(event)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return DurableProgressEvent(
        run_id=run_id,
        sequence=event.sequence,
        stage=stage,
        event_type=event_type,
        message=message,
        payload=event.payload,
        created_at=now,
    )


def persist_completed_run(
    db: Session,
    *,
    run_id: UUID,
    expected_citation_count: int,
) -> DurableProgressEvent:
    """Atomically enforce durable report artifacts and win the completion race."""
    now = utc_now()
    run = _load_locked_run(db, run_id)
    if run.status in TERMINAL_STATUSES:
        raise TerminalRunTransitionError(f"Run is already terminal with status {run.status}")
    if run.cancellation_requested_at is not None:
        raise TerminalRunTransitionError("Cancellation was requested before completion")
    citations = db.scalars(
        select(ReportCitation).where(ReportCitation.run_id == run_id)
    ).all()
    artifacts_ready = bool(
        run.title
        and run.verdict
        and run.evidence_reviewed_at
        and expected_citation_count > 0
        and len(citations) == expected_citation_count
        and all(row.audit_status == "passed" for row in citations)
    )
    if not artifacts_ready:
        raise InvalidRunTransitionError(
            "Citation-audited report artifacts must be durable before completion"
        )
    _validate_transition(run.status, RunStatus.COMPLETED)
    run.status = RunStatus.COMPLETED
    run.completed_at = now
    run.updated_at = now
    event = AgentEvent(
        run_id=run_id,
        sequence=_next_sequence(db, run_id),
        stage=RunStatus.COMPLETED,
        event_type="run.completed",
        public_message="Verification completed with a citation-audited report.",
        payload={"completed_steps": 13, "total_steps": 13},
        created_at=now,
    )
    db.add(event)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return DurableProgressEvent(
        run_id=run_id,
        sequence=event.sequence,
        stage=RunStatus.COMPLETED,
        event_type=event.event_type,
        message=event.public_message,
        payload=event.payload,
        created_at=now,
    )


def mirror_progress(client: Redis, *, settings: Settings, event: DurableProgressEvent) -> str:
    return publish_progress_event(
        client,
        settings=settings,
        run_id=event.run_id,
        sequence=event.sequence,
        stage=event.stage.value,
        event_type=event.event_type,
        message=event.message,
        payload=event.payload,
        created_at=event.created_at.isoformat(),
    )


def mirror_agent_event(
    client: Redis, *, settings: Settings, event: AgentEvent
) -> str:
    return publish_progress_event(
        client,
        settings=settings,
        run_id=event.run_id,
        sequence=event.sequence,
        stage=event.stage.value,
        event_type=event.event_type,
        message=event.public_message,
        payload=event.payload,
        created_at=event.created_at.isoformat(),
    )


def cancellation_requested(db: Session, run_id: UUID) -> bool:
    requested_at = db.scalar(
        select(VerificationRun.cancellation_requested_at).where(VerificationRun.id == run_id)
    )
    return requested_at is not None
