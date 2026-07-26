import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any
from uuid import UUID

from redis import Redis
from redis.exceptions import LockError, ResponseError
from redis.lock import Lock

from app.config import Settings, get_settings


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def progress_stream_key(run_id: UUID | str) -> str:
    return f"elara:run:{run_id}:events"


def cancellation_key(run_id: UUID | str) -> str:
    return f"elara:run:{run_id}:cancel"


def fetch_lock_key(canonical_url: str) -> str:
    return f"elara:lock:fetch:{_digest(canonical_url)}"


def run_lock_key(run_id: UUID | str) -> str:
    return f"elara:lock:run:{run_id}"


def user_rate_limit_key(user_id: UUID | str) -> str:
    return f"elara:rl:user:{user_id}"


def ip_rate_limit_key(ip_address: str) -> str:
    return f"elara:rl:ip:{_digest(ip_address)}"


def domain_rate_limit_key(domain: str) -> str:
    normalized = domain.strip().rstrip(".").lower().encode("idna").decode("ascii")
    return f"elara:rl:domain:{normalized}"


def source_cache_key(canonical_url: str, revision_hash: str) -> str:
    return f"elara:cache:source:{_digest(canonical_url)}:{revision_hash}"


def search_cache_key(query: str) -> str:
    return f"elara:cache:search:{_digest(query)}"


def extract_cache_key(content_hash: str, parser_version: str) -> str:
    return f"elara:cache:extract:{content_hash}:{parser_version}"


def worker_liveness_key() -> str:
    """Return the transient key refreshed by a ready Celery worker."""
    return "elara:worker:liveness"


def has_live_worker(client: Redis) -> bool:
    """Return whether a worker heartbeat is present without treating Redis as truth."""
    return bool(client.get(worker_liveness_key()))


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=35,
    )


def publish_progress_event(
    client: Redis,
    *,
    settings: Settings,
    run_id: UUID,
    sequence: int,
    stage: str,
    event_type: str,
    message: str,
    payload: dict[str, Any],
    created_at: str,
) -> str:
    stream = progress_stream_key(run_id)
    event_id = f"{sequence}-0"
    try:
        client.xadd(
            stream,
            {
                "run_id": str(run_id),
                "sequence": str(sequence),
                "stage": stage,
                "event_type": event_type,
                "message": message,
                "payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
                "created_at": created_at,
            },
            id=event_id,
            maxlen=settings.redis_progress_max_events,
            approximate=True,
        )
    except ResponseError as exc:
        if "equal or smaller" not in str(exc).lower():
            raise
    client.expire(stream, settings.redis_progress_ttl_seconds)
    return event_id


def request_cancellation(client: Redis, *, settings: Settings, run_id: UUID) -> None:
    client.set(cancellation_key(run_id), "1", ex=settings.redis_cancellation_ttl_seconds)


def has_cancellation_flag(client: Redis, run_id: UUID) -> bool:
    return bool(client.exists(cancellation_key(run_id)))


def run_lock(client: Redis, *, settings: Settings, run_id: UUID) -> Lock:
    return client.lock(
        run_lock_key(run_id),
        timeout=settings.redis_lock_ttl_seconds,
        blocking_timeout=0,
        thread_local=False,
    )


def fetch_lock(client: Redis, *, settings: Settings, canonical_url: str) -> Lock:
    return client.lock(
        fetch_lock_key(canonical_url),
        timeout=settings.redis_lock_ttl_seconds,
        blocking_timeout=0,
        thread_local=False,
    )


@contextmanager
def acquired_lock(lock: Lock) -> Iterator[bool]:
    acquired = lock.acquire(blocking=False)
    try:
        yield bool(acquired)
    finally:
        if acquired:
            try:
                lock.release()
            except LockError:
                # The timeout may have elapsed during a long stage. A later worker
                # still re-checks PostgreSQL before doing any work.
                pass
