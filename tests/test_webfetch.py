import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from webserp.webfetch import extract, webfetch
from webserp.webfetch.service import fetch_page_response
from webserp.client import FetchResponse


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

    async def test_fetch_page_response_falls_back_on_curl_challenge(self):
        challenge = b"""
        <html><head><title>Just a moment...</title></head>
        <body>Enable JavaScript and cookies to continue<script>""" + (b"x" * 6000) + b"""</script></body></html>
        """
        session = FakeSession([
            FakeResponse(status=403, body=challenge, headers={"cf-mitigated": "challenge"}, url="https://example.com/challenge"),
        ])
        fallback_response = FetchResponse(
            text="<html><body><main><h1>Fallback Article</h1><p>Plain HTTP retrieved usable content.</p></main></body></html>",
            status=200,
            url="https://example.com/page",
            headers={},
        )

        with patch("webserp.webfetch.service._plain_fetch_response", new=AsyncMock(return_value=fallback_response)) as mocked:
            response = await fetch_page_response("https://example.com/page", session=session, validate_url=False)

        self.assertEqual(response.text, fallback_response.text)
        mocked.assert_awaited_once()


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

    def test_role_main_with_many_links_is_not_poisoned(self):
        links = "".join(f'<a href="/library/asyncio-task.html#item-{index}">目录项 {index}</a>' for index in range(30))
        html = f"""
        <html><body>
          <div class="document">
            <div class="body" role="main">
              <h1>协程与任务</h1>
              <nav class="contents">{links}</nav>
              <section>
                <h2>任务组</h2>
                <p>TaskGroup 类组合了任务创建 API 和等待所有任务完成的便捷可靠方式。</p>
                <p>当任务组中的任务失败时，其余任务会被取消，并以异常组的形式报告错误。</p>
              </section>
            </div>
          </div>
        </body></html>
        """

        result = extract(html, "https://docs.python.org/zh-cn/3/library/asyncio-task.html")

        self.assertIn("协程与任务", result.markdown)
        self.assertIn("TaskGroup 类组合了任务创建 API", result.markdown)
        self.assertNotIn("empty_extraction", result.meta["warnings"])

    def test_id_content_container_with_many_links_is_not_poisoned(self):
        links = "".join(f'<a href="/abs/1706.03762v{index}">version {index}</a>' for index in range(20))
        html = f"""
        <html><body>
          <main>
            <div id="content">
              <div id="content-inner">
                <h1>Attention Is All You Need</h1>
                <p>Authors introduce the Transformer, a model architecture based solely on attention mechanisms.</p>
                <p>The model dispenses with recurrence and convolutions while improving parallelization.</p>
                <div class="versions">{links}</div>
              </div>
            </div>
          </main>
        </body></html>
        """

        result = extract(html, "https://arxiv.org/abs/1706.03762")

        self.assertIn("Attention Is All You Need", result.markdown)
        self.assertIn("based solely on attention mechanisms", result.markdown)
        self.assertNotIn("empty_extraction", result.meta["warnings"])

    def test_article_body_container_with_many_links_is_not_poisoned(self):
        links = "".join(f'<a href="/finance/related-{index}.shtml">相关阅读 {index}</a>' for index in range(20))
        html = f"""
        <html><body>
          <div class="article-content clearfix" id="article_content">
            <div class="article" id="artibody">
              <h1>新能源汽车出海2.0：从卖车到建生态</h1>
              <p>中国车企正在从单纯出口整车，转向建设供应链、渠道和售后生态。</p>
              <p>欧洲政策、关税和本地化要求推动企业重新设计出海路径。</p>
              <aside>{links}</aside>
            </div>
          </div>
        </body></html>
        """

        result = extract(html, "https://finance.sina.com.cn/jjxw/2026-02-19/doc.shtml")

        self.assertIn("新能源汽车出海2.0", result.markdown)
        self.assertIn("转向建设供应链、渠道和售后生态", result.markdown)
        self.assertNotIn("empty_extraction", result.meta["warnings"])

    def test_injects_display_title_when_content_starts_at_h2(self):
        html = """
        <html>
          <head><title>Using the Fetch API - Web APIs | MDN</title></head>
          <body><main>
            <h2>Making a request</h2>
            <p>The Fetch API provides a JavaScript interface for making HTTP requests.</p>
            <p>It is useful documentation content, even when the selected node starts below the page title.</p>
          </main></body>
        </html>
        """

        result = extract(html, "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch")

        self.assertTrue(result.markdown.startswith("# Using the Fetch API\n\n## Making a request"))
        self.assertTrue(result.text.startswith("Using the Fetch API\nMaking a request"))

    def test_trims_short_docs_navigation_prelude_before_h1(self):
        html = """
        <html>
          <head><title>Transformers documentation | Hugging Face</title></head>
          <body><main>
            <div class="docs-shell">Transformers documentation Transformers View all docs API Reference</div>
            <article>
              <h1>Transformers</h1>
              <p>Transformers provides APIs and tools to download and train pretrained models.</p>
              <p>This is the relevant documentation body that should lead the Markdown output.</p>
            </article>
          </main></body>
        </html>
        """

        result = extract(html, "https://huggingface.co/docs/transformers/en/index")

        self.assertTrue(result.markdown.startswith("# Transformers\n\nTransformers provides APIs"))
        self.assertNotIn("View all docs", "\n".join(result.markdown.splitlines()[0:3]))

    def test_trims_duplicate_h1_docs_navigation_block(self):
        versions = " ".join(f"v4.{index}.0" for index in range(60))
        html = f"""
        <html>
          <head><title>Transformers · Hugging Face</title></head>
          <body><main>
            <h1>Transformers</h1>
            <div class="docs-shell">View all docs AWS Trainium Accelerate Datasets {versions} doc-builder-html EN ZH Join the Hugging Face community</div>
            <h1>Transformers</h1>
            <p>Transformers acts as the model-definition framework for state-of-the-art machine learning models.</p>
            <p>It centralizes the model definition across the ecosystem.</p>
          </main></body>
        </html>
        """

        result = extract(html, "https://huggingface.co/docs/transformers/en/index")

        self.assertTrue(result.markdown.startswith("# Transformers\n\nTransformers acts as the model-definition framework"))
        self.assertNotIn("View all docs", result.markdown)

    def test_trims_repository_navigation_before_readme_h1(self):
        html = """
        <html>
          <head><title>GitHub - psf/requests: A simple, yet elegant, HTTP library.</title></head>
          <body><main>
            <p><a href="/branches">Branches</a> <a href="/tags">Tags</a> Open more actions menu</p>
            <h2>Repository files navigation</h2>
            <h1>Requests</h1>
            <p>Requests is a simple, yet elegant, HTTP library.</p>
            <p>It allows you to send HTTP requests extremely easily.</p>
          </main></body>
        </html>
        """

        result = extract(html, "https://github.com/psf/requests")

        self.assertTrue(result.markdown.startswith("# Requests\n\nRequests is a simple"))
        self.assertNotIn("Repository files navigation", result.markdown)

    def test_trims_microsoft_learn_navigation_before_h1(self):
        html = """
        <html>
          <head><title>Azure Identity client library for Python</title></head>
          <body><main>
            <p>Read in English</p>
            <p><a href="/edit">Edit</a></p>
            <p>Note</p>
            <p>Access to this page requires authorization. You can try changing directories.</p>
            <h1>Azure Identity client library for Python - version 1.25.3</h1>
            <p>The Azure Identity library provides token-based authentication support across the Azure SDK.</p>
          </main></body>
        </html>
        """

        result = extract(html, "https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme")

        self.assertTrue(result.markdown.startswith("# Azure Identity client library for Python - version 1.25.3"))
        self.assertNotIn("Read in English", result.markdown)

    def test_injects_title_when_first_h1_is_not_page_title(self):
        html = """
        <html>
          <head><title>What does the "yield" keyword do in Python?</title></head>
          <body><main>
            <p>Asked 17 years ago. Viewed 3.5m times.</p>
            <p>What functionality does the yield keyword in Python provide?</p>
            <pre><code>yield value</code></pre>
            <h1>Highest scored answer</h1>
            <p>A function containing yield is a generator function.</p>
          </main></body>
        </html>
        """

        result = extract(html, "https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python")

        self.assertTrue(result.markdown.startswith("# What does the \"yield\" keyword do in Python?"))
        self.assertIn("## Highest scored answer", result.markdown)

    def test_strips_leading_wikipedia_maintenance_notices(self):
        html = """
        <html>
          <head><title>Web scraping - Wikipedia</title></head>
          <body><main>
            <h1>Web scraping - Wikipedia</h1>
            <p>From Wikipedia, the free encyclopedia</p>
            <p><img src="/notice.svg" alt="icon"></p>
            <p>This article needs additional citations for verification.</p>
            <p>Find sources: "Web scraping" - news - books - scholar.</p>
            <p>Method of extracting data from websites</p>
            <p><b>Web scraping</b> is data scraping used for extracting data from websites.</p>
          </main></body>
        </html>
        """

        result = extract(html, "https://en.wikipedia.org/wiki/Web_scraping")

        self.assertTrue(result.markdown.startswith("# Web scraping - Wikipedia\n\nMethod of extracting data from websites"))
        self.assertNotIn("needs additional citations", result.markdown)

    def test_trims_leading_image_only_prelude_before_h1(self):
        html = """
        <html><body><main>
          <p><img src="/logo.png" alt=""></p>
          <h1>新能源汽车出海2.0：从“卖车”到“建生态”</h1>
          <p>中国车企正在从单纯出口整车，转向建设供应链、渠道和售后生态。</p>
          <p>欧洲政策、关税和本地化要求推动企业重新设计出海路径。</p>
        </main></body></html>
        """

        result = extract(html, "https://finance.sina.com.cn/jjxw/2026-02-19/doc.shtml")

        self.assertTrue(result.markdown.startswith("# 新能源汽车出海2.0：从“卖车”到“建生态”"))
        self.assertNotIn("logo.png", "\n".join(result.markdown.splitlines()[0:3]))

    def test_puts_title_before_leading_logo_image_when_no_h1_exists(self):
        html = """
        <html>
          <head><title>新能源汽车出海观察 | 证券日报</title></head>
          <body><div id="article_content">
            <p><img src="/logo.png" alt="证券日报"></p>
            <p>中国车企正在从单纯出口整车，转向建设供应链、渠道和售后生态。</p>
            <p>欧洲政策、关税和本地化要求推动企业重新设计出海路径。</p>
          </div></body>
        </html>
        """

        result = extract(html, "https://www.cs.com.cn/esg/202409/t20240923_6441250.html")

        self.assertTrue(result.markdown.startswith("# 新能源汽车出海观察\n\n![证券日报]"))
        self.assertTrue(result.text.startswith("新能源汽车出海观察\n证券日报"))

    def test_extracts_gov_pages_content_container(self):
        html = """
        <html>
          <head><title>国务院办公厅关于2026年部分节假日安排的通知_国务院文件_中国政府网</title></head>
          <body>
            <table class="border-table noneBorder pages_content"><tr><td>
              <div id="UCAP-CONTENT" class="b12c pages_content">
                <p>国务院办公厅关于2026年</p>
                <p>部分节假日安排的通知</p>
                <p>国办发明电〔2025〕7号</p>
                <p>各省、自治区、直辖市人民政府，国务院各部委、各直属机构：</p>
                <p>经国务院批准，现将2026年元旦、春节、清明节、劳动节、端午节、中秋节和国庆节放假调休日期的具体安排通知如下。</p>
              </div>
            </td></tr></table>
          </body>
        </html>
        """

        result = extract(html, "https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm")

        self.assertIn(result.meta["strategy"], {"semantic_exact", "semantic", "scored", "structural"})
        self.assertTrue(result.markdown.startswith("# 国务院办公厅关于2026年部分节假日安排的通知_国务院文件_中国政府网"))
        self.assertIn("国办发明电〔2025〕7号", result.markdown)
        self.assertNotIn("empty_extraction", result.meta["warnings"])


def _table_row_count(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.startswith("|") and line.endswith("|"))


def _link_type_counts(links: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for link in links:
        counts[link["type"]] = counts.get(link["type"], 0) + 1
    return counts


if __name__ == "__main__":
    unittest.main()
