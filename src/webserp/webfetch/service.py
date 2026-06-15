"""Network-backed webfetch service."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from curl_cffi.requests import AsyncSession

from webserp.challenge import raise_for_challenge
from webserp.client import DEFAULT_MAX_BODY_BYTES, DEFAULT_MAX_REDIRECTS, REDIRECT_STATUSES, FetchResponse, fetch_response
from webserp.errors import BodyTooLargeError, ChallengePageError, FetchRequestError, HttpStatusError
from webserp.security import DNSPolicy, STRICT_DNS_POLICY, validate_public_http_url

from .extractor import extract
from .types import WebFetchResult

PLAIN_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}


async def webfetch(
    url: str,
    *,
    timeout: int = 10,
    proxy: str | None = None,
    session: AsyncSession | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    validate_url: bool = True,
    dns_policy: DNSPolicy = STRICT_DNS_POLICY,
    retries: int = 0,
    allow_redirects: bool = True,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    impersonate: str | None = None,
) -> WebFetchResult:
    """Fetch one URL safely and extract Markdown-oriented page content."""
    response = await fetch_page_response(
        url,
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        proxy=proxy,
        session=session,
        impersonate=impersonate,
        max_body_bytes=max_body_bytes,
        validate_url=validate_url,
        dns_policy=dns_policy,
        retries=retries,
        allow_redirects=allow_redirects,
        max_redirects=max_redirects,
    )
    return extract(response.text, url, final_url=response.url, status=response.status)


async def fetch_page_response(
    url: str,
    *,
    timeout: int = 10,
    proxy: str | None = None,
    session: AsyncSession | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    validate_url: bool = True,
    dns_policy: DNSPolicy = STRICT_DNS_POLICY,
    retries: int = 0,
    allow_redirects: bool = True,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    impersonate: str | None = None,
) -> FetchResponse:
    try:
        return await fetch_response(
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            proxy=proxy,
            session=session,
            profile_key="webfetch",
            impersonate=impersonate,
            max_body_bytes=max_body_bytes,
            validate_url=validate_url,
            dns_policy=dns_policy,
            retries=retries,
            allow_redirects=allow_redirects,
            max_redirects=max_redirects,
        )
    except ChallengePageError:
        if proxy:
            raise
        return await _plain_fetch_response(
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            max_body_bytes=max_body_bytes,
            validate_url=validate_url,
            dns_policy=dns_policy,
            allow_redirects=allow_redirects,
            max_redirects=max_redirects,
        )


def result_to_dict(result: WebFetchResult) -> dict[str, Any]:
    return result.as_dict()


async def _plain_fetch_response(
    url: str,
    *,
    headers: dict[str, str] | None,
    cookies: dict[str, str] | None,
    timeout: int,
    max_body_bytes: int,
    validate_url: bool,
    dns_policy: DNSPolicy,
    allow_redirects: bool,
    max_redirects: int,
) -> FetchResponse:
    current_url = await validate_public_http_url(url, dns_policy=dns_policy) if validate_url else url
    redirects = 0

    while True:
        text, status, final_url, response_headers = await asyncio.to_thread(
            _plain_request_once,
            current_url,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            max_body_bytes=max_body_bytes,
        )

        location = _header_get(response_headers, "location")
        if status in REDIRECT_STATUSES and location and allow_redirects:
            if redirects >= max_redirects:
                raise FetchRequestError(f"too many redirects after {max_redirects} hops")
            next_url = urljoin(final_url or current_url, location)
            current_url = await validate_public_http_url(next_url, dns_policy=dns_policy) if validate_url else next_url
            redirects += 1
            continue

        raise_for_challenge(text, "plain_fetch", url=final_url, status=status, headers=response_headers)
        if status >= 400:
            raise HttpStatusError(status)
        return FetchResponse(text=text, status=status, url=final_url, headers=response_headers)


def _plain_request_once(
    url: str,
    *,
    headers: dict[str, str] | None,
    cookies: dict[str, str] | None,
    timeout: int,
    max_body_bytes: int,
) -> tuple[str, int, str, object]:
    request_headers = dict(PLAIN_FETCH_HEADERS)
    request_headers.update(headers or {})
    if cookies and "Cookie" not in request_headers:
        request_headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())

    opener = build_opener(_NoRedirectHandler)
    request = Request(url, headers=request_headers, method="GET")
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        response = exc
    except URLError as exc:
        raise FetchRequestError(str(exc)) from exc

    with response:
        body = response.read(max_body_bytes + 1)
        if len(body) > max_body_bytes:
            raise BodyTooLargeError(f"response exceeds {max_body_bytes} bytes")
        status = int(getattr(response, "status", response.getcode()) or 0)
        final_url = str(response.geturl() or url)
        headers_obj = response.headers
        return _decode_plain_body(body, headers_obj), status, final_url, headers_obj


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _decode_plain_body(body: bytes, headers: object) -> str:
    content_type = _header_get(headers, "content-type") or ""
    charset = "utf-8"
    for part in content_type.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            charset = value.strip()
            break
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _header_get(headers: object | None, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not getter:
        return None
    return getter(name) or getter(name.lower()) or getter(name.upper())
