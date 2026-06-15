"""Structured-data and data-island helpers for webfetch."""

from __future__ import annotations

import json
import re
from typing import Any

from lxml import html


JSON_LD_XPATH = "//script[contains(translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'application/ld+json')]/text()"
NEXT_DATA_XPATH = "//script[@id='__NEXT_DATA__']/text()"
APP_JSON_XPATH = "//script[contains(translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'application/json')]/text()"

CONTENT_KEYS = {
    "articlebody",
    "body",
    "content",
    "description",
    "headline",
    "name",
    "summary",
    "text",
    "title",
}
SKIP_KEYS = {
    "buildid",
    "class",
    "css",
    "href",
    "id",
    "image",
    "images",
    "key",
    "logo",
    "src",
    "style",
    "url",
}


def extract_structured_data(raw_html: str, root: html.HtmlElement) -> list[Any]:
    data: list[Any] = []
    for raw in root.xpath(JSON_LD_XPATH):
        parsed = _loads_loose(raw)
        if parsed is None:
            continue
        if isinstance(parsed, list):
            data.extend(parsed)
        else:
            data.append(parsed)

    for raw in root.xpath(NEXT_DATA_XPATH):
        parsed = _loads_loose(raw)
        if parsed is None:
            continue
        page_props = _dig(parsed, ["props", "pageProps"])
        data.append(page_props if page_props else parsed)

    svelte_data = _extract_svelte_data(raw_html)
    if svelte_data:
        data.extend(svelte_data)

    return data


def extract_data_island_markdown(root: html.HtmlElement, existing_text_chars: int) -> str:
    """Return markdown recovered from JSON data islands when DOM text is sparse."""
    if existing_text_chars >= 1200:
        return ""

    chunks: list[str] = []
    seen: set[str] = set()
    for raw in root.xpath(APP_JSON_XPATH + " | " + NEXT_DATA_XPATH):
        parsed = _loads_loose(raw)
        if parsed is None:
            continue
        for text in _walk_text(parsed):
            text = " ".join(text.split())
            if len(text) < 40 or text in seen:
                continue
            seen.add(text)
            chunks.append(text)
            if len(chunks) >= 80:
                break
        if len(chunks) >= 80:
            break

    if not chunks:
        return ""

    lines = ["## Page Data"]
    for chunk in chunks:
        if _looks_like_heading(chunk):
            lines.append(f"\n### {chunk}")
        else:
            lines.append(f"\n{chunk}")
    return "\n".join(lines).strip()


def _loads_loose(raw: str) -> Any | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(_sanitize_json_controls(text))
        except json.JSONDecodeError:
            return None


def _sanitize_json_controls(text: str) -> str:
    out = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
            continue
        out.append(ch)
    return "".join(out)


def _dig(value: Any, keys: list[str]) -> Any | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _walk_text(value: Any, key: str = "", depth: int = 0) -> list[str]:
    if depth > 12:
        return []
    if isinstance(value, str):
        if key.lower() in SKIP_KEYS:
            return []
        if _is_content_text(value) or key.lower() in CONTENT_KEYS:
            return [value]
        return []
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value[:200]:
            chunks.extend(_walk_text(item, key=key, depth=depth + 1))
        return chunks
    if isinstance(value, dict):
        chunks = []
        for child_key, child_value in value.items():
            lower = child_key.lower()
            if lower in SKIP_KEYS:
                continue
            chunks.extend(_walk_text(child_value, key=lower, depth=depth + 1))
        return chunks
    return []


def _is_content_text(text: str) -> bool:
    stripped = " ".join(text.split())
    if len(stripped) < 40:
        return False
    if len(stripped) > 2000:
        return False
    if re.search(r"[{}<>;]{3,}", stripped):
        return False
    letters = sum(ch.isalpha() or "\u4e00" <= ch <= "\u9fff" for ch in stripped)
    return letters >= max(20, len(stripped) // 3)


def _looks_like_heading(text: str) -> bool:
    return len(text) <= 90 and not text.endswith((".", "。", "!", "！", "?", "？"))


def _extract_svelte_data(raw_html: str) -> list[Any]:
    marker = "data: ["
    start = raw_html.find(marker)
    if start < 0:
        return []
    bracket_start = start + len("data: ")
    balanced = _extract_balanced(raw_html[bracket_start:], "[", "]")
    if not balanced:
        return []
    parsed = _loads_loose(_quote_js_keys(balanced))
    if not isinstance(parsed, list):
        return []
    result = []
    for item in parsed:
        if isinstance(item, dict) and isinstance(item.get("data"), (dict, list)):
            result.append(item["data"])
        elif isinstance(item, (dict, list)):
            result.append(item)
    return result


def _extract_balanced(text: str, open_char: str, close_char: str) -> str:
    if not text.startswith(open_char):
        return ""
    depth = 0
    in_string = False
    escape = False
    for idx, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[: idx + 1]
    return ""


def _quote_js_keys(text: str) -> str:
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)
