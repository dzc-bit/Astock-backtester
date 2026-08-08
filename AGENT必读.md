# AGENT 必读

新 agent 只需要读这一份即可开始。`README.md` 和 `docs/*` 只作补充背景，不是接手前置条件。`项目说明书.md`、`应用创新类项目报告.md` 和 `演示文档操作提醒.md` 都是本地人工材料，不上传 GitHub，也不作为 agent 接手依据。

这份文档把前面花了很久才踩明白的坑收进来：路径、未提交改动、实时行情完整性、爬虫边界、资金流位置、A 股交易日历、签名更新、安装后 sidecar 验证和临时产物清理。

## 1. 工作区和 git

真实业务根目录是：

```text
D:\New project 6
```

`C:\Users\大帝之资\Documents\New project 6` 是 Junction。所有命令、测试、构建、探针和 git 操作都必须在 `D:\New project 6` 执行。

接手后先跑：

```powershell
git status --short --untracked-files=all
git diff
git remote -v
git branch --show-current
```

期望 remote：

```text
https://github.com/dzc-bit/Astock-backtester.git
```

保护已有未提交修改。不要覆盖无关文件，不要清理、删除、迁移 `D:\New project 6\运行产物`。版本号统一跟随桌面端当前版本，当前为 `1.3.6`，除非用户明确要求改版本。

## 2. 绝对不要碰错边界

- 不修改 token、CORS、开放 API 安全边界。
- 不改无关模块，不做顺手重构。
- 不清理整个 `运行产物`。
- 不提交私钥、安装包、`.sig`、临时 `latest.json`、探针脚本、日志或运行数据。
- 不提交本地人工说明和演示材料：`项目说明书.md`、`应用创新类项目报告.md`、`演示文档操作提醒.md`。
- 前端只消费后端结构化响应，不写上游 URL、爬虫逻辑或字段清洗规则。
- 清理临时文件时不要直接执行 `git clean -fdX` 或等价的一把梭命令，因为它会把 `.tools`、`node_modules`、`src-tauri\bin`、`src-tauri\target` 和 `运行产物` 这类仍需保留的本地工具、构建产物或用户数据也列入删除范围；只点名删除 `.pytest_cache`、`.ruff_cache`、`.tmp`、`.pyinstaller`、`__pycache__` 等明确临时缓存。

## 3. JSON 文件别误判

仓库根目录没有很多业务 JSON 是正常的。源码 JSON 主要是：

- `package.json`
- `package-lock.json`
- `tsconfig.json`
- `src-tauri/tauri.conf.json`
- `src-tauri/capabilities/main.json`

这些 JSON 是运行或发布产物，不应作为源码提交：

- `运行产物\策略配置\saved-strategies.json`
- `release-assets\latest.json`
- 临时探针 JSON
- 临时日志 JSON

`latest.json` 只有在发布流程中由本次真实 `.sig` 生成才可信；验证后本地临时文件通常要删除，不能手写、伪造或复用旧文件。

## 4. 模块必须独立

不要把这些模块混成一个：

| 模块 | 接口或来源 |
| --- | --- |
| 今日实时行情 | `GET /realtime/market-snapshot` |
| 行情评价 | `GET /market/commentary` |
| 新闻汇总 | `GET /market/news-summary` |
| 资讯与事件 | `GET /market/news` |
| 同花顺复盘 | `GET /market/fupan` |
| 同花顺早盘 | `GET /market/zaopan` |
| user 模式候选 | `/run/backtest/stream` 最终 `result.latest_strategy_matches.matches` |
| 资金流补齐 | `POST /fetch/daily-bars`、`POST /fetch/capital-flow` |

复盘正文不能塞 user 候选；新闻不能替代行情评价；实时行情失败不能拿本地历史数据伪装成 live。

## 5. 实时行情完整性

红绿家数不能只看 `status=live`。必须检查：

- `breadth.total >= 3000`
- 或满足本地股票池合理比例

