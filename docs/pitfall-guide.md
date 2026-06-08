# A 股策略回测工作台避坑指南

本文给接手者做快速防偏。先按这里确认边界，再决定要不要改代码。

## 1. 工作目录和保护边界

1. 真实业务根目录是 `D:\New project 6`。`C:\Users\大帝之资\Documents\New project 6` 只是 Junction，命令、测试、构建、验证都从 D 盘根目录执行。
2. 接手后先看 `README.md`、`项目说明书.md`、`docs/dev.md`、`docs/release.md`，再跑 `git status --short --untracked-files=all`、`git diff`、`git remote -v`、`git branch --show-current`。
3. 不覆盖无关未提交修改。遇到不属于当前任务的 untracked 文件，只记录和避开。
4. 不清理、不删除、不迁移 `D:\New project 6\运行产物`。这里是业务数据、安装包、签名密钥和本地数据仓的归宿，不是普通缓存。
5. 不修改 token、CORS、开放 API 安全边界，除非任务明确要求并单独验证。

## 2. 模块边界

这些模块不要混成一个模块：

1. 今日实时行情：`/realtime/market-snapshot`
2. 行情评价：`/market/commentary`
3. 新闻汇总：`/market/news-summary`
4. 资讯与事件：`/market/news`
5. 同花顺复盘/早盘：`/market/fupan`、`/market/zaopan`
6. user 模式候选：`/run/backtest/stream` 的最终 `result.latest_strategy_matches.matches`

前端只消费结构化后端响应，不散落上游 URL、爬虫逻辑或字段清洗规则。行情、复盘、候选数据源必须封装在后端 provider。

## 3. 实时行情和爬虫链路

红绿家数不要只看 `status=live`。必须检查 `breadth.total` 是否达到全市场宽度：低于 3000，或低于本地最近股票池合理比例，都要判定该来源失败并写入 diagnostics。`total=192`、`total=26` 这类局部样本不能展示成全市场宽度。

红绿家数链路要保持严格：

1. 同花顺市场总览。
2. Sina 批量实时个股。
3. Tencent 批量实时个股。
4. AKShare 实时个股。
5. 后端重型公开行情爬虫。
6. 东方财富轻量 A 股 spot 只能是受控备选，默认不能混入主链。

强势板块可以走独立 fallback：

1. 同花顺概念页。
2. 同花顺行业页。
3. Sina 行业板块。
4. AKShare 概念/行业板块。
5. 东方财富板块接口只能作为受控备选，概念和行业都试，多 host 快速失败。
6. 同花顺热点归因只作为题材候选，不伪装成板块涨幅。
7. 仍失败才回退本地最近交易日题材聚合或空态。

板块源要有单源短超时，否则同花顺一个慢请求会吃完整体预算，东方财富 fallback 根本来不及执行。红绿家数和强势板块可以共享页面展示，但 provider 链路不能互相偷数据。

重型爬虫边界：

1. 优先公开 XHR，其次 Playwright headless DOM。
2. 固定超时、快速失败、可记录最近成功结果。
3. 不阻塞首页刷新。
4. 不做登录、cookie 池、代理池、验证码绕过、付费抓取。
5. 所有失败写 diagnostics，不能静默把局部数据包装成完整数据。
6. 最近成功红绿家数不能参与本次 `live` 判定；当前公开 XHR/DOM 都失败时应返回失败，让上层统一走最近成功完整快照或本地最近交易日，并标记为 `stale`。

资金流补齐边界：

1. `backend/astock_backtester/data/capital_flow_crawler.py` 已纳入 1.1.1，但只作为低层只读 crawler/provider。
2. 它返回结构化资金流行、`failures` 和 `diagnostics`，不直接写 `Warehouse` 或 `LocalCache`。
3. 大陆 IP 或风控导致东方财富断连时，只允许做固定超时、少量公开 header 变体重试、同进程最近成功行缓存和清晰 diagnostics；不做登录、cookie 池、代理池、验证码绕过或付费抓取。
4. 1.1.1 已由更高层 backfill 服务接入数据中心：`/fetch/daily-bars` 优先合并 crawler 的 `main_net_inflow`，`/fetch/capital-flow` 只补齐已有日线的资金流缺口。
5. 最近成功行缓存命中时必须追加 `recent_success_cache_used`，同时保留原始 `failures`，不能把断连伪装成实时成功。
6. 写仓只能发生在高层服务里，失败 symbol 必须作为 `failures/diagnostics` 返回 UI，不能让 crawler 直接写仓。

