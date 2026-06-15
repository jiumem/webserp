"""Search orchestrator: parallel search across engines, merge, dedupe."""

import asyncio
import sys

from curl_cffi.requests import AsyncSession

from .client import FetchContext, fetch
from .engines import ALL_ENGINES, DEFAULT_ENGINES, Result
from .engines.base import RequestSpec
from .engines.duckduckgo import DuckDuckGo
from .engines.startpage import Startpage
from .engines.presearch import Presearch


async def _fetch_engine(
    engine,
    query: str,
    max_results: int,
    timeout: int,
    proxy: str | None,
    context: FetchContext,
) -> tuple[str, list[Result], str | None]:
    """Fetch results from a single engine. Returns (engine_name, results, error)."""
    try:
        spec = engine.build_request(query, max_results)

        # Multi-step engines (DDG, Startpage, Presearch)
        if isinstance(spec, list):
            text = await _fetch_multistep(engine, spec, timeout, proxy, context)
        else:
            text = await _do_fetch(engine, spec, timeout, proxy, context)

        results = engine.parse_response(text)
        return engine.name, results[:max_results], None

    except Exception as e:
        return engine.name, [], str(e)


async def _do_fetch(
    engine,
    spec: RequestSpec,
    timeout: int,
    proxy: str | None,
    context: FetchContext,
) -> str:
    return await fetch(
        spec.url,
        method=spec.method,
        params=spec.params or None,
        data=spec.data or None,
        headers=spec.headers or None,
        cookies=spec.cookies or None,
        timeout=timeout,
        proxy=proxy,
        context=context,
        profile_key=engine.name,
    )


async def _fetch_multistep(
    engine,
    specs: list[RequestSpec],
    timeout: int,
    proxy: str | None,
    context: FetchContext,
) -> str:
    if isinstance(engine, DuckDuckGo):
        # Step 1: just POST directly, DDG HTML endpoint works without vqd for basic queries
        return await _do_fetch(engine, specs[1], timeout, proxy, context)

    elif isinstance(engine, Startpage):
        # Step 1: Get sc token
        homepage = await _do_fetch(engine, specs[0], timeout, proxy, context)
        sc = Startpage.extract_sc_token(homepage)
        if sc:
            specs[1].data["sc"] = sc
        # Step 2: Search
        return await _do_fetch(engine, specs[1], timeout, proxy, context)

    elif isinstance(engine, Presearch):
        # Step 1: Get search ID
        init_html = await _do_fetch(engine, specs[0], timeout, proxy, context)
        search_id = Presearch.extract_search_id(init_html)
        if not search_id:
            raise ValueError("Could not extract Presearch searchId")
        # Step 2: Fetch results
        specs[1].params["id"] = search_id
        return await _do_fetch(engine, specs[1], timeout, proxy, context)

    else:
        # Fallback: just fetch last spec
        return await _do_fetch(engine, specs[-1], timeout, proxy, context)


async def search(
    query: str,
    engine_names: list[str] | None = None,
    max_results: int = 10,
    timeout: int = 10,
    proxy: str | None = None,
) -> dict:
    """Search selected engines in parallel and return merged results."""
    engines_to_use = {}
    if engine_names:
        for name in engine_names:
            if name in ALL_ENGINES:
                engines_to_use[name] = ALL_ENGINES[name]
    else:
        engines_to_use = DEFAULT_ENGINES

    succeeded = []
    failed = []
    result_sets: list[list[Result]] = []

    async with AsyncSession() as session:
        # Engine URLs are fixed by code, not user supplied. Keep body caps,
        # challenge detection, status handling, and stable profiles here; reserve
        # DNS SSRF checks for future user-supplied URL fetches so local fake-ip
        # DNS/proxy setups do not block normal search engines.
        context = FetchContext(session=session, validate_urls=False)
        tasks = [
            _fetch_engine(engine, query, max_results, timeout, proxy, context)
            for engine in engines_to_use.values()
        ]
        outcomes = await asyncio.gather(*tasks)

    for engine_name, results, error in outcomes:
        if error:
            failed.append([engine_name, error])
        else:
            succeeded.append(engine_name)
            result_sets.append(results)

    deduped = _merge_ranked_results(result_sets)

    return {
        "query": query,
        "number_of_results": len(deduped),
        "results": [r.as_dict() for r in deduped],
        "suggestions": [],
        "unresponsive_engines": failed,
    }


def _merge_ranked_results(result_sets: list[list[Result]]) -> list[Result]:
    """Merge engine result sets by rank so one engine cannot dominate the top."""
    seen_urls: set[str] = set()
    deduped: list[Result] = []
    max_len = max((len(results) for results in result_sets), default=0)
    for index in range(max_len):
        for results in result_sets:
            if index >= len(results):
                continue
            result = results[index]
            normalized = result.url.rstrip("/").lower()
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            deduped.append(result)
    return deduped