`total=192`、`total=26` 这类局部样本必须判失败并写入 diagnostics，不能标记为全市场 live。

红绿家数 provider 链：

1. 财联社行情页对应的签名 XHR：`https://www.cls.cn/quotation` 背后的 `x-quote.cls.cn/quote/index/home`，解析 `up_down_dis`；该来源拿到数字后直接展示，不再用 `total>=3000` 额外丢弃。
2. 同花顺市场总览：`q.10jqka.com.cn/index/index/board/all/`
3. Sina 批量实时个股：`hq.sinajs.cn/list=...`
4. Tencent 批量实时个股：`qt.gtimg.cn/q=...`
5. AKShare：`stock_zh_a_spot_em()`
6. 后端重型公开行情爬虫：公开 XHR 优先，headless DOM 其次。
7. 东方财富轻量 spot：只作受控备选，必须有超时、字段校验、数量校验和 diagnostics。

财联社红绿家数是主源且已经代表全市场分布，不能在请求它之前先扫本地股票池或 coverage 数量；本地完整性扫描只允许在非财联社来源需要 `total>=3000`/本地比例校验时懒加载，否则主仓数据量大时会先耗尽红绿家数 2 秒预算，导致 CLS 明明可用却被判超时。

强势板块 provider 链：

1. 同花顺概念题材页。
2. 同花顺行业页。
3. Sina 行业板块。
4. AKShare 概念/行业板块。
5. 东方财富概念/行业板块受控备选。
6. 同花顺热点归因只作题材候选，不伪装成板块涨幅。

重型爬虫边界：

- 固定短超时，快速失败。
- 缓存最近成功结果只能作为 stale/fallback 明确标注。
- 当前请求失败时，内部缓存不能参与本次 live 判定。
- 不做登录、cookie 池、代理池、验证码绕过或付费抓取。

同花顺大盘评分卡片规则：

- 主源是 `q.10jqka.com.cn/api.php?t=indexflash&` 的 `dppj_data`，这是 10 分制同花顺大盘评级。
- 该接口缺少浏览器脚本生成的 `v` cookie 时会 403；后端必须先执行同花顺 `chameleon` 浏览器脚本（当前用 Node/jsdom）生成本次请求 cookie，再请求 `indexflash`。
- 桌面安装版 sidecar 旁边必须同时带 `node.exe`、`ths-cookie-worker.cjs`、`xhr-sync-worker.js`；只在开发机 `.tools` 里有 Node 不算安装版可用。
- 评分解析只能读取 `indexflash` 原始载荷或 `dppj_data` 等结构化字段；HTML 页面兜底只能从可见文本解析，不能把 `<div id="dppj">` 这类标签属性里的数字当评分。
- 成功解析后写入 `emotion.market_degree` / `emotion.market_degree_label`，前端“大盘评分”卡片直接消费该值。
- 不要用财联社热度、新闻、本地启发式或其他评分静默替代同花顺评分；失败时保留 diagnostics/failures 并显示不可用或明确 fallback。

## 6. 行情评价状态机

`/market/commentary` 必须是状态机：

1. 完整实时快照可用，生成盘中评价。
2. 实时失败，使用最近成功完整快照。
3. 再失败，尝试同花顺复盘或公开行情兜底。
4. 最后使用本地简短判断。
5. 新闻只作辅助线索，不能生成确定行情结论。

不要把不完整红绿家数、新闻列表、旧快照包装成实时盘面。

## 7. 同花顺复盘和早盘

`/market/fupan` 和 `/market/zaopan` 是独立模块，不承载 user 候选。

source 语义：

- `ths-fupan` / `ths-zaopan`：真实同花顺正文。
- `ths-fupan+market-fallback` / `ths-zaopan+market-fallback`：公开行情兜底，`source_url` 必须是真实公开行情链接。
- `ths-fupan+local-brief` / `ths-zaopan+local-brief`：本地简短防守口径，`source_url` 必须为空。