## 4. 行情评价

行情评价必须是严格状态机，不是新闻拼装器：

1. 盘中完整快照：指数、完整红绿家数、强势板块都可用时生成盘中评价。
2. 午间、收盘后、非交易日：使用最近成功完整快照或最近交易日回顾，并明确 mode。
3. 实时失败：先用最近成功完整快照或同花顺复盘。
4. 复盘也不可用：返回后端本地简短防守判断。
5. 新闻只能作为辅助线索，不能包装成确定行情结论。

如果复盘来源不是同花顺正文，要在文案中明确：

1. `ths-fupan` / `ths-zaopan`：同花顺复盘 / 早盘正文。
2. `ths-fupan+market-fallback` / `ths-zaopan+market-fallback`：公开行情兜底，`source_url` 必须是真实公开行情链接。
3. `ths-fupan+local-brief` / `ths-zaopan+local-brief`：本地简短防守口径，`source_url` 必须为空。

不要把公开行情兜底或本地短判断写成“同花顺公开页面”。

## 5. 同花顺复盘和早盘

复盘/早盘是独立模块，不承载 user 模式候选。

1. 原文按钮必须打开真实 `source_url` 或文章链接；无链接时禁用并说明。
2. 清洗重复时间戳、纯数字汤、`% %`、行业名后跟神秘数字等噪声。
3. 个股表格要识别为“个股 / 涨幅 / 现价”，不要误标为题材原因。
4. 同花顺主页请求失败时，`/market/fupan` 和 `/market/zaopan` 不能只返回空入口；应先走公开行情结构化 fallback，再退到本地简短 section。
5. 本地简短复盘 / 早盘只能给防守口径，不能伪装成已读取同花顺正文。

## 6. user 模式候选

user 模式候选只来自 `/run/backtest/stream` 最终 `result.latest_strategy_matches.matches` 或未来独立后端候选 provider。

展示要求：

1. 显示代码、名称、现价或本地收盘价、涨跌幅、匹配理由、`rank_score`。
2. 优先用实时行情补现价/涨跌幅；失败才回退本地最近交易日。
3. 回退本地时，文案和列名必须明确“本地最近交易日 / 非实时”。
4. 不把候选塞进同花顺复盘正文，也不从前端临时拼爬虫数据。

## 7. 数据中心和交易日历

`/coverage/daily-bars` 必须使用 A 股交易日历。春节、清明、劳动节、国庆等合法休市日不能被普通工作日 `freq="B"` 误报为 `missing_trade_dates`。
1.1.1 内置 2024、2025、2026 年 A 股休市区间；后续跨年发布前要先按交易所公告刷新 `backend/astock_backtester/data/trading_calendar.py` 并补对应覆盖测试。

数据仓路径规则：

1. 主仓：`D:\New project 6\运行产物\本地数据仓`
2. `.astock-cache`：指向主仓的 Junction，只是入口别名。
3. 旧仓：`D:\New project 6\运行产物\本地数据` 不能作为发布态候选或活跃写入源；确认绝对路径后可以只删除该旧目录残留，不能清理整个 `运行产物`。
4. UI、补齐、回测的活跃写入源必须是主仓。
5. 不要凭 `year=2026` 文件夹判断覆盖到了 2026，直接读 parquet 的 `trade_date.max()`，再对比 `Warehouse.coverage()`、`LocalCache.coverage()`、`/health`、`/coverage/daily-bars`。

## 8. 回测流接口

`/run/backtest/stream` 是 NDJSON 流，不能用 `Invoke-RestMethod` 当普通 JSON 判断。探针要逐行读取：

