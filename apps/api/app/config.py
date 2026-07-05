from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    s3_public_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket_name: str = "elara-local"
    s3_region: str = "us-east-1"
    s3_force_path_style: bool = True
    export_signed_url_ttl_seconds: int = Field(default=300, ge=60, le=900)
    sentry_dsn_api: str | None = None
    sentry_dsn_worker: str | None = None
    sentry_org: str | None = None
    sentry_project_web: str | None = None
    sentry_project_api: str | None = None
    sentry_project_worker: str | None = None
    sentry_auth_token: SecretStr | None = None
    sentry_traces_sample_rate: float = Field(default=0.05, ge=0, le=1)
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "elara-local"
    langsmith_endpoint: str | None = None
    deepseek_input_cost_per_million_tokens: float = Field(default=0, ge=0)
    deepseek_output_cost_per_million_tokens: float = Field(default=0, ge=0)
    search_cost_per_request: float = Field(default=0, ge=0)

    firebase_project_id: str | None = None
    firebase_client_email: str | None = None
    firebase_private_key: str | None = None
    firebase_session_cookie_name: str = "__Host-elara_session"
    firebase_session_ttl_minutes: int = Field(default=60, ge=5, le=120)
    firebase_fresh_token_max_age_seconds: int = Field(default=300, ge=60, le=600)
    firebase_session_same_site: Literal["lax", "strict", "none"] = "lax"

    verification_user_rate_limit: int = Field(default=10, ge=1, le=1_000)
    verification_ip_rate_limit: int = Field(default=30, ge=1, le=10_000)
    verification_rate_limit_window_seconds: int = Field(default=3_600, ge=60, le=86_400)
    upload_max_bytes: int = Field(default=25_000_000, ge=100_000, le=100_000_000)

    workflow_version: str = "step-18"
    citation_revision_limit: int = Field(default=2, ge=0, le=5)
    passage_embedding_dimension: int = Field(default=1536, gt=0)

    search_provider: Literal["brave"] = "brave"
    search_api_key: str | None = None
    search_base_url: str = "https://api.search.brave.com/res/v1"
    search_cache_ttl_seconds: int = Field(default=3_600, ge=60, le=86_400)
    fetch_cache_ttl_seconds: int = Field(default=21_600, ge=60, le=604_800)
    fetch_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=20)
    fetch_read_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    fetch_total_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    fetch_max_redirects: int = Field(default=3, ge=0, le=5)
    fetch_network_retries: int = Field(default=1, ge=0, le=2)
    fetch_max_html_bytes: int = Field(default=5_000_000, ge=100_000, le=25_000_000)
    fetch_max_pdf_bytes: int = Field(default=25_000_000, ge=100_000, le=100_000_000)
    fetch_allowed_ports: str = "80,443"
    fetch_storage_dir: Path = Field(
        default_factory=lambda: Path(gettempdir()) / "elara-fetched-sources"
    )

    @property
    def allowed_fetch_ports(self) -> frozenset[int]:
        try:
            ports = frozenset(int(value.strip()) for value in self.fetch_allowed_ports.split(","))
        except ValueError as exc:
            raise ValueError("FETCH_ALLOWED_PORTS must be a comma-separated list of ports") from exc
        if not ports or any(port < 1 or port > 65535 for port in ports):
            raise ValueError("FETCH_ALLOWED_PORTS contains an invalid port")
        return ports

    @model_validator(mode="after")
    def object_storage_credentials_are_paired(self) -> "Settings":
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be configured together")
        return self

    @property
    def effective_s3_public_endpoint_url(self) -> str:
        return self.s3_public_endpoint_url or self.s3_endpoint_url

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        origins: object
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

    @field_validator("web_app_url")
    @classmethod
    def validate_web_app_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or value.endswith("/")
        ):
            raise ValueError("WEB_APP_URL must be an exact HTTP(S) origin without a trailing slash")
        return value

    @field_validator("firebase_private_key")
    @classmethod
    def restore_private_key_newlines(cls, value: str | None) -> str | None:
        return value.replace("\\n", "\n") if value else value

    @field_validator("langsmith_endpoint")
    @classmethod
    def validate_langsmith_endpoint(cls, value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("LANGSMITH_ENDPOINT must be an HTTPS service URL without credentials")
        return value.rstrip("/")

    @model_validator(mode="after")
    def tracing_credentials_are_server_side_and_complete(self) -> "Settings":
        if self.langsmith_tracing and (not self.langsmith_api_key or not self.langsmith_project):
            raise ValueError(
                "LANGSMITH_API_KEY and LANGSMITH_PROJECT are required when LANGSMITH_TRACING is true"
            )
        return self

    @model_validator(mode="after")
    def production_settings_are_explicit_and_secure(self) -> "Settings":
        if self.environment not in {"staging", "production"}:
            return self
        origins = [urlsplit(value) for value in self.cors_allowed_origins]
        web_origin = urlsplit(self.web_app_url)
        if web_origin.scheme != "https":
            raise ValueError("WEB_APP_URL must use HTTPS outside development and test")
        normalized_web_origin = f"{web_origin.scheme}://{web_origin.netloc}"
        if normalized_web_origin not in self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must include the exact WEB_APP_URL origin")
        if any(origin.scheme != "https" for origin in origins):
            raise ValueError("CORS_ALLOWED_ORIGINS must use HTTPS outside development and test")
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("DATABASE_URL must use PostgreSQL outside development and test")
        database = urlsplit(self.database_url.replace("postgresql+psycopg://", "postgresql://", 1))
        if database.hostname in {"localhost", "127.0.0.1", "::1"} or "elara-local-password" in self.database_url:
            raise ValueError("DATABASE_URL must not use local or default credentials outside development and test")
        redis_urls = {
            "REDIS_URL": self.redis_url,
            "CELERY_BROKER_URL": self.effective_celery_broker_url,
            "CELERY_RESULT_BACKEND": self.effective_celery_result_backend,
        }
        if any(urlsplit(value).scheme != "rediss" for value in redis_urls.values()):
            raise ValueError(
                "Redis and Celery Redis URLs must use TLS (rediss://) outside development and test"
            )
        for name, value in {
            **redis_urls,
            "S3_ENDPOINT_URL": self.s3_endpoint_url,
            "S3_PUBLIC_ENDPOINT_URL": self.effective_s3_public_endpoint_url,
        }.items():
            parsed = urlsplit(value)
            if not parsed.hostname or parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError(f"{name} must not use a local endpoint outside development and test")
        if any(
            urlsplit(value).scheme != "https"
            for value in (self.s3_endpoint_url, self.effective_s3_public_endpoint_url)
        ):
            raise ValueError("S3 endpoints must use HTTPS outside development and test")
        required = {
            "FIREBASE_PROJECT_ID": self.firebase_project_id,
            "FIREBASE_CLIENT_EMAIL": self.firebase_client_email,
            "FIREBASE_PRIVATE_KEY": self.firebase_private_key,
            "S3_ACCESS_KEY_ID": self.s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
        }
        missing = [name for name, value in required.items() if not value or "replace-with" in value]
        if missing:
            raise ValueError(f"Production server credentials are missing or placeholders: {', '.join(missing)}")
        if not self.firebase_session_cookie_name.startswith("__Host-"):
            raise ValueError("Production Firebase session cookies must use the __Host- prefix")
        return self

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
