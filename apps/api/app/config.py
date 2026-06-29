from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.private",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        enable_decoding=False,
    )

    app_name: str = "Elara API"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://elara:elara-local-password@localhost:5432/elara"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    redis_progress_max_events: int = Field(default=1_000, ge=100, le=100_000)
    redis_progress_ttl_seconds: int = Field(default=86_400, ge=300)
    redis_cancellation_ttl_seconds: int = Field(default=86_400, ge=300)
    redis_lock_ttl_seconds: int = Field(default=3_600, ge=60)
    sse_heartbeat_seconds: int = Field(default=20, ge=15, le=30)
    web_app_url: str = "http://localhost:3000"
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket_name: str = "elara-local"
    s3_region: str = "us-east-1"
    s3_force_path_style: bool = True
    sentry_dsn_api: str | None = None

    firebase_project_id: str | None = None
    firebase_client_email: str | None = None
    firebase_private_key: str | None = None
    firebase_session_cookie_name: str = "elara_session"
    firebase_session_ttl_minutes: int = Field(default=60, ge=5, le=120)
    firebase_fresh_token_max_age_seconds: int = Field(default=300, ge=60, le=600)
    firebase_session_same_site: Literal["lax", "strict", "none"] = "lax"

    workflow_version: str = "step-8"
    passage_embedding_dimension: int = Field(default=1536, gt=0)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        else:
            origins = value
        if not isinstance(origins, list) or not origins:
            raise ValueError("At least one exact CORS origin is required")
        for origin in origins:
            if not isinstance(origin, str) or origin == "*" or "*" in origin:
                raise ValueError("Wildcard CORS origins are not allowed with credentials")
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("CORS origins must be absolute HTTP(S) origins")
            if parsed.username or parsed.password or parsed.path not in {"", "/"}:
                raise ValueError("CORS entries must be exact origins without credentials or paths")
            if parsed.query or parsed.fragment or origin.endswith("/"):
                raise ValueError("CORS entries must not include paths, queries, fragments, or trailing slashes")
        return origins

    @field_validator("firebase_private_key")
    @classmethod
    def restore_private_key_newlines(cls, value: str | None) -> str | None:
        return value.replace("\\n", "\n") if value else value

    @property
    def effective_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def effective_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    def firebase_admin_credentials(self) -> dict[str, str]:
        required_values = {
            "project_id": self.firebase_project_id,
            "client_email": self.firebase_client_email,
            "private_key": self.firebase_private_key,
        }
        missing = [name for name, value in required_values.items() if not value]
        if missing:
            raise RuntimeError(f"Missing Firebase Admin configuration: {', '.join(missing)}")
        return {
            "type": "service_account",
            "token_uri": "https://oauth2.googleapis.com/token",
            **{name: value for name, value in required_values.items() if value is not None},
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
