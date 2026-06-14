"""Sogou Zhihu site search engine."""

from .base import Engine, RequestSpec, Result
from .sogou import parse_sogou_web_results


class SogouZhihu(Engine):
    name = "sogou_zhihu"

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(
            url="https://www.sogou.com/sogou",
            params={
                "query": query,
                "insite": "zhihu.com",
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
