from app.observability import before_send


def test_sentry_event_scrubs_credentials_and_request_bodies():
    event = before_send({
        "request": {"data": "private upload", "cookies": {"session": "secret"}, "headers": {"Authorization": "Bearer secret", "Accept": "application/json"}},
        "extra": {"prompt": "private prompt", "run_id": "run-123"},
    }, {})
    assert "data" not in event["request"] and "cookies" not in event["request"]
    assert event["request"]["headers"]["Authorization"] == "[Filtered]"
    assert event["extra"] == {"prompt": "[Filtered]", "run_id": "run-123"}


def test_sentry_event_drops_exception_breadcrumb_and_url_content():
    event = before_send({
        "exception": {"values": [{"value": "database failed for private evidence"}]},
        "breadcrumbs": [{"message": "full upload contents"}],
        "request": {"url": "https://example.test/private?token=secret"},
    }, {})
    assert event["exception"] == "[Filtered]"
    assert event["breadcrumbs"] == "[Filtered]"
    assert event["request"]["url"] == "[Filtered]"
