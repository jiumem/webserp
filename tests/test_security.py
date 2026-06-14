import socket
import unittest
from unittest.mock import patch

from webserp.errors import BlockedUrlError, InvalidUrlError
from webserp.security import clear_dns_cache, is_blocked_ip, validate_http_url, validate_public_http_url


class SecurityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_dns_cache()

    def test_validate_http_url_rejects_invalid_inputs(self):
        for url in ["", "file:///tmp/a", "ftp://example.com", "https:///missing-host"]:
            with self.subTest(url=url):
                with self.assertRaises(InvalidUrlError):
                    validate_http_url(url)

    async def test_blocks_private_ip_literals(self):
        blocked = [
            "http://localhost/",
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://172.16.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/",
            "http://[::1]/",
            "http://[fc00::1]/",
        ]

        for url in blocked:
            with self.subTest(url=url):
                with self.assertRaises(BlockedUrlError):
                    await validate_public_http_url(url)

    async def test_allows_public_ip_literal(self):
        self.assertEqual(
            await validate_public_http_url("https://93.184.216.34/"),
            "https://93.184.216.34/",
        )

    async def test_blocks_domains_that_resolve_to_private_addresses(self):
        with patch(
            "webserp.security.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
            ],
        ):
            with self.assertRaises(BlockedUrlError):
                await validate_public_http_url("https://example.test/")

    async def test_allows_domains_that_resolve_to_public_addresses(self):
        with patch(
            "webserp.security.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            ],
        ):
            self.assertEqual(
                await validate_public_http_url("https://example.test/path?q=1"),
                "https://example.test/path?q=1",
            )

    def test_ip_range_helper(self):
        import ipaddress

        self.assertTrue(is_blocked_ip(ipaddress.ip_address("127.0.0.1")))
        self.assertTrue(is_blocked_ip(ipaddress.ip_address("169.254.169.254")))
        self.assertFalse(is_blocked_ip(ipaddress.ip_address("93.184.216.34")))


if __name__ == "__main__":
    unittest.main()
