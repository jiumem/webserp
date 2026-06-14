import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from webserp.webfetch import extract, webfetch
from webserp.webfetch_cli import main as webfetch_cli_main


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "webfetch"


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, url="https://example.com/final"):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.url = url
        self.encoding = "utf-8"

    async def acontent(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


class WebFetchGoldenTest(unittest.TestCase):
    def test_offline_fixtures_match_expected_goldens(self):
        expected_paths = sorted(FIXTURE_DIR.glob("*.expected.json"))
        self.assertGreaterEqual(len(expected_paths), 7)

        for expected_path in expected_paths:
            fixture_name = expected_path.name.replace(".expected.json", ".html")
            html_path = expected_path.with_name(fixture_name)
            expected = json.loads(expected_path.read_text(encoding="utf-8"))

            with self.subTest(fixture=html_path.name):
                result = extract(
                    html_path.read_text(encoding="utf-8"),
                    expected["url"],
                )
                payload = result.as_dict()
                markdown = payload["markdown"]

                self.assertIn(payload["meta"]["strategy"], expected["strategy_in"])
                for candidate_name in expected.get("candidate_names", []):
                    self.assertIn(candidate_name, payload["meta"]["candidates"])

                for fact in expected.get("must_include", []):
                    self.assertIn(fact, markdown)
                for forbidden in expected.get("must_exclude", []):
                    self.assertNotIn(forbidden, markdown)

                for key, value in expected.get("metadata", {}).items():
                    self.assertEqual(payload["metadata"][key], value)

                winner_score = payload["meta"]["candidates"][payload["meta"]["strategy"]]
                self.assertGreaterEqual(winner_score["text_chars"], expected.get("min_text_chars", 0))
                self.assertGreaterEqual(winner_score["cjk_chars"], expected.get("min_cjk_chars", 0))
                self.assertGreaterEqual(len(payload["images"]), expected.get("min_images", 0))
                self.assertGreaterEqual(len(payload["code_blocks"]), expected.get("min_code_blocks", 0))
                self.assertGreaterEqual(len(payload["structured_data"]), expected.get("min_structured_data", 0))

                table_rows = _table_row_count(markdown)
                self.assertGreaterEqual(table_rows, expected.get("min_table_rows", 0))
                if "max_table_rows" in expected:
                    self.assertLessEqual(table_rows, expected["max_table_rows"])

                languages = {block["language"] for block in payload["code_blocks"]}
                for language in expected.get("code_languages", []):
                    self.assertIn(language, languages)

                link_counts = _link_type_counts(payload["links"])
                for link_type, min_count in expected.get("min_link_types", {}).items():
                    self.assertGreaterEqual(link_counts.get(link_type, 0), min_count, payload["links"])


class WebFetchServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_webfetch_uses_safe_fetch_response_metadata(self):
        html = b"""
        <html><body><main><article>
          <h1>Fetched Article</h1>
          <p>The service layer should preserve final URL and status metadata.</p>
        </article></main></body></html>
        """
        session = FakeSession([
            FakeResponse(status=200, body=html, url="https://example.com/final"),
        ])

        result = await webfetch("https://example.com/start", session=session, validate_url=False)

        self.assertEqual(result.url, "https://example.com/start")
        self.assertEqual(result.final_url, "https://example.com/final")
        self.assertEqual(result.status, 200)
        self.assertIn("Fetched Article", result.markdown)
        self.assertEqual(session.calls[0][1]["stream"], True)


class WebFetchCliTest(unittest.TestCase):
    def test_cli_prints_webfetch_json(self):
        sample_html = (FIXTURE_DIR / "article_basic.html").read_text(encoding="utf-8")
        result = extract(sample_html, "https://example.com/news/climate-policy")

        async def fake_webfetch(*args, **kwargs):
            return result

        stdout = io.StringIO()
        with patch("webserp.webfetch_cli.webfetch", fake_webfetch), patch("sys.stdout", stdout):
            code = webfetch_cli_main(["https://example.com/news/climate-policy", "--no-indent"])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["url"], "https://example.com/news/climate-policy")
        self.assertIn("Climate Policy Update", payload["markdown"])
        self.assertIn("links", payload)
        self.assertIn("meta", payload)


def _table_row_count(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.startswith("|") and line.endswith("|"))


def _link_type_counts(links: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for link in links:
        counts[link["type"]] = counts.get(link["type"], 0) + 1
    return counts


if __name__ == "__main__":
    unittest.main()
