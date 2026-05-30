# A股策略回测工作台

Windows 桌面版 A 股回测工具，前端使用 React，桌面容器使用 Tauri，数据与回测逻辑使用 Python。本项目当前的设计原则很明确：历史数据、策略配置、安装产物、签名密钥都统一放在 `D:\New project 6` 目录树内，不再把业务数据写到 `AppData`。

## 当前版本重点

- 历史日线、资金流、市值覆盖统一由本地数据仓提供。
- 桌面端本地数据服务统一读取 `D:\New project 6\运行产物\本地数据仓`。
- 项目根下的 `.astock-cache` 只是指向该目录的 Junction。
- 已保存策略在桌面端写入 `D:\New project 6\运行产物\策略配置\saved-strategies.json`。
- 首页行情、资讯、风险、推荐策略都通过本地 HTTP 数据服务聚合。
- 实时行情链路已调整为“同花顺优先，东方财富与本地历史兜底”，避免首页继续显示空题材或纯本地红绿家数。
- 应用内“检查更新”走 Tauri updater，不走本地 HTTP 服务。

## 统一路径规则

业务路径统一按下面这一套理解：

- 项目根目录：`D:\New project 6`
- 本地数据仓：`D:\New project 6\运行产物\本地数据仓`
- 项目缓存别名：`D:\New project 6\.astock-cache`
- 策略配置：`D:\New project 6\运行产物\策略配置\saved-strategies.json`
- 安装包产物：`D:\New project 6\运行产物\安装包`
- 更新签名密钥：`D:\New project 6\运行产物\签名密钥`

说明：

- `.astock-cache` 是一个联接目录，目标是 `运行产物\本地数据仓`。
- 发布态桌面端不再把历史数据或策略配置落到 `C:\Users\<你>\AppData\Local\...`。
- 桌面端本地服务启动后返回的 `cache_dir` / `cache_path` 应该都指向 `D` 盘项目目录。

## 架构概览

1. 前端：`frontend/src`
2. 桌面容器：`src-tauri/src`
3. Python 数据服务与回测：`backend/astock_backtester`

桌面端运行链路：

1. 前端先调用 Tauri 命令 `ensure_data_service`。
2. Tauri 在本机 `127.0.0.1` 随机端口启动 `astock-data-service.exe` 或 Python 模块服务。
3. 前端通过这个本地 HTTP 服务读取行情、资讯、风险、数据覆盖与回测结果。
4. 历史回测只读本地数据仓，不在回测执行过程中联网。

## 按钮与接口总览

下面是当前界面里真正会触发接口的按钮或模块。更完整的明细见 [项目说明书.md](/D:/New%20project%206/项目说明书.md)。

| 页面 / 模块 | 按钮或动作 | 前端入口 | 调用接口 | 后端处理 |
| --- | --- | --- | --- | --- |
| 应用启动 | 连接本地服务 | `ensureDataService` | Tauri `ensure_data_service` | `src-tauri/src/commands.rs` -> `DataServiceManager::ensure_running` |
| 数据中心 | 刷新覆盖范围 | `handleRefreshDetails` | `POST /coverage/daily-bars` + `GET /health` + `GET /logs/recent` | `backend/astock_backtester/service.py` |
| 数据中心 | 下载全市场历史数据 | `handleFullMarketSync` | `POST /sync/full-market`，之后轮询 `GET /sync/jobs/{job_id}` | `SyncJobManager` |
| 数据中心 | 补全缺失数据 | `handleFetch` | `POST /fetch/daily-bars` | `fetch_daily_bars_into_cache` |
| 数据中心 | 导入示例数据 | `handleImportSample` | `POST /import/daily-bars` with `source=sample` | `import_daily_bars_into_cache` |
| 数据中心 | 导入本地文件 | `handleImportFile` | `POST /import/daily-bars` with `source=file` | `read_daily_bars` + `import_daily_bars_into_cache` |
| 首页行情 | 自动刷新行情 | `loadRealtimeMarketSnapshot` | `GET /realtime/market-snapshot` | `RealtimeMarketProvider.market_snapshot` |
| 资讯面板 | 刷新资讯 | `refreshNews` | `GET /market/news` | `MarketNewsProvider.latest_news` |
| 风险弹窗 | 刷新风险 | `refreshRiskAlerts` | `GET /risk/alerts` | `RiskAlertProvider.current_alerts` |
| 推荐策略 | 初始加载 | `loadRecommendedStrategies` | `GET /strategy/recommended` | `recommended_strategies(...)` |
| 策略配置 | 校验入场条件 | `onValidateCondition` | `POST /strategy/conditions/validate` with `mode=entry` | `validate_condition_text` |
| 策略配置 | 校验离场条件 | `validateExitCondition` | `POST /strategy/conditions/validate` with `mode=exit` | `validate_exit_condition_text` |
| 收益概览 | 运行历史回测 | `runBacktest` | `POST /run/backtest/stream` | `_run_backtest_stream` |
| 更新面板 | 检查更新 | `checkForUpdate` | Tauri updater `check()` | GitHub Release `latest.json` |
| 更新面板 | 安装并重启 | `installAndRelaunch` | Tauri updater `downloadAndInstall()` + process `relaunch()` | 不经过本地 HTTP 服务 |
| 策略配置 | 读取已保存策略 | `loadSavedStrategiesFromStore` | Tauri `load_saved_strategies` | 读取 `运行产物\策略配置\saved-strategies.json` |
| 策略配置 | 保存 / 删除已保存策略 | `persistSavedStrategiesToStore` | Tauri `persist_saved_strategies` | 写入 `运行产物\策略配置\saved-strategies.json` |

