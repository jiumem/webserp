# Markdown 转换质量真实站点评测

评测日期：2026-06-15

## 目标

验证 `webcli-lite fetch` 在真实中英文网页上的 Markdown 转换可用性，并对影响本地 Agent 阅读质量的问题做闭环优化。

本轮只评测网页读取与正文转 Markdown，不评测搜索引擎召回质量。

## 方法

执行方式：

```bash
PYTHONPATH=src python -m webserp.webcli_lite fetch "$url" --json --max-markdown-chars 0
```

约束：

- 先后 30 个真实网页样本，覆盖英文技术文档、中文技术文章、政策页、新闻页、论文摘要、RFC/W3C 规范页、百科、README、问答和教程页。
- 对外部站点串行低频请求，避免并发压测。
- 大体量网页原文与完整 Markdown 不提交仓库，只记录评测结论与必要样本现象。

## 第一轮样本与结果

| ID | 网站/页面 | 类型 | 最终结果 | 备注 |
| --- | --- | --- | --- | --- |
| 01 | Python asyncio EN | 英文技术文档 | 通过 | 语义容器准确，标题和章节完整 |
| 02 | Python asyncio ZH | 中文技术文档 | 通过 | CJK 正文、代码链接保留正常 |
| 03 | Pydantic validators | 英文技术文档 | 通过 | 标题、段落、代码块结构稳定 |
| 04 | FastAPI tutorial | 英文技术文档 | 通过 | 正文干净，目录噪声少 |
| 05 | Kubernetes Gateway API | 英文技术文档 | 通过 | 正文和内部链接可读 |
| 06 | Gateway API HTTP routing | 英文技术文档 | 通过 | 短文档抽取稳定 |
| 07 | MDN Using Fetch | 英文 Web 文档 | 通过 | 修复后自动补齐页面 H1 |
| 08 | RFC 9110 HTML | 英文规范 | 通过 | 内容巨大但结构完整，建议实际使用默认截断 |
| 09 | arXiv Attention | 论文摘要页 | 通过 | 保留提交版本、标题、作者与摘要 |
| 10 | PEP 703 | 英文规范 | 通过 | 标题重复前缀已清理 |
| 11 | 阮一峰 asyncio | 中文博客 | 通过 | 标题、作者、正文可读 |
| 12 | gov.cn 政策页 | 中文政务 | 通过 | 修复后优先 `UCAP-CONTENT` 正文，避免外层元数据表重复 |
| 13 | 科技日报新闻 | 中文新闻 | 通过 | 标题、来源、正文可读 |
| 14 | 新浪财经新闻 | 中文新闻 | 通过 | 修复后移除 H1 前 logo 图片前缀 |
| 15 | 中证网新闻 | 中文新闻 | 通过 | 无 H1 页面会补标题；仍保留少量站点 logo 图片 |
| 16 | Hugging Face Transformers | 英文技术文档 | 通过 | 修复后移除 docs 全局导航块 |
| 17 | React useEffect | 英文技术文档 | 通过 | 标题、说明、代码块可读 |
| 18 | NumPy beginners | 英文技术文档 | 通过 | 内容长但章节完整 |
| 19 | docs.rs Tokio | 英文 API 文档 | 通过 | crate 标题、说明、模块链接可读 |
| 20 | W3C WCAG 2.2 | 英文规范 | 通过 | curl 指纹触发 Cloudflare，plain HTTP fallback 后通过 |

第一轮结果：20/20 可用。

## 第二轮泛化样本与结果

第二轮追加 10 个页面形态，重点观察跨站泛化能力。

| ID | 网站/页面 | 类型 | 最终结果 | 备注 |
| --- | --- | --- | --- | --- |
| 21 | Rust Book ownership | 英文在线书籍 | 通过 | 章节、代码块和正文可读 |
| 22 | Go blog context | 英文官方博客 | 通过 | 博客标题、作者、正文结构稳定 |
| 23 | Wikipedia Web scraping | 英文百科 | 通过 | 追加优化后清理开头维护提示 |
| 24 | GitHub psf/requests | GitHub README | 通过 | 追加优化后清理 README 前的仓库导航 |
| 25 | Stack Overflow yield question | 问答页 | 通过 | 追加优化后补齐页面标题；仍保留少量问题元数据 |
| 26 | Microsoft Learn Azure Identity | 英文技术文档 | 通过 | 追加优化后清理语言/编辑/授权提示前缀 |
| 27 | 中文维基 搜索引擎 | 中文百科 | 通过 | 追加优化后清理维护提示，保留正文 |
| 28 | 百度百科 人工智能 | 中文百科 | 受限 | 返回反爬/安全验证页，按 challenge 明确失败 |
| 29 | 廖雪峰 Python 教程 | 中文教程 | 通过 | 正文、代码块、作者信息可读 |
| 30 | 菜鸟教程 Python3 | 中文教程 | 通过 | 教程正文和图片保留正常 |

