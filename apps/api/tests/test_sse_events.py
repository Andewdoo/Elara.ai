import json
from uuid import UUID

from app.models.enums import RunStatus
from app.redis_client import publish_progress_event


def _create_run(client):
    response = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "research_depth": "QUICK", "text": "A test claim"},
        headers={"Authorization": "Bearer valid-test-token"},
    )
    assert response.status_code == 202
    return response.json()["run_id"]


def test_sse_replays_after_last_event_id_and_closes_on_terminal(
    client, fake_redis, settings
):
    run_id = _create_run(client)
    publish_progress_event(
        fake_redis,
        settings=settings,
        run_id=UUID(run_id),
        sequence=2,
        stage=RunStatus.CANCELLED.value,
        event_type="run.cancelled",
        message="Verification cancelled.",
        payload={"completed_steps": 1, "total_steps": 9, "inaccessible_count": 2},
        created_at="2026-06-27T12:00:00+00:00",
    )

    response = client.get(
        f"/v1/verifications/{run_id}/events",
        headers={"Last-Event-ID": "1-0"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2-0" in response.text
    assert "id: 1-0" not in response.text
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    event = json.loads(data_line.removeprefix("data: "))
    assert event["stage"] == "CANCELLED"
    assert event["inaccessible_count"] == 2


def test_sse_rejects_url_tokens_and_invalid_replay_cursor(client):
    run_id = _create_run(client)
    token_response = client.get(f"/v1/verifications/{run_id}/events?token=secret")
    cursor_response = client.get(
        f"/v1/verifications/{run_id}/events", headers={"Last-Event-ID": "not-a-stream-id"}
    )

    assert token_response.status_code == 400
    assert cursor_response.status_code == 400


def test_sse_uses_terminal_postgresql_status_when_redis_stream_is_empty(
    client, fake_redis
):
    run_id = _create_run(client)
    cancelled = client.post(f"/v1/verifications/{run_id}/cancel")
    assert cancelled.status_code == 200
    fake_redis.streams.clear()
    fake_redis.stream_entries.clear()
    fake_redis.stream_ids.clear()

    response = client.get(f"/v1/verifications/{run_id}/events")

    assert response.status_code == 200
    assert '"stage":"CANCELLED"' in response.text
    assert "Verification cancelled before research began." in response.text


def test_cors_only_allows_configured_credentialed_origin(client):
    allowed = client.options(
        "/v1/verifications/example/events",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Last-Event-ID",
        },
    )
    denied = client.options(
        "/v1/verifications/example/events",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in denied.headers


def test_run_read_uses_durable_postgresql_state(client):
    run_id = _create_run(client)
    response = client.get(
        f"/v1/verifications/{run_id}",
        headers={"Authorization": "Bearer valid-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"
    assert response.json()["run_id"] == run_id
