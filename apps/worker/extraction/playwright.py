"""Isolated, policy-enforced Playwright fallback for important HTML sources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from extraction.html import extract_with_beautiful_soup
from extraction.models import ExtractedDocument
from research.url_guard import GuardedUrl, UnsafeUrlError, UrlGuard


class PlaywrightExtractionError(RuntimeError):
    def __init__(self, message: str, *, access_status: str = "INACCESSIBLE") -> None:
        super().__init__(message)
        self.access_status = access_status


@dataclass(frozen=True, slots=True)
class PlaywrightLimits:
    navigation_timeout_seconds: float = 12.0
    total_timeout_seconds: float = 20.0
    max_response_bytes: int = 5_000_000
    max_total_response_bytes: int = 8_000_000
    max_dom_bytes: int = 5_000_000
    max_dom_nodes: int = 50_000
    max_redirects: int = 3
    max_retries: int = 1
    settle_time_ms: int = 500

    def __post_init__(self) -> None:
        if self.navigation_timeout_seconds <= 0 or self.total_timeout_seconds <= 0:
            raise ValueError("Playwright timeouts must be positive")
        if self.navigation_timeout_seconds > self.total_timeout_seconds:
            raise ValueError("navigation timeout cannot exceed total timeout")
        if min(
            self.max_response_bytes,
            self.max_total_response_bytes,
            self.max_dom_bytes,
            self.max_dom_nodes,
        ) <= 0:
            raise ValueError("Playwright size limits must be positive")
        if not 0 <= self.max_redirects <= 5:
            raise ValueError("Playwright redirect limit must be between zero and five")
        if not 0 <= self.max_retries <= 1:
            raise ValueError("Playwright retries cannot exceed one")
        if not 0 <= self.settle_time_ms <= 2_000:
            raise ValueError("Playwright settle time must be between zero and 2000ms")


BrowserLauncher = Callable[[], Awaitable[Any]]
_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font", "websocket", "eventsource"})
_SENSITIVE_REQUEST_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization", "x-api-key", "x-auth-token"}
)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class PlaywrightExtractor:
    def __init__(
        self,
        *,
        guard: UrlGuard,
        limits: PlaywrightLimits | None = None,
        browser_launcher: BrowserLauncher | None = None,
    ) -> None:
        self.guard = guard
        self.limits = limits or PlaywrightLimits()
        self._browser_launcher = browser_launcher

    async def extract(self, *, url: str, fallback_reason: str) -> ExtractedDocument:
        last_error: PlaywrightExtractionError | None = None
        for _attempt in range(self.limits.max_retries + 1):
            try:
                async with asyncio.timeout(self.limits.total_timeout_seconds):
                    return await self._extract_once(
                        url=url,
                        fallback_reason=fallback_reason,
                    )
            except TimeoutError:
                last_error = PlaywrightExtractionError(
                    "browser fallback exceeded its total deadline", access_status="FAILED"
                )
            except PlaywrightExtractionError as exc:
                last_error = exc
                if exc.access_status in {"INACCESSIBLE", "UNSUPPORTED"}:
                    break
        assert last_error is not None
        raise last_error

    async def _extract_once(self, *, url: str, fallback_reason: str) -> ExtractedDocument:
        try:
            initial = await self.guard.validate(url)
        except UnsafeUrlError as exc:
            raise PlaywrightExtractionError(str(exc)) from exc
        browser, playwright_owner = await self._launch_browser(initial)
        context = None
        try:
            context = await browser.new_context(
                accept_downloads=False,
                java_script_enabled=True,
                service_workers="block",
                extra_http_headers={
                    "DNT": "1",
                    "User-Agent": "ElaraEvidenceBot/1.0 (+https://elara.ai/methodology)",
                },
            )
            page = await context.new_page()
            policy_error: PlaywrightExtractionError | None = None
            response_bytes = 0
            navigation_urls: list[str] = []
            document_host = (urlsplit(url).hostname or "").casefold()

            async def intercept(route: Any, request: Any) -> None:
                nonlocal policy_error, response_bytes, document_host
                try:
                    guarded = await self.guard.validate(request.url)
                    is_navigation = bool(request.is_navigation_request())
                    if is_navigation and request.frame != page.main_frame:
                        await route.abort("blockedbyclient")
                        return
                    is_document = is_navigation and request.frame == page.main_frame
                    if is_document:
                        if navigation_urls and guarded.hostname != document_host:
                            raise PlaywrightExtractionError(
                                "browser cross-host redirect is not allowed"
                            )
                        if not navigation_urls or navigation_urls[-1] != guarded.canonical_url:
                            navigation_urls.append(guarded.canonical_url)
                        if len(navigation_urls) - 1 > self.limits.max_redirects:
                            raise PlaywrightExtractionError("browser redirect limit exceeded")
                        document_host = guarded.hostname
                    elif guarded.hostname != document_host:
                        await route.abort("blockedbyclient")
                        return
                    if request.resource_type in _BLOCKED_RESOURCE_TYPES or request.method != "GET":
                        await route.abort("blockedbyclient")
                        return
                    headers = {
                        key: value
                        for key, value in (await request.all_headers()).items()
                        if key.casefold() not in _SENSITIVE_REQUEST_HEADERS
                    }
                    response = await route.fetch(
                        headers=headers,
                        max_redirects=0,
                        timeout=self.limits.navigation_timeout_seconds * 1_000,
                    )
                    response_headers = {
                        key: value
                        for key, value in response.headers.items()
                        if key.casefold() not in {"set-cookie", "set-cookie2"}
                    }
                    declared = response_headers.get("content-length")
                    if declared is not None:
                        try:
                            declared_size = int(declared)
                        except ValueError as exc:
                            raise PlaywrightExtractionError(
                                "browser response content length is invalid",
                                access_status="UNSUPPORTED",
                            ) from exc
                        if declared_size < 0 or declared_size > self.limits.max_response_bytes:
                            raise PlaywrightExtractionError(
                                "browser response exceeds its size limit",
                                access_status="UNSUPPORTED",
                            )
                    body = await response.body()
                    if len(body) > self.limits.max_response_bytes:
                        raise PlaywrightExtractionError(
                            "browser response exceeds its size limit",
                            access_status="UNSUPPORTED",
                        )
                    response_bytes += len(body)
                    if response_bytes > self.limits.max_total_response_bytes:
                        raise PlaywrightExtractionError(
                            "browser page exceeded its total response-size limit",
                            access_status="UNSUPPORTED",
                        )
                    if response.status in _REDIRECT_STATUSES and "location" not in response_headers:
                        raise PlaywrightExtractionError("browser redirect omitted its destination")
                    await route.fulfill(
                        status=response.status,
                        headers=response_headers,
                        body=body,
                    )
                except UnsafeUrlError as exc:
                    policy_error = PlaywrightExtractionError(str(exc))
                    await route.abort("blockedbyclient")
                except PlaywrightExtractionError as exc:
                    policy_error = exc
                    await route.abort("blockedbyclient")
                except Exception:
                    policy_error = PlaywrightExtractionError(
                        "browser request failed safely", access_status="FAILED"
                    )
                    await route.abort("failed")

            await context.route("**/*", intercept)

            async def close_popup(popup: Any) -> None:
                await popup.close()

            context.on("page", lambda popup: asyncio.create_task(close_popup(popup)) if popup != page else None)
            page.on("download", lambda download: asyncio.create_task(download.cancel()))
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.limits.navigation_timeout_seconds * 1_000,
                )
                if self.limits.settle_time_ms:
                    await page.wait_for_timeout(self.limits.settle_time_ms)
            except Exception as exc:
                if policy_error is not None:
                    raise policy_error from exc
                raise PlaywrightExtractionError(
                    "browser navigation failed safely", access_status="FAILED"
                ) from exc
            if policy_error is not None:
                raise policy_error
            if response is None or response.status >= 400:
                raise PlaywrightExtractionError("browser navigation did not return a readable page")
            try:
                final = await self.guard.validate(page.url)
            except UnsafeUrlError as exc:
                raise PlaywrightExtractionError(str(exc)) from exc
            if final.hostname != document_host:
                raise PlaywrightExtractionError("browser final URL did not match the validated navigation")
            html = await page.content()
            encoded = html.encode("utf-8", errors="replace")
            if len(encoded) > self.limits.max_dom_bytes:
                raise PlaywrightExtractionError(
                    "rendered DOM exceeds its size limit", access_status="UNSUPPORTED"
                )
            node_count = int(await page.evaluate("document.getElementsByTagName('*').length"))
            if node_count > self.limits.max_dom_nodes:
                raise PlaywrightExtractionError(
                    "rendered DOM exceeds its node limit", access_status="UNSUPPORTED"
                )
            document = extract_with_beautiful_soup(encoded, url=final.canonical_url)
            if document is None:
                raise PlaywrightExtractionError("rendered page contained insufficient readable content")
            try:
                parser_version = version("playwright")
            except PackageNotFoundError:
                parser_version = "unknown"
            return replace(
                document,
                parser_name="playwright",
                parser_version=parser_version,
                metadata={
                    **document.metadata,
                    "fallback_reason": fallback_reason,
                    "extraction_certainty": document.quality,
                    "rendered_url": final.canonical_url,
                    "browser_response_bytes": response_bytes,
                    "dom_bytes": len(encoded),
                    "dom_nodes": node_count,
                    "browser_context_isolated": True,
                },
            )
        finally:
            if context is not None:
                await context.close()
            await browser.close()
            if playwright_owner is not None:
                await playwright_owner.stop()

    async def _launch_browser(self, guarded: GuardedUrl) -> tuple[Any, Any | None]:
        if self._browser_launcher is not None:
            return await self._browser_launcher(), None
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise PlaywrightExtractionError(
                "browser fallback is unavailable", access_status="FAILED"
            ) from exc
        owner = await async_playwright().start()
        try:
            browser = await owner.chromium.launch(
                headless=True,
                args=[
                    "--disable-background-networking",
                    "--disable-breakpad",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-features=DnsOverHttps,UseDnsHttpsSvcbAlpn",
                    "--disable-sync",
                    f"--host-resolver-rules=MAP {guarded.hostname} {guarded.addresses[0]}",
                    "--metrics-recording-only",
                    "--no-first-run",
                ],
            )
        except Exception as exc:
            await owner.stop()
            raise PlaywrightExtractionError(
                "browser fallback is unavailable", access_status="FAILED"
            ) from exc
        return browser, owner

    @property
    def parser_version(self) -> str:
        try:
            return version("playwright")
        except PackageNotFoundError:
            return "unknown"


__all__ = [
    "PlaywrightExtractionError",
    "PlaywrightExtractor",
    "PlaywrightLimits",
]
