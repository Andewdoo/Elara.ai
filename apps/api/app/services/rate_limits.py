"""Redis-backed fixed-window limits enforced before expensive jobs are queued."""

from __future__ import annotations

from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError

from app.config import Settings
from app.redis_client import ip_rate_limit_key, user_rate_limit_key


class RateLimitExceededError(PermissionError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Verification request rate limit reached")
        self.retry_after = max(1, retry_after)


class RateLimitUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Limit:
    key: str
    maximum: int


def enforce_verification_rate_limit(
    client: Redis,
    *,
    settings: Settings,
    user_id: str,
    ip_address: str,
) -> None:
    limits = (
        _Limit(user_rate_limit_key(user_id), settings.verification_user_rate_limit),
        _Limit(ip_rate_limit_key(ip_address), settings.verification_ip_rate_limit),
    )
    try:
        for limit in limits:
            count = int(client.incr(limit.key))
            if count == 1:
                client.expire(limit.key, settings.verification_rate_limit_window_seconds)
            if count > limit.maximum:
                ttl = int(client.ttl(limit.key))
                raise RateLimitExceededError(
                    ttl if ttl > 0 else settings.verification_rate_limit_window_seconds
                )
    except RateLimitExceededError:
        raise
    except (RedisError, OSError, ValueError, TypeError) as exc:
        if settings.environment in {"staging", "production"}:
            raise RateLimitUnavailableError("Verification rate limiter is unavailable") from exc


__all__ = [
    "RateLimitExceededError",
    "RateLimitUnavailableError",
    "enforce_verification_rate_limit",
]
