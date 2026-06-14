"""Sogou web search engine."""

from lxml import html

from .base import Engine, RequestSpec, Result
from .utils import absolute_url, clean_text, is_http_url, raise_for_challenge


SOGOU_BASE_URL = "https://www.sogou.com"


def parse_sogou_web_results(text: str, engine_name: str) -> list[Result]:
    raise_for_challenge(text, engine_name)
    results = []
    seen_urls: set[str] = set()
    tree = html.fromstring(text)
    containers = tree.xpath('//div[contains(@class, "vrwrap")][.//a[@href]]')
    if not containers:
        containers = tree.xpath('//div[contains(@class, "results")][.//a[@href]]')

    for el in containers:
        link = (
            el.xpath('.//h3//a[@href]')
            or el.xpath('.//a[@name="dttl" and @href]')
            or el.xpath('.//a[contains(@class, "vr-title") and @href]')
            or el.xpath('.//a[@href]')
        )
        if not link:
            continue

        href = absolute_url(link[0].get("href", ""), SOGOU_BASE_URL)
        if not is_http_url(href):
            continue
        normalized_url = href.rstrip("/")
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        title = clean_text(link[0].text_content())
        if not title:
            continue

        content = _extract_sogou_snippet(el, title)
        results.append(Result(title=title, url=href, content=content, engine=engine_name))

    return results


def _extract_sogou_snippet(el, title: str) -> str:
    selectors = (
        './/p[contains(@class, "str_info")]',
        './/div[contains(@class, "str_info")]',
        './/p[contains(@class, "fz-mid")]',
        './/div[contains(@class, "text-layout")]',
        ".//p",
    )
    for selector in selectors:
        for node in el.xpath(selector):
            text = clean_text(node.text_content())
            if text and text != title:
                return text
    return ""


class Sogou(Engine):
    name = "sogou"

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(
            url="https://www.sogou.com/web",
            params={
                "query": query,
                "ie": "utf8",
                "num": str(max_results),
            },
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

    def parse_response(self, text: str) -> list[Result]:
        return parse_sogou_web_results(text, self.name)
