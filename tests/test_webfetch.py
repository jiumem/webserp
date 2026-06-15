import json
import unittest
from pathlib import Path

from webserp.webfetch import extract, webfetch


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


class WebFetchAdversarialTest(unittest.TestCase):
    def test_rejects_unsafe_markdown_url_schemes(self):
        html = """
        <html><body><main>
          <h1>Unsafe URLs</h1>
          <p>This paragraph has enough text to be viable and includes
          <a href="Javascript:alert(1)">bad javascript</a>
          plus more words for extraction.</p>
          <img src="File:///etc/passwd" alt="local file">
        </main></body></html>
        """

        result = extract(html, "https://example.com/unsafe")

        self.assertIn("bad javascript", result.markdown)
        self.assertNotIn("javascript:", result.markdown.lower())
        self.assertNotIn("file:", result.markdown.lower())
        self.assertEqual(result.images, [])
        self.assertNotIn("bad javascript", [link.text for link in result.links])

    def test_data_island_does_not_pollute_complete_short_article(self):
        html = """
        <html><head><title>Good Article</title></head><body>
          <main><article>
            <h1>Good Article</h1>
            <p>This is a complete short article with a clear factual sentence
            about the release checklist and review policy.</p>
            <p>The content is intentionally short but already sufficient for
            an agent answer.</p>
          </article></main>
          <script type="application/json">
          {"modal":{"title":"Newsletter signup","body":"Subscribe to our weekly marketing digest to receive promotional offers and unrelated onboarding campaigns that should not be appended to the article markdown."}}
          </script>
        </body></html>
        """

        result = extract(html, "https://example.com/good")

        self.assertIn(result.meta["strategy"], {"semantic", "scored", "structural"})
        self.assertNotIn("data_enriched", result.meta["candidates"])
        self.assertNotIn("weekly marketing digest", result.markdown)

    def test_layout_table_filters_noisy_navigation_cells(self):
        html = """
        <html><body><table><tr>
          <td class="sidebar nav"><a href="/login">Login</a><a href="/archive">Archive</a></td>
          <td><article><h1>Main</h1>
          <p>This is the actual article body with enough text to be a candidate
          and it should not contain navigation.</p>
          </article></td>
        </tr></table></body></html>
        """

        result = extract(html, "https://example.com/layout")

        self.assertIn("actual article body", result.markdown)
        self.assertNotIn("Login", result.markdown)
        self.assertNotIn("Archive", result.markdown)

    def test_markdown_escapes_labels_and_code_fences(self):
        html = """
        <html><body><main>
          <h1>Fence</h1>
          <p>Example includes a code block with Markdown syntax.</p>
          <pre><code class="language-md">```
inside
```</code></pre>
          <p>See <a href="/x">bad ](text</a>
          and <img src="/i.png" alt="alt ](bad)"></p>
        </main></body></html>
        """

        result = extract(html, "https://example.com/fence")

        self.assertIn("````md\n```\ninside\n```\n````", result.markdown)
        self.assertIn("[bad \\](text](https://example.com/x)", result.markdown)
        self.assertIn("![alt \\](bad)](https://example.com/i.png)", result.markdown)
        self.assertNotIn("[bad ](text]", result.markdown)


def _table_row_count(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.startswith("|") and line.endswith("|"))


def _link_type_counts(links: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for link in links:
        counts[link["type"]] = counts.get(link["type"], 0) + 1
    return counts


if __name__ == "__main__":
    unittest.main()
