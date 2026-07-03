from app.observability import before_send


def test_sentry_event_scrubs_credentials_and_request_bodies():
    event = before_send({
        "request": {"data": "private upload", "cookies": {"session": "secret"}, "headers": {"Authorization": "Bearer secret", "Accept": "application/json"}},
        "extra": {"prompt": "private prompt", "run_id": "run-123"},
    }, {})
    assert "data" not in event["request"] and "cookies" not in event["request"]
    assert event["request"]["headers"]["Authorization"] == "[Filtered]"
    assert event["extra"] == {"prompt": "[Filtered]", "run_id": "run-123"}
