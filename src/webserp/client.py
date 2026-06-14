"""HTTP client with browser impersonation via curl_cffi."""

from dataclasses import dataclass, field
import random
from typing import Any
from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession

from .challenge import raise_for_challenge
from .errors import (
    BodyTooLargeError,
    ChallengePageError,
    FetchRequestError,
    FetchTimeoutError,
    HttpStatusError,
    WebSerpError,
)
from .security import validate_public_http_url

CHROME_VERSIONS = [
    "chrome110", "chrome116", "chrome119", "chrome120",
    "chrome123", "chrome124", "chrome131", "chrome133a",
]

DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
RETRYABLE_STATUSES = {500, 502, 503, 504}


def random_impersonate() -> str:
    return random.choice(CHROME_VERSIONS)


@dataclass
class FetchContext:
    """Per-search request context.

    A context keeps a stable impersonation profile for each logical key
    (normally an engine name) within one search operation. Different searches
    still get fresh choices.
    """

    session: AsyncSession
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    validate_urls: bool = True
    _impersonates: dict[str, str] = field(default_factory=dict)

    def impersonate_for(self, key: str) -> str:
        if key not in self._impersonates:
            self._impersonates[key] = random_impersonate()
        return self._impersonates[key]


@dataclass(frozen=True)
class FetchResponse:
    text: str
    status: int
    url: str
    headers: Any


