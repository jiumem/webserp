---
name: webserp
description: Local-agent web CLI. Use `webcli-lite serper` to search current web results, `webcli-lite fetch` to read one URL as Markdown, and `webcli-lite map` to extract follow-up links. Default search uses only Bing China and Brave, 5 results each. No API keys needed. Install with `pip install webserp`.
---

# webcli-lite

Use `webcli-lite` for local-agent web search, page reading, and link mapping.

## Default Workflow

```bash
# 1. Search. Default engines: bing_cn,brave. Default max results: 5 each.
webcli-lite serper "query"

# 2. Fetch one selected result as Markdown.
webcli-lite fetch "URL_FROM_RESULT"

# 3. Optionally map follow-up links. Default link types: content,directory.
webcli-lite map "URL_FROM_RESULT"
```

Do not default to broad engine sets. Use additional engines only when the first pass is insufficient.

## Search

```bash
webcli-lite serper "query"
webcli-lite serper "query" --engines bing_cn,brave
webcli-lite serper "query" --profile cn-deep
webcli-lite serper "query" --fallback yahoo,presearch
```

Default `serper` behavior:

- Engines: `bing_cn,brave`
- Results: `2 x 5 = 10` maximum before dedupe
- Output: JSON on stdout
- Errors: JSON on stderr

Available profiles:

- `agent`: `bing_cn,brave`
- `zh`: `bing_cn,brave`
- `en`: `brave,bing_cn`
- `mixed`: `bing_cn,brave,baidu,sogou,sogou_weixin,yahoo,presearch`
- `cn-deep`: `bing_cn,baidu,sogou,sogou_weixin`
- `all`: all engines

Avoid these in default Agent use unless explicitly requested: `google`, `duckduckgo`, `startpage`, `mojeek`, `sogou_zhihu`.

## Fetch

```bash
# Markdown to stdout
webcli-lite fetch "https://example.com/article"

# Markdown to local document
webcli-lite fetch "https://example.com/article" -o article.md

# Original HTML
webcli-lite fetch "https://example.com/article" --format html

# Structured wrapper without links by default
webcli-lite fetch "https://example.com/article" --json

# Offline HTML, no network fetch
webcli-lite fetch --html-file page.html --base-url "https://example.com/page"
cat page.html | webcli-lite fetch --stdin --base-url "https://example.com/page"
```

`fetch` is for readable content. Do not expect links in fetch output; use `map`.

## Map

```bash
# content + directory links
webcli-lite map "https://example.com/article"

# one class of links
webcli-lite map "https://example.com/article" --type directory

# all links, including navigation/noise
webcli-lite map "https://example.com/article" --all
```

Link types:

- `content`: links inside extracted content
- `directory`: useful follow-up/resource/index links
- `navigation`: header/footer/nav links
- `noise`: login/share/privacy/ad-like links

## Files and Pipes

```bash
webcli-lite serper "query" > search.json
webcli-lite fetch "URL" > article.md
webcli-lite map "URL" > links.json

webcli-lite serper "query" -o search.json
webcli-lite fetch "URL" -o article.md
webcli-lite map "URL" -o links.json
```

`-o/--output` refuses to overwrite existing files unless `--force` is set.

## Safety

- No API keys.
- No CAPTCHA solving.
- No proxy pools.
- No browser rendering.
- `fetch` and `map` allow only HTTP(S) URLs and block localhost/private/internal targets by default.
- Do not retry challenge pages. Pick another search result instead.
