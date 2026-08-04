from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
CONTAINER_REDIS_URLS = {
    "REDIS_URL": "redis://redis:6379/0",
    "CELERY_BROKER_URL": "redis://redis:6379/0",
    "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
}


def _service_definition(compose: str, service: str) -> str:
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|^volumes:)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"Missing Compose service: {service}"
    return match.group("body")


def _environment_value(service_definition: str, name: str) -> str:
    match = re.search(rf"^      {re.escape(name)}: (?P<value>[^\n]+)$", service_definition, re.MULTILINE)
    assert match is not None, f"Missing {name} environment value"
    return match.group("value").strip()


def test_api_and_worker_use_fixed_compose_redis_service_urls():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    for service in ("api", "worker"):
        definition = _service_definition(compose, service)
        assert ".env.private" in definition

        for name, expected in CONTAINER_REDIS_URLS.items():
            value = _environment_value(definition, name)
            assert value == expected
            assert "${" not in value
            assert urlsplit(value).hostname == "redis"


def test_compose_environment_overrides_private_host_redis_urls_for_containers():
    """Compose's explicit environment mapping wins over values loaded by env_file."""
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    for service in ("api", "worker"):
        definition = _service_definition(compose, service)
        for name in CONTAINER_REDIS_URLS:
            value = _environment_value(definition, name)
            assert "localhost" not in value
            assert "127.0.0.1" not in value


def test_web_compose_service_uses_live_host_source_with_an_isolated_next_cache():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    definition = _service_definition(compose, "web")

    assert _environment_value(definition, "WATCHPACK_POLLING") == '"true"'
    assert "./apps/web:/app/apps/web" in definition
    assert "web-next-cache:/app/apps/web/.next" in definition
    assert "  web-next-cache:" in compose