原文按钮只能打开真实 `source_url` 或文章链接。无链接时前端禁用。

## 8. 资金流 crawler

资金流 crawler 已纳入当前版本，并且是主要资金流补齐手段：

```text
backend/astock_backtester/data/capital_flow_crawler.py
tests/test_capital_flow_crawler.py
docs/capital-flow-crawler-report.md
```

边界：

- 东方财富公开 XHR 是主源，百度公开资金流是受控备选源；允许继续接入同花顺或其他可靠公开接口作为备用。
- 返回 `rows/failures/diagnostics`，日期覆盖不足必须通过 diagnostics/failures 明确展示，不能把未补齐股票算完成。
- crawler 本身不直接写 `Warehouse` 或 `LocalCache`；写入边界在 operations/service/sync 层。
- `/fetch/daily-bars` 负责把 `main_net_inflow` 合并到新拉取的日线。
- `/fetch/capital-flow` 负责补齐资金流缺口；即使个股暂无日 K，也允许先写资金流独立行。
- 日线覆盖、回测和实时行情本地兜底只认 OHLC 完整行；资金流独立行不能让股票变成可回测日线数据。

大陆 IP 或上游风控导致断连时，可以做固定 header 变体、Eastmoney `ut` 参数变体、curl_cffi 浏览器 TLS 指纹、短超时、重试退避、限速、分批并发、备用源切换、JSON/JSONP 响应解析、同进程最近成功行缓存和 diagnostics；不能做登录、cookie 池、代理池、验证码绕过或付费抓取。最近成功缓存命中时必须保留原始 failure，并追加 `recent_success_cache_used`。

## 9. 数据中心和交易日历

`/coverage/daily-bars` 必须使用 A 股交易日历。不要用普通工作日直接判断缺失交易日。

数据中心的“补全缺失数据”默认是全市场补齐：股票代码为空时走 `/sync/full-market`；只有用户显式输入股票代码时，才走指定股票 `/fetch/daily-bars`。覆盖表的 `missing_rows` 只能来自刷新后的真实仓库 coverage，前端绝不能用本次 `imported_rows` 抵扣或估算缺失行，否则会出现“任务没补完却显示缺失为 0”的错误。同步进度里 `imported_rows` 表示接口返回并写入/合并的行，不等于缺口减少；全市场日线任务的实际补缺必须拆分展示后端 `filled_daily_rows` 和 `filled_market_cap_rows`，`filled_missing_rows` 仅保留为兼容总数，不能当成单一日线缺口。

全市场日线同步的股票池必须优先来自本地仓库全量 OHLC 股票集合，不能用本次补齐日期范围过滤后的股票集合。否则缺最新交易日 OHLC 的股票会在任务创建时被排除，出现覆盖表显示仍有缺口但同步任务总数小于本地股票数的问题。

全市场日线同步的跳过条件必须同时满足 OHLC 完整和 `float_market_cap` 完整。不能因为某只股票 OHLC 已有就跳过它的市值缺口；市值缺口应随 `/sync/full-market` 或指定 `/fetch/daily-bars` 的日线补齐一并修复。后端计算 `filled_missing_rows` 时应复用任务开始时的仓库完整性快照，避免每个写入批次重复扫仓拖慢数据中心。

回测设置的默认日期在用户未手动编辑前应跟随 `daily_bars` coverage 的最新日期，并按最近 A 股交易日范围回填；用户一旦手动修改日期或点“套用数据中心日期”，后续不要再自动覆盖用户选择。这样本地仓库已到 2026-06-18 时，回测候选不应仍停在旧的 2026-01-20。

补缺日线 provider 顺序必须以公开 HTTP 爬虫为主：`HttpAStockProvider -> ADataProvider -> AkshareProvider`。`HttpAStockProvider` 的百度日 K 线普通 `requests` 可能被 403，必须保留 `curl_cffi` 浏览器 TLS 指纹传输作为同一 HTTP 主源内的备用，不要因为普通 requests 403 就直接跳到 adata/AKShare。`adata` 数据可能只覆盖到 2025 年底，不能放在近期补缺主路径第一位；AKShare 只能作为最后保底。所有来源都失败或返回空时，错误必须聚合展示每个 provider 的尝试结果，不能只把 AKShare 的断连显示成唯一失败原因。

