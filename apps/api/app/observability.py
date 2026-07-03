"""Privacy-safe API error and performance monitoring."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
except ImportError:  # Allows lightweight tooling before optional runtime deps are installed.
    sentry_sdk = None  # type: ignore[assignment]
    FastApiIntegration = SqlalchemyIntegration = None  # type: ignore[assignment,misc]

from app.config import Settings


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "firebase_private_key",
    "password",
    "prompt",
    "request_body",
    "s3_secret_access_key",
    "search_api_key",
    "source_content",
    "token",
    "upload",
}


def _scrub(value: Any, *, key: str = "") -> Any:
    normalized = key.casefold()
    if any(part in normalized for part in _SENSITIVE_KEYS):
        return "[Filtered]"
    if isinstance(value, dict):
        return {str(item_key): _scrub(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item, key=key) for item in value[:50]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "...[truncated]"
    return value


def before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request["headers"] = _scrub(request.get("headers", {}))
    return _scrub(event)


@lru_cache(maxsize=4)
def _initialize(dsn: str, environment: str, sample_rate: float) -> None:
    if sentry_sdk is None:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=sample_rate,
        send_default_pii=False,
        before_send=before_send,
        max_request_body_size="never",
    )


def initialize_api_sentry(settings: Settings) -> None:
    if settings.environment != "test" and settings.sentry_dsn_api:
        _initialize(
            settings.sentry_dsn_api,
            settings.environment,
            settings.sentry_traces_sample_rate,
        )


__all__ = ["before_send", "initialize_api_sentry"]
