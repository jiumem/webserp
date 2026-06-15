import unittest
from unittest.mock import patch

from webserp.client import FetchContext, fetch, fetch_response
from webserp.errors import BlockedUrlError, BodyTooLargeError, ChallengePageError, HttpStatusError
from webserp.security import clear_dns_cache


class FakeResponse:
    def __init__(self, status=200, body=b"ok", headers=None, url="https://example.com/"):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.url = url
        self.encoding = "utf-8"

    async def acontent(self):
        return self._body


class FakeBufferedResponse(FakeResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content = self._body

    async def acontent(self):
        raise RuntimeError("stream mode is not enabled")


class FakeStreamResponse(FakeResponse):
    def __init__(self, chunks, status=200, headers=None, url="https://example.com/"):
        super().__init__(status=status, body=b"", headers=headers, url=url)
        self.content = b""
        self.queue = object()
        self.curl = object()
        self.chunks = chunks
        self.closed = False

    async def aiter_content(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_declared_body_too_large_raises_before_decode(self):
        session = FakeSession([
            FakeResponse(headers={"content-length": "10"}, body=b"short"),
        ])

        with self.assertRaises(BodyTooLargeError):
            await fetch("https://example.com", session=session, validate_url=False, max_body_bytes=5)

    async def test_declared_stream_body_too_large_closes_response(self):
        response = FakeStreamResponse([b"short"], headers={"content-length": "10"})
        session = FakeSession([response])

        with self.assertRaises(BodyTooLargeError):
            await fetch("https://example.com", session=session, validate_url=False, max_body_bytes=5)

        self.assertTrue(response.closed)

    async def test_actual_body_too_large_raises(self):
        session = FakeSession([
            FakeResponse(body=b"abcdef"),
        ])

        with self.assertRaises(BodyTooLargeError):
            await fetch("https://example.com", session=session, validate_url=False, max_body_bytes=5)

    async def test_429_is_not_retried(self):
        session = FakeSession([
            FakeResponse(status=429, body=b"rate limited"),
            FakeResponse(status=200, body=b"should not be used"),
        ])

        with self.assertRaises(HttpStatusError) as caught:
            await fetch("https://example.com", session=session, validate_url=False, retries=1)

        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(len(session.calls), 1)

    async def test_5xx_retries_once(self):
        session = FakeSession([
            FakeResponse(status=503, body=b"temporary"),
            FakeResponse(status=200, body=b"ok"),
        ])

        text = await fetch("https://example.com", session=session, validate_url=False, retries=1)

        self.assertEqual(text, "ok")
        self.assertEqual(len(session.calls), 2)

    async def test_fetch_response_returns_metadata(self):
        session = FakeSession([
            FakeResponse(status=200, body=b"ok", headers={"x-test": "yes"}, url="https://example.com/final"),
        ])

        response = await fetch_response("https://example.com/start", session=session, validate_url=False)

        self.assertEqual(response.text, "ok")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.url, "https://example.com/final")
        self.assertEqual(response.headers["x-test"], "yes")

    async def test_requests_stream_responses(self):
        session = FakeSession([
            FakeResponse(body=b"ok"),
        ])

        await fetch("https://example.com", session=session, validate_url=False)

        self.assertTrue(session.calls[0][1]["stream"])
        self.assertTrue(session.calls[0][1]["allow_redirects"])

    async def test_buffered_response_content_is_used_before_stream_content(self):
        session = FakeSession([
            FakeBufferedResponse(body=b"ok"),
        ])

        text = await fetch("https://example.com", session=session, validate_url=False)

        self.assertEqual(text, "ok")

    async def test_streaming_body_too_large_closes_response(self):
        response = FakeStreamResponse([b"abc", b"def"])
        session = FakeSession([response])

        with self.assertRaises(BodyTooLargeError):
            await fetch("https://example.com", session=session, validate_url=False, max_body_bytes=5)

        self.assertTrue(response.closed)

    async def test_validated_fetch_blocks_redirect_to_private_address(self):
        response = FakeStreamResponse(
            [b""],
            status=302,
            headers={"location": "http://127.0.0.1/"},
            url="https://93.184.216.34/start",
        )
        session = FakeSession([response])

        with self.assertRaises(BlockedUrlError):
            await fetch("https://93.184.216.34/start", session=session)

        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertTrue(response.closed)

    async def test_validated_fetch_follows_public_redirects_manually(self):
        session = FakeSession([
            FakeStreamResponse(
                [b""],
                status=302,
                headers={"location": "/final"},
                url="https://93.184.216.34/start",
            ),
            FakeStreamResponse([b"ok"], url="https://93.184.216.34/final"),
        ])

        text = await fetch("https://93.184.216.34/start", session=session)

        self.assertEqual(text, "ok")
        self.assertEqual(len(session.calls), 2)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertEqual(session.calls[1][0][1], "https://93.184.216.34/final")

    async def test_local_agent_dns_policy_allows_fake_ip_hostname_redirects(self):
        clear_dns_cache()
        session = FakeSession([
            FakeStreamResponse(
                [b""],
                status=302,
                headers={"location": "https://docs.example.test/final"},
                url="https://example.test/start",
            ),
            FakeStreamResponse([b"ok"], url="https://docs.example.test/final"),
        ])

        with patch(
            "webserp.security.socket.getaddrinfo",
            return_value=[(0, 0, 0, "", ("198.18.3.174", 443))],
        ):
            text = await fetch("https://example.test/start", session=session, dns_policy="local-agent")

        self.assertEqual(text, "ok")
        self.assertEqual(len(session.calls), 2)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertEqual(session.calls[1][0][1], "https://docs.example.test/final")

    async def test_challenge_is_not_retried(self):
        session = FakeSession([
            FakeResponse(status=202, body=b"Unfortunately, bots use DuckDuckGo too."),
            FakeResponse(status=200, body=b"should not be used"),
        ])

        with self.assertRaises(ChallengePageError):
            await fetch("https://example.com", session=session, validate_url=False, retries=1)

        self.assertEqual(len(session.calls), 1)

    async def test_fetch_context_reuses_profile_per_engine(self):
        session = FakeSession([
            FakeResponse(body=b"first"),
            FakeResponse(body=b"second"),
        ])
        context = FetchContext(session=session, validate_urls=False)

        with patch("webserp.client.random_impersonate", side_effect=["chrome110", "chrome120"]):
            await fetch("https://example.com/1", context=context, profile_key="engine-a")
            await fetch("https://example.com/2", context=context, profile_key="engine-a")

        first = session.calls[0][1]["impersonate"]
        second = session.calls[1][1]["impersonate"]
        self.assertEqual(first, "chrome110")
        self.assertEqual(second, "chrome110")


if __name__ == "__main__":
    unittest.main()
