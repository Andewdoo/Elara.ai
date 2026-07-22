from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest

from research.cache import RetrievalCache
from research.fetcher import FetchError, S3SnapshotStore, SecureFetcher, SnapshotFileStore
from research.url_guard import UnsafeUrlError, UrlGuard, canonicalize_url


def run(value):
    return asyncio.run(value)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://100.100.100.200/",
        "http://example.test:22/",
        "http://user:secret@example.test/",
        "http://[::1",
    ],
)
def test_url_guard_rejects_ssrf_and_credentials(url):
    guard = UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"]))
    with pytest.raises(UnsafeUrlError):
        run(guard.validate(url))


def test_url_guard_rejects_any_mixed_private_dns_answer():
    guard = UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34", "10.0.0.9"]))
    with pytest.raises(UnsafeUrlError, match="non-public"):
        run(guard.validate("https://example.test/story"))


def test_canonicalization_removes_fragment_tracking_and_credentials_are_forbidden():
    assert canonicalize_url("HTTPS://Example.COM:443/a?utm_source=x&b=2&a=1#section") == (
        "https://example.com/a?a=1&b=2"
    )


def test_fetcher_pins_validated_ip_sends_no_credentials_and_enforces_size(tmp_path):
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "999"},
            content=b"small",
            request=request,
        )

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"])),
        store=SnapshotFileStore(tmp_path),
        max_html_bytes=100,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="size limit"):
        run(fetcher.fetch("https://example.test/story"))
    run(fetcher.aclose())
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "example.test"
    assert seen[0].headers["connection"] == "close"
    assert "authorization" not in seen[0].headers
    assert "cookie" not in seen[0].headers


def test_redirect_destination_is_re_resolved_and_private_target_is_blocked(tmp_path):
    resolutions: list[str] = []

    async def resolver(hostname: str, _port: int):
        resolutions.append(hostname)
        return ["93.184.216.34"] if hostname == "example.test" else ["10.0.0.7"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://internal.test/admin"}, request=request)

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=resolver),
        store=SnapshotFileStore(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="non-public"):
        run(fetcher.fetch("https://example.test/start"))
    run(fetcher.aclose())
    assert resolutions.count("example.test") >= 1
    assert "internal.test" in resolutions


def test_google_news_wrapper_redirects_to_a_revalidated_publisher_url(tmp_path):
    resolved_hosts: list[str] = []
    requested_hosts: list[str] = []

    async def resolver(hostname: str, _port: int):
        resolved_hosts.append(hostname)
        return ["93.184.216.34"]

    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        requested_hosts.append(host)
        if host == "news.google.com":
            return httpx.Response(
                302,
                headers={"location": "https://publisher.example/story?utm_source=news&b=2&a=1"},
                request=request,
            )
        assert host == "publisher.example"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body>Publisher article</body></html>",
            request=request,
        )

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=resolver),
        store=SnapshotFileStore(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    result = run(fetcher.fetch("https://news.google.com/articles/example"))
    run(fetcher.aclose())

    assert requested_hosts == ["news.google.com", "publisher.example"]
    assert "news.google.com" in resolved_hosts
    assert "publisher.example" in resolved_hosts
    assert result.requested_url == "https://news.google.com/articles/example"
    assert result.final_url == "https://publisher.example/story?a=1&b=2"
    assert result.redirect_chain == ("https://news.google.com/articles/example",)


def test_google_news_wrapper_fails_closed_when_publisher_redirect_is_private(tmp_path):
    async def resolver(hostname: str, _port: int):
        return ["93.184.216.34"] if hostname == "news.google.com" else ["10.0.0.9"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://private.publisher.example/article"},
            request=request,
        )

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=resolver),
        store=SnapshotFileStore(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="non-public"):
        run(fetcher.fetch("https://news.google.com/articles/example"))
    run(fetcher.aclose())


def test_dns_is_revalidated_immediately_before_connect_to_block_rebinding(tmp_path):
    resolutions = iter((["93.184.216.34"], ["10.0.0.8"]))
    requested = False

    async def resolver(_hostname: str, _port: int):
        return next(resolutions)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"unsafe", request=request)

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=resolver),
        store=SnapshotFileStore(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="non-public"):
        run(fetcher.fetch("https://example.test/rebind"))
    run(fetcher.aclose())
    assert requested is False


def test_chunked_response_is_aborted_when_streamed_bytes_exceed_limit(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"x" * 101,
            request=request,
        )

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"])),
        store=SnapshotFileStore(tmp_path),
        max_html_bytes=100,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="size limit"):
        run(fetcher.fetch("https://example.test/chunked"))
    run(fetcher.aclose())


