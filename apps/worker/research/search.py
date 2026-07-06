"""Brave Search API client. This module is worker-only by construction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from research.cache import RetrievalCache


class SearchConfigurationError(RuntimeError):
    pass


class SearchProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class SearchResult:
    url: str
    title: str | None
    snippet: str | None
    rank: int
    published_at: str | None = None
    profile: str | None = None


class BraveSearchClient:
    def __init__(
        self,
        *,
        provider: str,
        api_key: str | None,
        base_url: str,
        cache: RetrievalCache | None = None,
        cache_ttl_seconds: int = 3_600,
        max_retries: int = 1,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if provider.casefold() != "brave":
            raise SearchConfigurationError("SEARCH_PROVIDER must be brave")
        if not api_key:
            raise SearchConfigurationError("SEARCH_API_KEY is required for Brave Search")
        parsed_base = urlsplit(base_url)
        if (
            parsed_base.scheme != "https"
            or not parsed_base.hostname
            or parsed_base.username
            or parsed_base.password
            or parsed_base.query
            or parsed_base.fragment
        ):
            raise SearchConfigurationError("SEARCH_BASE_URL must be an HTTPS service URL without credentials")
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/web/search"
        self._cache = cache
        self._cache_ttl = cache_ttl_seconds
        if not 0 <= max_retries <= 2:
            raise SearchConfigurationError("Brave Search retries must be between zero and two")
        self._max_retries = max_retries
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False, trust_env=False
        )
        self._owns_client = client is None

    async def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        count = max(1, min(count, 20))
        cache_key = self._cache.key("search-v1", self._endpoint, query, str(count)) if self._cache else None
        cached = self._cache.get_json(cache_key) if self._cache and cache_key else None
        if isinstance(cached, list):
            return [SearchResult(**item) for item in cached]
        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(
                    self._endpoint,
                    params={"q": query, "count": count, "safesearch": "moderate"},
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip",
                        "X-Subscription-Token": self._api_key,
                    },
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < self._max_retries:
                    continue
                message = (
                    "Brave Search timed out"
                    if isinstance(exc, httpx.TimeoutException)
                    else "Brave Search was unavailable"
                )
                raise SearchProviderError(message, retryable=True) from exc
            if response.status_code in {408, 429} or response.status_code >= 500:
                if attempt < self._max_retries:
                    continue
                raise SearchProviderError("Brave Search returned a transient error", retryable=True)
            break
        assert response is not None
        if response.status_code >= 400:
            raise SearchProviderError("Brave Search rejected the request")
        if len(response.content) > 2_000_000:
            raise SearchProviderError("Brave Search returned an oversized response")
        try:
            payload: dict[str, Any] = response.json()
            raw_results = payload.get("web", {}).get("results", [])
        except (ValueError, AttributeError) as exc:
            raise SearchProviderError("Brave Search returned an invalid response") from exc
        results = [
            SearchResult(
                url=str(item["url"]),
                title=_optional_text(item.get("title")),
                snippet=_optional_text(item.get("description")),
                rank=index,
                published_at=_optional_text(item.get("page_age") or item.get("age")),
                profile=_optional_text(item.get("profile", {}).get("long_name"))
                if isinstance(item.get("profile"), dict)
                else None,
            )
            for index, item in enumerate(raw_results, start=1)
            if isinstance(item, dict) and item.get("url")
        ]
        if self._cache and cache_key:
            self._cache.set_json(cache_key, [asdict(item) for item in results], ttl_seconds=self._cache_ttl)
        return results

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _optional_text(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


__all__ = [
    "BraveSearchClient",
    "SearchConfigurationError",
    "SearchProviderError",
    "SearchResult",
]
