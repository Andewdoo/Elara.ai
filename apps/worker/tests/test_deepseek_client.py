import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from agents.deepseek_client import (
    CallMetadata,
    DeepSeekAuthenticationError,
    DeepSeekClient,
    DeepSeekConfig,
    DeepSeekConfigurationError,
    DeepSeekRateLimitError,
    DeepSeekResponseError,
    DeepSeekTimeoutError,
    DeepSeekUnavailableError,
    TokenUsage,
    aggregate_call_metadata,
)
from elara_worker.errors import TransientProviderError


class ExampleOutput(BaseModel):
    answer: str


def config() -> DeepSeekConfig:
    return DeepSeekConfig(
        api_key="server-secret-key",
        base_url="https://provider.example.test",
        chat_model="deepseek-chat-test",
        reasoning_model="deepseek-reasoning-test",
        embedding_model=None,
    )


def run(coro):
    return asyncio.run(coro)


def test_environment_validation_requires_only_deepseek_server_settings(monkeypatch):
    names = (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_CHAT_MODEL",
        "DEEPSEEK_REASONING_MODEL",
        "DEEPSEEK_EMBEDDING_MODEL",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(DeepSeekConfigurationError) as exc_info:
        DeepSeekConfig.from_env()

    assert "DEEPSEEK_API_KEY" in str(exc_info.value)
    assert "DEEPSEEK_EMBEDDING_MODEL" not in str(exc_info.value)


def test_environment_loads_optional_embedding_model_and_validates_base_url():
    values = {
        "DEEPSEEK_API_KEY": "secret",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.example/v1/",
        "DEEPSEEK_CHAT_MODEL": "chat",
        "DEEPSEEK_REASONING_MODEL": "reasoner",
        "DEEPSEEK_EMBEDDING_MODEL": "embedding-approved",
    }

    loaded = DeepSeekConfig.from_env(values)

    assert loaded.base_url == "https://api.deepseek.example/v1"
    assert loaded.embedding_model == "embedding-approved"
    with pytest.raises(DeepSeekConfigurationError):
        DeepSeekConfig.from_env({**values, "DEEPSEEK_BASE_URL": "file:///private"})
    with pytest.raises(DeepSeekConfigurationError):
        DeepSeekConfig.from_env({**values, "DEEPSEEK_CHAT_MODEL": "private\ncontent"})


def test_structured_json_parsing_and_metadata_are_recorded():
    captured_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "response-123",
                "model": "deepseek-chat-test",
                "choices": [
                    {
                        "message": {"content": "```json\n{\"answer\":\"grounded\"}\n```"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 17,
                    "completion_tokens": 5,
                    "total_tokens": 22,
                },
            },
        )

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "private source passage"}],
                output_schema=ExampleOutput,
                prompt_version="intake-v1",
                temperature=0.1,
            )
        finally:
            await http_client.aclose()

    result = run(exercise())

    assert result.output.answer == "grounded"
    assert result.metadata.model == "deepseek-chat-test"
    assert result.metadata.prompt_version == "intake-v1"
    assert result.metadata.usage.total_tokens == 22
    assert result.metadata.latency_ms >= 0
    assert captured_request["response_format"] == {"type": "json_object"}
    assert captured_request["temperature"] == 0.1
    assert captured_request["stream"] is False
    assert "untrusted evidence" in captured_request["messages"][0]["content"]


@pytest.mark.parametrize(
    ("status_code", "expected_error", "is_transient"),
    [
        (401, DeepSeekAuthenticationError, False),
        (408, DeepSeekTimeoutError, True),
        (429, DeepSeekRateLimitError, True),
        (503, DeepSeekUnavailableError, True),
    ],
)
def test_provider_error_mapping_and_safe_logging(
    caplog: pytest.LogCaptureFixture,
    status_code: int,
    expected_error: type[Exception],
    is_transient: bool,
):
    private_text = "DO-NOT-LOG-PRIVATE-SOURCE"
    provider_detail = "DO-NOT-LOG-PROVIDER-BODY"
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code,
            json={"error": {"code": "rate_limit", "message": provider_detail}},
        )

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": private_text}],
                output_schema=ExampleOutput,
                prompt_version="evidence-v2",
                repair_invalid_response=True,
            )
        finally:
            await http_client.aclose()

    with caplog.at_level(logging.WARNING), pytest.raises(expected_error) as exc_info:
        run(exercise())

    assert isinstance(exc_info.value, TransientProviderError) is is_transient
    assert exc_info.value.metadata.status_code == status_code
    assert exc_info.value.metadata.prompt_version == "evidence-v2"
    assert exc_info.value.metadata.temperature == 0.1
    assert private_text not in caplog.text
    assert provider_detail not in caplog.text
    assert "server-secret-key" not in caplog.text
    assert call_count == 1


