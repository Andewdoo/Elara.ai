"""Bounded httpx fetcher with DNS pinning and redirect revalidation."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from research.url_guard import GuardedUrl, UnsafeUrlError, UrlGuard
from research.cache import RetrievalCache


class FetchError(RuntimeError):
    def __init__(self, message: str, *, access_status: str = "FAILED", retryable: bool = False) -> None:
        super().__init__(message)
        self.access_status = access_status
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    content_length: int
    content_hash: str
    storage_path: str
    redirect_chain: tuple[str, ...]
    origin_fetched_at: str
    cache_hit: bool = False


class SnapshotStore(Protocol):
    def write(self, content: bytes, *, content_hash: str, suffix: str) -> str: ...
    def read(self, storage_path: str, *, expected_hash: str) -> bytes: ...
    def exists(self, storage_path: str, *, expected_hash: str) -> bool: ...


class SnapshotFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        worker_code = Path(__file__).resolve().parents[1]
        if self.root == worker_code or worker_code in self.root.parents:
            raise FetchError("snapshot storage must be outside worker executable paths")
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, content: bytes, *, content_hash: str, suffix: str) -> str:
        target = self.path_for(content_hash, suffix)
        if self.root not in target.parents:
            raise FetchError("snapshot storage path escaped its configured root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != content_hash:
            target.unlink()
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, target)
            try:
                target.chmod(0o600)
            except OSError:
                pass
        return str(target)

    def path_for(self, content_hash: str, suffix: str) -> Path:
        if len(content_hash) != 64 or any(value not in "0123456789abcdef" for value in content_hash):
            raise FetchError("snapshot content hash is invalid")
        return (self.root / content_hash[:2] / f"{content_hash}{suffix}").resolve()

    def read(self, storage_path: str, *, expected_hash: str) -> bytes:
        target = Path(storage_path).resolve()
        if self.root != target and self.root not in target.parents:
            raise FetchError("snapshot path is outside managed storage")
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise FetchError("snapshot content hash does not match durable metadata")
        return content

    def exists(self, storage_path: str, *, expected_hash: str) -> bool:
        try:
            self.read(storage_path, expected_hash=expected_hash)
        except (FetchError, OSError):
            return False
        return True


class S3SnapshotStore:
    """Private S3-compatible snapshot storage backed by safe local staging."""

    def __init__(
        self,
        *,
        client,
        bucket: str,
        staging: SnapshotFileStore,
        prefix: str = "source-snapshots",
        create_bucket_if_missing: bool = False,
        region: str = "us-east-1",
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.staging = staging
        self.prefix = prefix.strip("/")
        self.create_bucket_if_missing = create_bucket_if_missing
        self.region = region

    def write(self, content: bytes, *, content_hash: str, suffix: str) -> str:
        local_path = self.staging.write(content, content_hash=content_hash, suffix=suffix)
        key = self._key(content_hash, suffix)
        extra_args = {"ContentType": "application/pdf" if suffix == ".pdf" else "text/html"}
        try:
            self.client.upload_file(local_path, self.bucket, key, ExtraArgs=extra_args)
        except Exception:
            if not self.create_bucket_if_missing:
                raise
            create_args: dict[str, object] = {"Bucket": self.bucket}
            if self.region != "us-east-1":
                create_args["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.region
                }
            self.client.create_bucket(**create_args)
            self.client.upload_file(local_path, self.bucket, key, ExtraArgs=extra_args)
        return key

    def read(self, storage_path: str, *, expected_hash: str) -> bytes:
        suffix = Path(storage_path).suffix
        expected_key = self._key(expected_hash, suffix)
        if storage_path != expected_key:
            raise FetchError("snapshot object key does not match durable metadata")
        local_path = self.staging.path_for(expected_hash, suffix)
        if not self.staging.exists(str(local_path), expected_hash=expected_hash):
            local_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = local_path.with_suffix(local_path.suffix + ".download")
            self.client.download_file(self.bucket, storage_path, str(temporary))
            os.replace(temporary, local_path)
        return self.staging.read(str(local_path), expected_hash=expected_hash)

    def exists(self, storage_path: str, *, expected_hash: str) -> bool:
        try:
            if storage_path != self._key(expected_hash, Path(storage_path).suffix):
                return False
            self.client.head_object(Bucket=self.bucket, Key=storage_path)
            return True
        except Exception:
            return False

    def _key(self, content_hash: str, suffix: str) -> str:
        # path_for performs the strict hash validation without exposing its path.
        self.staging.path_for(content_hash, suffix)
        return f"{self.prefix}/{content_hash[:2]}/{content_hash}{suffix}"


class SecureFetcher:
    _HTML_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
    _PDF_TYPES = frozenset({"application/pdf"})
    _EXECUTABLE_TYPES = (
        "application/x-executable",
        "application/x-msdownload",
        "application/x-dosexec",
        "application/java-archive",
        "application/vnd.microsoft.portable-executable",
    )

    def __init__(
        self,
        *,
        guard: UrlGuard,
        store: SnapshotStore,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        total_timeout: float = 20.0,
        max_redirects: int = 3,
        max_html_bytes: int = 5_000_000,
        max_pdf_bytes: int = 25_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: RetrievalCache | None = None,
        cache_ttl_seconds: int = 21_600,
        network_retries: int = 1,
    ) -> None:
        self.guard = guard
        self.store = store
        self.total_timeout = total_timeout
        self.max_redirects = max_redirects
        self.max_html_bytes = max_html_bytes
        self.max_pdf_bytes = max_pdf_bytes
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.network_retries = network_retries
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout, pool=connect_timeout),
            follow_redirects=False,
            trust_env=False,
        )

    async def fetch(self, url: str) -> FetchResult:
        try:
            initial = await self.guard.validate(url)
        except UnsafeUrlError as exc:
            raise FetchError(str(exc), access_status="INACCESSIBLE") from exc
        cache_key = self.cache.key("fetch", initial.canonical_url) if self.cache else None
        cached_result = self._cached_result(cache_key)
        if cached_result is not None:
            return cached_result
        if self.cache is not None:
            with self.cache.fetch_lock(initial.canonical_url) as acquired:
                cached_result = self._cached_result(cache_key)
                if cached_result is not None:
                    return cached_result
                if not acquired:
                    raise FetchError("source fetch is already in progress", retryable=True)
                return await self._fetch_uncached(initial, cache_key)
        return await self._fetch_uncached(initial, cache_key)

    def _cached_result(self, cache_key: str | None) -> FetchResult | None:
        cached = self.cache.get_json(cache_key) if self.cache and cache_key else None
        if isinstance(cached, dict):
            try:
                values = {**cached, "redirect_chain": tuple(cached.get("redirect_chain", ()))}
                cached_result = FetchResult(**values)
            except (TypeError, ValueError):
                cached_result = None
            if cached_result is not None and self.store.exists(
                cached_result.storage_path, expected_hash=cached_result.content_hash
            ):
                return replace(cached_result, cache_hit=True)
        return None

    async def _fetch_uncached(
        self, initial: GuardedUrl, cache_key: str | None
    ) -> FetchResult:
        current = initial.canonical_url
        chain: list[str] = []
        try:
            async with asyncio.timeout(self.total_timeout):
                for redirect_count in range(self.max_redirects + 1):
                    response = None
                    guarded = None
                    for attempt in range(self.network_retries + 1):
                        guarded = await self.guard.validate(current)
                        try:
                            response = await self._request_pinned(guarded)
                            if response.status_code in {408, 429} or response.status_code >= 500:
                                await response.aclose()
                                if attempt >= self.network_retries:
                                    raise FetchError(
                                        "source returned a transient HTTP error",
                                        access_status="FAILED",
                                        retryable=True,
                                    )
                                continue
                            break
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt >= self.network_retries:
                                raise
                    assert response is not None and guarded is not None
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        await response.aclose()
                        if not location:
                            raise FetchError("redirect response did not include a destination")
                        if redirect_count >= self.max_redirects:
                            raise FetchError("redirect limit exceeded")
                        chain.append(guarded.canonical_url)
                        current = urljoin(guarded.canonical_url, location)
                        continue
                    result = await self._consume(response, guarded, tuple(chain))
                    if self.cache and cache_key:
                        self.cache.set_json(cache_key, asdict(result), ttl_seconds=self.cache_ttl_seconds)
                    return result
        except TimeoutError as exc:
            raise FetchError(
                "fetch exceeded the total request deadline",
                access_status="FAILED",
                retryable=True,
            ) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise FetchError(
                "source network request failed", access_status="FAILED", retryable=True
            ) from exc
        except UnsafeUrlError as exc:
            raise FetchError(str(exc), access_status="INACCESSIBLE") from exc
        raise FetchError("redirect handling failed")

    async def _request_pinned(self, guarded: GuardedUrl) -> httpx.Response:
        # The validated IP is put directly into the connection URL. Host and TLS
        # SNI retain the public hostname, preventing a second DNS lookup/rebind.
        address = guarded.addresses[0]
        parsed = urlsplit(guarded.canonical_url)
        host = f"[{address}]" if isinstance(ipaddress.ip_address(address), ipaddress.IPv6Address) else address
        default_port = 443 if parsed.scheme == "https" else 80
        netloc = host if guarded.port == default_port else f"{host}:{guarded.port}"
        pinned_url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
        host_header = guarded.hostname if guarded.port == default_port else f"{guarded.hostname}:{guarded.port}"
        request = self._client.build_request(
            "GET",
            pinned_url,
            headers={
                "Host": host_header,
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,text/plain;q=0.5",
                "User-Agent": "ElaraEvidenceBot/1.0 (+https://elara.ai/methodology)",
                "Connection": "close",
            },
            extensions={"sni_hostname": guarded.hostname},
        )
        return await self._client.send(request, stream=True)

    async def _consume(
        self, response: httpx.Response, guarded: GuardedUrl, chain: tuple[str, ...]
    ) -> FetchResult:
        try:
            if response.status_code in {401, 403}:
                status = "BOT_BLOCKED" if response.status_code == 403 else "PAYWALLED"
                raise FetchError("source requires authentication or denied automated access", access_status=status)
            if response.status_code == 402:
                raise FetchError("source is paywalled", access_status="PAYWALLED")
            if response.status_code >= 400:
                raise FetchError(f"source returned HTTP {response.status_code}", access_status="INACCESSIBLE")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
            if any(content_type == value for value in self._EXECUTABLE_TYPES):
                raise FetchError("executable content is not supported", access_status="UNSUPPORTED")
            if content_type not in self._HTML_TYPES | self._PDF_TYPES:
                raise FetchError("response content type is not supported", access_status="UNSUPPORTED")
            limit = self.max_pdf_bytes if content_type in self._PDF_TYPES else self.max_html_bytes
            declared = response.headers.get("content-length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise FetchError("response content length is invalid", access_status="UNSUPPORTED") from exc
                if declared_size < 0:
                    raise FetchError("response content length is invalid", access_status="UNSUPPORTED")
                if declared_size > limit:
                    raise FetchError("response exceeds the configured size limit", access_status="UNSUPPORTED")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise FetchError("response exceeds the configured size limit", access_status="UNSUPPORTED")
            raw = bytes(body)
            if content_type in self._HTML_TYPES and b"\x00" in raw[:4096]:
                raise FetchError("binary content is not supported as readable text", access_status="UNSUPPORTED")
            if content_type == "application/pdf" and not raw.startswith(b"%PDF-"):
                raise FetchError("PDF signature does not match its content type", access_status="UNSUPPORTED")
            if raw.startswith((b"MZ", b"\x7fELF")):
                raise FetchError("executable file signature is not supported", access_status="UNSUPPORTED")
            if raw.startswith((b"PK\x03\x04", b"\xfe\xed\xfa\xce", b"\xcf\xfa\xed\xfe", b"#!")):
                raise FetchError("archive or executable file signature is not supported", access_status="UNSUPPORTED")
            digest = hashlib.sha256(raw).hexdigest()
            suffix = ".pdf" if content_type == "application/pdf" else ".html"
            try:
                storage_path = self.store.write(raw, content_hash=digest, suffix=suffix)
            except FetchError:
                raise
            except Exception as exc:
                raise FetchError("private snapshot storage is unavailable", retryable=True) from exc
            return FetchResult(
                requested_url=chain[0] if chain else guarded.canonical_url,
                final_url=guarded.canonical_url,
                status_code=response.status_code,
                content_type=content_type,
                content_length=len(raw),
                content_hash=digest,
                storage_path=storage_path,
                redirect_chain=chain,
                origin_fetched_at=datetime.now(UTC).isoformat(),
            )
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def read_content(self, storage_path: str, *, expected_hash: str) -> bytes:
        return self.store.read(storage_path, expected_hash=expected_hash)


__all__ = [
    "FetchError",
    "FetchResult",
    "S3SnapshotStore",
    "SecureFetcher",
    "SnapshotFileStore",
    "SnapshotStore",
]
