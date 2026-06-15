# webfetch 需求定义与验收说明

## 需求范围

`webcli-lite` 面向本地个人 Agent 的按需网页搜索和读取场景。产品入口收缩为一个命名空间：

- `webcli-lite serper`：搜索 URL。
- `webcli-lite fetch`：把单个 URL 转换成 Markdown，除非显式指定 HTML、text 或 JSON。
- `webcli-lite map`：提取链接，默认返回 `content` 和 `directory`。

本 PR 覆盖：

- 新增 `webcli-lite` CLI，包含 `serper`、`fetch`、`map` 子命令。
- 只安装 `webcli-lite` 命令；旧 `webserp` / `webfetch` 命令不再保留。
- 新增 Python API：`webserp.webfetch.webfetch(url)` 和纯离线抽取 API：`webserp.webfetch.extract(html, url)`。
- 复用现有安全请求层：HTTP(S) URL 校验、私网/本地地址拦截、逐跳 redirect 校验、响应体大小上限、challenge 页面识别。
- `fetch` 默认输出 Markdown，不混入 links；`map` 单独输出 links JSON。
- `serper` 默认只跑 `bing_cn,brave`，每个引擎 5 条结果。
- 所有 `webcli-lite` 子命令支持 stdout 管道和 `-o/--output` 落盘，默认不覆盖已有文件。
- `webcli-lite` 失败路径输出 JSON 到 stderr。
- 覆盖英文、中文、代码教程、复杂表格、SPA 数据岛、目录链接、旧式 layout table 的离线金标测试。

本 PR 不覆盖：

- 不做浏览器渲染。
- 不绕过验证码、安全验证或反爬挑战。
- 不引入代理池。
- 不面向批量爬取或服务端高并发 API。
- 不把 Trafilatura、Readability 等库作为主抽取路径。

## 方案

抽取流程分为四层：

1. 安全获取：`fetch_response()` 返回正文、HTTP 状态、最终 URL 和响应头，保持原 `fetch()` 返回字符串的兼容行为。
2. 候选生成：生成 `semantic`、`scored`、`structural`、`body_fallback`、`data_island` 候选。
3. 候选仲裁：按文本字符数、CJK 字符数、结构分、链接密度、Link Mass、噪声短语、标题匹配度综合评分。
4. Markdown 输出：保留标题、段落、链接、图片、代码块、列表、引用和数据表；对 layout table 输出块级 Markdown，避免伪造数据表。

链接拓扑会把页面链接分类为：

- `content`：正文候选中实际出现的链接。
- `directory`：目录型链接集合，适合 Agent 后续探索。
- `navigation`：导航、页眉、页脚、面包屑等链接。
- `noise`：登录、注册、分享、广告、隐私政策等噪声链接。

## 输出结构

`webcli-lite fetch --json` 输出精简 JSON，不默认包含 links：

```json
{
  "url": "https://example.com/start",
  "final_url": "https://example.com/final",
  "status": 200,
  "title": "Page title",
  "description": "Page description",
  "markdown": "# Page title\n\nMain content...",
  "text": null,
  "html": null,
  "metadata": {
    "title": "Page title",
    "description": "Page description",
    "author": "",
    "published_date": "",
    "language": "en",
    "site_name": "",
    "image": "",
    "favicon": ""
  },
  "meta": {
    "strategy": "semantic",
    "warnings": [],
    "truncated": {"markdown": false, "text": false, "html": false}
  }
}
```

## 测试策略

核心测试全部离线，不依赖真实网站：

- `tests/fixtures/webfetch/*.html`：覆盖代表性页面结构。
- `tests/fixtures/webfetch/*.expected.json`：Codex 标记的金标，包含 facts、must_exclude、结构计数、链接类型、候选 winner 期望。
- `tests/test_webfetch.py`：逐 fixture 校验 Markdown 事实包含、噪声排除、元数据、候选策略、CJK、表格、代码块、图片、结构化数据和链接拓扑。
- 额外 adversarial tests 覆盖 unsafe URL scheme、正常短文被数据岛污染、layout table 导航列混入、Markdown label escaping 和代码 fence escaping。
- `tests/test_webcli_lite.py`：覆盖统一 CLI 的默认 `serper` 引擎、fallback、`fetch` 默认 Markdown、`fetch --json` 不含 links、`map` 默认 link types、输出文件保护和 JSON 错误协议。
- `tests/test_client.py`：校验 `fetch_response()` 在保持 `fetch()` 兼容的同时返回 final URL、status、headers。

真实网络只适合作低频 smoke，不作为抽取质量判据，避免触发搜索引擎或站点限制。

## 验收标准

- `PYTHONPATH=src python -m unittest discover -s tests` 全量通过。
- `python -m compileall -q src` 通过。
- `fetch()` 字符串返回兼容不破坏。
- `webcli-lite serper` 默认 `bing_cn,brave`，每个引擎 5 条。
- `webcli-lite fetch` 默认输出 Markdown；只有 `--format html` 输出 HTML。
- `webcli-lite map` 默认只返回 `content,directory` links，`--all` 才返回全部。
- `-o/--output` 支持本地落盘，默认不覆盖已有文件。
- 离线金标覆盖英文、中文、代码、表格、SPA 数据岛、目录链接、旧式 layout table。
- challenge、私网 URL、超大响应体等安全约束仍由现有 fetch 层统一处理。
