# webcli-lite 发布验收记录（2026-06-15）

## 验收对象

- 仓库：`jiumem/webserp`
- 分支：`main`
- Commit：`cf23bd188a479ecd9e34644f0b3152376e253998`
- 版本：`webcli-lite 0.2.0`
- 验收方式：低频 live smoke，不对同一搜索接口做重复压力测试。
- 临时结果目录：`/var/folders/g2/b5r2c68d3t9c0nxp16txxsfr0000gn/T/webcli-lite-accept.XXXXXX.2E1YLPp0Bo`

## 初次结论

初次验收不建议发布。

主要阻塞有两类：

1. `fetch` / `map` 在本地 fake-ip / 代理 DNS 环境下全部被 DNS 安全层阻断，CLI 真实读取能力不可用。
2. 绕过 DNS 校验做诊断后，10 个真实页面里有 5 个 HTTP 200 页面抽取为空，说明正文抽取候选还需要补强。

## 安装入口验收

临时 venv 安装本地包：

```bash
python -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install .
"$VENV_DIR/bin/webcli-lite" --version
```

结果：

- `webcli-lite --version`：通过，输出 `webcli-lite 0.2.0`。
- 旧命令 `webserp`：未暴露，通过。
- 旧命令 `webfetch`：未暴露，通过。

## 搜索验收

执行 6 个 query，默认 profile 为 `agent`，即 `bing_cn,brave`，每个引擎 5 条：

中文：

- `2026 人工智能 开源 大模型 最新进展`
- `新能源汽车 出海 欧洲 政策 2026`
- `Python 异步 编程 TaskGroup 教程`

英文：

- `pydantic v2 model_validator examples`
- `"Attention Is All You Need" paper PDF`
- `Kubernetes Gateway API HTTPRoute example`

结果：

- 6/6 命令返回 code 0。
- 6/6 JSON schema 正常。
- 6/6 返回 10 条结果。
- 6/6 `unresponsive_engines` 为空。

质量问题：

- 当前结果合并是按引擎块输出，`bing_cn` 的 5 条排在 `brave` 前面。
- 英文技术 query 中，`brave` 结果质量明显更好，但排在第 6-10 位。
- 部分中文长 query 中，`bing_cn` 对首词过度匹配，例如新能源汽车 query 前 5 条集中在“新”字解释和新浪首页。

建议：

- 搜索结果合并改为按 rank round-robin：`bing_cn#1, brave#1, bing_cn#2, brave#2...`，避免单个引擎低相关结果强占前排。
- skill 中英文技术、论文、官方文档场景应明确优先 `--profile en`，或 CLI 增加轻量语言/意图 profile 提示。

## fetch CLI 验收

选取 10 个 URL，全部使用公开 CLI：

```bash
PYTHONPATH=src python -m webserp.webcli_lite fetch "$URL" --json
```

结果：

- 10/10 失败。
- 失败类型全部为 `BlockedUrlError`。
- 错误信息全部为 `URL resolves to a private, reserved, or internal address`。

定位：

当前系统 DNS 会把公网域名解析到 `198.18.x.x`：

- `docs.pydantic.dev -> 198.18.3.174`
- `arxiv.org -> 198.18.3.175`
- `kubernetes.io -> 198.18.3.176`
- `docs.python.org -> 198.18.3.178`

`198.18.0.0/15` 是 fake-ip / 代理环境常见保留网段，当前安全层按 private/reserved/internal 阻断，因此本地 Agent 场景下 `fetch` 不可用。

建议：

- 为本地 CLI 增加 DNS safety policy，例如 `strict` / `hostname-only` / `off`。
- 默认仍阻断 IP literal、localhost、`.localhost`、明显私网 host。
- 对 hostname DNS 解析到 `198.18.0.0/15` 的 fake-ip 场景，应允许本地 CLI 继续请求，或提供显式开关并在 stderr 给出安全提示。
- 服务端 API 场景可以保留 strict DNS 校验，但本项目定位是个人本地 Agent，默认不能被 fake-ip DNS 阻断。

## fetch 抽取诊断

为定位是否只是 DNS 安全层问题，使用库内 `fetch_response(validate_url=False)` 做一次诊断性抽取。该结果不代表 CLI 发布通过，只用于判断正文抽取质量。

结果：

| ID | URL 类型 | 结果 |
|---|---|---|
| f01 | Pydantic 文档 | HTTP 200，但 Markdown 为空 |
| f02 | arXiv 论文页 | HTTP 200，但 Markdown 为空 |
| f03 | Kubernetes 文档 | 可用，Markdown 约 12k 字符 |
| f04 | Gateway API 文档 | 可用，Markdown 约 3.8k 字符 |
| f05 | Python 中文官方文档 | HTTP 200，但 Markdown 为空 |
| f06 | 阮一峰博客 | 可用，Markdown 约 5.8k 字符 |
| f07 | 科技日报文章 | 可用，Markdown 约 3.5k 字符 |
| f08 | 新浪财经文章 | HTTP 200，但 Markdown 为空 |
| f09 | Hanspub 论文页 | HTTP 200，但 Markdown 为空 |
| f10 | 中证网文章 | 可用，Markdown 约 2.8k 字符 |

