"""Shared helpers for HTML search engines."""

from html import unescape
import re
from urllib.parse import urljoin


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


def is_challenge_page(text: str) -> bool:
    """Detect anti-bot or verification pages returned as successful HTTP responses."""
    lower = text.lower()
    if "antispider" in lower:
        return True
    if "unfortunately, bots use duckduckgo too" in lower:
        return True
    if "please complete the following challenge" in lower:
        return True
    if "captcha" in lower and any(marker in lower for marker in ("human", "robot", "verify", "challenge")):
        return True

    strong_markers = (
        "请输入验证码",
        "安全验证",
        "百度安全验证",
        "访问过于频繁",
        "异常访问",
        "异常流量",
        "我们的系统检测到您网络中存在异常访问请求",
        "检测到您网络中存在异常访问请求",
    )
    return any(marker in text for marker in strong_markers)


def raise_for_challenge(text: str, engine_name: str) -> None:
    if is_challenge_page(text):
        raise ValueError(f"{engine_name}: anti-bot challenge page returned")
