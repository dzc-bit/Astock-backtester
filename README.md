# A股策略回测工作台

Windows 桌面版 A 股策略回测工具。项目使用 React 构建界面，Tauri 提供桌面容器，Python 负责本地数据服务、行情聚合和回测逻辑。

## 核心能力

- 本地历史数据仓：支持日线、资金流、市值等数据的导入、补齐、资金流独立回填和覆盖检查。
- 策略配置：支持入场条件、离场条件、仓位参数、止盈止损和股票池配置。
- 流式回测：回测过程返回阶段进度、交易事件和最终收益统计。
- 实时行情看板：聚合指数、红绿家数、强势板块、昨日强势追踪、行情评价、新闻汇总、资讯和风险提示。
- 复盘阅读：独立展示同花顺复盘/早盘总评，支持摘要、分段全文、表格和原文跳转。
- 策略候选：回测结果通过 `latest_strategy_matches.matches` 展示当日符合用户策略的个股；本地回测快照明确标注为非实时。
- 策略保存：回测后可保存用户策略，并保留基础内置策略。
- 桌面更新：通过 Tauri updater 读取 GitHub Release 更新信息。

## 技术架构

| 层级 | 目录 | 说明 |
| --- | --- | --- |
| 前端界面 | `frontend/src` | React + TypeScript，负责策略配置、数据中心、行情看板和结果展示 |
| 桌面容器 | `src-tauri/src` | Tauri + Rust，负责本地服务启动、桌面命令和更新集成 |
| 数据与回测 | `backend/astock_backtester` | Python，负责数据仓、行情接口、条件解析和回测引擎 |
| 验证用例 | `tests`、`frontend/src/**/*.test.*` | 后端、前端和构建脚本的自动化验证 |

## 数据与接口概览

前端主要通过本机 HTTP 数据服务访问数据与回测能力。桌面端启动后会先拉起本地数据服务，再由前端访问以下接口：

| 能力 | 接口 |
| --- | --- |
| 服务健康与覆盖信息 | `GET /ping`、`GET /health`、`POST /coverage/daily-bars` |
| 历史数据同步与导入 | `POST /sync/full-market`、`GET /sync/jobs/{job_id}`、`POST /import/daily-bars`、`POST /fetch/daily-bars`、`POST /fetch/capital-flow` |
| 行情、资讯与风险 | `GET /realtime/market-snapshot`、`GET /market/commentary`、`GET /market/news-summary`、`GET /market/news`、`GET /market/fupan`、`GET /market/zaopan`、`GET /risk/alerts` |
| 策略校验与推荐 | `POST /strategy/conditions/validate`、`GET /strategy/recommended` |
| 回测执行 | `POST /run/backtest/stream` |

实时行情、复盘和候选股保持独立模块：行情宽度在后端 provider 中按同花顺、Sina、Tencent、AKShare、重型公开行情爬虫链路校验，东方财富轻量 spot 只能作为受控备选；重型爬虫当前请求失败时不会把最近成功红绿家数伪装成本次 live。同花顺复盘/早盘只展示原文和结构化表格，不拼入 user 模式候选；公开行情或本地简短兜底会通过结构化 `source/source_url/diagnostics` 明确标注。
资金流 crawler 纳入 1.1.1 后作为后端只读 provider 边界：低层 crawler 返回 `main_net_inflow` 行、`failures` 和 `diagnostics`，不直接写本地仓；高层数据服务在 `/fetch/daily-bars` 中优先用它合并资金流，并通过 `/fetch/capital-flow` 单独补齐已有日线的资金流缺口。东方财富断连时只复用同进程最近成功的同股票日期行并写入 `recent_success_cache_used` diagnostics，仍保留失败记录。前端只消费结构化响应，不包含上游 URL、爬虫逻辑或字段清洗规则。

更完整的设计、接口、数据源和运行配置细节见 [项目说明书.md](./项目说明书.md)。

## 开发命令

```powershell
npm run dev
npm run test:ui -- --run
python -m pytest tests -q
npm run build
npm run build:data-service
npm run tauri -- build
```

## 文档

- [项目说明书.md](./项目说明书.md)：完整项目细节、按钮接口映射、行情上游来源、运行配置和清理边界。
- [docs/pitfall-guide.md](./docs/pitfall-guide.md)：接手避坑清单，覆盖路径、行情、复盘、数据仓、sidecar、发布和探针高风险点。
- [docs/dev.md](./docs/dev.md)：开发环境和构建补充说明。
- [docs/release.md](./docs/release.md)：桌面版本发布和更新流程。
