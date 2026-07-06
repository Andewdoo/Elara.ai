from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AgentEvent, ResearchDepth, User, VerificationRun
from app.redis_client import cancellation_key, progress_stream_key
from app.schemas.verifications import RunStatus
from app.services.run_lifecycle import persist_progress
from app.services.verifications import RunNotFoundError, get_authorized_run, get_owned_run


def test_create_verification_persists_run_and_first_event(
    client: TestClient,
    session_factory: sessionmaker[Session],
    owner: User,
    fake_redis,
    dispatcher,
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
        assert dispatcher.calls == [(run.id, ResearchDepth.STANDARD)]
        assert fake_redis.streams[progress_stream_key(run.id)][0]["event_type"] == "run.queued"


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

        with pytest.raises(RunNotFoundError):
            get_authorized_run(db, viewer_id=other.id, run_id=run.id)
        run.visibility = "public"
        db.commit()
        assert get_authorized_run(db, viewer_id=other.id, run_id=run.id).id == run.id


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


def test_cancel_queued_run_sets_durable_and_transient_flags(
    client: TestClient, session_factory: sessionmaker[Session], fake_redis
):
    created = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "research_depth": "QUICK", "text": "A claim"},
    ).json()

    response = client.post(f"/v1/verifications/{created['run_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert cancellation_key(created["run_id"]) in fake_redis.values
    with session_factory() as db:
        run_id = UUID(created["run_id"])
        run = db.get(VerificationRun, run_id)
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.sequence)
        ).all()
        assert run is not None and run.cancellation_requested_at is not None
        assert [event.event_type for event in events] == ["run.queued", "run.cancelled"]


def test_queue_failure_is_durable_and_uses_a_concise_public_code(
    client: TestClient, session_factory: sessionmaker[Session], dispatcher, fake_redis
):
    dispatcher.failure = RuntimeError("private broker connection details")

    response = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "text": "A claim"},
    )

    assert response.status_code == 503
    with session_factory() as db:
        run = db.scalar(select(VerificationRun))
        events = db.scalars(select(AgentEvent).order_by(AgentEvent.sequence)).all()
    assert run is not None and run.status == RunStatus.FAILED
    assert run.failure_code == "QUEUE_UNAVAILABLE"
    assert "private broker" not in (run.failure_message or "")
    assert [event.event_type for event in events] == ["run.queued", "run.failed"]
    stream = fake_redis.streams[progress_stream_key(run.id)]
    assert [event["event_type"] for event in stream] == ["run.queued", "run.failed"]


def test_active_run_cancellation_is_idempotent(
    client: TestClient, session_factory: sessionmaker[Session]
):
    created = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "text": "A claim"},
    ).json()
    run_id = UUID(created["run_id"])
    with session_factory() as db:
        persist_progress(
            db,
            run_id=run_id,
            stage=RunStatus.VALIDATING,
            event_type="run.validating",
            message="Validating input.",
        )

    first = client.post(f"/v1/verifications/{run_id}/cancel")
    second = client.post(f"/v1/verifications/{run_id}/cancel")

    assert first.status_code == second.status_code == 200
    assert first.json()["cancellation_requested_at"] == second.json()[
        "cancellation_requested_at"
    ]
    with session_factory() as db:
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.sequence)
        ).all()
    assert [event.event_type for event in events] == [
        "run.queued",
        "run.validating",
        "run.cancellation_requested",
    ]


def test_retry_creates_a_fresh_durable_attempt(client, session_factory, dispatcher):
    created = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "research_depth": "QUICK", "text": "A retryable claim"},
    ).json()
    original_id = UUID(created["run_id"])
    with session_factory() as db:
        run = db.get(VerificationRun, original_id)
        assert run is not None
        run.status = RunStatus.FAILED
        run.failure_code = "PROVIDER_UNAVAILABLE"
        db.commit()

    response = client.post(f"/v1/verifications/{original_id}/retry")

    assert response.status_code == 202
    retried_id = UUID(response.json()["run_id"])
    assert retried_id != original_id
    with session_factory() as db:
        original = db.get(VerificationRun, original_id)
        retried = db.get(VerificationRun, retried_id)
        event = db.scalar(select(AgentEvent).where(AgentEvent.run_id == retried_id))
        assert original is not None and original.status == RunStatus.FAILED
        assert retried is not None and retried.status == RunStatus.QUEUED
        assert retried.normalized_target["retried_from_run_id"] == str(original_id)
        assert event is not None and event.event_type == "run.retried"
    assert dispatcher.calls[-1][0] == retried_id


def test_retry_rejects_active_and_completed_runs(client):
    active = client.post(
        "/v1/verifications", json={"input_type": "CLAIM", "text": "An active claim"}
    ).json()
    assert client.post(f"/v1/verifications/{active['run_id']}/retry").status_code == 409
