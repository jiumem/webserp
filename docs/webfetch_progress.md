# webfetch PR 推进记录

## 目标范围

- 新增 `webfetch URL` CLI，用于把单个 URL 抽取为 Agent 可消费的 JSON。
- 复用现有安全请求层：HTTP(S) 校验、DNS/私网拦截、逐跳 redirect 校验、body cap、challenge 检测。
- 不引入 Trafilatura/Readability 作为主路径；实现自研候选抽取、Markdown 转换、链接拓扑和仲裁。
- 不做浏览器渲染、验证码绕过、代理池、云端反爬、批量爬取。

## 方案口径

- 抽取候选：`semantic`、`scored`、`structural`、`body_fallback`、`data_island`。
- 仲裁指标：文本长度、CJK 友好字符统计、结构分、链接噪声惩罚、Link Mass 惩罚、标题一致性。
- 输出结构：`url`、`final_url`、`status`、`title`、`description`、`markdown`、`text`、`links`、`images`、`code_blocks`、`structured_data`、`meta`。
- 链接拓扑：输出 `content`、`directory`、`navigation`、`noise` 分类。
- 表格：支持标准 table 与 rowspan/colspan 展平；layout table 避免误转为数据表。

## 测试策略

- 用离线 fixtures + expected.json 金标，不依赖 live URL 作为质量判据。
- 金标由 Codex 自动生成并审核写入，覆盖 facts、must_exclude、结构计数、链接样本、winner 期望。
- 低频 live smoke 只验证网络路径，不作为抽取质量判断。

## 任务清单

- [x] 扩展 fetch 层，暴露 `FetchResponse` 给 webfetch 使用。
- [x] 实现 webfetch 抽取模块与 CLI。
- [x] 构建离线 fixtures 和 expected 金标。
- [x] 覆盖安全、抽取、仲裁、Markdown、链接拓扑测试。
- [x] 更新 README、skill 和专项说明文档。
- [x] 本地验证和 PR 提交材料准备。

## 当前验证结果

- `python -m compileall -q src`：通过。
- `PYTHONPATH=src python -m unittest discover -s tests`：通过，35 个测试。