问题：

- 5/10 真实页面抽取为空，但 HTTP 状态是 200。
- 失败页面包含高价值目标：Pydantic docs、arXiv、Python docs。
- 空结果的 `strategy` 为空，触发 `low_text_content`，说明候选筛选没有找到 viable candidate。

建议：

- 把 Pydantic、arXiv、Python docs 至少三类页面纳入 live snapshot fixture。
- 当所有候选不 viable 但 body 有可见文本或 links 时，不应返回空 Markdown；应增加保守 body text fallback 或 broaden structural candidate。
- 对常见文档站的主体容器增加识别：`role=main`、`[class*=content]`、`[class*=document]`、`[class*=md-content]`、`article` 邻近容器。
- 对抽取空结果增加 CLI warning 或 JSON warning，避免 Agent 把空正文当成有效读取。

## map CLI 验收

执行一个文档站 map：

```bash
PYTHONPATH=src python -m webserp.webcli_lite map "https://docs.python.org/zh-cn/3/" \
  --type directory \
  --format tsv \
  --fields id,type,text,href,path \
  --max-links 0
```

结果：

- 失败，code 2。
- 失败类型：`BlockedUrlError`。
- 原因与 fetch 相同：DNS fake-ip 被安全层阻断。

结论：

- 当前无法进入真实文档站 map 工作流。
- 修复 DNS policy 后需要重新跑 3 个文档站 map 验收。

## 初次发布判定

不通过。

必须修复：

1. `fetch/map` DNS fake-ip 环境不可用。
2. 高价值真实页面抽取为空。

建议修复：

1. 搜索结果合并顺序改为 rank round-robin，或强化英文技术场景 profile 指令。
2. 空 Markdown 时暴露明确 warning。
3. 将本次失败页面沉淀为 fixtures 和验收用例。

## 修复后复验

修复分支：`release-acceptance-fixes`

静态验证：

- `PYTHONPATH=src python -m pytest -q`：81 passed。
- `PYTHONPATH=src python -m compileall -q src tests`：通过。
- `git diff --check`：通过。
- `python /Users/nuc8/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill/webserp`：通过。

修复内容：

- `fetch` / `map` 默认使用 `local-agent` DNS policy，允许 hostname 解析到 `198.18.0.0/15` fake-ip；IP literal、localhost、真实私网地址仍被阻断。
- 搜索默认仍先跑 `bing_cn,brave`；结果不足 10 条时才补 `yahoo,presearch`。
- 主引擎和 fallback 结果均按 rank 交错合并，避免单引擎低相关结果占满前排。
- 正文抽取器扩大常见文档站主体容器识别，修复 Pydantic、arXiv、Python docs、Sina 等页面空 Markdown。
- 裸 JavaScript cookie/challenge 页面识别为 challenge，不再伪装成成功空正文。

搜索复验：

- 6 个中英文 query 均返回 code 0 和稳定 JSON。
- Brave 在本机验收阶段多次返回 `HTTP 429`，默认 fallback 自动触发。
- 代表性 query `pydantic v2 model_validator examples` 的前排结果已交错为 `bing_cn,yahoo,bing_cn,yahoo...`，第 2 条即 Pydantic 官方 validators 页面。

fetch 复验：

| ID | URL 类型 | 结果 |
|---|---|---|
| f01 | Pydantic 文档 | 通过，Markdown 27,524 字符 |
| f02 | arXiv 论文页 | 通过，Markdown 7,267 字符 |
| f03 | Kubernetes 文档 | 通过，Markdown 12,164 字符 |
| f04 | Gateway API 文档 | 通过，Markdown 3,813 字符 |
| f05 | Python 中文官方文档 | 通过，Markdown 34,953 字符 |
| f06 | 阮一峰博客 | 通过，Markdown 7,604 字符 |
| f07 | 科技日报文章 | 通过，Markdown 3,505 字符 |
| f08 | 新浪财经文章 | 通过，Markdown 5,158 字符 |
| f09 | Hanspub 论文页 | 预期失败，返回 `ChallengePageError` |
| f10 | 中证网文章 | 通过，Markdown 2,885 字符 |

map 复验：

- Pydantic docs：TSV 落盘成功，94 行，`rg` 可命中 `Pydantic Validation`、`Installation`、`Migration Guide`。
- Python docs library：TSV 落盘成功，305 行，`rg -i "asyncio|任务|TaskGroup"` 可命中 `asyncio --- 异步 I/O`。
- Gateway API docs：TSV 落盘成功，10 行，`rg` 可命中 `Gateway API`、`Guides`、`Reference`。

## 修复后发布判定

通过，可进入发布候选。

剩余风险：

- 搜索引擎 HTML 抓取仍会受单个引擎限流影响；当前通过 fallback 降低影响，不承诺每个引擎稳定成功。
- Hanspub 这类裸 JS challenge 页面不会渲染或绕过，按安全边界返回失败。