`/health` 不能同步阻塞重型 `warehouse.coverage()` 扫描。数据中心连接和操作后刷新应快速返回最近 coverage 快照，并用后台刷新更新缺失行数；不要让 60 秒级 coverage 扫描卡住“本地服务已连接”、按钮状态或全市场同步进度。

后台刷新期间如果 `/health` 返回三项 coverage 全是 `symbols=0`、无日期、`missing_rows=0` 且 `coverage_refreshing=true`，前端不能把它当权威结果覆盖已有覆盖表；应保留旧覆盖并继续轮询，等刷新完成后的真实快照再更新。

春节、清明、劳动节、国庆等合法休市日不能进入 `missing_trade_dates`。

主仓路径：

```text
D:\New project 6\运行产物\本地数据仓
```

旧路径：

```text
D:\New project 6\运行产物\本地数据
```

旧路径不能作为 UI、补齐或回测的活跃写入源。如果任务要求删除旧路径，必须确认绝对路径，只处理旧目录本身，不能清理整个 `运行产物`。

## 10. user 模式候选

正式来源：

```text
POST /run/backtest/stream
最后一个 NDJSON 事件 result.latest_strategy_matches.matches
```

旧的非流式 `/run/backtest` 接口不是兼容目标，不要恢复；前端也不要继续保留旧 `matched_stocks` 结果字段。user 候选只认 `latest_strategy_matches`。

不要把 user 候选塞进同花顺复盘正文。

如果实时失败并回退本地最近交易日，前端必须标注：

- 本地最近交易日
- 非实时

## 11. 接口探针

安装后至少探测：

- `GET /ping`
- `GET /health`
- `GET /market/finance`
- `POST /coverage/daily-bars`
- `GET /realtime/market-snapshot`
- `GET /market/commentary`
- `GET /market/fupan`
- `GET /market/zaopan`
- `POST /run/backtest/stream`

`/run/backtest/stream` 是 NDJSON，不能用 `Invoke-RestMethod` 当普通 JSON 判断。用 Python/Node 逐行读：

```python
events = [json.loads(line) for line in response_text.splitlines() if line.strip()]
assert events[-1]["type"] == "result"
```

中文路径和空格路径容易被 PowerShell 拆参。启动 sidecar 探针时优先用 Python `subprocess.Popen([...])` 参数数组，不要把 `D:\New project 6\运行产物\本地数据仓` 拼成未转义字符串。

不要落地长期探针。临时 `.py`、`.ps1`、`.js`、`.json`、`.log` 跑完删除。

## 12. 桌面安装包构建、签名和覆盖安装

本节是 2026-07-17 构建 `1.3.6` 安装包时实际使用的流程。所有工具、缓存、构建产物和安装包均在 `D:\New project 6` 所在的 D 盘；不要重新下载工具，也不要再使用或恢复 `C:\BuildTool`、`C:\BuildTools` 下的构建环境。

### 固定工具与目录

以下内容已经存在于项目内，构建前只检查，不执行 `npm install`、Rust 安装器、NSIS 安装器或任何额外下载：

```text
D:\New project 6\.tools\node-v20.18.1-win-x64\node.exe
D:\New project 6\.tools\node-v20.18.1-win-x64\npm.cmd
D:\New project 6\.tools\python-build\Scripts\python.exe
D:\New project 6\.tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe
D:\New project 6\.tools\msvc-build-tools\VC\Auxiliary\Build\vcvars64.bat
D:\New project 6\src-tauri\target\.tauri\NSIS
```