async def fetch(
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    cookies: dict | None = None,
    timeout: int = 10,
    proxy: str | None = None,
    session: AsyncSession | None = None,
    context: FetchContext | None = None,
    profile_key: str | None = None,
    impersonate: str | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    validate_url: bool = True,
    retries: int = 1,
    allow_redirects: bool = True,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> str:
    """Fetch a URL with browser impersonation. Returns response text."""
    response = await fetch_response(
        url,
        method=method,
        params=params,
        data=data,
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        proxy=proxy,
        session=session,
        context=context,
        profile_key=profile_key,
        impersonate=impersonate,
        max_body_bytes=max_body_bytes,
        validate_url=validate_url,
        retries=retries,
        allow_redirects=allow_redirects,
        max_redirects=max_redirects,
    )
    return response.text


async def fetch_response(
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    cookies: dict | None = None,
    timeout: int = 10,
    proxy: str | None = None,
    session: AsyncSession | None = None,
    context: FetchContext | None = None,
    profile_key: str | None = None,
    impersonate: str | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    validate_url: bool = True,
    retries: int = 1,
    allow_redirects: bool = True,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> FetchResponse:
    """Fetch a URL with browser impersonation. Returns response metadata and text."""
    if context:
        return await _fetch_with_session_response(
            context.session,
            url,
            method=method,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            proxy=proxy,
            impersonate=impersonate or context.impersonate_for(profile_key or url),
            max_body_bytes=context.max_body_bytes,
            validate_url=context.validate_urls,
            retries=retries,
            allow_redirects=allow_redirects,
            max_redirects=max_redirects,
        )

    if session:
        return await _fetch_with_session_response(
            session,
            url,
            method=method,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            proxy=proxy,
            impersonate=impersonate or random_impersonate(),
            max_body_bytes=max_body_bytes,
            validate_url=validate_url,
            retries=retries,
            allow_redirects=allow_redirects,
            max_redirects=max_redirects,
        )

    async with AsyncSession() as s:
        return await _fetch_with_session_response(
            s,
            url,
            method=method,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            proxy=proxy,
            impersonate=impersonate or random_impersonate(),
            max_body_bytes=max_body_bytes,
            validate_url=validate_url,
            retries=retries,
            allow_redirects=allow_redirects,
            max_redirects=max_redirects,
        )


async def _fetch_with_session(
    session: AsyncSession,
    url: str,
    *,
    method: str,
    params: dict | None,
    data: dict | None,
    headers: dict | None,
    cookies: dict | None,
    timeout: int,
    proxy: str | None,
    impersonate: str,
    max_body_bytes: int,
    validate_url: bool,
    retries: int,
    allow_redirects: bool,
    max_redirects: int,
) -> str:
    response = await _fetch_with_session_response(
        session,
        url,
        method=method,
        params=params,
        data=data,
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        proxy=proxy,
        impersonate=impersonate,
        max_body_bytes=max_body_bytes,
        validate_url=validate_url,
        retries=retries,
        allow_redirects=allow_redirects,
        max_redirects=max_redirects,
    )
    return response.text


async def _fetch_with_session_response(
    session: AsyncSession,
    url: str,
    *,
    method: str,
    params: dict | None,
    data: dict | None,
    headers: dict | None,
    cookies: dict | None,
    timeout: int,
    proxy: str | None,
    impersonate: str,
    max_body_bytes: int,
    validate_url: bool,
    retries: int,
    allow_redirects: bool,
    max_redirects: int,
) -> FetchResponse:
    if validate_url:
        url = await validate_public_http_url(url)

    last_error: Exception | None = None
    attempts = max(0, retries) + 1
    for attempt in range(attempts):
        try:
            text, status, final_url, response_headers = await _request_with_redirects(
                session,
                url,
                method=method,
                params=params,
                data=data,
                headers=headers,
                cookies=cookies,
                timeout=timeout,
                impersonate=impersonate,
                proxy=proxy,
                max_body_bytes=max_body_bytes,
                validate_url=validate_url,
                allow_redirects=allow_redirects,
                max_redirects=max_redirects,
            )

            try:
                raise_for_challenge(
                    text,
                    "fetch",
                    url=final_url,
                    status=status,
                    headers=response_headers,
                )
            except ChallengePageError:
                raise

            if status in RETRYABLE_STATUSES and attempt < attempts - 1:
                last_error = HttpStatusError(status)
                continue
            if status >= 400:
                raise HttpStatusError(status)
            return FetchResponse(text=text, status=status, url=final_url, headers=response_headers)
        except WebSerpError:
            raise
        except Exception as exc:
            if _looks_like_timeout(exc):
                raise FetchTimeoutError(str(exc)) from exc
            last_error = exc
            if attempt >= attempts - 1:
                raise FetchRequestError(str(exc)) from exc

    if isinstance(last_error, WebSerpError):
        raise last_error
    raise WebSerpError(str(last_error or "fetch failed"))


async def _request_with_redirects(
    session: AsyncSession,
    url: str,
    *,
    method: str,
    params: dict | None,
    data: dict | None,
    headers: dict | None,
    cookies: dict | None,
    timeout: int,
    impersonate: str,
    proxy: str | None,
    max_body_bytes: int,
    validate_url: bool,
    allow_redirects: bool,
    max_redirects: int,
) -> tuple[str, int, str, Any]:
    if not (validate_url and allow_redirects):
        return await _request_once(
            session,
            url,
            method=method,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            impersonate=impersonate,
            proxy=proxy,
            max_body_bytes=max_body_bytes,
            allow_redirects=allow_redirects,
            max_redirects=max_redirects,
        )

    current_url = url
    current_method = method
    current_params = params
    current_data = data
    redirects = 0

    while True:
        text, status, final_url, response_headers = await _request_once(
            session,
            current_url,
            method=current_method,
            params=current_params,
            data=current_data,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            impersonate=impersonate,
            proxy=proxy,
            max_body_bytes=max_body_bytes,
            allow_redirects=False,
            max_redirects=0,
        )

        location = _header_get(response_headers, "location")
        if status not in REDIRECT_STATUSES or not location:
            return text, status, final_url, response_headers

        if redirects >= max_redirects:
            raise FetchRequestError(f"too many redirects after {max_redirects} hops")

        next_url = urljoin(final_url or current_url, location)
        current_url = await validate_public_http_url(next_url)
        redirects += 1

        # Match browser/client redirect semantics for common POST-to-GET redirects.
        if status in {301, 302, 303} and current_method.upper() not in {"GET", "HEAD"}:
            current_method = "GET"
            current_data = None

        current_params = None


async def _request_once(
    session: AsyncSession,
    url: str,
    *,
    method: str,
    params: dict | None,
    data: dict | None,
    headers: dict | None,
    cookies: dict | None,
    timeout: int,
    impersonate: str,
    proxy: str | None,
    max_body_bytes: int,
    allow_redirects: bool,
    max_redirects: int,
) -> tuple[str, int, str, Any]:
    resp = await session.request(
        method,
        url,
        params=params,
        data=data,
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        impersonate=impersonate,
        proxy=proxy,
        stream=True,
        allow_redirects=allow_redirects,
        max_redirects=max_redirects,
    )
    try:
        _reject_declared_large_body(resp, max_body_bytes)
        body = await _response_bytes(resp, max_body_bytes)
        if len(body) > max_body_bytes:
            raise BodyTooLargeError(f"response exceeds {max_body_bytes} bytes")
    except Exception:
        await _close_response(resp)
        raise

    status = int(getattr(resp, "status_code", getattr(resp, "status", 0)) or 0)
    final_url = str(getattr(resp, "url", url))
    return _decode_body(body, resp), status, final_url, getattr(resp, "headers", {})


def _reject_declared_large_body(resp: Any, max_body_bytes: int) -> None:
    raw = _header_get(getattr(resp, "headers", None), "content-length")
    if not raw:
        return
    try:
        length = int(raw)
    except (TypeError, ValueError):
        return
    if length > max_body_bytes:
        raise BodyTooLargeError(f"response body {length} bytes exceeds {max_body_bytes} bytes")


async def _response_bytes(resp: Any, max_body_bytes: int) -> bytes:
    if _is_stream_response(resp):
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in resp.aiter_content():
                chunk = _coerce_bytes(chunk)
                size += len(chunk)
                if size > max_body_bytes:
                    raise BodyTooLargeError(f"response exceeds {max_body_bytes} bytes")
                chunks.append(chunk)
        finally:
            await _close_response(resp)
        return b"".join(chunks)

    content = getattr(resp, "content", None)
    if content is not None:
        return _coerce_bytes(content)

    if hasattr(resp, "acontent"):
        content = resp.acontent
        if callable(content):
            return _coerce_bytes(await content())
        return _coerce_bytes(content)
    return b""


def _is_stream_response(resp: Any) -> bool:
    return (
        callable(getattr(resp, "aiter_content", None))
        and getattr(resp, "queue", None) is not None
        and getattr(resp, "curl", None) is not None
    )


def _coerce_bytes(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content)


async def _close_response(resp: Any) -> None:
    close = getattr(resp, "aclose", None)
    if callable(close):
        await close()
        return

    close = getattr(resp, "close", None)
    if callable(close):
        close()


def _decode_body(body: bytes, resp: Any) -> str:
    encoding = (
        getattr(resp, "encoding", None)
        or getattr(resp, "charset", None)
        or getattr(resp, "charset_encoding", None)
        or "utf-8"
    )
    if callable(encoding):
        encoding = encoding()
    try:
        return body.decode(encoding or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _header_get(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not getter:
        return None
    return getter(name) or getter(name.lower()) or getter(name.upper())


def _looks_like_timeout(exc: Exception) -> bool:
    text = str(exc).lower()
    return "timeout" in text or "timed out" in text or "operation timed out" in text
