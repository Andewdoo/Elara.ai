import json
from unittest.mock import Mock
from uuid import uuid4

from app.celery_app import VERIFICATION_QUEUES, celery_app
from app.config import Settings
from app.models.enums import ResearchDepth
from app.redis_client import (
    cancellation_key,
    domain_rate_limit_key,
    extract_cache_key,
    fetch_lock_key,
    ip_rate_limit_key,
    progress_stream_key,
    publish_progress_event,
    run_lock_key,
    search_cache_key,
    source_cache_key,
    user_rate_limit_key,
)
from app.services.queueing import CeleryVerificationDispatcher, QUEUE_BY_DEPTH, TASK_NAME


def test_research_depths_route_to_distinct_named_queues():
    application = Mock()
    application.send_task.return_value.id = "task-id"
    dispatcher = CeleryVerificationDispatcher(application)
    run_id = uuid4()

    for depth, queue in QUEUE_BY_DEPTH.items():
        assert dispatcher.enqueue(run_id, depth) == "task-id"
        application.send_task.assert_called_with(TASK_NAME, args=[str(run_id)], queue=queue)

    assert set(QUEUE_BY_DEPTH) == set(ResearchDepth)


def test_celery_declares_all_verification_queues_and_safe_delivery_defaults():
    assert {queue.name for queue in celery_app.conf.task_queues} == set(VERIFICATION_QUEUES)
    assert celery_app.conf.task_default_queue == "verification.standard"
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_redis_keys_are_namespaced_stable_and_privacy_preserving():
    run_id = uuid4()
    assert progress_stream_key(run_id) == f"elara:run:{run_id}:events"
    assert cancellation_key(run_id) == f"elara:run:{run_id}:cancel"
    assert run_lock_key(run_id) == f"elara:lock:run:{run_id}"
    assert fetch_lock_key("https://example.com/a") == fetch_lock_key("https://example.com/a")
    assert "example.com" not in fetch_lock_key("https://example.com/a")
    assert user_rate_limit_key("user-1") == "elara:rl:user:user-1"
    assert "203.0.113.10" not in ip_rate_limit_key("203.0.113.10")
    assert domain_rate_limit_key("EXAMPLE.COM.") == "elara:rl:domain:example.com"
    assert source_cache_key("https://example.com", "rev").endswith(":rev")
    assert search_cache_key("query") == search_cache_key("query")
    assert extract_cache_key("content", "parser-v1").startswith("elara:cache:extract:content:")


def test_progress_event_is_json_safe_and_gets_a_ttl(fake_redis):
    settings = Settings(environment="test", redis_progress_ttl_seconds=600)
    run_id = uuid4()
    event_id = publish_progress_event(
        fake_redis,
        settings=settings,
        run_id=run_id,
        sequence=2,
        stage="VALIDATING",
        event_type="run.validating",
        message="Validating the submitted verification target.",
        payload={"completed_steps": 0, "total_steps": 9},
        created_at="2026-06-27T12:00:00+00:00",
    )

    key = progress_stream_key(run_id)
    assert event_id == "2-0"
    assert json.loads(fake_redis.streams[key][0]["payload"])["total_steps"] == 9
    assert fake_redis.expirations[key] == 600

    duplicate_id = publish_progress_event(
        fake_redis,
        settings=settings,
        run_id=run_id,
        sequence=2,
        stage="VALIDATING",
        event_type="run.validating",
        message="Validating the submitted verification target.",
        payload={"completed_steps": 0, "total_steps": 9},
        created_at="2026-06-27T12:00:00+00:00",
    )
    assert duplicate_id == "2-0"
    assert len(fake_redis.streams[key]) == 1
