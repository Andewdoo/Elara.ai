import pytest
from pydantic import ValidationError

from app.config import Settings


def test_server_environment_names_and_private_key_newlines(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://server/db")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com,https://preview.example.com")
    monkeypatch.setenv("FIREBASE_PRIVATE_KEY", "first\\nsecond")

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://server/db"
    assert settings.cors_allowed_origins == ["https://app.example.com", "https://preview.example.com"]
    assert settings.firebase_private_key == "first\nsecond"


def test_firebase_admin_certificate_metadata_is_constructed_server_side():
    settings = Settings(
        environment="test",
        firebase_project_id="firebase-project",
        firebase_client_email="firebase-admin@example.test",
        firebase_private_key="private-key",
    )

    certificate = settings.firebase_admin_credentials()

    assert certificate == {
        "type": "service_account",
        "token_uri": "https://oauth2.googleapis.com/token",
        "project_id": "firebase-project",
        "client_email": "firebase-admin@example.test",
        "private_key": "private-key",
    }


def test_credentialed_cors_rejects_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "origin",
    [
        "https://*.example.com",
        "https://example.com/app",
        "https://example.com/",
        "https://example.com?preview=true",
        "example.com",
    ],
)
def test_credentialed_cors_requires_exact_origins(monkeypatch, origin: str):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origin)
    with pytest.raises(ValidationError):
        Settings()


def test_object_storage_credentials_must_be_paired():
    with pytest.raises(ValidationError, match="configured together"):
        Settings(environment="test", s3_access_key_id="access", s3_secret_access_key=None)


def test_acceptance_mode_is_fail_closed_outside_test():
    with pytest.raises(ValidationError, match="only be enabled"):
        Settings(environment="development", acceptance_test_mode=True)

    assert Settings(environment="test", acceptance_test_mode=True).acceptance_test_mode