第二轮结果：9/10 可用，1/10 为站点反爬限制。

综合结果：29/30 可用；唯一失败样本是百度百科 challenge，属于真实访问限制，不是 Markdown 抽取失败。

## 发现的问题

1. W3C 站点对 curl_cffi 指纹返回 Cloudflare challenge，但普通 HTTP 客户端能读取正文。
2. challenge 检测将 `<style>` 计入脚本比例，存在 CSS-heavy 页面被误判为空脚本壳的风险。
3. gov.cn 政策页在 lxml `deepcopy` 后会丢失关键正文节点，导致抽取为空或选中外层元数据表。
4. 一些页面正文从 `h2` 开始，Markdown 缺少页面 H1。
5. 部分新闻页在 H1 前输出站点 logo 图片。
6. Hugging Face 文档页会把 docs 全局导航夹在重复 H1 中间。

## 已完成优化

- `webfetch` 增加 `fetch_page_response()`，在 curl_cffi 命中 challenge 时启用 plain HTTP fallback。
- fallback 继续执行 URL/DNS 安全校验、重定向目标校验、最大 body 限制和 challenge 检测；指定 proxy 时不绕过 proxy。
- challenge 脚本壳比例只统计 `<script>`，不再把 `<style>` 当脚本。
- extractor 不再对 lxml root 直接 `deepcopy`，改为二次解析 HTML，避免畸形页面节点丢失。
- 增加 `UCAP-CONTENT`、`pages_content` 等政务站常见正文容器识别。
- 增加 `semantic_exact` 高置信正文候选，优先 `content-inner`、`artibody`、`article_content`、`UCAP-CONTENT`。
- 最终 Markdown 增加抛光步骤：补 H1、清理短导航前缀、清理 H1 前图片/链接前缀、清理重复 H1 之间的 docs 导航块。
- 追加泛化优化：清理 GitHub README 仓库导航、Microsoft Learn 文档前缀、维基百科维护提示；当页面第一个 H1 不是页面标题时补标题并将原 H1 降级。

## 测试覆盖

新增/扩展测试覆盖：

- CSS-heavy 正常页面不被识别为空脚本壳。
- curl challenge 后 webfetch plain HTTP fallback 被调用。
- `UCAP-CONTENT/pages_content` 政务正文抽取。
- 内容从 `h2` 开始时补页面 H1。
- H1 前纯图片前缀清理。
- docs 导航前缀和重复 H1 导航块清理。
- 无 H1 且前置 logo 图片时补页面标题。
- GitHub README 前仓库导航清理。
- Microsoft Learn 语言/编辑/授权提示前缀清理。
- Stack Overflow 类问答页标题补齐。
- 维基百科开头维护提示清理。

验证命令：

```bash
PYTHONPATH=src python -m pytest -q
```

结果：

```text
93 passed
```

## 验收标准

- 30 个真实网页样本均能返回非空 Markdown 或明确可解释错误：已满足，29 个通过，1 个 challenge 明确失败。
- 中英文正文标题、段落和主要内容可读：已满足。
- 失败样本必须转化为代码修复或记录为不可控站点限制：已满足。
- 修复必须有离线测试覆盖，避免依赖外部站点稳定性：已满足。
- 不提交大体量抓取产物，避免仓库污染：已满足。

## 剩余边界

- RFC/W3C/NumPy 这类长规范文档会产生很大的 Markdown；Agent 实际使用时仍建议依赖默认截断，必要时再指定更大输出。
- 对 JavaScript 渲染后才出现正文的纯 SPA，本轮没有引入浏览器渲染 fallback。
- 站点 logo 图片如果位于标题之后且和正文混排，目前保守保留，避免误删文章主图。
