import unittest

from webserp.challenge import is_challenge_page, is_js_only_shell


class ChallengeDetectionTest(unittest.TestCase):
    def test_detects_known_challenge_pages(self):
        self.assertTrue(is_challenge_page("Unfortunately, bots use DuckDuckGo too."))
        self.assertTrue(is_challenge_page("<html>antispider 请输入验证码</html>"))
        self.assertTrue(is_challenge_page("<title>Just a moment...</title>Checking your browser"))
        self.assertTrue(is_challenge_page("用户您好，我们的系统检测到您网络中存在异常访问请求"))

    def test_detects_consent_wall(self):
        html = "<html><title>Before you continue</title><body>Accept cookies</body></html>"
        self.assertTrue(is_challenge_page(html, url="https://consent.example.com/"))

    def test_detects_js_only_shell(self):
        html = '<html><body><div id="root"></div><script>' + ("x" * 6000) + "</script></body></html>"
        self.assertTrue(is_js_only_shell(html))
        self.assertTrue(is_challenge_page(html))

    def test_detects_short_script_only_shell(self):
        html = "<html><body><script>" + ("var arg1='abc';" * 200) + "</script></body></html>"
        self.assertTrue(is_js_only_shell(html))
        self.assertTrue(is_challenge_page(html))

    def test_detects_raw_javascript_cookie_challenge(self):
        text = "var arg1='abc';function setCookie(){document.cookie=arg1;}window.location.href='/journal/paperinformation';"
        self.assertTrue(is_challenge_page(text))

    def test_does_not_flag_short_normal_page_with_script(self):
        html = """
        <html><body>
          <article><p>This short article has useful visible text and a small analytics script.</p></article>
          <script>console.log("analytics")</script>
        </body></html>
        """
        self.assertFalse(is_js_only_shell(html))
        self.assertFalse(is_challenge_page(html))

    def test_does_not_flag_normal_captcha_article(self):
        html = """
        <html>
          <head><title>How CAPTCHA Works</title></head>
          <body>
            <article>
              <p>This article explains captcha systems, bot detection, and verification UX.</p>
              <p>It is normal content, not a blocking challenge page.</p>
            </article>
          </body>
        </html>
        """
        self.assertFalse(is_challenge_page(html))


if __name__ == "__main__":
    unittest.main()
