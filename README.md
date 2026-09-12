# A 股策略回测工作台

Windows 桌面版 A 股策略回测工具。项目使用 React + TypeScript 构建界面，Tauri 提供桌面容器，Python 负责本地数据服务、行情聚合、数据补齐和回测执行，并内置一个基于 LLM 的 AI 投研助手（工具调用 + 本地知识检索 + 快讯推送）。

当前版本：`1.4.0`

## 1.4.0 当前发布内容

本轮新增 AI 投研助手模块（`backend/astock_backtester/ai/`，独立子包，对存量模块只读）：

- **评股 Agent**：`POST /ai/chat/stream` NDJSON 流式对话。Agent 通过 11 个只读工具（实时行情、新闻、复盘、风险清单、本地日线+均线、条件校验、受控回测、腾讯估值、东财研报、龙虎榜、涨停池）完成个股诊断与行情问答；正文流式输出，工具调用过程可视化，所有数字要求标注来源工具。
- **NL→策略 DSL**：自然语言生成条件 DSL → 先校验（校验失败带模板示例自我修正）→ 受控运行本地回测 → 结果可一键"应用到策略工作台"。
- **上下文工程与分层记忆**（参考 MemGPT/Letta、mem0 的分层思路，本地化裁剪）：短期上下文窗口硬性保留最近 10 条协议消息，溢出部分归档并压缩为会话滚动纪要；长期记忆由模型在每轮结束后提取持久事实（关注标的/策略偏好/参数习惯），去重合并进 `运行产物/AI记忆/memory.json`，并按更新时间注入后续 system prompt。工具全量结果留在后端 `ToolResultStore`，进上下文的只有每工具摘要；爬取内容以不可信分隔符包裹（提示词注入防御）。
- **真实执行能力（NL→SQL + 计算函数 + 受控写入）**：Agent 可对本地日线数据仓发起 DuckDB 只读 SQL 查询（`query_warehouse_sql`，hive 分区 parquet 直查，强制 SELECT/WITH、自动 LIMIT 500），可调用统计函数（`compute_stock_stats`：区间收益/年化波动/最大回撤/资金合计），可通过 `update_stock_data` 用数据中心同款补齐链路把指定股票区间数据写回仓库——这是唯一的写路径，SQL 层禁止任何写语句。
- **本地知识检索（RAG）**：投研方法论 / 条件 DSL 语法 / 数据字段规则三份语料，langchain-text-splitters 分块 + OpenAI 兼容 embedding（磁盘缓存）+ numpy 余弦 Top-K，以 `retrieve_knowledge` 工具挂给 Agent。
- **AI 快讯推送**：`GET /ai/events/stream` 长连接。规则触发器（新闻更新 / 市场宽度异动 / 风险清单变化）发出 `data_fresh` 信号，前端立即刷新对应模块（推拉结合，替代死等轮询）；配置模型后按小时级配额生成 AI 快讯（`insight`，强制标注 ai-insight，不构成投资建议）。
- **配置与安全**：LLM 配置存于 `运行产物/AI配置/ai-config.json`（不进 Git；设置弹窗可显示/隐藏自己的 API Key，接口默认只回掩码）；AI 模块对数据仓默认只读，唯一写路径是 `update_stock_data` 补齐链路；AI 生成的策略/结论不进入 `latest_strategy_matches` 候选管线；评测集见 `scripts/ai_eval.py`（20 条 NL→DSL 用例，本地跑，不进 CI）。

LLM 客户端复用官方 `openai` SDK（任何 OpenAI 兼容服务商均可，配置默认留空，由用户在应用内"AI 助手 → 设置"填写）。

## 面向用户

- AI 助手：右上角"AI 助手"唤起右侧抽屉，支持个股诊断（技术/资金/估值/消息四维）、大盘快评、自然语言生成策略并一键回测、回测结果解读；工具调用过程与数据来源全部可见。
- 数据中心：维护 A 股日线、资金流、市值和覆盖信息，支持导入、全市场同步、指定股票补齐和资金流补齐。
- 策略回测：支持入场/离场条件、仓位参数、止盈止损、涨跌停约束和流式回测结果。
- 行情看板：展示指数、红绿家数、强势板块、行情评价、新闻摘要、资讯事件、同花顺复盘/早盘和风险提示；后端有新数据或出现 AI 快讯时通过事件流即时提醒。
- 候选股票：回测结果通过 `latest_strategy_matches.matches` 展示符合当前策略的个股。
- 桌面更新：通过 GitHub Releases 发布 Windows 安装包，并由应用内更新入口检查新版本。

