from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.rate_limits import RateLimitUnavailableError, enforce_verification_rate_limit
from app.services.uploads import UploadValidationError, validate_upload


def test_api_responses_include_browser_hardening_headers(client):
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-permitted-cross-domain-policies"] == "none"


def test_verification_rate_limit_runs_before_second_job_is_persisted(
    client, settings, dispatcher
):
    settings.verification_user_rate_limit = 1
    payload = {"input_type": "CLAIM", "text": "A bounded claim."}

    first = client.post("/v1/verifications", json=payload)
    second = client.post("/v1/verifications", json=payload)

    assert first.status_code == 202
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) > 0
    assert len(dispatcher.calls) == 1


def test_rate_limiter_fails_closed_in_production():
    class BrokenRedis:
        def incr(self, _key):
            raise OSError("private connection detail")

    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        cors_allowed_origins=["http://localhost:3000"],
    )
    settings.environment = "production"
    with pytest.raises(RateLimitUnavailableError):
        enforce_verification_rate_limit(
            BrokenRedis(), settings=settings, user_id=str(uuid4()), ip_address="203.0.113.2"
        )


@pytest.mark.parametrize(
    ("filename", "content_type", "body"),
    [
        ("payload.exe", "application/x-msdownload", b"MZbad"),
        ("report.pdf", "application/pdf", b"MZnot-a-pdf"),
        ("archive.txt", "text/plain", b"PK\x03\x04bad"),
        ("binary.txt", "text/plain", b"hello\x00world"),
        ("invalid-utf8.txt", "text/plain", b"hello\xffworld"),
        ("nested\\escape.pdf", "application/pdf", b"%PDF-1.7"),
        ("line\nbreak.pdf", "application/pdf", b"%PDF-1.7"),
        ("../escape.pdf", "application/pdf", b"%PDF-1.7"),
    ],
)
def test_upload_validation_rejects_executable_mismatched_and_unsafe_files(
    filename, content_type, body
):
    with pytest.raises(UploadValidationError):
        validate_upload(
            filename=filename, content_type=content_type, body=body, max_bytes=1_000_000
        )


def test_upload_validation_accepts_only_bounded_supported_content():
    result = validate_upload(
        filename="evidence.pdf",
        content_type="application/pdf",
        body=b"%PDF-1.7\nminimal",
        max_bytes=1_000_000,
    )
    assert result.content_hash
    with pytest.raises(UploadValidationError, match="size limit"):
        validate_upload(
            filename="evidence.pdf",
            content_type="application/pdf",
            body=b"%PDF-" + b"x" * 20,
            max_bytes=10,
        )


def test_production_config_rejects_insecure_origins_and_placeholder_credentials():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            web_app_url="http://app.example.com",
            cors_allowed_origins=["http://app.example.com"],
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"celery_broker_url": "redis://broker.example.com/0"}, "Redis and Celery"),
        ({"celery_result_backend": "redis://results.example.com/0"}, "Redis and Celery"),
        ({"s3_endpoint_url": "http://storage.example.com"}, "S3 endpoints"),
    ],
)
def test_production_config_rejects_insecure_worker_and_storage_transports(override, message):
    values = {
        "environment": "production",
        "ELARA_RELEASE_REVISION": "a" * 40,
        "web_app_url": "https://app.example.com",
        "cors_allowed_origins": ["https://app.example.com"],
        "database_url": "postgresql+psycopg://elara:secret@db.example.com/elara",
        "redis_url": "rediss://redis.example.com/0",
        "celery_broker_url": "rediss://broker.example.com/0",
        "celery_result_backend": "rediss://results.example.com/0",
        "s3_endpoint_url": "https://storage.example.com",
        "s3_public_endpoint_url": "https://downloads.example.com",
        "s3_access_key_id": "access-key",
        "s3_secret_access_key": "secret-key",
        "firebase_project_id": "firebase-project",
        "firebase_client_email": "admin@example.com",
        "firebase_private_key": "private-key",
    }
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **{**values, **override})
