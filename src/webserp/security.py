"""Best-effort URL safety checks for server-side/local-agent fetching."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from .errors import BlockedUrlError, InvalidUrlError


DNS_CACHE_TTL_SECONDS = 300
LOCAL_AGENT_DNS_POLICY = "local-agent"
STRICT_DNS_POLICY = "strict"
DNSPolicy = Literal["strict", "local-agent"]
FAKE_IP_V4_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_DNS_CACHE: dict[tuple[str, int], tuple[float, list[ipaddress.IPv4Address | ipaddress.IPv6Address]]] = {}


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    host: str
    port: int


def validate_http_url(raw: str) -> ValidatedUrl:
    """Require a non-empty HTTP(S) URL with a hostname."""
    trimmed = (raw or "").strip()
    if not trimmed:
        raise InvalidUrlError("URL must not be empty")

    parsed = urlsplit(trimmed)
    if parsed.scheme not in ("http", "https"):
        scheme = parsed.scheme or "<missing>"
        raise InvalidUrlError(f"scheme {scheme!r} is not allowed; use http:// or https://")

    if not parsed.hostname:
        raise InvalidUrlError("URL must include a host")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise InvalidUrlError(f"invalid port: {exc}") from exc

    if not (1 <= port <= 65535):
        raise InvalidUrlError("URL port must be between 1 and 65535")

    # Recompose to normalize leading/trailing whitespace without changing path/query.
    url = urlunsplit(parsed)
    return ValidatedUrl(url=url, host=parsed.hostname, port=port)


async def validate_public_http_url(raw: str, *, dns_policy: DNSPolicy = STRICT_DNS_POLICY) -> str:
    """Parse, resolve, and reject private/internal destinations.

    This is a best-effort guard for local-agent fetches. It validates before
    handing the URL to the HTTP client; the transport may still resolve again.

    ``local-agent`` keeps strict checks for URL syntax, localhost, IP literals,
    and redirects to real private/internal addresses, but allows hostname DNS
    answers in 198.18.0.0/15. That range is commonly used by local proxy
    fake-ip DNS and is not directly routable as a target IP literal.
    """
    _validate_dns_policy(dns_policy)
    validated = validate_http_url(raw)
    host = validated.host

    ip = _parse_ip_literal(host)
    if ip is not None:
        _reject_blocked_ip(ip)
        return validated.url

    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise BlockedUrlError("URL host is localhost")

    addrs = await _resolve_host(host, validated.port)
    if not addrs:
        raise InvalidUrlError("host did not resolve to any addresses")

    for addr in addrs:
        if dns_policy == LOCAL_AGENT_DNS_POLICY and is_fake_ip(addr):
            continue
        _reject_blocked_ip(addr)

    return validated.url


def is_fake_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return isinstance(ip, ipaddress.IPv4Address) and ip in FAKE_IP_V4_NETWORK


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return true for IP ranges unsafe for server-side/local-agent fetching."""
    if ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True

    if ip.is_private or ip.is_reserved:
        return True

    if isinstance(ip, ipaddress.IPv4Address):
        return _is_blocked_ipv4(ip)

    return _is_blocked_ipv6(ip)


def clear_dns_cache() -> None:
    _DNS_CACHE.clear()


def _validate_dns_policy(dns_policy: str) -> None:
    if dns_policy not in {STRICT_DNS_POLICY, LOCAL_AGENT_DNS_POLICY}:
        raise InvalidUrlError(f"unknown DNS policy: {dns_policy}")


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _reject_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if is_blocked_ip(ip):
        raise BlockedUrlError("URL resolves to a private, reserved, or internal address")


def _is_blocked_ipv4(ip: ipaddress.IPv4Address) -> bool:
    o = ip.packed
    first, second, third = o[0], o[1], o[2]

    return (
        first == 0
        or first >= 224
        or (first == 100 and 64 <= second <= 127)
        or (first == 169 and second == 254)
        or (first == 192 and second == 0 and third == 0)
        or (first == 192 and second == 0 and third == 2)
        or (first == 198 and 18 <= second <= 19)
        or (first == 198 and second == 51 and third == 100)
        or (first == 203 and second == 0 and third == 113)
    )


def _is_blocked_ipv6(ip: ipaddress.IPv6Address) -> bool:
    if ip.ipv4_mapped and is_blocked_ip(ip.ipv4_mapped):
        return True

    if ip.sixtofour and is_blocked_ip(ip.sixtofour):
        return True

    if ip.teredo:
        server, client = ip.teredo
        return is_blocked_ip(server) or is_blocked_ip(client)

    return False


async def _resolve_host(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    key = (host.lower(), port)
    now = time.monotonic()
    cached = _DNS_CACHE.get(key)
    if cached and cached[0] > now:
        return cached[1]

    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise InvalidUrlError(f"failed to resolve host: {exc}") from exc

    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        raw_ip = sockaddr[0]
        if raw_ip in seen:
            continue
        seen.add(raw_ip)
        try:
            addrs.append(ipaddress.ip_address(raw_ip))
        except ValueError:
            raise InvalidUrlError(f"resolver returned invalid address: {raw_ip}")

    _DNS_CACHE[key] = (now + DNS_CACHE_TTL_SECONDS, addrs)
    return addrs