最新安装包见 [GitHub Releases](https://github.com/dzc-bit/Astock-backtester/releases)。

## 数据源概览

- 历史行情：AData、AKShare、百度股市通 / PAE、东方财富公开接口。
- 实时行情：财联社、同花顺、Sina、Tencent、AKShare 及后端公开行情爬虫。
- 强势板块：同花顺概念/行业、Sina 行业、AKShare、东方财富板块接口。
- 新闻资讯：东方财富栏目资讯、东方财富要闻、财联社电报。
- 复盘早盘：同花顺复盘/早盘页面，失败时使用公开行情或本地简短判断兜底。
- 资金流：东方财富公开资金流接口，缺口和失败原因会通过 diagnostics/failures 暴露给上层服务。

## 技术架构

| 层级 | 目录 | 说明 |
| --- | --- | --- |
| 前端 | `frontend/src` | React + TypeScript，页面、状态、图表和结构化接口消费；API 层统一在 `api.ts`（含浏览器预览 mock 双轨），AI 对话流在 `aiApi.ts`，轮询类逻辑收敛在 `hooks/` |
| 桌面容器 | `src-tauri/src` | Tauri + Rust，负责桌面命令、本地服务启动（含 sidecar 五重身份校验）、策略保存和更新器 |
| 本地后端 | `backend/astock_backtester` | Python，自写 HTTP 服务 + 数据 provider + 仓库 + 回测引擎；回测条件在 `conditions.py` 注册表统一维护（行级求值与向量化预过滤成对注册） |
| AI 子系统 | `backend/astock_backtester/ai` | 独立子包：openai SDK 薄封装、工具注册表（本地数据 + a-stock-data 裁剪端点）、Agent 循环、上下文预算、会话存储、RAG 检索、快讯引擎；对数据仓只读 |
| 共享数据设施 | `backend/astock_backtester/data` | `symbols.py`/`parsing.py` 收敛符号与数值解析，`http_transport.py` 统一 UA、代理策略和重试传输 |
| 测试 | `tests`、`frontend/src/*.test.*` | 三层测试：后端（行为级，含 AI 子系统 49 例）、前端、Rust；回环 HTTP 测试自带代理隔离 |

依赖方向保持单向（`service → data/* → models`，data 层不反向依赖根包），全仓零 import 环。错误响应携带稳定 `code`（`no_local_data` / `validation_error` / `payload_error` / `request_failed`），前端按错误码翻译文案。

## 质量门禁

CI（`.github/workflows/ci.yml`，windows-latest）在 push/PR 时运行三组检查：pytest + ruff、eslint + tsc + vitest、cargo test。本地等价命令：

```powershell
python -m ruff check backend tests scripts
npm run lint
npm run typecheck
npm run test:coverage
cargo test --manifest-path src-tauri/Cargo.toml
```

覆盖率（pytest-cov + vitest v8）当前只出报告不设阈值。

## 本地 HTTP 接口

桌面端启动后会拉起本地 sidecar，前端访问 `http://127.0.0.1:<port>`。

| 能力 | 接口 |
| --- | --- |
| 健康检查 | `GET /ping`、`GET /health`、`GET /logs/recent` |
| 覆盖查询 | `POST /coverage/daily-bars` |
| 数据同步 | `POST /sync/full-market`、`GET /sync/jobs/{job_id}` |
| 数据导入与补齐 | `POST /import/daily-bars`、`POST /fetch/daily-bars`、`POST /fetch/capital-flow` |
| 行情与资讯 | `GET /realtime/market-snapshot`、`GET /market/commentary`、`GET /market/news-summary`、`GET /market/news` |
| 复盘/早盘 | `GET /market/fupan`、`GET /market/zaopan` |
| 风险与策略 | `GET /risk/alerts`、`GET /strategy/recommended`、`POST /strategy/conditions/validate` |
| 回测 | `POST /run/backtest/stream` |
| AI 助手 | `GET /ai/status`、`GET /ai/config`、`POST /ai/config`、`POST /ai/chat/stream`、`GET /ai/events/stream` |

`/run/backtest/stream` 与 `/ai/chat/stream` 返回 NDJSON，需要逐行解析；`/ai/chat/stream` 的最后一个事件为 `{"type":"result", ...}`（错误时为 `error`）。`/ai/events/stream` 为长连接（insight / data_fresh / heartbeat）。

## 开发环境

建议环境：

- Node.js 20+
- Python 3.11+
- Rust stable toolchain
- Windows 桌面构建需要 Tauri 支持的 MSVC 构建工具

安装依赖：

```powershell
npm install
python -m pip install -e .
```

常用命令：

```powershell
npm run test:ui -- --run
npm run lint
npm run typecheck
npm run build
npm run build:data-service
python -m pytest tests -q
python -m ruff check backend tests scripts
cargo test --manifest-path src-tauri/Cargo.toml
```

开发模式：

```powershell
npm run tauri -- dev
```

生产构建：

```powershell
npm run tauri -- build --ci
```

Windows 发布使用项目内固定的 Node、Python、Rust、MSVC 和 NSIS 工具，完整的签名、覆盖安装、sidecar 哈希和 HTTP 探针流程见 [`docs/release.md`](docs/release.md)。

发布前请确认生成的安装包、签名文件、临时更新清单、日志和运行数据没有提交到 Git 仓库。
