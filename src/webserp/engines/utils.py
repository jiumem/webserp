"""Shared helpers for HTML search engines."""

from html import unescape
import re
from urllib.parse import urljoin

from ..challenge import is_challenge_page, raise_for_challenge


def clean_text(text: str | None) -> str:
    """Normalize text extracted from HTML."""
    if not text:
        return ""
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def absolute_url(href: str | None, base_url: str) -> str:
    """Return an absolute URL, preserving empty values."""
    if not href:
        return ""
    return urljoin(base_url, href.strip())


def is_http_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


__all__ = [
    "absolute_url",
    "clean_text",
    "is_challenge_page",
    "is_http_url",
    "raise_for_challenge",
]
