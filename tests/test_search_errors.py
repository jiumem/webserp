import unittest
from unittest.mock import AsyncMock, patch

from webserp.engines.base import Engine, RequestSpec
from webserp.engines.base import Result
from webserp.errors import ChallengePageError
from webserp.search import search
from webserp import search as search_module


class FakeEngine(Engine):
    name = "fake_error_engine"

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(url="https://example.com")

    def parse_response(self, text: str):
        return []


class FakeResultEngine(Engine):
    def __init__(self, name: str, results: list[Result]):
        self.name = name
        self._results = results

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(url=f"https://{self.name}.example.test/search")

    def parse_response(self, text: str):
        return self._results


class SearchErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_errors_are_reported_as_unresponsive_engines(self):
        engine = FakeEngine()
        search_module.ALL_ENGINES[engine.name] = engine
        try:
            with patch("webserp.search.fetch", new=AsyncMock(side_effect=ChallengePageError("blocked"))):
                result = await search("query", engine_names=[engine.name])
        finally:
            search_module.ALL_ENGINES.pop(engine.name, None)

        self.assertEqual(result["results"], [])
        self.assertEqual(result["unresponsive_engines"], [[engine.name, "challenge: blocked"]])

    async def test_search_merges_results_by_rank_across_engines(self):
        engine_a = FakeResultEngine("fake_a", [
            Result(title="A1", url="https://example.com/a1", content="", engine="fake_a"),
            Result(title="A2", url="https://example.com/a2", content="", engine="fake_a"),
        ])
        engine_b = FakeResultEngine("fake_b", [
            Result(title="B1", url="https://example.com/b1", content="", engine="fake_b"),
            Result(title="B2", url="https://example.com/b2", content="", engine="fake_b"),
        ])
        search_module.ALL_ENGINES[engine_a.name] = engine_a
        search_module.ALL_ENGINES[engine_b.name] = engine_b
        try:
            with patch("webserp.search.fetch", new=AsyncMock(return_value="")):
                result = await search("query", engine_names=[engine_a.name, engine_b.name], max_results=2)
        finally:
            search_module.ALL_ENGINES.pop(engine_a.name, None)
            search_module.ALL_ENGINES.pop(engine_b.name, None)

        self.assertEqual(
            [item["title"] for item in result["results"]],
            ["A1", "B1", "A2", "B2"],
        )

    async def test_search_rank_merge_dedupes_urls(self):
        engine_a = FakeResultEngine("fake_a", [
            Result(title="A1", url="https://example.com/shared", content="", engine="fake_a"),
            Result(title="A2", url="https://example.com/a2", content="", engine="fake_a"),
        ])
        engine_b = FakeResultEngine("fake_b", [
            Result(title="B1", url="https://example.com/shared/", content="", engine="fake_b"),
            Result(title="B2", url="https://example.com/b2", content="", engine="fake_b"),
        ])
        search_module.ALL_ENGINES[engine_a.name] = engine_a
        search_module.ALL_ENGINES[engine_b.name] = engine_b
        try:
            with patch("webserp.search.fetch", new=AsyncMock(return_value="")):
                result = await search("query", engine_names=[engine_a.name, engine_b.name], max_results=2)
        finally:
            search_module.ALL_ENGINES.pop(engine_a.name, None)
            search_module.ALL_ENGINES.pop(engine_b.name, None)

        self.assertEqual(
            [item["title"] for item in result["results"]],
            ["A1", "A2", "B2"],
        )


if __name__ == "__main__":
    unittest.main()
