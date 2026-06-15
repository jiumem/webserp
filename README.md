# webcli-lite

Local-agent web CLI — search, fetch readable Markdown, and map links.

`webcli-lite` exposes three focused subcommands:

- `serper`: search the web and return compact JSON results.
- `fetch`: fetch one page and return Markdown by default.
- `map`: extract page links, defaulting to `content` and `directory` links.

The package installs a single command: `webcli-lite`.

## Why webcli-lite?

- **Agent-safe defaults** — default search uses only `bing_cn` and `brave`, 5 results each.
- **Clear command boundaries** — search, content fetch, and link mapping are separate operations.
- **Browser-like requests** via [curl_cffi](https://github.com/lexiforest/curl_cffi) with stable per-search impersonation profiles.
- **Local-agent safety checks** for HTTP(S) URLs, private/internal destinations, response size, redirects, and challenge pages.
- **No API keys** — scrapes search engine HTML directly.
- **Pipe-friendly output** — stdout by default, `-o/--output` for local documents.

## Install

```bash
pip install webserp
```

## Usage

```bash
# Search default engines: bing_cn + brave, 5 results each
webcli-lite serper "how to deploy docker containers"

# Search specific engines
webcli-lite serper "python async tutorial" --engines brave,yahoo,presearch

# Fetch one page as Markdown
webcli-lite fetch "https://example.com/article"

# Fetch original HTML
webcli-lite fetch "https://example.com/article" --format html

# Extract follow-up links; default returns content + directory links
webcli-lite map "https://example.com/article"

# Extract all links, including navigation and noise
webcli-lite map "https://example.com/article" --all

# Write a large documentation link index for local grep
TMPDIR="$(mktemp -d -t webcli-lite-map.XXXXXX)"
webcli-lite map "https://docs.example.com/" --type directory --format tsv --fields id,type,text,href,path --max-links 0 -o "$TMPDIR/links.tsv"
rg -i "install|quickstart|auth" "$TMPDIR/links.tsv"
```

## Output to Files

Every subcommand writes to stdout by default, so shell redirection works:

```bash
webcli-lite serper "新能源汽车 出海" > search.json
webcli-lite fetch "https://example.com/article" > article.md
webcli-lite map "https://example.com/article" > links.json
```

You can also use `-o/--output`. Existing files are not overwritten unless `--force` is set. For large link maps, prefer a system temporary directory so intermediate indexes do not pollute the project:

```bash
webcli-lite serper "腾讯 混元 最新进展" -o research/search.json
webcli-lite fetch "https://example.com/article" -o research/article.md
webcli-lite map "https://example.com/article" --type directory -o research/links.json

TMPDIR="$(mktemp -d -t webcli-lite-map.XXXXXX)"
webcli-lite map "https://docs.example.com/" --format tsv --fields id,type,text,href,path --max-links 0 -o "$TMPDIR/links.tsv"
```

## Output Format

`serper` writes JSON:

```json
{
  "query": "deployment issue",
  "number_of_results": 10,
  "results": [
    {
      "title": "How to fix Docker deployment issues",
      "url": "https://example.com/docker-fix",
      "content": "Common Docker deployment problems and solutions...",
      "engine": "bing_cn"
    }
  ],
  "suggestions": [],
  "unresponsive_engines": []
}
```

`fetch` writes Markdown by default:

```md
# Page title

Main content...
```

`fetch --json` wraps Markdown and metadata without links by default. Use `map` for links.

`map` writes JSON:

```json
{
  "url": "https://example.com/article",
  "final_url": "https://example.com/article",
  "status": 200,
  "title": "Page title",
  "links": [
    {"text": "Related", "href": "https://example.com/related", "type": "directory", "is_external": false}
  ],
  "meta": {"link_types": ["content", "directory"], "truncated": {"links": false}}
}
```

For large documentation pages, `map` can write one link per line for local filtering:

```bash
webcli-lite map "https://docs.example.com/" \
  --type directory \
  --format tsv \
  --fields id,type,text,href,path \
  --max-links 0 \
  -o "$TMPDIR/links.tsv"

rg -i "install|quickstart|authentication|api key" "$TMPDIR/links.tsv"
```

TSV output is headered and grep-friendly:

```text
id	type	text	href	path
1	directory	Quickstart	https://docs.example.com/quickstart	/quickstart
2	directory	Authentication	https://docs.example.com/auth	/auth
```

`--format jsonl` emits one JSON object per link for streaming tools.

Line-oriented `map` output keeps stdout/file content data-only. If the default `--max-links 50` limit truncates TSV or JSONL output, `webcli-lite` prints a warning to stderr. Use `--max-links 0` for complete local indexes.

All `webcli-lite` errors are JSON on stderr.

## Subcommands

### serper

```bash
webcli-lite serper "query"
webcli-lite serper "query" --engines bing_cn,brave
webcli-lite serper "query" --profile cn-deep
webcli-lite serper "query" --fallback yahoo,presearch
webcli-lite serper --list-engines
webcli-lite serper --list-profiles
```

| Flag | Description | Default |
|------|-------------|---------|
| `-e, --engines` | Comma-separated engine list | `bing_cn,brave` |
| `--profile` | Engine profile | `agent` |
| `--fallback` | Engines used only when results are insufficient | none |
| `-n, --max-results` | Max results per engine | 5 |
| `--timeout` | Per-engine timeout (seconds) | 10 |
| `--proxy` | Proxy URL for all requests | none |
| `--verbose` | Show engine status in stderr | false |

### fetch

```bash
webcli-lite fetch "URL"
webcli-lite fetch "URL" --format html
webcli-lite fetch "URL" --json
webcli-lite fetch --html-file page.html --base-url "https://example.com/page"
cat page.html | webcli-lite fetch --stdin --base-url "https://example.com/page"
```

`fetch` does not include links by default. Use `map` for link extraction.

### map

```bash
webcli-lite map "URL"
webcli-lite map "URL" --type directory
webcli-lite map "URL" --type content,directory
webcli-lite map "URL" --all
webcli-lite map "URL" --format tsv --fields id,type,text,href,path -o links.tsv
webcli-lite map "URL" --format jsonl --fields id,text,href,domain,path -o links.jsonl
```

Default `map` link types: `content,directory`.

`--format` supports `json`, `jsonl`, and `tsv`. `--fields` supports `id,type,text,href,is_external,domain,path`.

## Engines

google, duckduckgo, brave, yahoo, mojeek, startpage, presearch, bing_cn, baidu, sogou, sogou_weixin, sogou_zhihu

`webcli-lite serper` defaults to `bing_cn,brave`. Other engines are available through `--engines`, `--profile`, or `--fallback`. Use `sogou_zhihu` explicitly; it is more likely to return Sogou antispider pages.

## 中文搜索

中文搜索建议优先使用：

```bash
webcli-lite serper "新能源汽车 新闻" --profile cn-deep
```

- `bing_cn`：中文 Bing 网页搜索，结构稳定，URL 通常直出。
- `baidu`：百度网页搜索，优先读取结果容器中的真实目标 URL。
- `sogou`：搜狗普通网页搜索，部分结果 URL 是搜狗跳转链接。
- `sogou_weixin`：搜狗微信文章搜索，用于微信公众号文章结果。
- `sogou_zhihu`：搜狗知乎站内搜索，可选使用；它更容易触发搜狗反爬页面，不建议放入默认组合。

webcli-lite 会识别常见验证码、安全验证、`antispider`、异常访问等页面，并把搜索失败引擎放入 `unresponsive_engines`。它不会识别验证码、绕过反爬、使用代理池或批量抓取正文。

## 推荐 Agent 工作流

```bash
webcli-lite serper "query"
webcli-lite fetch "URL_FROM_RESULT" -o article.md
webcli-lite map "URL_FROM_RESULT" --type directory -o links.json
```

`serper` 负责发现候选 URL，`fetch` 负责读取已选页面正文，`map` 负责后续链接探索。这样可以把搜索引擎请求次数保持在较低水平，也避免为了判断页面质量而反复访问搜索接口。

For document-style sites with many links, do not put the full link set in the conversation. Write a local TSV/JSONL index to a temporary directory, filter by link text with `rg`, and fetch only a few selected URLs:

```bash
TMPDIR="$(mktemp -d -t webcli-lite-map.XXXXXX)"
webcli-lite map "URL_FROM_RESULT" --type directory --format tsv --fields id,type,text,href,path --max-links 0 -o "$TMPDIR/links.tsv"
rg -i "install|quickstart|auth|api key" "$TMPDIR/links.tsv"
```

## 请求安全

webcli-lite 面向本地 Agent 按需搜索场景，默认采用温和请求策略：

- 只允许请求 `http` / `https` URL。
- 安全模块支持 best-effort DNS 校验，可用于后续用户 URL 抓取能力，阻止 localhost、内网地址、链路本地地址、保留地址、组播地址等内部目标。
- 用户 URL 安全模式会逐跳校验重定向目标，避免公网 URL 跳转到内部地址。
- 内置搜索引擎 URL 是代码固定的公网域名，不是用户输入；搜索路径会跳过 DNS SSRF 校验，以兼容本地 fake-ip DNS/代理环境。
- 响应体默认限制为 5MB，避免异常响应或压缩炸弹拖垮进程。
- 一次 `search()` 内每个 engine 使用稳定的浏览器 impersonation profile，避免单次任务内反复抖动指纹。
- `429` 不重试；`5xx` 等临时服务端错误最多重试一次；验证码/安全验证/challenge 页面不重试。
- 常见 challenge、consent wall、JS-only 空壳页会进入 `unresponsive_engines`，不会伪装成成功结果。
- `fetch` 和 `map` 复用同一套安全请求层，并把单页读取结果交给离线正文抽取器转换成 Markdown 或链接 JSON。

DNS 校验是面向用户 URL 抓取的本地 Agent 安全防线，不是完整 DNS pinning；HTTP 传输层仍可能自行解析域名。webcli-lite 不绕过验证码、不使用代理池、不做浏览器渲染。

## For OpenClaw and AI agents

**Built for AI agents.** Tools like [OpenClaw](https://github.com/openclaw/openclaw) and other AI agents need reliable web search without API keys. webcli-lite uses [curl_cffi](https://github.com/lexiforest/curl_cffi) to send browser-like requests and queries selected engines in parallel, so if one engine fails others can still return results.

### Why CLI tools instead of only a Python library?

CLI tools keep web search and page reading out of the agent's process. The agent calls `webcli-lite`, gets stdout back, and the process exits — no persistent HTTP sessions, no in-process state, no import overhead. Agents that never need web access pay zero cost.

### Example agent use cases

- **Research** — searching the web for current information before answering user questions
- **Fact checking** — verifying claims against multiple search engines
- **Link discovery** — finding relevant URLs, documentation, or source code
- **News monitoring** — checking for recent events or updates on a topic

```bash
# Agent searching for current information
webcli-lite serper "latest python 3.14 release date"

# Searching multiple engines for diverse results
webcli-lite serper "docker networking troubleshooting" --engines brave,yahoo,presearch

# Quick search with verbose to see which engines responded
webcli-lite serper "CVE-2024 critical vulnerabilities" --verbose

# Read one selected page as Markdown
webcli-lite fetch "https://example.com/report"
```


## License

MIT
