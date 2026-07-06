"""Worker-only Sentry setup with aggressive payload scrubbing."""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Any

try:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
except ImportError:  # Runtime dependencies are installed by the worker image.
    sentry_sdk = None  # type: ignore[assignment]
    CeleryIntegration = RedisIntegration = None  # type: ignore[assignment,misc]


_FILTERED = ("authorization", "cookie", "credential", "key", "prompt", "secret", "source", "token", "upload")
_CONTENT_KEYS = {"breadcrumbs", "exception", "logentry", "message", "query_string", "stacktrace", "url", "value"}
_SECRET_VALUE = re.compile(r"(?i)(bearer\s+\S+|password\s*[=:]|api[_-]?key\s*[=:]|-----BEGIN [A-Z ]+PRIVATE KEY-----|[?&](?:token|key|secret)=)")
_SAFE_STRING_KEYS = {"environment", "event_id", "level", "logger", "release", "run_id", "status", "transaction", "type"}


def _scrub(value: Any, key: str = "") -> Any:
    if any(part in key.casefold() for part in _FILTERED):
        return "[Filtered]"
    if key.casefold() in _CONTENT_KEYS:
        return "[Filtered]"
    if isinstance(value, dict):
        return {str(k): _scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item, key) for item in value[:50]]
    if isinstance(value, str):
        if _SECRET_VALUE.search(value) or (len(value) > 100 and key.casefold() not in _SAFE_STRING_KEYS):
            return "[Filtered]"
    return value


def before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    event.pop("request", None)
    return _scrub(event)


@lru_cache(maxsize=4)
def _initialize(dsn: str, environment: str, sample_rate: float) -> None:
    if sentry_sdk is None:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[CeleryIntegration(), RedisIntegration()],
        traces_sample_rate=sample_rate,
        send_default_pii=False,
        before_send=before_send,
        max_request_body_size="never",
    )


def initialize_worker_sentry(settings: Any) -> None:
    if settings.environment != "test" and settings.sentry_dsn_worker:
        _initialize(
            settings.sentry_dsn_worker,
            settings.environment,
            settings.sentry_traces_sample_rate,
        )


__all__ = ["before_send", "initialize_worker_sentry"]
