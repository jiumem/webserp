import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webserp.client import FetchResponse
from webserp.webcli_lite import main as webcli_main


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "webfetch"


class WebCliLiteSerperTest(unittest.TestCase):
    def test_serper_defaults_to_bing_cn_and_brave_with_five_results_each(self):
        calls = []

        async def fake_search(**kwargs):
            calls.append(kwargs)
            return {
                "query": kwargs["query"],
                "number_of_results": 2,
                "results": [
                    {"title": "A", "url": "https://example.com/a", "content": "a", "engine": "bing_cn"},
                    {"title": "B", "url": "https://example.com/b", "content": "b", "engine": "brave"},
                ],
                "suggestions": [],
                "unresponsive_engines": [],
            }

        stdout = io.StringIO()
        with patch("webserp.webcli_lite.search", fake_search), patch("sys.stdout", stdout):
            code = webcli_main(["serper", "agent query", "--no-indent"])

        self.assertEqual(code, 0)
        self.assertEqual(calls[0]["engine_names"], ["bing_cn", "brave"])
        self.assertEqual(calls[0]["max_results"], 5)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["meta"]["engines"], ["bing_cn", "brave"])
        self.assertEqual(payload["meta"]["max_results_per_engine"], 5)

    def test_serper_fallback_runs_only_when_results_are_insufficient(self):
        calls = []

        async def fake_search(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                results = [{"title": "A", "url": "https://example.com/a", "content": "a", "engine": "bing_cn"}]
            else:
                results = [{"title": "C", "url": "https://example.com/c", "content": "c", "engine": "yahoo"}]
            return {
                "query": kwargs["query"],
                "number_of_results": len(results),
                "results": results,
                "suggestions": [],
                "unresponsive_engines": [],
            }

        stdout = io.StringIO()
        with patch("webserp.webcli_lite.search", fake_search), patch("sys.stdout", stdout):
            code = webcli_main(["serper", "agent query", "--fallback", "yahoo,presearch", "--no-indent"])

        self.assertEqual(code, 0)
        self.assertEqual(calls[0]["engine_names"], ["bing_cn", "brave"])
        self.assertEqual(calls[1]["engine_names"], ["yahoo", "presearch"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["number_of_results"], 2)
        self.assertEqual(payload["meta"]["fallback_used"], ["yahoo", "presearch"])

    def test_serper_invalid_engine_returns_json_error(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = webcli_main(["serper", "query", "--engines", "missing"])

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["type"], "InvalidEngineError")

    def test_serper_invalid_fallback_is_rejected_before_search(self):
        async def fake_search(**kwargs):
            raise AssertionError("search should not run")

        stderr = io.StringIO()
        with patch("webserp.webcli_lite.search", fake_search), patch("sys.stderr", stderr):
            code = webcli_main(["serper", "query", "--fallback", "missing"])

        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr.getvalue())["error"]["type"], "InvalidEngineError")


class WebCliLiteFetchTest(unittest.TestCase):
    def test_fetch_defaults_to_markdown_stdout(self):
        html = (FIXTURE_DIR / "article_basic.html").read_text(encoding="utf-8")

        async def fake_fetch_response(*args, **kwargs):
            return FetchResponse(text=html, status=200, url="https://example.com/news/climate-policy", headers={})

        stdout = io.StringIO()
        with patch("webserp.webcli_lite.fetch_response", fake_fetch_response), patch("sys.stdout", stdout):
            code = webcli_main(["fetch", "https://example.com/news/climate-policy"])

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("# Climate Policy Update", output)
        self.assertNotIn('"links"', output)

    def test_fetch_json_excludes_links_by_default(self):
        html = (FIXTURE_DIR / "article_basic.html").read_text(encoding="utf-8")

        async def fake_fetch_response(*args, **kwargs):
            return FetchResponse(text=html, status=200, url="https://example.com/news/climate-policy", headers={})

        stdout = io.StringIO()
        with patch("webserp.webcli_lite.fetch_response", fake_fetch_response), patch("sys.stdout", stdout):
            code = webcli_main(["fetch", "https://example.com/news/climate-policy", "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertIn("markdown", payload)
        self.assertNotIn("links", payload)
        self.assertNotIn("structured_data", payload)

    def test_fetch_html_file_can_write_markdown_to_output_file(self):
        html_path = FIXTURE_DIR / "article_basic.html"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.md"
            stdout = io.StringIO()
            code = webcli_main([
                "fetch",
                "--html-file",
                str(html_path),
                "--base-url",
                "https://example.com/news/climate-policy",
                "-o",
                str(output),
            ])

            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("# Climate Policy Update", output.read_text(encoding="utf-8"))

            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                code = webcli_main([
                    "fetch",
                    "--html-file",
                    str(html_path),
                    "--base-url",
                    "https://example.com/news/climate-policy",
                    "-o",
                    str(output),
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stderr.getvalue())["error"]["type"], "OutputExistsError")

    def test_fetch_rejects_url_together_with_offline_html_source(self):
        html_path = FIXTURE_DIR / "article_basic.html"
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = webcli_main([
                "fetch",
                "https://example.com/article",
                "--html-file",
                str(html_path),
                "--base-url",
                "https://example.com/article",
            ])

        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr.getvalue())["error"]["type"], "ArgumentError")


class WebCliLiteMapTest(unittest.TestCase):
    def test_map_defaults_to_content_and_directory_links(self):
        html_path = FIXTURE_DIR / "directory_page.html"
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = webcli_main([
                "map",
                "--html-file",
                str(html_path),
                "--base-url",
                "https://example.com/resources/agent-tooling",
                "--no-indent",
            ])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        link_types = {link["type"] for link in payload["links"]}
        self.assertLessEqual(link_types, {"content", "directory"})
        self.assertIn("directory", link_types)

    def test_map_all_returns_navigation_and_noise_when_requested(self):
        html_path = FIXTURE_DIR / "directory_page.html"
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = webcli_main([
                "map",
                "--html-file",
                str(html_path),
                "--base-url",
                "https://example.com/resources/agent-tooling",
                "--all",
                "--no-indent",
            ])

        self.assertEqual(code, 0)
        link_types = {link["type"] for link in json.loads(stdout.getvalue())["links"]}
        self.assertIn("navigation", link_types)
        self.assertIn("noise", link_types)


class WebCliLiteProtocolTest(unittest.TestCase):
    def test_argparse_errors_are_json(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = webcli_main(["serper", "query", "--unknown"])

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["type"], "ArgumentError")


if __name__ == "__main__":
    unittest.main()
