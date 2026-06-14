# webserp

Metasearch CLI — query multiple search engines in parallel with browser impersonation.

Like `grep` for the web. Searches Google, DuckDuckGo, Brave, Yahoo, Mojeek, Startpage, Presearch, Bing China, Baidu, Sogou, Sogou Weixin, and optionally Sogou Zhihu, deduplicates results, and returns clean JSON.

## Why webserp?

Most search scraping tools get rate-limited and blocked because they use standard HTTP libraries. webserp uses [curl_cffi](https://github.com/lexiforest/curl_cffi) to send browser-like requests with Chrome TLS/JA3 fingerprints.

- **12 search engines** available
- **Browser-like requests** via curl_cffi with stable per-search impersonation profiles
- **Local-agent safety checks** for HTTP(S) URLs, private/internal destinations, response size, and challenge pages
- **Fault tolerant** — if one engine fails, others still return results
- **SearXNG-compatible JSON** output format
- **No API keys** — scrapes search engine HTML directly
- **Fast** — parallel async requests, typically completes in 2-5s

## Install

```bash
pip install webserp
```

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

# Use a proxy
webserp "query" --proxy "socks5://127.0.0.1:1080"
```

## Output Format

JSON output matching SearXNG's format:

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

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-e, --engines` | Comma-separated engine list | default engine set |
| `-n, --max-results` | Max results per engine | 10 |
| `--timeout` | Per-engine timeout (seconds) | 10 |
| `--proxy` | Proxy URL for all requests | none |
| `--verbose` | Show engine status in stderr | false |
| `--version` | Print version | |

## Engines

google, duckduckgo, brave, yahoo, mojeek, startpage, presearch, bing_cn, baidu, sogou, sogou_weixin, sogou_zhihu

Default engine set: all engines above except `sogou_zhihu`. Use `--engines sogou_zhihu` to run the Zhihu site search explicitly.

## 中文搜索

中文搜索建议优先使用：

```bash
webserp "新能源汽车 新闻" --engines bing_cn,baidu,sogou,sogou_weixin --max-results 3
```

- `bing_cn`：中文 Bing 网页搜索，结构稳定，URL 通常直出。
- `baidu`：百度网页搜索，优先读取结果容器中的真实目标 URL。
- `sogou`：搜狗普通网页搜索，部分结果 URL 是搜狗跳转链接。
- `sogou_weixin`：搜狗微信文章搜索，用于微信公众号文章结果。
- `sogou_zhihu`：搜狗知乎站内搜索，可选使用；它更容易触发搜狗反爬页面，不建议放入默认组合。

webserp 会识别常见验证码、安全验证、`antispider`、异常访问等页面，并把对应引擎放入 `unresponsive_engines`。它不会识别验证码、绕过反爬、使用代理池或批量抓取正文。

## 请求安全

webserp 面向本地 Agent 按需搜索场景，默认采用温和请求策略：

- 只允许请求 `http` / `https` URL。
- 安全模块支持 best-effort DNS 校验，可用于后续用户 URL 抓取能力，阻止 localhost、内网地址、链路本地地址、保留地址、组播地址等内部目标。
- 用户 URL 安全模式会逐跳校验重定向目标，避免公网 URL 跳转到内部地址。
- 内置搜索引擎 URL 是代码固定的公网域名，不是用户输入；搜索路径会跳过 DNS SSRF 校验，以兼容本地 fake-ip DNS/代理环境。
- 响应体默认限制为 5MB，避免异常响应或压缩炸弹拖垮进程。
- 一次 `search()` 内每个 engine 使用稳定的浏览器 impersonation profile，避免单次任务内反复抖动指纹。
- `429` 不重试；`5xx` 等临时服务端错误最多重试一次；验证码/安全验证/challenge 页面不重试。
- 常见 challenge、consent wall、JS-only 空壳页会进入 `unresponsive_engines`，不会伪装成成功结果。

DNS 校验是面向用户 URL 抓取的本地 Agent 安全防线，不是完整 DNS pinning；HTTP 传输层仍可能自行解析域名。webserp 不绕过验证码、不使用代理池、不做浏览器渲染。

## For OpenClaw and AI agents

**Built for AI agents.** Tools like [OpenClaw](https://github.com/openclaw/openclaw) and other AI agents need reliable web search without API keys. webserp uses [curl_cffi](https://github.com/lexiforest/curl_cffi) to send browser-like requests and queries multiple engines in parallel, so if one engine fails others can still return results.

### Why a CLI tool instead of a Python library?

A CLI tool keeps web search out of the agent's process. The agent calls `webserp`, gets JSON back, and the process exits — no persistent HTTP sessions, no in-process state, no import overhead. Agents that never need web search pay zero cost.

### Example agent use cases

- **Research** — searching the web for current information before answering user questions
- **Fact checking** — verifying claims against multiple search engines
- **Link discovery** — finding relevant URLs, documentation, or source code
- **News monitoring** — checking for recent events or updates on a topic

```bash
# Agent searching for current information
webserp "latest python 3.14 release date" --max-results 5

# Searching multiple engines for diverse results
webserp "docker networking troubleshooting" --engines brave,yahoo,presearch --max-results 3

# Quick search with verbose to see which engines responded
webserp "CVE-2024 critical vulnerabilities" --verbose --max-results 5
```


## License

MIT