def test_invalid_json_maps_to_redacted_response_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not json"}}]},
        )

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "untrusted evidence"}],
                output_schema=ExampleOutput,
                prompt_version="audit-v1",
            )
        finally:
            await http_client.aclose()

    with pytest.raises(DeepSeekResponseError) as exc_info:
        run(exercise())

    assert exc_info.value.metadata.error_code == "STRUCTURED_RESPONSE_INVALID"
    assert exc_info.value.metadata.attempt_count == 1
    assert exc_info.value.__cause__ is None


def test_invalid_json_is_repaired_once_without_exposing_raw_response(
    caplog: pytest.LogCaptureFixture,
):
    raw_invalid_marker = "RAW-INVALID-JSON-MARKER"
    captured_requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        content = raw_invalid_marker if len(captured_requests) == 1 else '{"answer":"repaired"}'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 7},
            },
        )

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "trusted task context"}],
                output_schema=ExampleOutput,
                prompt_version="planner-v2",
                model_role="reasoning",
                temperature=0.1,
                repair_invalid_response=True,
            )
        finally:
            await http_client.aclose()

    with caplog.at_level(logging.INFO):
        result = run(exercise())

    assert result.output.answer == "repaired"
    assert result.metadata.attempt_count == 2
    assert len(captured_requests) == 2
    assert all(request["model"] == "deepseek-reasoning-test" for request in captured_requests)
    assert all(request["temperature"] == 0.1 for request in captured_requests)
    assert captured_requests[0]["messages"] == captured_requests[1]["messages"][:-1]
    assert captured_requests[1]["messages"][-1] == {
        "role": "system",
        "content": (
            "The previous response failed schema validation. Regenerate the complete response "
            "to conform exactly to the JSON Schema. Return only one JSON object."
        ),
    }
    assert raw_invalid_marker not in caplog.text
    assert raw_invalid_marker not in json.dumps(captured_requests)


def test_schema_invalid_json_is_repaired_once():
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        content = '{"unexpected":"field"}' if call_count == 1 else '{"answer":"valid"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "trusted task context"}],
                output_schema=ExampleOutput,
                prompt_version="planner-v2",
                repair_invalid_response=True,
            )
        finally:
            await http_client.aclose()

    result = run(exercise())

    assert result.output.answer == "valid"
    assert result.metadata.attempt_count == 2
    assert call_count == 2


def test_second_schema_invalid_response_is_repaired_one_final_time():
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        content = '{"unexpected":"field"}' if call_count < 3 else '{"answer":"valid"}'
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "trusted task context"}],
                output_schema=ExampleOutput,
                prompt_version="planner-v2",
                repair_invalid_response=True,
            )
        finally:
            await http_client.aclose()

    result = run(exercise())

    assert result.output.answer == "valid"
    assert result.metadata.attempt_count == 3
    assert call_count == 3


def test_third_schema_invalid_response_is_terminal_after_two_repairs():
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"unexpected":"field"}'}}]},
        )

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "trusted task context"}],
                output_schema=ExampleOutput,
                prompt_version="planner-v2",
                repair_invalid_response=True,
            )
        finally:
            await http_client.aclose()

    with pytest.raises(DeepSeekResponseError) as exc_info:
        run(exercise())

    assert call_count == 3
    assert exc_info.value.metadata.error_code == "STRUCTURED_RESPONSE_REPAIR_EXHAUSTED"
    assert exc_info.value.metadata.attempt_count == 3
    assert not isinstance(exc_info.value, TransientProviderError)


@pytest.mark.parametrize("max_schema_attempts", [1, 2, 3])
def test_configured_schema_attempt_bounds_are_exact(max_schema_attempts: int):
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"unexpected":"field"}'}}]},
        )

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "trusted task context"}],
                output_schema=ExampleOutput,
                prompt_version="bounded-v1",
                repair_invalid_response=True,
                max_schema_attempts=max_schema_attempts,
            )
        finally:
            await http_client.aclose()

    with pytest.raises(DeepSeekResponseError) as exc_info:
        run(exercise())

    assert call_count == max_schema_attempts
    assert exc_info.value.metadata.attempt_count == max_schema_attempts
    assert exc_info.value.metadata.error_code == (
        "STRUCTURED_RESPONSE_INVALID"
        if max_schema_attempts == 1
        else "STRUCTURED_RESPONSE_REPAIR_EXHAUSTED"
    )


