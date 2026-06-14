"""Single-page fetch and extraction for webserp."""

from .extractor import extract
from .service import webfetch
from .types import CodeBlock, Image, Link, Metadata, WebFetchResult

__all__ = [
    "CodeBlock",
    "Image",
    "Link",
    "Metadata",
    "WebFetchResult",
    "extract",
    "webfetch",
]
