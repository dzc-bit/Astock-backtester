# A 股策略回测工作台

Windows 桌面版 A 股策略回测工具。项目使用 React + TypeScript 构建界面，Tauri 提供桌面容器，Python 负责本地数据服务、行情聚合、数据补齐和回测执行。

当前版本：`1.3.4`

## 面向用户

- 数据中心：维护 A 股日线、资金流、市值和覆盖信息，支持导入、全市场同步、指定股票补齐和资金流补齐。
- 策略回测：支持入场/离场条件、仓位参数、止盈止损、涨跌停约束和流式回测结果。
- 行情看板：展示指数、红绿家数、强势板块、行情评价、新闻摘要、资讯事件、同花顺复盘/早盘和风险提示。
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
| 前端 | `frontend/src` | React + TypeScript，负责页面、状态、图表和结构化接口消费 |
| 桌面容器 | `src-tauri/src` | Tauri + Rust，负责桌面命令、本地服务启动、策略保存和更新器 |
| 本地后端 | `backend/astock_backtester` | Python，负责 HTTP 服务、数据 provider、仓库、回测和模型 |
| 测试 | `tests`、`frontend/src/**/*.test.*` | 覆盖后端、前端、Rust 和数据服务边界 |

前端只消费本地后端返回的结构化 JSON；上游网站、爬虫逻辑和字段清洗规则由后端 provider 封装。

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
npm run typecheck
npm run build
npm run build:data-service
python -m pytest tests -q
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

发布前请确认生成的安装包、签名文件、临时更新清单、日志和运行数据没有提交到 Git 仓库。
