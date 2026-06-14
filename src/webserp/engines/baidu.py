"""Baidu search engine."""

from lxml import html

from .base import Engine, RequestSpec, Result
from .utils import absolute_url, clean_text, is_http_url, raise_for_challenge


class Baidu(Engine):
    name = "baidu"

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(
            url="https://www.baidu.com/s",
            params={
                "wd": query,
                "rn": str(max_results),
                "ie": "utf-8",
            },
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

    def parse_response(self, text: str) -> list[Result]:
        raise_for_challenge(text, self.name)
        results = []
        tree = html.fromstring(text)
        containers = tree.xpath(
            '//div[(contains(concat(" ", normalize-space(@class), " "), " result ") or @tpl) and .//h3]'
        )

        for el in containers:
            link = el.xpath('.//h3//a[@href]')
            if not link:
                link = el.xpath('.//a[@data-module="title" and @href]')
            if not link:
                continue

            title = clean_text(link[0].text_content())
            if not title:
                continue

            href = clean_text(el.get("mu"))
            if not is_http_url(href):
                href = absolute_url(link[0].get("href", ""), "https://www.baidu.com")
            if not is_http_url(href):
                continue

            content = self._extract_snippet(el, title)
            results.append(Result(title=title, url=href, content=content, engine=self.name))

        return results

    def _extract_snippet(self, el, title: str) -> str:
        selectors = (
            './/div[contains(@class, "c-abstract")]',
            './/span[contains(@class, "content-right")]',
            './/span[contains(@class, "content-text")]',
            './/div[contains(@class, "c-span-last")]',
            './/div[contains(@class, "summary")]',
            './/span[contains(@class, "c-color-text")]',
        )
        for selector in selectors:
            for node in el.xpath(selector):
                text = clean_text(node.text_content())
                if text and text != title:
                    return text
        return ""
