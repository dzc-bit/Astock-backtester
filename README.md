# A 股策略回测工作台

Windows 桌面版 A 股策略回测工具。项目使用 React + TypeScript 构建界面，Tauri 提供桌面容器，Python 负责本地数据服务、行情聚合、数据补齐和回测执行。

当前版本：`1.3.1`。

## 核心能力

- 本地历史数据仓：维护 A 股日线、资金流、市值和覆盖信息。
- 数据中心：支持导入、全市场同步、指定股票补齐、资金流补齐和覆盖查询；“补全缺失数据”默认走全市场，输入股票代码时才只补个股。
- 策略回测：支持入场/离场条件、仓位参数、止盈止损、涨跌停约束和流式回测结果。
- 行情看板：展示指数、红绿家数、强势板块、行情评价、新闻摘要、资讯事件、同花顺复盘/早盘和风险提示。
- user 模式候选：回测结果通过 `latest_strategy_matches.matches` 展示符合用户策略的个股。
- 桌面更新：通过 Tauri updater、签名安装包、`.sig` 和 `latest.json` 发布。

## 技术架构

| 层级 | 目录 | 说明 |
| --- | --- | --- |
| 前端 | `frontend/src` | React + TypeScript，负责页面、状态、图表和结构化接口消费 |
| 桌面容器 | `src-tauri/src` | Tauri + Rust，负责本地服务启动、运行产物路径、策略保存和更新器 |
| 本地后端 | `backend/astock_backtester` | Python，负责 HTTP 服务、数据 provider、仓库、回测和模型 |
| 测试 | `tests`、`frontend/src/**/*.test.*` | 覆盖后端、前端、Rust 和数据服务边界 |

前端只调用本地后端返回的结构化 JSON；上游网站、爬虫逻辑和字段清洗规则由后端 provider 封装。

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

`/run/backtest/stream` 返回 NDJSON，需要逐行解析，最后一行应为 `{"type":"result", ...}`。

## 数据源概览

- 历史行情：AData、AKShare、百度股市通 / PAE、东方财富公开接口。
- 实时行情：同花顺市场页、Sina 批量行情、Tencent 批量行情、AKShare、后端公开行情爬虫。
- 强势板块：同花顺概念/行业、Sina 行业、AKShare、东方财富板块接口。
- 新闻资讯：东方财富栏目资讯、东方财富要闻、财联社电报。
- 复盘早盘：同花顺复盘/早盘页面，失败时由公开行情或本地简短判断兜底。
- 资金流：`CapitalFlowCrawler` 抓取东方财富公开资金流 XHR，使用固定 header / `ut` 参数变体和短超时兜底，由上层服务合并 `main_net_inflow`。

## JSON 文件说明

仓库根目录源码 JSON 主要是：

- `package.json`
- `package-lock.json`
- `tsconfig.json`
- `src-tauri/tauri.conf.json`
- `src-tauri/capabilities/main.json`

`运行产物\策略配置\saved-strategies.json`、`release-assets\latest.json`、探针 JSON 和日志 JSON 都是运行或发布产物，不应作为源码文件提交。

## 本地材料

`项目说明书.md`、`应用创新类项目报告.md` 和 `演示文档操作提醒.md` 是本机人工说明或演示材料，不纳入 GitHub 仓库。公开仓库只保留源码、测试、README、`AGENT必读.md` 和必要的 `docs/` 专项说明。

## 开发命令

所有命令都应在真实根目录 `D:\New project 6` 执行。

```powershell
python -m pytest tests -q
.\.tools\node-v20.18.1-win-x64\npm.cmd run test:ui -- --run
.\.tools\node-v20.18.1-win-x64\npm.cmd run typecheck
.\.tools\node-v20.18.1-win-x64\npm.cmd run build
.\.tools\node-v20.18.1-win-x64\npm.cmd run build:data-service
```

Rust 测试：

```powershell
$env:CARGO_HOME='D:\New project 6\.tools\cargo-home'
$env:RUSTUP_HOME='D:\New project 6\.tools\rustup-home'
$env:PATH='D:\New project 6\.tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin;' + $env:PATH
cargo test --manifest-path src-tauri\Cargo.toml
```

更多开发背景见 [AGENT必读.md](./AGENT必读.md) 和 `docs/` 下的专项说明。