```python
events = [json.loads(line.decode("utf-8")) for line in resp.readlines() if line.strip()]
assert events[-1]["type"] == "result"
```

真实验证要使用 sidecar 和主仓，限制股票池和日期范围可以很小，但必须拿到最终 `result`，并确认 `latest_strategy_matches` 已记录。

## 9. 桌面安装和 sidecar

安装器退出码 0 不等于 sidecar 已替换。覆盖安装后：

1. 先停旧桌面进程和旧数据服务。
2. 比较安装目录 sidecar 和工作区 sidecar 的 SHA256。
3. 再探测 `/ping`、`/health`、`/coverage/daily-bars`、`/realtime/market-snapshot`、`/market/commentary`、`/market/fupan`、`/market/zaopan`、`/run/backtest/stream`。

路径传参是最容易卡住的点。`D:\New project 6\运行产物\本地数据仓` 有空格和中文，PowerShell `Start-Process -ArgumentList @(..., $cacheDir)` 可能拆参。要么传已加引号的单个参数字符串，要么用 Python `subprocess.Popen([...])` 参数数组。

不要落地临时 `.ps1`；必须写时用 UTF-8 BOM，跑完立即删除。探针 `.py`、`.json`、`.log` 也不要留下进 git diff。

## 10. 构建、签名和发布

1. 优先用项目内工具，不靠全局 PATH 猜：`.tools\node-v20.18.1-win-x64\node.exe` 和 `.tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe`。
2. PyInstaller 的 optional warning 不等于失败，关键看 `src-tauri\bin\astock-data-service.exe` 是否生成。
3. `npm run tauri -- build` 退出码 1 不一定代表 NSIS 安装包失败。NSIS `.exe` 存在只能说明本地安装包生成；`.sig` 和 `latest.json` 才决定 updater 资产是否有效。
4. 签名密钥优先看 `D:\New project 6\运行产物\签名密钥`。不要把私钥内容写进 Git、日志、说明书或最终回复。
5. 没有真实 `.sig` 时，只能报告“安装包已生成但签名发布阻塞”，不能伪造或复用旧 `latest.json`。
6. Git 推送前确认 remote、branch、status。remote 应为 `https://github.com/dzc-bit/Astock-backtester.git`。

## 11. 接口探针习惯

不要把所有端点串在一个大脚本里。逐个端点输出：

1. endpoint
2. elapsed
3. 核心字段
4. 错误信息

实时行情验收不能只看 `status=live`，还要断言 `breadth.total >= 3000` 或满足本地股票池比例。行情评价要反查它使用的 breadth 是否有效，确认 diagnostics、summary、mode 没有把不完整红绿家数包装成确定结论。

## 12. 本轮实现仍需改进

1. 最初强势板块 fallback 已加回东方财富板块接口，但没有第一时间补“同花顺单源慢导致 fallback 来不及执行”的测试。后面已补单源短超时，但这个缺口本该在第一版设计时发现。
2. 先修了 `/market/commentary` 的本地简短判断，再发现 `/market/fupan` 自身在同花顺请求异常时仍可能是空入口。以后遇到“结构化复盘不可用”，应同时验证消费端和源端。
3. 本地简短复盘目前是安全、保守的兜底，展示可用性比以前好，但信息密度不高。后续可以在后端 provider 中用本地主仓最近交易日、指数和强势板块聚合生成更有内容的简短判断，同时保持“非实时 / 本地”标签。
4. 前端仍保留 `frontend-fallback`。只要本地服务端口不可达或 base_url 过期，前端仍会进入前端兜底。后续应在 `loadMarketCommentary` 失败时先重新 `ensureDataService` 或探测 `/health`，重试一次后端 `/market/commentary`，再显示前端 fallback。
5. 这轮验证主要是相关后端测试和 TypeScript 类型检查，没有做安装后 sidecar 探针。只要涉及桌面发布或安装包，就必须补安装后端点验证和 sidecar hash 比对。
6. 文档中已有部分旧表述可能仍写“实时失败后用同花顺复盘总评”，但现在实现会区分同花顺正文、公开行情兜底、本地简短复盘。后续整理说明书时应同步这些措辞。
