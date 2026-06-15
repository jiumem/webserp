---
name: webserp
description: Use for web search, URL-to-Markdown reading, and page link mapping with `webcli-lite`.
---

# webcli-lite

使用 `webcli-lite` 做本地 Agent 的按需 Web 访问。目标是少请求、少上下文、可复查：搜索只找候选，`fetch` 只读选中的页面，`map` 只在需要继续导航时使用。

## 默认流程

```bash
webcli-lite serper "query"
webcli-lite fetch "URL_FROM_RESULT"
webcli-lite map "URL_FROM_RESULT"
```

默认只搜索一次，先看搜索结果，再 `fetch` 1-3 个最可能有用的 URL。不要批量 `fetch` 全部搜索结果，也不要为了判断页面质量反复访问搜索接口。

## Search

默认搜索已经是 Agent 用法的安全路径，适合中文、英文和中英混合查询：

- engines: `bing_cn,brave`
- max results: 每个引擎 5 条
- fallback: 默认结果不足 10 条时补 `yahoo,presearch`
- merge: 多引擎结果按 rank 交错输出
- output: JSON stdout
- errors: JSON stderr

先用用户原始语言搜索，不要先翻译或改写得过宽：

```bash
webcli-lite serper "query"
```

需要中文结果更深时：

```bash
webcli-lite serper "query" --profile cn-deep
```

建议英文搜索的场景：

- IT 技术文档、开源项目、SDK/API、错误码、issue、release notes。
- 国际论文、期刊、arXiv、PubMed、IEEE、ACM、Springer、Nature、Science 等资料。
- 国际标准、RFC、W3C、IETF、ISO/IEC、CNCF、Kubernetes、Python/Node/Rust 等官方文档。
- 海外公司、英文产品、英文法规政策、国际新闻源。
- 中文搜索结果明显是转载、摘要、过时内容，而问题需要原始出处。

英文搜索时保留专有名词、错误码、论文题名、库名和版本号，不要翻译它们：

```bash
webcli-lite serper "pydantic v2 model_validator examples" --profile en
webcli-lite serper "\"Attention Is All You Need\" paper PDF" --profile en
webcli-lite serper "site:docs.python.org asyncio TaskGroup" --profile en
```

中英文都可能有价值时，先跑用户原始语言；结果不足时再换语言重查一次。不要同时对同一问题连续跑多组宽泛 query。

可用 profile：

- `agent`: `bing_cn,brave`，默认 Agent 搜索。
- `zh`: `bing_cn,brave`，中文/中英混合默认路径。
- `en`: `brave,bing_cn`，英文优先但保留中文 Bing 兜底。
- `cn-deep`: `bing_cn,baidu,sogou,sogou_weixin`，中文深搜、微信公众号内容。
- `mixed`: `bing_cn,brave,baidu,sogou,sogou_weixin,yahoo,presearch`，需要更广覆盖时使用。
- `all`: 全部引擎，只用于明确的诊断或广泛 sweep。

可用 engines：

- `bing_cn`: 默认中文/混合搜索主力，结构相对稳定。
- `brave`: 默认英文/国际网页搜索主力。
- `baidu`: 中文网页补充，适合中文站点、政策、百科、论坛等。
- `sogou`: 中文网页补充。
- `sogou_weixin`: 微信公众号内容。
- `sogou_zhihu`: 知乎内容，但更容易触发搜狗反爬，非默认。
- `yahoo`, `presearch`: 默认不足时的低频 fallback。
- `google`, `duckduckgo`, `startpage`, `mojeek`: 非默认英文/国际补充，只在明确需要时使用。

默认 fallback 只在结果不足时触发。其他扩展引擎只在默认结果不足、用户要求更广覆盖、或需要特定中文来源时使用：

```bash
webcli-lite serper "query" --fallback yahoo,presearch
webcli-lite serper "query" --profile cn-deep
webcli-lite serper "query" --engines brave,yahoo,presearch
webcli-lite serper "query" --engines sogou_weixin
```

不要默认使用 `--profile all`。`google`、`duckduckgo`、`startpage`、`mojeek`、`sogou_zhihu` 只在明确需要时使用。搜索结果里如果某个引擎进入 `unresponsive_engines`，不要立即重试同一引擎；先使用其他结果。

## Fetch

`fetch` 默认输出 Markdown，适合直接读入上下文：

```bash
webcli-lite fetch "https://example.com/article"
webcli-lite fetch "https://example.com/article" -o article.md
```

只有需要原始 HTML 时才用：

```bash
webcli-lite fetch "https://example.com/article" --format html
```

`fetch --json` 返回内容和元数据，但默认不包含 links；要 links 使用 `map`：

```bash
webcli-lite fetch "https://example.com/article" --json
```

如果 Markdown 被截断，针对同一个已选 URL 重试：

```bash
webcli-lite fetch "https://example.com/article" --max-markdown-chars 0
```

不要因为单页截断就扩大搜索范围。