`src-tauri\tauri.conf.json` 已设置 `bundle.useLocalToolsDir: true`，所以 Tauri 的 NSIS 缓存必须保留在 `src-tauri\target\.tauri\NSIS`，而不是用户目录或 C 盘。`.tools\llvm-mingw`、GNU/GNULLVM 工具链不是本流程的一部分，不能作为 MSVC 构建的替代品；是否清理它们必须另行确认，不能在构建命令中顺带删除。

签名私钥仅从以下运行产物路径读入当前 PowerShell 进程，绝不输出、写入日志或提交：

```text
D:\New project 6\运行产物\签名密钥\a-stock-backtester-v017.key
```

### 构建前检查

版本必须在 `package.json`、`pyproject.toml`、`src-tauri\Cargo.toml` 与 `src-tauri\tauri.conf.json` 保持一致；本次为 `1.3.6`。在项目根目录执行：

```powershell
$root = 'D:\New project 6'
Set-Location -LiteralPath $root

$nodeDir = Join-Path $root '.tools\node-v20.18.1-win-x64'
$cargoBin = Join-Path $root '.tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin'
$msvcEnv = Join-Path $root '.tools\msvc-build-tools\VC\Auxiliary\Build\vcvars64.bat'
$signingKey = Join-Path $root '运行产物\签名密钥\a-stock-backtester-v017.key'
$required = @(
  (Join-Path $nodeDir 'node.exe'),
  (Join-Path $nodeDir 'npm.cmd'),
  (Join-Path $root '.tools\python-build\Scripts\python.exe'),
  (Join-Path $cargoBin 'cargo.exe'),
  $msvcEnv,
  (Join-Path $root 'src-tauri\target\.tauri\NSIS\makensis.exe'),
  $signingKey
)
$missing = $required | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { throw "缺少项目内构建依赖：$($missing -join '; ')" }
```

不要把 `node.exe`、`npm.cmd`、Python、MSVC、Rust 或 NSIS 的路径改到 C 盘。缺少依赖时先停止并说明缺哪一项；只有用户明确授权后，才可将缺少的工具下载到项目内的 `.tools`。

### 本次实际构建命令

`tauri.conf.json` 的 `beforeBuildCommand` 会依次执行前端 `vite build` 与 `scripts\build-data-service.ps1`。后者用项目内 Python 打包 `astock-data-service.exe`，并把 `node.exe`、`ths-cookie-worker.cjs`、`xhr-sync-worker.js` 一起放入 `src-tauri\bin`。因此本次只运行一次 Tauri release 构建，不再另跑重复的前端或 sidecar 打包命令。

```powershell
$env:RUSTUP_HOME = Join-Path $root '.tools\rustup-home'
$env:CARGO_HOME = Join-Path $root '.tools\cargo-home'
$env:TAURI_SIGNING_PRIVATE_KEY = [System.IO.File]::ReadAllText($signingKey).Trim()
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ''

try {
  $build = "call `"$msvcEnv`" && set `"PATH=$cargoBin;$nodeDir;%PATH%`" && set `"RUSTUP_HOME=$env:RUSTUP_HOME`" && set `"CARGO_HOME=$env:CARGO_HOME`" && `"$nodeDir\npm.cmd`" run tauri -- build --ci"
  cmd.exe /S /C $build
  if ($LASTEXITCODE -ne 0) { throw "Tauri 构建失败，退出码：$LASTEXITCODE" }
} finally {
  Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY -ErrorAction SilentlyContinue
  Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY_PASSWORD -ErrorAction SilentlyContinue
}
```

本次产生的签名安装包为：

```text
D:\New project 6\src-tauri\target\release\bundle\nsis\A股策略回测工作台_1.3.6_x64-setup.exe
D:\New project 6\src-tauri\target\release\bundle\nsis\A股策略回测工作台_1.3.6_x64-setup.exe.sig
```

产物名、版本和 `.sig` 必须同一轮生成。非零退出码就是失败，不能因为目录里留下了旧 `.exe` 就把它当成本次可用安装包；签名缺失时也不得复用旧 `.sig` 或生成 `latest.json`。

### 覆盖安装和最低验证

覆盖安装前先退出桌面端及旧 sidecar，随后只使用刚生成的安装包静默安装：

```powershell
Get-Process -ErrorAction SilentlyContinue |
  Where-Object { $_.ProcessName -like '*astock*' -or $_.Path -like '*A股策略回测工作台*' } |
  Stop-Process -Force

