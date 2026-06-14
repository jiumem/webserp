"""Metadata extraction for webfetch."""

from __future__ import annotations

from urllib.parse import urljoin

from lxml import html

from .types import Metadata


def extract_metadata(root: html.HtmlElement, base_url: str) -> Metadata:
    return Metadata(
        title=_first_content(
            root,
            [
                "//meta[@property='og:title']/@content",
                "//meta[@name='twitter:title']/@content",
                "//title/text()",
                "//h1/text()",
            ],
        ),
        description=_first_content(
            root,
            [
                "//meta[@name='description']/@content",
                "//meta[@property='og:description']/@content",
                "//meta[@name='twitter:description']/@content",
            ],
        ),
        author=_first_content(
            root,
            [
                "//meta[@name='author']/@content",
                "//meta[@property='article:author']/@content",
                "//*[@rel='author']/text()",
            ],
        ),
        published_date=_first_content(
            root,
            [
                "//meta[@property='article:published_time']/@content",
                "//meta[@name='date']/@content",
                "//time/@datetime",
            ],
        ),
        language=_language(root),
        site_name=_first_content(root, ["//meta[@property='og:site_name']/@content"]),
        image=_absolute(
            _first_content(
                root,
                [
                    "//meta[@property='og:image']/@content",
                    "//meta[@name='twitter:image']/@content",
                ],
            ),
            base_url,
        ),
        favicon=_absolute(
            _first_content(
                root,
                [
                    "//link[contains(translate(@rel, 'ICON', 'icon'), 'icon')]/@href",
                    "//link[contains(translate(@rel, 'SHORTCUT', 'shortcut'), 'shortcut')]/@href",
                ],
            ),
            base_url,
        ),
    )


def _first_content(root: html.HtmlElement, xpaths: list[str]) -> str:
    for xpath in xpaths:
        values = root.xpath(xpath)
        for value in values:
            text = _normalize(value)
            if text:
                return text
    return ""


def _normalize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if hasattr(value, "text_content"):
        return " ".join(value.text_content().split())
    return " ".join(str(value).split())


def _absolute(value: str, base_url: str) -> str:
    if not value:
        return ""
    return urljoin(base_url, value)


def _language(root: html.HtmlElement) -> str:
    lang = root.get("lang") or root.xpath("string(/html/@lang)")
    return " ".join(str(lang or "").split())
