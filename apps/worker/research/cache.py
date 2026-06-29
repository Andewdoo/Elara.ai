"""Namespaced Redis cache helpers; durable evidence remains in PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from redis.exceptions import RedisError


class CacheBackend(Protocol):
    def get(self, key: str) -> bytes | str | None: ...
    def setex(self, key: str, ttl: int, value: str) -> object: ...
    def incr(self, key: str) -> int: ...
    def expire(self, key: str, ttl: int) -> object: ...


class RetrievalCache:
    def __init__(self, backend: CacheBackend | None, *, namespace: str = "elara:retrieval") -> None:
        self._backend = backend
        self._namespace = namespace

    @staticmethod
    def digest(*parts: str) -> str:
        payload = "\x1f".join(parts).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def key(self, category: str, *parts: str) -> str:
        return f"{self._namespace}:{category}:{self.digest(*parts)}"

    def get_json(self, key: str) -> Any | None:
        if self._backend is None:
            return None
        try:
            value = self._backend.get(key)
            if value is None:
                return None
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return json.loads(value)
        except (OSError, RedisError, UnicodeError, ValueError):
            return None

    def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        if self._backend is None:
            return
        try:
            self._backend.setex(
                key,
                ttl_seconds,
                json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str),
            )
        except (OSError, RedisError):
            return


class RetrievalRateLimiter:
    def __init__(
        self,
        backend: CacheBackend | None,
        *,
        window_seconds: int = 60,
        per_user: int = 30,
        per_domain: int = 10,
    ) -> None:
        self._backend = backend
        self.window_seconds = window_seconds
        self.per_user = per_user
        self.per_domain = per_domain

    def allow(self, *, user_id: str, domain: str) -> bool:
        if self._backend is None:
            return True
        try:
            return self._increment(f"elara:retrieval:rate:user:{user_id}") <= self.per_user and self._increment(
                f"elara:retrieval:rate:domain:{domain}"
            ) <= self.per_domain
        except (OSError, RedisError):
            # A transient cache outage must not silently erase durable work;
            # bounded per-run selection remains the fail-open safety limit.
            return True

    def _increment(self, key: str) -> int:
        count = self._backend.incr(key)  # type: ignore[union-attr]
        if count == 1:
            self._backend.expire(key, self.window_seconds)  # type: ignore[union-attr]
        return count


__all__ = ["RetrievalCache", "RetrievalRateLimiter"]
