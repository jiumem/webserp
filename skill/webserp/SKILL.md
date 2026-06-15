---
name: webserp
description: Use for web search, URL-to-Markdown reading, and page link mapping with `webcli-lite`.
---

# webcli-lite

Use `webcli-lite` for local-agent web search, page reading, and link mapping. Keep request volume low and keep large intermediate link sets out of conversation context.

## Default Workflow

```bash
# 1. Search. Default engines: bing_cn,brave. Default max results: 5 each.
webcli-lite serper "query"

# 2. Fetch 1-3 selected results as Markdown.
webcli-lite fetch "URL_FROM_RESULT"

# 3. Optionally map follow-up links. Default link types: content,directory.
webcli-lite map "URL_FROM_RESULT"
```

Do not default to broad engine sets, `--profile all`, or bulk fetching. Use one default search pass first, inspect results, then fetch only the most likely useful URLs. Use additional engines only when the first pass is insufficient or the user explicitly asks for broad coverage.

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
- `all`: all engines; use only for explicit diagnostic or broad sweep requests

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

`fetch` is for readable content. Do not expect links in fetch output; use `map`. If Markdown is truncated, retry the same selected URL with a larger `--max-markdown-chars` value or `--max-markdown-chars 0`; do not broaden search just because a selected page was truncated.

For offline HTML, `--base-url` must be the original public HTTP(S) page URL. Do not use localhost, private IPs, or `file://` URLs.

## Map

```bash
# content + directory links
webcli-lite map "https://example.com/article"

# one class of links
webcli-lite map "https://example.com/article" --type directory

# all links, including navigation/noise
webcli-lite map "https://example.com/article" --all

# large documentation pages: write a grep-friendly local index
TMPDIR="$(mktemp -d -t webcli-lite-map.XXXXXX)"
webcli-lite map "https://docs.example.com/" \
  --type directory \
  --format tsv \
  --fields id,type,text,href,path \
  --max-links 0 \
  -o "$TMPDIR/links.tsv"
rg -i "install|quickstart|auth|api key" "$TMPDIR/links.tsv"
```

Link types:

- `content`: links inside extracted content
- `directory`: useful follow-up/resource/index links
- `navigation`: header/footer/nav links
- `noise`: login/share/privacy/ad-like links

For large document-style sites, do not return all links to the conversation. Write TSV or JSONL to a system temporary directory with `mktemp -d`, use `rg`, `cut`, or `awk` to select a few candidates by link text, then `fetch` only the chosen URLs. Use project directories only when the user explicitly asks to keep the link index.

Useful map formats:

- `--format json`: default envelope for small results.
- `--format tsv`: one link per line; best for `rg`.
- `--format jsonl`: one JSON object per link; useful for streaming tools.
- `--fields id,type,text,href,is_external,domain,path`: choose columns for TSV/JSONL or enriched JSON links.

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
- Do not bulk fetch all search results or all mapped links.
