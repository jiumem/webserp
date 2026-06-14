"""Bing China search engine."""

from lxml import html

from .base import Engine, RequestSpec, Result
from .utils import clean_text, is_http_url, raise_for_challenge


class BingCn(Engine):
    name = "bing_cn"

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(
            url="https://cn.bing.com/search",
            params={
                "q": query,
                "ensearch": "0",
                "mkt": "zh-CN",
                "count": str(max_results),
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

        for el in tree.xpath('//li[contains(@class, "b_algo")]'):
            link = el.xpath('.//h2//a[@href]')
            if not link:
                link = el.xpath('.//a[@href]')
            if not link:
                continue

            href = link[0].get("href", "")
            if not is_http_url(href):
                continue

            title = clean_text(link[0].text_content())
            if not title:
                continue

            snippets = el.xpath('.//p')
            content = clean_text(snippets[0].text_content()) if snippets else ""
            results.append(Result(title=title, url=href, content=content, engine=self.name))

        return results
