---
name: webserp
description: Web search across 12 available engines with browser impersonation, including Chinese sources such as Bing China, Baidu, Sogou web, Sogou Weixin, and optional Sogou Zhihu. Use when the agent needs current information from the web — news, documentation, recent events, or anything beyond training data. Returns structured JSON (SearXNG-compatible) with title, URL, and content. Install with `pip install webserp`. No API keys needed.
---

# webserp

Metasearch CLI — queries Google, DuckDuckGo, Brave, Yahoo, Mojeek, Startpage, Presearch, Bing China, Baidu, Sogou, Sogou Weixin, and optional Sogou Zhihu. Uses curl_cffi for browser impersonation. Results like a browser, speed like an API.

## When to use webserp

1. You need current/recent information not in your training data
2. You need to verify facts or find sources
3. You need to discover URLs, documentation, or code repositories
4. The user asks about recent events, releases, or news

## Install

```bash
pip install webserp
```

No API keys, no configuration. Just install and search.

## Usage

```bash
# Search default engines
webserp "how to deploy docker containers"

# Search specific engines
webserp "python async tutorial" --engines brave,yahoo,presearch

# Search Chinese engines
webserp "新能源汽车 新闻" --engines bing_cn,baidu,sogou,sogou_weixin

# Limit results per engine
webserp "rust vs go" --max-results 5

# Show which engines succeeded/failed
webserp "test query" --verbose

# Set per-engine timeout
webserp "query" --timeout 15

# Use a proxy
webserp "query" --proxy "socks5://127.0.0.1:1080"
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-e, --engines` | Comma-separated engine list | default engine set |
| `-n, --max-results` | Max results per engine | 10 |
| `--timeout` | Per-engine timeout (seconds) | 10 |
| `--proxy` | Proxy URL for all requests | none |
| `--verbose` | Show engine status in stderr | false |

## Output format

JSON to stdout (SearXNG-compatible):

```json
{
  "query": "deployment issue",
  "number_of_results": 42,
  "results": [
    {
      "title": "How to fix Docker deployment issues",
      "url": "https://example.com/docker-fix",
      "content": "Common Docker deployment problems and solutions...",
      "engine": "google"
    }
  ],
  "suggestions": [],
  "unresponsive_engines": []
}
```

Parse with `jq` or any JSON parser. The `results` array contains `title`, `url`, `content`, and `engine` for each result. `unresponsive_engines` lists any engines that failed with the error reason.

## Recommended engine sets

Recommended default set for agent use:

```bash
webserp "query" --engines brave,yahoo,presearch,bing_cn,baidu,sogou,sogou_weixin --max-results 3
```

For English or general web search:

```bash
webserp "query" --engines brave,yahoo,presearch --max-results 3
```

For Chinese search:

```bash
webserp "query" --engines bing_cn,baidu,sogou,sogou_weixin --max-results 3
```

Avoid using these in the agent default set unless explicitly requested: `google`, `duckduckgo`, `startpage`, `mojeek`, `sogou_zhihu`. In local testing, Google/DuckDuckGo/Startpage often returned empty parsed results or verification pages, Mojeek timed out repeatedly, and Sogou Zhihu is more likely to return Sogou antispider pages.

## Chinese search

Recommended Chinese engine set:

```bash
webserp "新能源汽车 新闻" --engines bing_cn,baidu,sogou,sogou_weixin --max-results 3
```

- `bing_cn`: Bing China web search.
- `baidu`: Baidu web search, preferring original target URLs when Baidu exposes them.
- `sogou`: Sogou web search.
- `sogou_weixin`: Sogou Weixin article search.
- `sogou_zhihu`: Sogou Zhihu site search. Use explicitly; it is more likely to return Sogou antispider pages.

Anti-bot or verification pages are reported through `unresponsive_engines`. webserp does not solve CAPTCHAs, bypass verification, use proxy pools, or crawl linked page bodies.

## Tips

- Use `--max-results 5` to keep output concise when you just need a few links
- Use `--engines brave,yahoo,presearch` to target tested general-purpose engines
- Use `--verbose` (writes to stderr) to see which engines responded — the JSON on stdout is unaffected
- Results are deduplicated by URL across engines — you won't get the same link twice
