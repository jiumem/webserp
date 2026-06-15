"""Anti-bot, consent-wall, and empty-shell detection."""

from __future__ import annotations

import re

from .errors import ChallengePageError


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def is_challenge_page(
    text: str,
    *,
    url: str | None = None,
    status: int | None = None,
    headers: object | None = None,
) -> bool:
    """Detect pages that are not usable search/content responses.

    Rules intentionally combine strong phrases, title/URL signals, page size,
    and status/header hints to avoid flagging normal articles that mention
    CAPTCHAs or bot protection in passing.
    """
    if not text:
        return False

    lower = text.lower()
    title = _extract_title(text).lower()
    url_lower = (url or "").lower()
    length = len(text)

    if _is_duckduckgo_challenge(lower):
        return True
    if _is_sogou_antispider(lower, url_lower):
        return True
    if _is_baidu_security_check(text):
        return True
    if _is_cloudflare_challenge(lower, title, headers):
        return True
    if _is_hcaptcha_blocking_page(lower, length):
        return True
    if _is_consent_wall(title, url_lower, text):
        return True
    if _is_raw_javascript_challenge(text, lower):
        return True
    if status == 202 and "challenge" in lower and length < 50_000:
        return True

    return is_js_only_shell(text)


def raise_for_challenge(
    text: str,
    engine_name: str,
    *,
    url: str | None = None,
    status: int | None = None,
    headers: object | None = None,
) -> None:
    if is_challenge_page(text, url=url, status=status, headers=headers):
        raise ChallengePageError(f"{engine_name}: anti-bot, consent, or empty-shell page returned")


def is_js_only_shell(text: str) -> bool:
    """Detect large SPA shells with very little visible text."""
    lower = text.lower()
    if "<script" not in lower:
        return False

    visible_text = _visible_text(text)
    word_count = len(visible_text.split())
    if word_count < 10 and _script_text_ratio(text) >= 0.6:
        return True

    if len(text) < 5_000:
        return False

    has_spa_marker = any(
        marker in lower
        for marker in (
            'id="root"',
            'id="app"',
            'id="__next"',
            "__next_data__",
            "window.__nuxt__",
            "ng-app",
            "react-app",
        )
    )
    if not has_spa_marker:
        return False

    return word_count < 50


def _extract_title(text: str) -> str:
    match = _TITLE_RE.search(text)
    if not match:
        return ""
    return " ".join(_TAG_RE.sub("", match.group(1)).split())


def _visible_text(text: str) -> str:
    stripped = _SCRIPT_STYLE_RE.sub(" ", text)
    stripped = _TAG_RE.sub(" ", stripped)
    return " ".join(stripped.split())


def _script_text_ratio(text: str) -> float:
    script_chars = sum(len(match.group(0)) for match in _SCRIPT_STYLE_RE.finditer(text))
    return script_chars / max(1, len(text))


def _is_raw_javascript_challenge(text: str, lower: str) -> bool:
    stripped = text.lstrip()
    if not stripped or stripped.startswith(("<", "{", "[")):
        return False
    prefix = stripped[:2_000].lower()
    if not re.search(r"\b(var|let|const|function)\b", prefix):
        return False
    markers = (
        "document.cookie",
        "window.location",
        "location.href",
        "arg1",
        "setcookie",
        "eval(",
    )
    return any(marker in lower for marker in markers)


def _is_duckduckgo_challenge(lower: str) -> bool:
    return (
        "unfortunately, bots use duckduckgo too" in lower
        or "please complete the following challenge" in lower
    )


def _is_sogou_antispider(lower: str, url_lower: str) -> bool:
    return "antispider" in lower or "/antispider/" in url_lower


def _is_baidu_security_check(text: str) -> bool:
    markers = (
        "百度安全验证",
        "请输入验证码",
        "访问过于频繁",
        "异常访问",
        "异常流量",
        "我们的系统检测到您网络中存在异常访问请求",
        "检测到您网络中存在异常访问请求",
    )
    return any(marker in text for marker in markers)


def _is_cloudflare_challenge(lower: str, title: str, headers: object | None) -> bool:
    title_markers = (
        "just a moment",
        "checking your browser",
        "attention required",
        "verify you are human",
        "security check",
    )
    if any(title.startswith(marker) for marker in title_markers):
        return True

    has_cf_header = _header_get(headers, "cf-ray") or _header_get(headers, "cf-mitigated")
    return bool(has_cf_header and ("just a moment" in lower or "checking your browser" in lower))


def _is_hcaptcha_blocking_page(lower: str, length: int) -> bool:
    return "hcaptcha.com" in lower and "h-captcha" in lower and length < 50_000


def _is_consent_wall(title: str, url_lower: str, text: str) -> bool:
    consent_url_markers = (
        "://consent.",
        "/consent?",
        "/consent/",
        "collectconsent",
        "consentcheck",
        "/cmp/",
        "guce.advertising.com",
    )
    if any(marker in url_lower for marker in consent_url_markers):
        return True

    consent_titles = (
        "before you continue",
        "your privacy choices",
        "we value your privacy",
        "we care about your privacy",
        "cookie consent",
        "consent required",
    )
    return len(_visible_text(text).split()) <= 80 and any(title.startswith(t) for t in consent_titles)


def _header_get(headers: object | None, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not getter:
        return None
    return getter(name) or getter(name.lower()) or getter(name.upper())
