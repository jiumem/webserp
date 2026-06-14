import unittest
from unittest.mock import AsyncMock, patch

from webserp.engines.base import Engine, RequestSpec
from webserp.errors import ChallengePageError
from webserp.search import search
from webserp import search as search_module


class FakeEngine(Engine):
    name = "fake_error_engine"

    def build_request(self, query: str, max_results: int = 10) -> RequestSpec:
        return RequestSpec(url="https://example.com")

    def parse_response(self, text: str):
        return []


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


if __name__ == "__main__":
    unittest.main()
