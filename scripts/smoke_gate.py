from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class SmokeGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeResult:
    name: str
    url: str
    status: int


def _origin(value: str | None, *, name: str, require_https: bool) -> str:
    if value is None or not value.strip():
        raise SmokeGateError(f"{name} is required for the deployment smoke gate")
    normalized = value.strip().removesuffix("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SmokeGateError(f"{name} must be an absolute HTTP(S) origin")
    if require_https and parsed.scheme != "https":
        raise SmokeGateError(f"{name} must use HTTPS for staging and production")
    if parsed.username or parsed.password:
        raise SmokeGateError(f"{name} must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SmokeGateError(f"{name} must be an exact origin without path, query, or fragment")
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch(url: str, *, timeout: float) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": "elara-smoke-gate/1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(64_000)
    except HTTPError as exc:
        raise SmokeGateError(f"{url} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise SmokeGateError(f"{url} is unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise SmokeGateError(f"{url} timed out") from exc


def smoke_api(
    api_base_url: str,
    *,
    timeout: float,
    expected_revision: str | None = None,
) -> SmokeResult:
    url = f"{api_base_url}/health"
    status, body = _fetch(url, timeout=timeout)
    if status != 200:
        raise SmokeGateError(f"{url} returned HTTP {status}")
    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SmokeGateError(f"{url} did not return JSON health") from exc
    if payload.get("status") != "ok":
        raise SmokeGateError(f"{url} did not report status=ok")
    if expected_revision and payload.get("revision") != expected_revision:
        raise SmokeGateError(
            f"{url} reported revision {payload.get('revision')!r}, expected {expected_revision!r}"
        )
    return SmokeResult("api", url, status)


def smoke_web(web_app_url: str, *, timeout: float) -> SmokeResult:
    status, _body = _fetch(web_app_url, timeout=timeout)
    if status < 200 or status >= 400:
        raise SmokeGateError(f"{web_app_url} returned HTTP {status}")
    return SmokeResult("web", web_app_url, status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Credential-free Elara deployment smoke gate")
    parser.add_argument("--environment", choices=["staging", "production"], required=True)
    parser.add_argument("--api-base-url", default=os.getenv("API_BASE_URL"))
    parser.add_argument("--web-app-url", default=os.getenv("WEB_APP_URL"))
    parser.add_argument("--expected-revision", default=os.getenv("EXPECTED_REVISION"))
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--require-https", action="store_true")
    args = parser.parse_args(argv)

    try:
        api_base_url = _origin(
            args.api_base_url,
            name="API_BASE_URL",
            require_https=args.require_https,
        )
        web_app_url = _origin(
            args.web_app_url,
            name="WEB_APP_URL",
            require_https=args.require_https,
        )
        results = [
            smoke_api(
                api_base_url,
                timeout=args.timeout,
                expected_revision=args.expected_revision,
            ),
            smoke_web(web_app_url, timeout=args.timeout),
        ]
    except SmokeGateError as exc:
        print(f"smoke gate failed: {exc}", file=sys.stderr)
        return 1

    for result in results:
        print(f"{args.environment} {result.name} smoke ok: {result.status} {result.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