def test_fetcher_rejects_executable_signature_and_writes_safe_html(tmp_path):
    responses = iter(
        [
            ("text/html", b"MZ" + b"x" * 20),
            ("text/html", b"<html><body>safe evidence</body></html>"),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        content_type, content = next(responses)
        return httpx.Response(200, headers={"content-type": content_type}, content=content, request=request)

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"])),
        store=SnapshotFileStore(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="executable"):
        run(fetcher.fetch("https://example.test/bad"))
    result = run(fetcher.fetch("https://example.test/good"))
    run(fetcher.aclose())
    assert Path(result.storage_path).is_file()
    assert tmp_path.resolve() in Path(result.storage_path).resolve().parents


def test_tampered_fetch_cache_cannot_read_paths_outside_managed_storage(tmp_path):
    backend = MemoryCache()
    cache = RetrievalCache(backend)
    key = cache.key("fetch", "https://example.test/story")
    cache.set_json(
        key,
        {
            "requested_url": "https://example.test/story",
            "final_url": "https://example.test/story",
            "status_code": 200,
            "content_type": "text/html",
            "content_length": 10,
            "content_hash": "a" * 64,
            "storage_path": str(tmp_path.parent / "outside-secret.txt"),
            "redirect_chain": [],
            "origin_fetched_at": "2026-06-29T00:00:00+00:00",
            "cache_hit": False,
        },
        ttl_seconds=60,
    )
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"safe", request=request)

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"])),
        store=SnapshotFileStore(tmp_path / "managed"),
        cache=cache,
        transport=httpx.MockTransport(handler),
    )
    result = run(fetcher.fetch("https://example.test/story"))
    run(fetcher.aclose())
    assert requests == 1
    assert result.cache_hit is False


def test_fetch_cache_reuses_verified_snapshot_without_second_origin_request(tmp_path):
    backend = MemoryCache()
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body>cached evidence</body></html>",
            request=request,
        )

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"])),
        store=SnapshotFileStore(tmp_path),
        cache=RetrievalCache(backend),
        transport=httpx.MockTransport(handler),
    )
    first = run(fetcher.fetch("https://example.test/cache"))
    second = run(fetcher.fetch("https://example.test/cache"))
    run(fetcher.aclose())

    assert requests == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.content_hash == first.content_hash


def test_fetcher_bounds_transient_http_retries(tmp_path):
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503, request=request)

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"])),
        store=SnapshotFileStore(tmp_path),
        network_retries=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="transient HTTP") as error:
        run(fetcher.fetch("https://example.test/transient"))
    run(fetcher.aclose())

    assert requests == 2
    assert error.value.retryable is True


def test_distributed_fetch_lock_prevents_duplicate_origin_request(tmp_path):
    backend = LockingMemoryCache(acquired=False)
    requested = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, content=b"must not run", request=request)

    fetcher = SecureFetcher(
        guard=UrlGuard(resolver=lambda *_: _resolved(["93.184.216.34"])),
        store=SnapshotFileStore(tmp_path),
        cache=RetrievalCache(backend),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError, match="already in progress") as error:
        run(fetcher.fetch("https://example.test/locked"))
    run(fetcher.aclose())

    assert requested is False
    assert error.value.retryable is True
    assert backend.last_lock is not None
    assert backend.last_lock.acquire_calls == 1


def test_s3_store_returns_private_object_key_and_verifies_download_hash(tmp_path):
    client = FakeS3Client()
    staging = SnapshotFileStore(tmp_path / "staging")
    store = S3SnapshotStore(client=client, bucket="private-evidence", staging=staging)
    content = b"durable source snapshot"
    digest = hashlib.sha256(content).hexdigest()
    key = store.write(content, content_hash=digest, suffix=".html")
    assert key == f"source-snapshots/{digest[:2]}/{digest}.html"
    assert "://" not in key
    assert store.exists(key, expected_hash=digest)
    assert store.read(key, expected_hash=digest) == content
    assert client.last_extra_args["ServerSideEncryption"] == "AES256"
    assert client.last_extra_args["CacheControl"] == "private, no-store"


def test_s3_store_can_use_local_minio_without_kms(tmp_path):
    client = FakeS3Client()
    store = S3SnapshotStore(
        client=client,
        bucket="private-evidence",
        staging=SnapshotFileStore(tmp_path / "staging"),
        server_side_encryption=None,
    )

    content = b"durable local source snapshot"
    store.write(content, content_hash=hashlib.sha256(content).hexdigest(), suffix=".html")

    assert "ServerSideEncryption" not in client.last_extra_args
    assert client.last_extra_args["CacheControl"] == "private, no-store"


class MemoryCache:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, _ttl, value):
        self.values[key] = value


class FakeLock:
    def __init__(self, acquired: bool):
        self.acquired = acquired
        self.acquire_calls = 0
        self.release_calls = 0

    def acquire(self, *, blocking: bool):
        assert blocking is False
        self.acquire_calls += 1
        return self.acquired

    def release(self):
        self.release_calls += 1


class LockingMemoryCache(MemoryCache):
    def __init__(self, *, acquired: bool):
        super().__init__()
        self.acquired = acquired
        self.last_lock: FakeLock | None = None

    def lock(self, _key, **kwargs):
        assert kwargs["blocking_timeout"] == 0
        assert kwargs["thread_local"] is False
        self.last_lock = FakeLock(self.acquired)
        return self.last_lock


class FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.last_extra_args = {}

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.last_extra_args = ExtraArgs or {}
        self.objects[(bucket, key)] = Path(path).read_bytes()

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {}

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[(bucket, key)])


async def _resolved(values: list[str]) -> list[str]:
    return values
