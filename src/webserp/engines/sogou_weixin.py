"""Sogou Weixin article search engine."""

from lxml import html

from .base import Engine, RequestSpec, Result
from .utils import absolute_url, clean_text, is_http_url, raise_for_challenge


class SogouWeixin(Engine):
    name = "sogou_weixin"

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(
            url="https://weixin.sogou.com/weixin",
            params={
                "type": "2",
                "query": query,
                "ie": "utf8",
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

        for el in tree.xpath('//ul[contains(@class, "news-list")]/li[.//a[@href]]'):
            link = el.xpath('.//div[contains(@class, "txt-box")]//h3//a[@href]')
            if not link:
                link = el.xpath('.//h3//a[@href]') or el.xpath('.//a[@href]')
            if not link:
                continue

            href = absolute_url(link[0].get("href", ""), "https://weixin.sogou.com")
            if not is_http_url(href):
                continue

            title = clean_text(link[0].text_content())
            if not title:
                continue

            content = self._extract_snippet(el)
            results.append(Result(title=title, url=href, content=content, engine=self.name))

        return results

    def _extract_snippet(self, el) -> str:
        selectors = (
            './/p[contains(@class, "txt-info")]',
            './/p[contains(@class, "info")]',
            './/div[contains(@class, "txt-box")]//p',
        )
        for selector in selectors:
            for node in el.xpath(selector):
                text = clean_text(node.text_content())
                if text:
                    return text
        return ""
