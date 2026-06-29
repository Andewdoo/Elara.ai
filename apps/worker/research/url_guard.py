"""Deterministic URL canonicalization and SSRF defenses."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    pass


_METADATA_HOSTS = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.azure.internal",
        "instance-data",
        "169.254.169.254",
        "100.100.100.200",
    }
)
_TRACKING_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid"})


@dataclass(frozen=True, slots=True)
class GuardedUrl:
    canonical_url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def canonicalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise UnsafeUrlError("URL syntax is invalid") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError("only HTTP and HTTPS URLs are supported")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs containing credentials are not allowed")
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if not hostname:
        raise UnsafeUrlError("URL hostname is required")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeUrlError("URL hostname is invalid") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("URL port is invalid") from exc
    default_port = 80 if scheme == "http" else 443
    host_display = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host_display if port in {None, default_port} else f"{host_display}:{port}"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_KEYS
        ),
        doseq=True,
    )
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return bool(address.is_global and not address.is_multicast and not address.is_unspecified)


class UrlGuard:
    def __init__(self, *, allowed_ports: frozenset[int] = frozenset({80, 443}), resolver=None) -> None:
        self.allowed_ports = allowed_ports
        self._resolver = resolver or self._resolve

    async def validate(self, value: str) -> GuardedUrl:
        canonical = canonicalize_url(value)
        parsed = urlsplit(canonical)
        hostname = parsed.hostname or ""
        if hostname in _METADATA_HOSTS or hostname == "localhost" or hostname.endswith(".localhost"):
            raise UnsafeUrlError("local and metadata hostnames are not allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in self.allowed_ports:
            raise UnsafeUrlError("URL port is not allowed")
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            addresses = tuple(dict.fromkeys(await self._resolver(hostname, port)))
        else:
            addresses = (str(literal),)
        if not addresses or any(not is_public_address(address) for address in addresses):
            raise UnsafeUrlError("URL resolves to a non-public address")
        return GuardedUrl(canonical, hostname, port, addresses)

    @staticmethod
    async def _resolve(hostname: str, port: int) -> list[str]:
        loop = asyncio.get_running_loop()
        try:
            records = await loop.getaddrinfo(
                hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise UnsafeUrlError("URL hostname could not be resolved") from exc
        return [record[4][0] for record in records]


__all__ = ["GuardedUrl", "UnsafeUrlError", "UrlGuard", "canonicalize_url", "is_public_address"]