$installer = Join-Path $root 'src-tauri\target\release\bundle\nsis\A股策略回测工作台_1.3.6_x64-setup.exe'
$install = Start-Process -FilePath $installer -ArgumentList '/S' -Wait -PassThru
if ($install.ExitCode -ne 0) { throw "覆盖安装失败，退出码：$($install.ExitCode)" }
```

本次静默覆盖安装退出码为 `0`。安装后必须启动安装版并确认没有访问开发地址 `127.0.0.1:1420`，再比较工作区与安装目录 `bin\astock-data-service.exe` 的 SHA-256，并至少探测 `/ping`、`/health`、`/market/finance`、`/realtime/market-snapshot`、`/market/commentary`、`/market/fupan`、`/market/zaopan` 与 `/run/backtest/stream`。`/run/backtest/stream` 是 NDJSON，需逐行解析并断言最后一条事件的 `type` 为 `result`。

桌面端 release 主程序必须使用 Windows GUI subsystem（`windows_subsystem = "windows"`）；启动 `astock-data-service.exe` 与同花顺 cookie worker 的 `node.exe` 都必须隐藏控制台窗口。安装成功不代表 sidecar 已替换，也不代表服务自动启动成功，这两项需要分别验证。

### GitHub 与清理边界

本次只构建并覆盖安装，未创建 GitHub Release。后续需要发布时，GitHub updater 资产名必须使用 ASCII，例如 `Astock-backtester_1.3.6_x64-setup.exe`；只能由本次真实 `.sig` 使用 `scripts\write-latest-json.ps1` 生成 `latest.json`，且不提交安装包、`.sig`、`latest.json` 或私钥。

构建后可点名清理 `.pyinstaller`、明确的临时探针、日志和下载残留；不要使用 `git clean -fdX`，也不要删除 `.tools`、`node_modules`、`src-tauri\bin`、`src-tauri\target`、`src-tauri\target\.tauri\NSIS` 或整个 `运行产物`。

## 13. 验证命令

常规：

```powershell
python -m pytest tests -q
.\.tools\node-v20.18.1-win-x64\npm.cmd run test:ui -- --run
.\.tools\node-v20.18.1-win-x64\npm.cmd run typecheck
.\.tools\node-v20.18.1-win-x64\npm.cmd run build
.\.tools\node-v20.18.1-win-x64\npm.cmd run build:data-service
```

Rust：

```powershell
$env:CARGO_HOME='D:\New project 6\.tools\cargo-home'
$env:RUSTUP_HOME='D:\New project 6\.tools\rustup-home'
$env:PATH='D:\New project 6\.tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin;' + $env:PATH
cargo test --manifest-path src-tauri\Cargo.toml
```

资金流变更：

```powershell
python -m pytest tests/test_capital_flow_crawler.py tests/test_data_operations.py tests/test_data_service_http.py -q
```

行情/复盘变更：

```powershell
python -m pytest tests/test_market.py tests/test_data_service_http.py -q
```

## 14. 最终交付前检查

提交前确认：

```powershell
git status --short --untracked-files=all
git diff --check
git remote -v
git branch --show-current
```

不应留下：

- 临时探针 `.py` / `.ps1` / `.js`
- 临时 `.json`
- 日志
- 安装包
- `.sig`
- 临时 `latest.json`
- 无归属 untracked 文件

只提交源码、测试、文档和必要版本文件。提交前额外确认 `项目说明书.md`、`应用创新类项目报告.md`、`演示文档操作提醒.md` 仍为 ignored/untracked，不能进入 GitHub。
