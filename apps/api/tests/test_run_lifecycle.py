from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AgentEvent, RunStatus, VerificationRun
from app.services.run_lifecycle import (
    InvalidRunTransitionError,
    TerminalRunTransitionError,
    persist_progress,
)


def create_run(client: TestClient) -> UUID:
    response = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "text": "A claim"},
    )
    assert response.status_code == 202
    return UUID(response.json()["run_id"])


def test_durable_status_transitions_cannot_move_backward(
    client: TestClient, session_factory: sessionmaker[Session]
):
    run_id = create_run(client)
    with session_factory() as db:
        persist_progress(
            db,
            run_id=run_id,
            stage=RunStatus.RESEARCHING,
            event_type="run.researching",
            message="Researching public evidence.",
        )
        with pytest.raises(InvalidRunTransitionError):
            persist_progress(
                db,
                run_id=run_id,
                stage=RunStatus.VALIDATING,
                event_type="run.validating",
                message="Invalid rewind.",
            )

    with session_factory() as db:
        run = db.get(VerificationRun, run_id)
        assert run is not None and run.status == RunStatus.RESEARCHING


def test_terminal_runs_reject_late_progress(
    client: TestClient, session_factory: sessionmaker[Session]
):
    run_id = create_run(client)
    with session_factory() as db:
        persist_progress(
            db,
            run_id=run_id,
            stage=RunStatus.CANCELLED,
            event_type="run.cancelled",
            message="Verification cancelled.",
        )
        with pytest.raises(TerminalRunTransitionError):
            persist_progress(
                db,
                run_id=run_id,
                stage=RunStatus.RESEARCHING,
                event_type="run.researching",
                message="Late progress.",
            )


@pytest.mark.parametrize(
    "payload",
    [
        {"private_reasoning": "hidden"},
        {"reasoning": "hidden"},
        {"nested": {"chain-of-thought": "hidden"}},
        {"items": [{"raw_prompt": "hidden"}]},
    ],
)
def test_public_events_reject_private_reasoning_fields(
    client: TestClient,
    session_factory: sessionmaker[Session],
    payload: dict[str, object],
):
    run_id = create_run(client)
    with session_factory() as db:
        with pytest.raises(ValueError, match="not allowed in public events"):
            persist_progress(
                db,
                run_id=run_id,
                stage=RunStatus.VALIDATING,
                event_type="run.validating",
                message="Validating input.",
                payload=payload,
            )

    with session_factory() as db:
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.sequence)
        ).all()
        assert [event.event_type for event in events] == ["run.queued"]
