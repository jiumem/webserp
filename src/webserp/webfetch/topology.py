"""Link topology classification for webfetch."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from lxml import etree, html

from .types import Link

NOISE_TEXT_RE = re.compile(
    r"^(read more|more|click here|login|sign up|register|privacy policy|terms|share|comment|reply|prev|next|"
    r"上一页|下一页|登录|注册|分享|分享到.*|广告.*)$",
    re.I,
)
AD_HOST_PARTS = {"doubleclick", "googleadservices", "adsystem", "adservice"}
USELESS_PREFIXES = ("javascript:", "mailto:", "tel:", "sms:", "#")
SAFE_URL_SCHEMES = {"http", "https"}


class LinkTopologyAnalyzer:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.base_host = urlparse(base_url).netloc.lower()
        self._mass_cache: dict[str, float] = {}

    def analyze(self, root: html.HtmlElement, content_links: list[Link]) -> list[Link]:
        content_hrefs = {link.href for link in content_links}
        result: list[Link] = []
        seen: set[str] = set()

        for anchor in root.xpath("//a[@href]"):
            href = self._normalize(anchor.get("href", ""))
            if not href or href in seen:
                continue
            text = " ".join(anchor.text_content().split())
            if self._is_noise_link(href, text):
                link_type = "noise"
            elif href in content_hrefs:
                link_type = "content"
            elif self._is_directory_link(anchor, text):
                link_type = "directory"
            elif self._is_navigation_link(anchor):
                link_type = "navigation"
            else:
                link_type = "navigation"
            result.append(
                Link(
                    text=text,
                    href=href,
                    type=link_type,
                    is_external=urlparse(href).netloc.lower() != self.base_host,
                )
            )
            seen.add(href)
        return result

    def link_mass(self, node: etree._Element) -> float:
        key = node.getroottree().getpath(node)
        if key in self._mass_cache:
            return self._mass_cache[key]

        if len(node) > 800:
            self._mass_cache[key] = 0.0
            return 0.0

        total = _compact(node.text_content())
        total_len = len(total) or 1
        if total_len > 200_000:
            self._mass_cache[key] = 0.0
            return 0.0

        link_len = 0
        for anchor in node.xpath(".//a"):
            link_len += len(_compact(anchor.text_content()))
        score = (link_len * link_len) / total_len if link_len else 0.0
        self._mass_cache[key] = score
        return score

    def _normalize(self, href: str) -> str:
        href = (href or "").strip()
        if not href:
            return ""
        if href.lower().startswith(USELESS_PREFIXES):
            return ""
        resolved = urljoin(self.base_url, href)
        if urlparse(resolved).scheme.lower() not in SAFE_URL_SCHEMES:
            return ""
        return resolved

    def _is_noise_link(self, href: str, text: str) -> bool:
        if not text or len(text) < 2:
            return True
        if NOISE_TEXT_RE.match(text):
            return True
        host = urlparse(href).netloc.lower()
        return any(part in host for part in AD_HOST_PARTS)

    def _is_navigation_link(self, node: etree._Element) -> bool:
        parent = node
        for _ in range(4):
            if parent is None:
                return False
            tag = _tag(parent)
            role = (parent.get("role") or "").lower()
            cls = (parent.get("class") or "").lower()
            if tag in {"nav", "footer", "header", "aside"}:
                return True
            if role in {"navigation", "banner", "contentinfo"}:
                return True
            if any(token in cls for token in ("nav", "menu", "footer", "header", "breadcrumb")):
                return True
            parent = parent.getparent()
        return False

    def _is_directory_link(self, node: etree._Element, text: str) -> bool:
        if len(text) < 4 or len(text) > 120:
            return False
        parent = node.getparent()
        for _ in range(4):
            if parent is None:
                return False
            tag = _tag(parent)
            if tag in {"ul", "ol", "dl", "section", "aside"} or (tag == "div" and len(parent) > 2):
                return self.link_mass(parent) > 20.0
            parent = parent.getparent()
        return False


def _tag(node: etree._Element) -> str:
    return str(node.tag).lower() if isinstance(node.tag, str) else ""


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")
