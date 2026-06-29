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


class MemoryCache:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, _ttl, value):
        self.values[key] = value


class FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        del ExtraArgs
        self.objects[(bucket, key)] = Path(path).read_bytes()

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {}

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[(bucket, key)])


async def _resolved(values: list[str]) -> list[str]:
    return values
