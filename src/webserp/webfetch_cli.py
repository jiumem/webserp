"""CLI entry point for webfetch."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .client import DEFAULT_MAX_BODY_BYTES
from .errors import WebSerpError
from .webfetch import webfetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="webfetch",
        description="Fetch one URL and extract Agent-friendly Markdown JSON.",
    )
    parser.add_argument("url", help="HTTP(S) URL to fetch")
    parser.add_argument("--timeout", type=int, default=10, help="Request timeout in seconds (default: 10)")
    parser.add_argument("--proxy", default=None, help="Proxy URL")
    parser.add_argument(
        "--max-body-bytes",
        type=int,
        default=DEFAULT_MAX_BODY_BYTES,
        help="Maximum response body size in bytes (default: 5242880)",
    )
    parser.add_argument("--retries", type=int, default=0, help="Retries for transient 5xx errors (default: 0)")
    parser.add_argument("--no-indent", action="store_true", help="Print compact JSON")
    parser.add_argument("--version", action="version", version=f"webfetch {__version__}")

    args = parser.parse_args(argv)

    try:
        result = asyncio.run(
            webfetch(
                args.url,
                timeout=args.timeout,
                proxy=args.proxy,
                max_body_bytes=args.max_body_bytes,
                retries=args.retries,
            )
        )
    except WebSerpError as exc:
        payload = {"url": args.url, "error": exc.__class__.__name__, "message": str(exc)}
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2

    indent = None if args.no_indent else 2
    print(json.dumps(result.as_dict(), indent=indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
