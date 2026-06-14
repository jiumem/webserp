"""Stable error types for fetch and search failures."""


class WebSerpError(Exception):
    """Base class that renders a stable error code for CLI JSON output."""

    code = "error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class InvalidUrlError(WebSerpError):
    code = "invalid_url"


class BlockedUrlError(WebSerpError):
    code = "blocked_url"


class FetchTimeoutError(WebSerpError):
    code = "timeout"


class FetchRequestError(WebSerpError):
    code = "request_error"


class BodyTooLargeError(WebSerpError):
    code = "body_too_large"


class ChallengePageError(WebSerpError):
    code = "challenge"


class HttpStatusError(WebSerpError):
    code = "http_error"

    def __init__(self, status: int, message: str | None = None):
        self.status = status
        super().__init__(message or f"HTTP {status}")
