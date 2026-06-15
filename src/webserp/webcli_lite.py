"""Unified CLI entry point for webcli-lite."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .client import DEFAULT_MAX_BODY_BYTES, fetch_response
from .engines import ALL_ENGINES
from .errors import BlockedUrlError, WebSerpError
from .search import search
from .security import is_blocked_ip, validate_http_url
from .webfetch import extract
from .webfetch.types import Link, WebFetchResult

SERPER_DEFAULT_ENGINES = ["bing_cn", "brave"]
SERPER_DEFAULT_MAX_RESULTS = 5
FETCH_DEFAULT_MAX_MARKDOWN_CHARS = 20_000
MAP_DEFAULT_LINK_TYPES = {"content", "directory"}
MAP_DEFAULT_MAX_LINKS = 50

SERPER_PROFILES = {
    "agent": SERPER_DEFAULT_ENGINES,
    "zh": ["bing_cn", "brave"],
    "en": ["brave", "bing_cn"],
    "mixed": ["bing_cn", "brave", "baidu", "sogou", "sogou_weixin", "yahoo", "presearch"],
    "cn-deep": ["bing_cn", "baidu", "sogou", "sogou_weixin"],
    "all": list(ALL_ENGINES.keys()),
}


class CliError(Exception):
    def __init__(self, error_type: str, message: str, *, code: int = 2, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.code = code
        self.details = details or {}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliError("ArgumentError", message, code=2)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status:
            raise CliError("ArgumentError", (message or "").strip(), code=status)
        super().exit(status, message)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if not hasattr(args, "handler"):
            parser.print_help()
            return 0
        result = args.handler(args)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result
    except CliError as exc:
        _write_json_error(exc.error_type, exc.message, details=exc.details)
        return exc.code
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        if exc.code is None:
            return 0
        _write_json_error("SystemExit", str(exc.code))
        return 1
    except WebSerpError as exc:
        _write_json_error(exc.__class__.__name__, str(exc))
        return 2
    except Exception as exc:
        _write_json_error(exc.__class__.__name__, str(exc))
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="webcli-lite",
        description="Local-agent web search, fetch, and link mapping.",
    )
    parser.add_argument("--version", action="version", version=f"webcli-lite {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    serper = subparsers.add_parser("serper", help="Search the web and return JSON results")
    serper.add_argument("query", nargs="?", help="Search query")
    serper.add_argument("-e", "--engines", default=None, help="Comma-separated engine list")
    serper.add_argument(
        "--profile",
        choices=sorted(SERPER_PROFILES.keys()),
        default="agent",
        help="Engine profile (default: agent)",
    )
    serper.add_argument("--fallback", default=None, help="Comma-separated fallback engines used only when results are insufficient")
    serper.add_argument("--min-results", type=_non_negative_int, default=10, help="Minimum result count before fallback runs (default: 10)")
    serper.add_argument("-n", "--max-results", type=_positive_int, default=SERPER_DEFAULT_MAX_RESULTS, help="Max results per engine (default: 5)")
    serper.add_argument("--timeout", type=_positive_int, default=10, help="Per-engine timeout in seconds (default: 10)")
    serper.add_argument("--proxy", default=None, help="Proxy URL for all requests")
    serper.add_argument("--verbose", action="store_true", help="Show engine success/failure in stderr")
    serper.add_argument("--list-engines", action="store_true", help="Print available engines as JSON")
    serper.add_argument("--list-profiles", action="store_true", help="Print available profiles as JSON")
    serper.add_argument("--no-indent", action="store_true", help="Print compact JSON")
    _add_output_args(serper)
    serper.set_defaults(handler=_handle_serper)

    fetch = subparsers.add_parser("fetch", help="Fetch a page and return Markdown by default")
    fetch.add_argument("url", nargs="?", help="HTTP(S) URL to fetch")
    fetch.add_argument("--format", choices=["md", "html", "text"], default="md", help="Output format (default: md)")
    fetch.add_argument("--json", action="store_true", help="Wrap output and metadata in JSON")
    fetch.add_argument("--html-file", default=None, help="Read HTML from a local file without network access")
    fetch.add_argument("--stdin", action="store_true", help="Read HTML from stdin without network access")
    fetch.add_argument("--base-url", default=None, help="Base URL for offline HTML relative-link resolution")
    fetch.add_argument("--max-markdown-chars", type=_non_negative_int, default=FETCH_DEFAULT_MAX_MARKDOWN_CHARS, help="Max Markdown/text chars; 0 disables truncation")
    fetch.add_argument("--include-structured-data", action="store_true", help="Include structured_data in --json output")
    fetch.add_argument("--debug", action="store_true", help="Include extraction candidates in --json output")
    _add_fetch_network_args(fetch)
    _add_output_args(fetch)
    fetch.set_defaults(handler=_handle_fetch)

    map_cmd = subparsers.add_parser("map", help="Extract page links and return JSON")
    map_cmd.add_argument("url", nargs="?", help="HTTP(S) URL to fetch")
    map_cmd.add_argument("--type", action="append", default=None, help="Link type to include: content,directory,navigation,noise")
    map_cmd.add_argument("--all", action="store_true", help="Return all link types")
    map_cmd.add_argument("--max-links", type=_non_negative_int, default=MAP_DEFAULT_MAX_LINKS, help="Max links to return; 0 disables truncation")
    map_cmd.add_argument("--html-file", default=None, help="Read HTML from a local file without network access")
    map_cmd.add_argument("--stdin", action="store_true", help="Read HTML from stdin without network access")
    map_cmd.add_argument("--base-url", default=None, help="Base URL for offline HTML relative-link resolution")
    map_cmd.add_argument("--no-indent", action="store_true", help="Print compact JSON")
    _add_fetch_network_args(map_cmd)
    _add_output_args(map_cmd)
    map_cmd.set_defaults(handler=_handle_map)

    return parser


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output", default=None, help="Write output to a file instead of stdout")
    parser.add_argument("--force", action="store_true", help="Overwrite --output if it already exists")


def _add_fetch_network_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout", type=_positive_int, default=10, help="Request timeout in seconds (default: 10)")
    parser.add_argument("--proxy", default=None, help="Proxy URL")
    parser.add_argument("--max-body-bytes", type=_positive_int, default=DEFAULT_MAX_BODY_BYTES, help="Maximum response body size in bytes")
    parser.add_argument("--retries", type=_non_negative_int, default=0, help="Retries for transient 5xx errors (default: 0)")


async def _handle_serper(args: argparse.Namespace) -> int:
    if args.list_engines:
        return _emit_json({"engines": list(ALL_ENGINES.keys())}, args.output, args.force, indent=not args.no_indent)
    if args.list_profiles:
        return _emit_json({"profiles": SERPER_PROFILES}, args.output, args.force, indent=not args.no_indent)
    if not args.query:
        raise CliError("ArgumentError", "serper requires a query")

    engines = _engine_list(args.engines, profile=args.profile)
    fallback = _parse_csv(args.fallback)
    if fallback:
        _validate_engines(fallback)

    result = await search(
        query=args.query,
        engine_names=engines,
        max_results=args.max_results,
        timeout=args.timeout,
        proxy=args.proxy,
    )

    fallback_used: list[str] = []
    if fallback and result["number_of_results"] < max(0, args.min_results):
        fallback_result = await search(
            query=args.query,
            engine_names=fallback,
            max_results=args.max_results,
            timeout=args.timeout,
            proxy=args.proxy,
        )
        result = _merge_search_results(result, fallback_result)
        fallback_used = fallback

    result["meta"] = {
        "profile": args.profile,
        "engines": engines,
        "fallback_used": fallback_used,
        "max_results_per_engine": args.max_results,
    }

    if args.verbose:
        failed = {engine_name for engine_name, _error in result["unresponsive_engines"]}
        succeeded = [engine for engine in engines + fallback_used if engine not in failed]
        print(f"Succeeded: {', '.join(succeeded)}", file=sys.stderr)
        for engine_name, error in result["unresponsive_engines"]:
            print(f"Failed: {engine_name} ({error})", file=sys.stderr)

    return _emit_json(result, args.output, args.force, indent=not args.no_indent)


async def _handle_fetch(args: argparse.Namespace) -> int:
    page = await _load_page(args)

    if args.format == "html" and not args.json:
        return _emit_text(page["html"], args.output, args.force, expected_suffixes={".html", ".htm"})

    result = extract(page["html"], page["url"], final_url=page["final_url"], status=page["status"])
    if args.format == "text":
        content, truncated = _truncate(result.text, args.max_markdown_chars)
        if truncated and not args.json:
            content += f"\n\n[webcli-lite: text truncated at {args.max_markdown_chars} chars]\n"
        expected_suffixes = {".txt"}
    else:
        content, truncated = _truncate(result.markdown, args.max_markdown_chars)
        if truncated and not args.json:
            content += f"\n\n<!-- webcli-lite: markdown truncated at {args.max_markdown_chars} chars -->\n"
        expected_suffixes = {".md", ".markdown", ".txt"}

    if not args.json:
        return _emit_text(content, args.output, args.force, expected_suffixes=expected_suffixes)

    payload = _fetch_json_payload(result, args.format, content, truncated, page["html"], args)
    return _emit_json(payload, args.output, args.force, indent=True)


async def _handle_map(args: argparse.Namespace) -> int:
    page = await _load_page(args)
    result = extract(page["html"], page["url"], final_url=page["final_url"], status=page["status"])
    link_types = _map_link_types(args)
    links = [link for link in result.links if args.all or link.type in link_types]
    links, truncated = _truncate_links(links, args.max_links)
    payload = {
        "url": result.url,
        "final_url": result.final_url,
        "status": result.status,
        "title": result.title,
        "links": [link.as_dict() for link in links],
        "meta": {
            "link_types": "all" if args.all else sorted(link_types),
            "truncated": {"links": truncated},
        },
    }
    return _emit_json(payload, args.output, args.force, indent=not args.no_indent)


async def _load_page(args: argparse.Namespace) -> dict[str, Any]:
    offline_sources = [bool(getattr(args, "html_file", None)), bool(getattr(args, "stdin", False))]
    if sum(offline_sources) > 1:
        raise CliError("ArgumentError", "use only one of --html-file or --stdin")
    if any(offline_sources) and args.url:
        raise CliError("ArgumentError", "do not pass URL together with --html-file or --stdin")

    if getattr(args, "html_file", None):
        if not args.base_url:
            raise CliError("ArgumentError", "--base-url is required with --html-file")
        base_url = _validate_offline_base_url(args.base_url)
        html_text = Path(args.html_file).read_text(encoding="utf-8")
        return {"html": html_text, "url": base_url, "final_url": base_url, "status": 0}

    if getattr(args, "stdin", False):
        if not args.base_url:
            raise CliError("ArgumentError", "--base-url is required with --stdin")
        base_url = _validate_offline_base_url(args.base_url)
        html_text = sys.stdin.read()
        return {"html": html_text, "url": base_url, "final_url": base_url, "status": 0}

    if not args.url:
        raise CliError("ArgumentError", "URL is required unless --html-file or --stdin is used")

    response = await fetch_response(
        args.url,
        timeout=args.timeout,
        proxy=args.proxy,
        max_body_bytes=args.max_body_bytes,
        retries=args.retries,
    )
    return {"html": response.text, "url": args.url, "final_url": response.url, "status": response.status}


def _fetch_json_payload(
    result: WebFetchResult,
    output_format: str,
    content: str,
    truncated: bool,
    html_text: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": result.url,
        "final_url": result.final_url,
        "status": result.status,
        "title": result.title,
        "description": result.description,
        "markdown": None,
        "text": None,
        "html": None,
        "metadata": result.metadata.as_dict(),
        "meta": {
            "strategy": result.meta.get("strategy"),
            "warnings": result.meta.get("warnings", []),
            "truncated": {"markdown": False, "text": False, "html": False},
        },
    }
    if output_format == "html":
        payload["html"] = html_text
    elif output_format == "text":
        payload["text"] = content
        payload["meta"]["truncated"]["text"] = truncated
    else:
        payload["markdown"] = content
        payload["meta"]["truncated"]["markdown"] = truncated

    if args.include_structured_data:
        payload["structured_data"] = result.structured_data
    if args.debug:
        payload["meta"]["candidates"] = result.meta.get("candidates", {})
    return payload


def _engine_list(raw: str | None, *, profile: str) -> list[str]:
    engines = _parse_csv(raw) if raw else list(SERPER_PROFILES[profile])
    _validate_engines(engines)
    return engines


def _validate_engines(engines: list[str]) -> None:
    invalid = [engine for engine in engines if engine not in ALL_ENGINES]
    if invalid:
        raise CliError(
            "InvalidEngineError",
            f"unknown engines: {', '.join(invalid)}",
            details={"available": list(ALL_ENGINES.keys())},
        )


def _positive_int(value: str) -> int:
    parsed = _parse_int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = _parse_int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _parse_int(value: str) -> int:
    try:
        return int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc


def _validate_offline_base_url(raw: str) -> str:
    validated = validate_http_url(raw)
    host = validated.host.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise BlockedUrlError("base URL host is localhost")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return validated.url
    if is_blocked_ip(ip):
        raise BlockedUrlError("base URL uses a private, reserved, or internal address")
    return validated.url


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _merge_search_results(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    results = []
    seen = set()
    for result in primary["results"] + fallback["results"]:
        normalized = result["url"].rstrip("/").lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append(result)
    merged["results"] = results
    merged["number_of_results"] = len(results)
    merged["unresponsive_engines"] = primary["unresponsive_engines"] + fallback["unresponsive_engines"]
    return merged


def _map_link_types(args: argparse.Namespace) -> set[str]:
    if args.all:
        return {"content", "directory", "navigation", "noise"}
    raw_types: list[str] = []
    for entry in args.type or []:
        raw_types.extend(_parse_csv(entry))
    link_types = set(raw_types) if raw_types else set(MAP_DEFAULT_LINK_TYPES)
    invalid = sorted(link_types - {"content", "directory", "navigation", "noise"})
    if invalid:
        raise CliError("ArgumentError", f"unknown link types: {', '.join(invalid)}")
    return link_types


def _truncate(value: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(value) <= max_chars:
        return value, False
    return value[:max_chars].rstrip(), True


def _truncate_links(links: list[Link], max_links: int) -> tuple[list[Link], bool]:
    if max_links <= 0 or len(links) <= max_links:
        return links, False
    return links[:max_links], True


def _emit_json(payload: dict[str, Any], output: str | None, force: bool, *, indent: bool) -> int:
    text = json.dumps(payload, indent=2 if indent else None, ensure_ascii=False)
    return _emit_text(text + "\n", output, force, expected_suffixes={".json"})


def _emit_text(text: str, output: str | None, force: bool, *, expected_suffixes: set[str]) -> int:
    if output:
        _write_output(output, text, force, expected_suffixes=expected_suffixes)
        return 0
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _write_output(output: str, text: str, force: bool, *, expected_suffixes: set[str]) -> None:
    path = Path(output)
    if path.exists() and not force:
        raise CliError("OutputExistsError", f"output file already exists: {path}", details={"path": str(path)})
    if path.suffix and path.suffix.lower() not in expected_suffixes:
        print(
            f"webcli-lite: warning: output extension '{path.suffix}' does not match expected {sorted(expected_suffixes)}",
            file=sys.stderr,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json_error(error_type: str, message: str, *, details: dict[str, Any] | None = None) -> None:
    payload = {"error": {"type": error_type, "message": message, "details": details or {}}}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