`fetch` 默认使用本地 Agent DNS policy，可兼容本机代理的 fake-ip DNS。只有明确需要服务端式严格 DNS 校验时才加：

```bash
webcli-lite fetch "https://example.com/article" --dns-policy strict
```

离线 HTML 只用于本地已有页面，`--base-url` 必须是原始公共 HTTP(S) 页面 URL，不能用 localhost、私网 IP 或 `file://`：

```bash
webcli-lite fetch --html-file page.html --base-url "https://example.com/page"
cat page.html | webcli-lite fetch --stdin --base-url "https://example.com/page"
```

## Map

`map` 用来发现当前页面上的后续链接，不负责正文读取。默认只返回 `content,directory` links，适合小页面直接进上下文。

### 小页面

当前页面链接不多时，直接用默认 JSON：

```bash
webcli-lite map "https://example.com/article"
webcli-lite map "https://example.com/article" --type directory
webcli-lite map "https://example.com/article" --all
```

link type 含义：

- `content`: 正文内部链接
- `directory`: 目录、资源、索引、后续阅读链接
- `navigation`: 页头、页脚、侧栏、面包屑等导航链接
- `noise`: 登录、注册、分享、隐私、广告类链接

优先看 `directory`。如果目录结果太少，再看 `content`。只有诊断页面结构或确实需要全量索引时才用 `--all`。

### 大文档站

文档站、SDK 文档、产品手册、API reference 通常会产生大量 links。不要把完整 link set 输出到会话上下文。把索引写入系统临时目录，再用 `rg` 基于 link text 筛选。

推荐流程：

```bash
MAPDIR="$(mktemp -d -t webcli-lite-map.XXXXXX)"
webcli-lite map "https://docs.example.com/" \
  --type directory \
  --format tsv \
  --fields id,type,text,href,path \
  --max-links 0 \
  -o "$MAPDIR/links.tsv"
```

按意图筛选 link text：

```bash
rg -i "install|quickstart|getting started" "$MAPDIR/links.tsv"
rg -i "auth|token|api key|oauth" "$MAPDIR/links.tsv"
rg -i "python|sdk|client|example" "$MAPDIR/links.tsv"
rg -i "reference|api|endpoint|schema" "$MAPDIR/links.tsv"
```

只把 `rg` 命中的少量行带回上下文。选定后再 `fetch` 1-3 个 URL：

```bash
webcli-lite fetch "https://docs.example.com/quickstart"
```

如果需要从 TSV 里按 ID 取 URL：

```bash
awk -F '\t' '$1=="12"{print $4}' "$MAPDIR/links.tsv"
```

如果只想看 ID 和文本，减少 URL 噪声：

```bash
cut -f1,3 "$MAPDIR/links.tsv" | rg -i "auth|token|api key"
```

### Map 输出格式

默认 JSON 适合小结果：

```bash
webcli-lite map "URL"
```

TSV 最适合 `rg`：

```bash
webcli-lite map "URL" \
  --format tsv \
  --fields id,type,text,href,path \
  -o "$MAPDIR/links.tsv"
```

JSONL 适合流式工具：

```bash
webcli-lite map "URL" \
  --format jsonl \
  --fields id,text,href,domain,path \
  -o "$MAPDIR/links.jsonl"
```

可选字段：

- `id`: 当前输出内的稳定序号，用于回查 URL
- `type`: `content` / `directory` / `navigation` / `noise`
- `text`: 页面上的链接可见文本，优先用它做筛选
- `href`: 规范化后的绝对 URL
- `is_external`: 是否外链
- `domain`: URL host
- `path`: URL path 和 query

### Map 决策规则

- 小页面直接用默认 JSON。
- 大文档站用 `--format tsv --fields id,type,text,href,path --max-links 0 -o "$MAPDIR/links.tsv"`。
- 默认优先 `--type directory`；结果不足时再试 `--type content` 或 `--all`。
- 不要批量 `fetch` map 得到的全部链接。
- 不要把大 TSV/JSONL 全文贴回上下文；只带回命中行和少量候选 URL。
- 中间索引默认放 `mktemp -d` 创建的系统临时目录；只有用户要求保留时才写入项目目录。

## 文件输出

小结果可以 stdout；用户要留档时用 `-o`：

```bash
webcli-lite serper "query" -o search.json
webcli-lite fetch "URL" -o article.md
webcli-lite map "URL" -o links.json
```

`-o/--output` 默认不覆盖已有文件；确需覆盖时加 `--force`。

## 安全边界

- 不做 CAPTCHA 识别或绕过。
- 不使用代理池。
- 不做浏览器渲染。
- 不做批量爬取。
- `fetch` 和 `map` 只接受 HTTP(S) URL，并阻断 localhost、私网和内部地址。
- `fetch` / `map` 默认允许 hostname 解析到 `198.18.0.0/15` fake-ip；IP literal、localhost 和真实私网地址仍会被阻断。
- challenge / antispider / safety check 页面视为失败；换搜索结果，不要重试刷请求。
