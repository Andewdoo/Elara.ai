from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models.enums import InputType


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_smoke_gate():
    path = REPO_ROOT / "scripts" / "smoke_gate.py"
    spec = importlib.util.spec_from_file_location("elara_smoke_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_health_exposes_non_secret_revision(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "test",
        "revision": "local",
    }


def test_staging_and_production_require_release_revision():
    with pytest.raises(ValidationError, match="ELARA_RELEASE_REVISION"):
        Settings(
            environment="staging",
            web_app_url="https://app.example.test",
            cors_allowed_origins=["https://app.example.test"],
            database_url="postgresql+psycopg://elara:password@db.example.test:5432/elara",
            redis_url="rediss://redis.example.test:6379/0",
            celery_broker_url="rediss://redis.example.test:6379/0",
            celery_result_backend="rediss://redis.example.test:6379/1",
            s3_endpoint_url="https://objects-internal.example.test",
            s3_public_endpoint_url="https://downloads.example.test",
            firebase_project_id="firebase-project",
            firebase_client_email="firebase-admin@example.test",
            firebase_private_key="private-key",
            s3_access_key_id="access-key",
            s3_secret_access_key="secret-key",
        )


def test_staging_allows_internal_compose_redis_and_instance_role_s3():
    settings = Settings(
        _env_file=None,
        environment="staging",
        ELARA_RELEASE_REVISION="a" * 40,
        web_app_url="https://app.example.test",
        cors_allowed_origins=["https://app.example.test"],
        database_url="postgresql+psycopg://elara:strong-password@postgres:5432/elara",
        redis_url="redis://redis:6379/0",
        celery_broker_url="redis://redis:6379/0",
        celery_result_backend="redis://redis:6379/1",
        s3_endpoint_url="https://s3.us-east-1.amazonaws.com",
        s3_public_endpoint_url="https://s3.us-east-1.amazonaws.com",
        s3_bucket_name="private-evidence-bucket",
        s3_force_path_style=False,
        firebase_project_id="firebase-project",
        firebase_client_email="firebase-admin@example.test",
        firebase_private_key="private-key",
        s3_access_key_id=None,
        s3_secret_access_key=None,
    )

    assert settings.environment == "staging"
    assert settings.s3_access_key_id is None


def test_staging_rejects_plaintext_remote_redis():
    with pytest.raises(ValidationError, match="internal Compose hostname redis"):
        Settings(
            _env_file=None,
            environment="staging",
            ELARA_RELEASE_REVISION="a" * 40,
            web_app_url="https://app.example.test",
            cors_allowed_origins=["https://app.example.test"],
            database_url="postgresql+psycopg://elara:strong-password@postgres:5432/elara",
            redis_url="redis://cache.example.test:6379/0",
            celery_broker_url="redis://cache.example.test:6379/0",
            celery_result_backend="redis://cache.example.test:6379/1",
            s3_endpoint_url="https://s3.us-east-1.amazonaws.com",
            s3_public_endpoint_url="https://s3.us-east-1.amazonaws.com",
            firebase_project_id="firebase-project",
            firebase_client_email="firebase-admin@example.test",
            firebase_private_key="private-key",
        )


def test_smoke_gate_fails_when_required_urls_are_missing(capsys):
    smoke_gate = _load_smoke_gate()

    status = smoke_gate.main(["--environment", "staging", "--require-https"])

    assert status == 1
    assert "API_BASE_URL is required" in capsys.readouterr().err


def test_smoke_gate_rejects_non_https_urls():
    smoke_gate = _load_smoke_gate()

    with pytest.raises(smoke_gate.SmokeGateError, match="must use HTTPS"):
        smoke_gate._origin("http://api.example.test", name="API_BASE_URL", require_https=True)


def test_smoke_gate_checks_api_health_and_web_origin(monkeypatch, capsys):
    smoke_gate = _load_smoke_gate()

    class FakeResponse:
        def __init__(self, status: int, body: bytes) -> None:
            self.status = status
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return self._body

    def fake_urlopen(request, *, timeout: float):
        assert timeout == 10
        if request.full_url == "https://api.example.test/health":
            return FakeResponse(200, b'{"status":"ok","revision":"abc123"}')
        if request.full_url == "https://app.example.test":
            return FakeResponse(200, b"<html></html>")
        raise AssertionError(request.full_url)

    monkeypatch.setattr(smoke_gate, "urlopen", fake_urlopen)

    status = smoke_gate.main(
        [
            "--environment",
            "staging",
            "--api-base-url",
            "https://api.example.test",
            "--web-app-url",
            "https://app.example.test",
            "--expected-revision",
            "abc123",
            "--require-https",
        ]
    )

    assert status == 0
    output = capsys.readouterr().out
    assert "staging api smoke ok" in output
    assert "staging web smoke ok" in output


def test_step25a_alert_definitions_cover_required_operational_signals():
    definitions = json.loads((REPO_ROOT / "infrastructure" / "alerts.step25a.json").read_text())

    assert {alert["id"] for alert in definitions["alerts"]} == {
        "api_failure_rate",
        "queue_depth",
        "run_duration",
        "provider_failure",
        "extraction_failure",
        "low_evidence_yield",
        "citation_audit_failure",
        "cost",
        "security_event",
    }


def test_step25a_controlled_live_cases_cover_every_mvp_input_type():
    plan = json.loads(
        (REPO_ROOT / "infrastructure" / "controlled-live-cases.step25a.json").read_text()
    )

    assert {case["input_type"] for case in plan["cases"]} == {item.value for item in InputType}
    assert "Do not place private data" in plan["log_policy"]
