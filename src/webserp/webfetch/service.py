"""Network-backed webfetch service."""

from __future__ import annotations

from typing import Any

from curl_cffi.requests import AsyncSession

from webserp.client import DEFAULT_MAX_BODY_BYTES, DEFAULT_MAX_REDIRECTS, fetch_response

from .extractor import extract
from .types import WebFetchResult


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
    retries: int = 0,
    allow_redirects: bool = True,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    impersonate: str | None = None,
) -> WebFetchResult:
    """Fetch one URL safely and extract Markdown-oriented page content."""
    response = await fetch_response(
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
        retries=retries,
        allow_redirects=allow_redirects,
        max_redirects=max_redirects,
    )
    return extract(response.text, url, final_url=response.url, status=response.status)


def result_to_dict(result: WebFetchResult) -> dict[str, Any]:
    return result.as_dict()