不走 HTTP 的纯前端动作：

- 套用推荐策略
- 套用已保存策略
- 重置策略
- 套用数据中心日期
- 打开 / 关闭风险弹窗

## 行情模块与上游来源

首页“今日实时行情”虽然只有一个前端接口 `GET /realtime/market-snapshot`，但后端内部是多源聚合：

| 行情模块 | 本地接口 | 后端实现 | 上游来源 / 兜底 |
| --- | --- | --- | --- |
| 指数行情 | `GET /realtime/market-snapshot` | `RealtimeMarketProvider._fetch_indexes` | Sina `https://hq.sinajs.cn/list=...` |
| 红绿家数 | `GET /realtime/market-snapshot` | `RealtimeMarketProvider._fetch_live_breadth` | 同花顺市场总览页优先，失败时退回东方财富全 A 按市场段分页聚合统计，再失败退回本地 `warehouse` 最近交易日统计 |
| 强势板块 | `GET /realtime/market-snapshot` | `RealtimeMarketProvider._fetch_live_sectors` | 同花顺概念题材板块优先，再退回东方财富概念板块、同花顺行业板块、东方财富行业板块、Sina 板块；这些真实板块源都不可用时，才用同花顺热点归因标签兜底 |
| 昨日强势追踪 | `GET /realtime/market-snapshot` | `RealtimeMarketProvider._snapshot_from_local` + `RealtimeMarketProvider._local_market_groups` | 使用当前实时板块成员与本地 `warehouse` 前一交易日涨跌幅聚合，无法实时取板块成员时退回空列表 |
| 市场资讯 | `GET /market/news` | `MarketNewsProvider.latest_news` | 东方财富栏目、东方财富要闻页、财联社电报 |
| 风险清单 | `GET /risk/alerts` | `RiskAlertProvider.current_alerts` | 本地潜在风险观察名单、东方财富、Sina 名称扫描、AData、本地仓库兜底 |

## 数据导入与写入规则

当前数据写入规则：

1. 历史数据导入 / 补齐时，同时写 `LocalCache` 和 `Warehouse`。
2. 覆盖范围查询优先读 `Warehouse`，没有命中才退回旧缓存。
3. 回测读取优先读 `Warehouse` 指定日期区间，没有数据才退回旧缓存。
4. 桌面端已保存策略写入 `运行产物\策略配置\saved-strategies.json`。

## 开发与验证

常用命令：

```powershell
python -m pytest tests/test_data_operations.py tests/test_data_service_http.py tests/test_build_scripts.py -q
npm run test:ui -- --run
powershell -ExecutionPolicy Bypass -File scripts/build-data-service.ps1
npm run tauri -- build --debug
```

如果只看本地服务健康状态，可手动检查：

```powershell
Invoke-WebRequest http://127.0.0.1:<port>/health | Select-Object -ExpandProperty Content
```

期望重点：

- `cache_path` 指向 `D:\New project 6\运行产物\本地数据仓` 或 `D:\New project 6\.astock-cache`
- 红绿家数、强势板块、昨日强势追踪非空
- 已保存策略文件落在 `运行产物\策略配置`

## 清理规则

可以安全清理的生成物：

- `.pytest_cache`
- `dist`
- `.pyinstaller`
- `src-tauri\target`

不要清理：

- `运行产物\本地数据仓`
- `运行产物\签名密钥`
- 你自己仍在使用的安装包或桌面运行目录

## 相关文件

- [项目说明书.md](/D:/New%20project%206/项目说明书.md)
- [运行产物/目录说明.md](</D:/New project 6/运行产物/目录说明.md>)