@pytest.mark.parametrize("invalid_bound", [0, 4, True, 1.5])
def test_invalid_schema_attempt_bounds_are_rejected_before_request(invalid_bound):
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={})

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "trusted task context"}],
                output_schema=ExampleOutput,
                prompt_version="bounded-v1",
                repair_invalid_response=True,
                max_schema_attempts=invalid_bound,
            )
        finally:
            await http_client.aclose()

    with pytest.raises(ValueError, match="max_schema_attempts"):
        run(exercise())
    assert call_count == 0


def test_schema_diagnostics_and_repair_requests_exclude_invalid_content(
    caplog: pytest.LogCaptureFixture,
):
    private_marker = "PRIVATE-EVIDENCE-MARKER"
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = (
            json.dumps({"answer": {"marker": private_marker}})
            if len(requests) == 1
            else '{"answer":"valid"}'
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async def exercise():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "trusted task context"}],
                output_schema=ExampleOutput,
                prompt_version="safe-schema-v1",
                repair_invalid_response=True,
                max_schema_attempts=2,
            )
        finally:
            await http_client.aclose()

    with caplog.at_level(logging.WARNING):
        result = run(exercise())

    schema_record = next(
        record
        for record in caplog.records
        if getattr(record, "schema_error_kind", None) == "schema_validation"
    )
    assert schema_record.schema_error_types == ["string_type"]
    assert schema_record.schema_error_paths == ["answer"]
    assert result.metadata.request_count == 2
    assert result.metadata.repair_count == 1
    assert private_marker not in caplog.text
    assert private_marker not in json.dumps(requests)


def test_aggregate_metadata_sums_usage_and_requests_but_uses_wall_latency():
    calls = [
        CallMetadata(
            model="deepseek-chat-test",
            prompt_version="batch-v1",
            temperature=0,
            latency_ms=90,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        ),
        CallMetadata(
            model="deepseek-chat-test",
            prompt_version="batch-v1",
            temperature=0,
            latency_ms=80,
            usage=TokenUsage(prompt_tokens=20, completion_tokens=3, total_tokens=23),
            attempt_count=2,
            request_count=2,
            repair_count=1,
        ),
    ]

    aggregate = aggregate_call_metadata(calls, latency_ms=100)

    assert aggregate.latency_ms == 100
    assert aggregate.usage.model_dump() == {
        "prompt_tokens": 30,
        "completion_tokens": 5,
        "total_tokens": 35,
    }
    assert aggregate.request_count == 3
    assert aggregate.batch_count == 2
    assert aggregate.repair_count == 1
    assert aggregate.response_id is None


def test_legacy_call_metadata_defaults_remain_readable():
    metadata = CallMetadata.model_validate(
        {
            "model": "deepseek-chat-test",
            "prompt_version": "legacy-v1",
            "temperature": 0,
            "latency_ms": 5,
        }
    )

    assert (metadata.request_count, metadata.batch_count, metadata.repair_count) == (1, 1, 0)


def test_loggable_request_metadata_must_be_non_sensitive_identifiers():
    async def exercise():
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500, json={"error": {}})
            )
        )
        client = DeepSeekClient(config(), http_client=http_client)
        try:
            return await client.generate_structured(
                messages=[{"role": "user", "content": "evidence"}],
                output_schema=ExampleOutput,
                prompt_version="private source text with spaces",
            )
        finally:
            await http_client.aclose()

    with pytest.raises(ValueError, match="non-sensitive identifier"):
        run(exercise())


def test_api_key_is_redacted_from_configuration_representation():
    assert "server-secret-key" not in repr(config())


def test_worker_has_no_disallowed_provider_or_environment_references():
    worker_root = Path(__file__).resolve().parents[1]
    repository_root = worker_root.parents[1]
    forbidden_provider = "open" + "ai"
    forbidden_environment = forbidden_provider + "_api_key"

    inspected_paths = [
        *worker_root.rglob("*.py"),
        worker_root / "pyproject.toml",
        repository_root / ".env.example",
    ]
    for source_path in inspected_paths:
        source = source_path.read_text(encoding="utf-8").casefold()
        assert forbidden_provider not in source, source_path
        assert forbidden_environment not in source, source_path

    generated_web_directories = {".expo", ".next", "coverage", "node_modules"}
    for source_path in (repository_root / "apps" / "web").rglob("*"):
        if (
            source_path.is_file()
            and "tests" not in source_path.parts
            and not generated_web_directories.intersection(source_path.parts)
            and source_path.suffix in {".ts", ".tsx", ".js", ".mjs"}
        ):
            # Server-only web modules may legitimately use the provider's private
            # configuration. Browser bundles must never receive a public provider
            # environment variable.
            assert "next_public_deepseek_" not in source_path.read_text(
                encoding="utf-8"
            ).casefold()
