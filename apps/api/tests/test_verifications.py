from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AgentEvent, User, VerificationRun
from app.schemas.verifications import RunStatus
from app.services.verifications import RunNotFoundError, get_owned_run


def test_create_verification_persists_run_and_first_event(
    client: TestClient, session_factory: sessionmaker[Session], owner: User
):
    response = client.post(
        "/v1/verifications",
        json={
            "input_type": "CLAIM",
            "research_depth": "STANDARD",
            "text": "The city added 20 kilometres of protected bike lanes in 2025.",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["events_url"] == f"/v1/verifications/{body['run_id']}/events"
    assert body["report_url"] is None

    with session_factory() as db:
        run = db.scalar(select(VerificationRun))
        event = db.scalar(select(AgentEvent))
        assert run is not None and run.user_id == owner.id
        assert run.status == RunStatus.QUEUED
        assert event is not None and event.run_id == run.id
        assert event.sequence == 1
        assert event.event_type == "run.queued"
        assert db.scalar(select(func.count()).select_from(AgentEvent)) == 1


def test_owned_run_lookup_does_not_cross_user_boundary(
    session_factory: sessionmaker[Session], owner: User
):
    with session_factory() as db:
        other = User(
            auth_provider="firebase",
            auth_subject="other",
            email="other@example.com",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(other)
        db.commit()
        run = VerificationRun(
            user_id=owner.id,
            input_type="CLAIM",
            research_depth="QUICK",
            status="QUEUED",
            submitted_text="Owned claim",
            normalized_target={},
            workflow_version="test",
        )
        db.add(run)
        db.commit()

        assert get_owned_run(db, owner_id=owner.id, run_id=run.id).id == run.id
        with pytest.raises(RunNotFoundError):
            get_owned_run(db, owner_id=other.id, run_id=run.id)
        with pytest.raises(RunNotFoundError):
            get_owned_run(db, owner_id=owner.id, run_id=uuid4())


def test_research_depth_limit_is_enforced_before_persistence(
    client: TestClient, session_factory: sessionmaker[Session], owner: User
):
    owner.usage_limits = {"allowed_research_depths": ["QUICK"]}

    response = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "research_depth": "DEEP", "text": "A claim"},
    )

    assert response.status_code == 403
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(VerificationRun)) == 0
        assert db.scalar(select(func.count()).select_from(AgentEvent)) == 0


def test_active_run_limit_is_enforced_before_persistence(
    client: TestClient, session_factory: sessionmaker[Session], owner: User
):
    owner.usage_limits = {"max_active_runs": 0}

    response = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "text": "A claim"},
    )

    assert response.status_code == 429
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(VerificationRun)) == 0
