import unittest

from webserp.engines.baidu import Baidu
from webserp.engines.bing_cn import BingCn
from webserp.engines.duckduckgo import DuckDuckGo
from webserp.engines import ALL_ENGINES, DEFAULT_ENGINES
from webserp.engines.sogou import Sogou
from webserp.engines.sogou_weixin import SogouWeixin
from webserp.engines.sogou_zhihu import SogouZhihu
from webserp.engines.utils import is_challenge_page
from webserp.errors import ChallengePageError


class ChineseEnginesTest(unittest.TestCase):
    def test_sogou_zhihu_is_available_but_not_default(self):
        self.assertIn("sogou_zhihu", ALL_ENGINES)
        self.assertNotIn("sogou_zhihu", DEFAULT_ENGINES)

    def test_bing_cn_parses_standard_results(self):
        html = """
        <html><body><ol id="b_results">
          <li class="b_algo">
            <h2><a href="https://example.cn/news">新能源汽车新闻</a></h2>
            <p>最新产业新闻和政策解读。</p>
          </li>
        </ol></body></html>
        """

        results = BingCn().parse_response(html)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "新能源汽车新闻")
        self.assertEqual(results[0].url, "https://example.cn/news")
        self.assertEqual(results[0].content, "最新产业新闻和政策解读。")
        self.assertEqual(results[0].engine, "bing_cn")

    def test_baidu_prefers_mu_over_redirect_url(self):
        html = """
        <html><body>
          <div class="result c-container" tpl="www_index" mu="https://www.gov.cn/policy">
            <h3><a href="http://www.baidu.com/link?url=redirect">促进新能源汽车产业发展</a></h3>
            <div class="c-abstract">国务院政策文件摘要。</div>
          </div>
        </body></html>
        """

        results = Baidu().parse_response(html)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://www.gov.cn/policy")
        self.assertEqual(results[0].engine, "baidu")

    def test_sogou_parses_web_results(self):
        html = """
        <html><body>
          <div class="vrwrap">
            <h3><a name="dttl" href="/link?url=abc">Python 异步编程教程</a></h3>
            <p class="str_info">asyncio 入门和实战内容。</p>
          </div>
        </body></html>
        """

        results = Sogou().parse_response(html)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Python 异步编程教程")
        self.assertEqual(results[0].url, "https://www.sogou.com/link?url=abc")
        self.assertEqual(results[0].content, "asyncio 入门和实战内容。")
        self.assertEqual(results[0].engine, "sogou")

    def test_sogou_dedupes_nested_duplicate_links(self):
        html = """
        <html><body>
          <div class="vrwrap">
            <h3><a href="/link?url=abc">重复标题</a></h3>
            <p>第一条摘要。</p>
          </div>
          <div class="vrwrap">
            <h3><a href="/link?url=abc">重复标题</a></h3>
            <p>重复摘要。</p>
          </div>
          <div class="vrwrap">
            <h3><a href="/link?url=def">第二条标题</a></h3>
            <p>第二条摘要。</p>
          </div>
        </body></html>
        """

        results = Sogou().parse_response(html)

        self.assertEqual([result.title for result in results], ["重复标题", "第二条标题"])

    def test_sogou_weixin_parses_article_results(self):
        html = """
        <html><body>
          <ul class="news-list">
            <li>
              <div class="txt-box">
                <h3><a href="/link?url=wx">公众号文章标题</a></h3>
                <p class="txt-info">这是一篇微信公众号文章摘要。</p>
              </div>
            </li>
          </ul>
        </body></html>
        """

        results = SogouWeixin().parse_response(html)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "公众号文章标题")
        self.assertEqual(results[0].url, "https://weixin.sogou.com/link?url=wx")
        self.assertEqual(results[0].content, "这是一篇微信公众号文章摘要。")
        self.assertEqual(results[0].engine, "sogou_weixin")

    def test_sogou_zhihu_uses_same_web_parser_with_distinct_engine_name(self):
        html = """
        <html><body>
          <div class="vrwrap">
            <h3><a href="https://www.zhihu.com/question/1">知乎回答标题</a></h3>
            <p>知乎回答摘要。</p>
          </div>
        </body></html>
        """

        results = SogouZhihu().parse_response(html)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://www.zhihu.com/question/1")
        self.assertEqual(results[0].engine, "sogou_zhihu")

    def test_challenge_pages_are_detected(self):
        self.assertTrue(is_challenge_page("用户您好，我们的系统检测到您网络中存在异常访问请求"))
        self.assertTrue(is_challenge_page("Unfortunately, bots use DuckDuckGo too."))

        with self.assertRaises(ChallengePageError):
            Sogou().parse_response("antispider 请输入验证码")

        with self.assertRaises(ChallengePageError):
            DuckDuckGo().parse_response("Unfortunately, bots use DuckDuckGo too.")


if __name__ == "__main__":
    unittest.main()
