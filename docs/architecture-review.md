# 架构审核报告 — A股策略回测工作台

> 审核人：高见远（架构师）
> 审核模式：只读审核，未修改任何代码文件
> 审核日期：2026-06-26
> 工作目录：`D:\New project 6`

---

## 审核摘要

本项目是一个三层架构的 Windows 桌面端 A 股策略回测工具：Tauri(Rust) 桌面容器 → React(TypeScript) 前端 → Python 本地 sidecar 后端。整体架构选型合理，模块划分层次分明，代码质量在同类桌面工具中属于上乘。但存在若干架构层面的改进空间，主要集中在 `service.py` 的路由-业务耦合、`Warehouse` 与 `LocalCache` 的职责重叠、前端 `App.tsx` 的状态集中度，以及版本号文档不同步等问题。

**问题统计：P0 × 0 | P1 × 6 | P2 × 8**

---

## 1. 架构合理性

### 1.1 三层架构边界评估

**结论：边界总体清晰，职责分层合理。**

| 层级 | 技术 | 职责 | 边界评价 |
|------|------|------|----------|
| 桌面容器 | Tauri 2 + Rust | 进程管理、sidecar 生命周期、文件原子写入、URL 安全打开 | ✅ 边界清晰，未越权处理业务逻辑 |
| 前端 | React 18 + TypeScript | UI 渲染、用户交互、HTTP/NDJSON 消费、本地状态管理 | ✅ 通过 `api.ts` 统一封装后端通信 |
| 后端 | Python stdlib `http.server` | 数据服务、回测引擎、数据同步、行情聚合 | ⚠️ 路由与业务逻辑耦合（见 §2.1） |

三层之间的通信模式为：
- **Rust → Python sidecar**：通过 `Command::spawn` 启动进程，通过 HTTP `/identity` 端点验证健康状态，通过文件锁 (`astock-data-service.lock.json`) 防止多实例冲突
- **React → Python sidecar**：通过 `fetch` 发送 HTTP 请求（JSON）或消费 NDJSON 流（回测进度、实时行情）
- **React → Rust**：通过 `@tauri-apps/api` 的 `invoke` 调用 Tauri 命令（`ensure_data_service`、`load_saved_strategies` 等）

### 1.2 HTTP + NDJSON 流式通信评估

**结论：选型合理，适合桌面端本地通信场景。**

- **NDJSON 流式回测**（`/run/backtest/stream`）：回测过程可能耗时较长，流式推送 phase/progress/trade 事件是正确的设计选择。前端 `consumeNdjsonStream` 实现了空闲超时和 abort 取消机制，健壮性良好。
- **NDJSON 实时行情**（`/realtime/market-snapshot/stream`）：将指数、红绿家数、板块分块推送，避免单次大响应阻塞 UI。
- **普通 HTTP JSON**：覆盖短请求场景（health、news、coverage 等）。

前端 `api.ts` 对每个端点设置了差异化超时（12s ~ 300s），且在非 Tauri 环境下有完整的 mock 回退（`apiMocks`），支持前端独立开发和测试。

### 1.3 Python stdlib `http.server` vs Flask/FastAPI

**结论：在当前项目约束下，stdlib `http.server` 是可接受的务实选择，但存在扩展性瓶颈。**（P2 — 建议）

**优势：**
- 零依赖：打包为 PyInstaller onefile 时不引入额外运行时依赖，减小包体积
- 启动快：无需 WSGI/ASGI 服务器初始化
- 完全控制：`ThreadingHTTPServer` + `BaseHTTPRequestHandler` 足以实现当前路由

**劣势：**
- 路由分发使用 `if/elif` 链（`do_GET` / `do_POST`），随着端点增长会变得难以维护
- 无中间件支持：CORS、日志、错误处理等横切关注点需手动在每个方法中重复
- 无请求体校验框架：依赖手动 `json.loads` + Pydantic `model_validate`
- 无 OpenAPI/Swagger 自动文档生成

**当前规模（~15 个路由端点）仍在可控范围内**，但如果后续需要增加认证、WebSocket、或更多端点，建议迁移到 FastAPI。

### 1.4 模块划分评估

**结论：模块划分层次分明，命名清晰。**

```
backend/astock_backtester/
├── service.py          # HTTP 服务入口 + 路由 + 业务编排
├── engine.py           # 回测引擎核心（纯函数式，无 IO 依赖）
├── backtest_runner.py  # 回测运行器（编排 engine + 指标计算）
├── condition_parser.py # 条件表达式解析
├── models.py           # Pydantic 数据模型
├── cli.py              # CLI 入口（供 Rust 调用）
├── data/
│   ├── providers.py    # 数据源抽象 + Composite 模式
│   ├── warehouse.py    # Parquet 分区数据仓
│   ├── cache.py        # 本地缓存（Legacy）
│   ├── operations.py   # 数据操作（import/fetch/coverage）
│   ├── sync.py         # 同步任务管理
│   ├── importer.py     # 数据标准化
│   ├── realtime.py     # 实时行情
│   ├── news.py         # 新闻
│   ├── risk.py         # 风险提示
│   └── ...
└── ...
```

- `engine.py` 作为回测引擎，**纯函数式设计**，接收 `pd.DataFrame` + 配置，返回 `BacktestResult`，无 IO 依赖。这是优秀的架构决策。
- `data/providers.py` 使用 `Protocol` + `CompositeProvider` 实现数据源组合，扩展性好。
- `data/operations.py` 将数据操作逻辑从 HTTP handler 中抽出，是正确的关注点分离。

---

## 2. 模块耦合度

### 2.1 `service.py` 路由与业务逻辑耦合（P1 — 重要）

**问题描述：**

`service.py`（778 行）中 `DataServiceHandler` 类同时承担了 HTTP 路由分发和业务逻辑编排的职责：

- `do_GET` 方法是一个长达 ~80 行的 `if/elif` 链，每个分支直接调用 `self.server.state` 上的各种 provider 方法
- `do_POST` 方法更长（~170 行），包含数据导入、同步、回测等复杂业务编排
- `_run_backtest_stream` 方法在 handler 中直接组装回测流程（读取数据 → 调用 `run_configured_backtest` → 流式推送事件）
- `_capital_flow_backfill_symbols` 是一个 ~35 行的复杂业务方法，却位于 HTTP handler 类中
- `_fetch_daily_bars_from_provider` 和 `_fetch_capital_flow_from_crawler` 作为 handler 方法，仅是对 `self.server.state` 的简单委托

**影响分析：**
1. **可测试性降低**：业务逻辑绑定在 HTTP handler 上，难以脱离 HTTP 上下文进行单元测试
2. **可维护性下降**：路由变更需要修改 handler 方法，业务逻辑变更也需要在同一文件中操作
3. **职责模糊**：handler 既是协议适配层（HTTP ↔ Python），又是业务编排层

**优化方案：**
将 `DataServiceHandler` 拆分为路由层和业务服务层：
```
service.py          # 仅保留 HTTP 路由分发 + 请求/响应序列化
routes/             # 按功能域拆分路由处理
├── backtest_routes.py    # /run/backtest/stream
├── data_routes.py        # /fetch/*, /import/*, /sync/*
├── market_routes.py      # /market/*, /realtime/*
└── strategy_routes.py    # /strategy/*, /symbols/validate
```
每个路由模块仅负责参数提取和委托调用，业务逻辑由对应的 service 类承载。

### 2.2 `engine.py` 与 data 层的依赖关系

**结论：耦合度极低，设计优秀。**

`engine.py` 的 `run_backtest` 函数仅依赖 `pandas` 和 `astock_backtester.models` / `astock_backtester.conditions`，完全不依赖 `data` 层的任何模块。数据读取由 `service.py` 的 `_read_backtest_frame` 负责，引擎只接收 `pd.DataFrame` 输入。这是教科书式的关注点分离。

### 2.3 前端 `App.tsx` 状态管理集中度（P1 — 重要）

**问题描述：**

`App.tsx`（915 行）中 `App` 函数组件维护了 **30+ 个 `useState`** 状态：

```typescript
const [coverage, setCoverage] = useState<DatasetCoverage[]>([]);
const [result, setResult] = useState<BacktestResult | null>(null);
const [streamedTrades, setStreamedTrades] = useState<...>([]);
const [strategy, setStrategy] = useState<StrategyConfig>(defaultStrategy);
const [settings, setSettings] = useState<BacktestSettingsConfig>(defaultSettings);
const [error, setError] = useState<string | null>(null);
const [dataService, setDataService] = useState<DataServiceStatus | null>(null);
const [isRunningBacktest, setIsRunningBacktest] = useState(false);
const [runPhases, setRunPhases] = useState<string[]>([]);
const [runProgressMessage, setRunProgressMessage] = useState<string | null>(null);
const [marketSnapshot, setMarketSnapshot] = useState<...>(null);
const [marketRefreshMeta, setMarketRefreshMeta] = useState<...>(...);
const [isLoadingMarket, setIsLoadingMarket] = useState(false);
const [marketNews, setMarketNews] = useState<...>(null);
const [clsFinance, setClsFinance] = useState<...>(null);
const [newsSummary, setNewsSummary] = useState<...>(null);
const [fupanBriefing, setFupanBriefing] = useState<...>(null);
const [zaopanBriefing, setZaopanBriefing] = useState<...>(null);
const [isLoadingNews, setIsLoadingNews] = useState(false);
const [riskAlerts, setRiskAlerts] = useState<...>(null);
const [isLoadingRiskAlerts, setIsLoadingRiskAlerts] = useState(false);
const [riskModalOpen, setRiskModalOpen] = useState(false);
const [recommendedStrategies, setRecommendedStrategies] = useState<...>([]);
const [conditionValidation, setConditionValidation] = useState<...>(null);
const [isValidatingCondition, setIsValidatingCondition] = useState(false);
const [stockSymbolValidation, setStockSymbolValidation] = useState<...>(null);
const [isValidatingStockSymbols, setIsValidatingStockSymbols] = useState(false);
const [settingsDraftErrors, setSettingsDraftErrors] = useState<string[]>([]);
const [strategySaveMessage, setStrategySaveMessage] = useState<string | null>(null);
const [pendingStrategySave, setPendingStrategySave] = useState<...>(null);
const [settingsDateTouched, setSettingsDateTouched] = useState(false);
```

此外，`App.tsx` 还内联了：
- 节假日判断逻辑（`A_SHARE_HOLIDAY_RANGES`、`isAShareTradingDay`、`recentTradingDateRangeEnding`）
- 回测参数校验逻辑（`validateBacktestSettings`，~50 行）
- 错误翻译逻辑（`translateError`，~20 行）
- 实时行情刷新轮询逻辑（`useEffect` 内 ~120 行）
- 辅助数据加载逻辑（`useEffect` 内 ~50 行）
- 策略保存提示逻辑（`queueStrategySavePrompt`、`confirmPendingStrategySave` 等）

**影响分析：**
1. **状态管理分散且难以追踪**：30+ 个 useState 之间的关系复杂（如 `result` ↔ `streamedTrades` ↔ `isRunningBacktest`），状态变更链路难以推理
2. **组件职责过重**：`App.tsx` 同时是布局容器、状态管理器、业务逻辑处理器和 API 调用者
3. **可扩展性受限**：新增功能需要在已经 900+ 行的文件中继续添加状态和逻辑
4. **性能优化困难**：由于所有状态集中在一个组件，任何状态变更都会触发整个组件树的重渲染

**优化方案：**
1. **引入轻量状态管理**：使用 Zustand 或 React Context + useReducer 将状态按领域拆分：
   - `useBacktestStore`：回测结果、运行状态、进度
   - `useMarketStore`：行情快照、新闻、资讯
   - `useStrategyStore`：策略配置、设置、校验
   - `useDataServiceStore`：服务状态、覆盖度
2. **提取自定义 Hook**：将 `useEffect` 内的复杂逻辑提取为 `useMarketRefresh`、`useAuxiliaryDataLoader` 等
3. **提取工具函数**：`validateBacktestSettings`、`translateError`、`isAShareTradingDay` 等移至 `utils/` 目录

### 2.4 Rust 层与 Python sidecar 的进程管理边界

**结论：边界清晰，管理健壮。**（P2 — 表扬）

`service_manager.rs` 实现了完善的 sidecar 生命周期管理：
- **端口选择**：`TcpListener::bind("127.0.0.1:0")` 动态分配空闲端口
- **健康检查**：通过 `/identity` 端点验证服务身份（port、cache_path、process_id、executable_sha256）
- **文件锁**：`astock-data-service.lock.json` 防止多实例冲突，支持锁超时重建
- **进程清理**：启动失败时 `stop_child_after_start_failure` 确保 kill 子进程
- **打包模式**：Release 使用 `astock-data-service.exe`（PyInstaller onefile），Debug 使用 `python -m astock_backtester.service`
- **窗口隐藏**：`CREATE_NO_WINDOW` 标志避免弹出控制台窗口

---

## 3. 数据流与状态管理

### 3.1 `Warehouse` 与 `LocalCache` 的职责重叠（P1 — 重要）

**问题描述：**

项目中存在两套数据存储机制：

| 特性 | `LocalCache` (`data/cache.py`) | `Warehouse` (`data/warehouse.py`) |
|------|------|------|
| 存储格式 | 单个 `daily_bars.parquet` | 按年分区 `year=YYYY/daily_bars.parquet` |
| 元数据库 | `metadata.sqlite`（仅 datasets 表） | `metadata.sqlite`（datasets + symbol_sync_state 表） |
| 写入方式 | 全量 combine_first + 覆写 | 分区 combine_first |
| 读取方式 | 全量读取 | 支持按日期范围、symbol 过滤的分区读取 |
| Coverage | 全量扫描计算 | 分区扫描 + 缺失行统计 |

**职责重叠表现：**
1. `service.py` 中 `_read_coverage_snapshot` 先尝试 `warehouse.coverage()`，失败后 fallback 到 `cache.coverage()`
2. `operations.py` 中 `build_daily_bars_coverage` 先尝试 `warehouse.read_daily_bars()`，空则 fallback 到 `cache.read_daily_bars()`
3. `operations.py` 中 `_safe_coverage` 同样先 warehouse 后 cache
4. `service.py` 中 `_read_backtest_frame` 先读 warehouse，空则 fallback 到 cache
5. 写入时同时写入两者：`cache.write_daily_bars(frame)` + `warehouse.write_daily_bars(frame)`

**影响分析：**
1. **维护成本翻倍**：两个类都需要维护数据格式兼容性
2. **数据一致性风险**：虽然每次写入都同时写两者，但如果其中一方写入失败，两者会不一致
3. **代码复杂度增加**：大量 fallback 逻辑分散在各处
4. **性能浪费**：`LocalCache.read_daily_bars()` 每次读取全部数据，当数据量大时（全市场 5000+ 股票 × 10 年日线）会非常慢

**优化方案：**
1. **短期**：明确 `Warehouse` 为主存储，`LocalCache` 仅作为迁移期的兼容层。在 `LocalCache` 的方法上标注 `@deprecated`
2. **中期**：将所有 fallback 到 `cache` 的逻辑移除，统一使用 `Warehouse`
3. **长期**：删除 `LocalCache` 类，或将其改造为 `Warehouse` 的薄包装

### 3.2 前端状态管理方式评估

**结论：纯 `useState` 对当前规模勉强可用，但已达瓶颈。**（见 §2.3）

当前前端未使用 Redux/Zustand/Jotai 等状态管理库。对于 30+ 个状态变量的大型组件，纯 `useState` 已经导致：
- 状态更新逻辑分散在多个 `useEffect` 和回调函数中
- 状态间的依赖关系隐式且难以追踪（如 `coverage` 变更触发 `settings` 的日期自动设置）
- 无法利用 selector 优化重渲染

### 3.3 Coverage 异步刷新机制评估

**结论：设计合理，但实现细节有改进空间。**（P2 — 建议）

`DataServiceState` 中的 coverage 异步刷新机制：

```python
def health_payload(self) -> ServiceHealth:
    refresh_finished = self._start_coverage_refresh()
    if refresh_finished is not None:
        refresh_finished.wait(HEALTH_COVERAGE_WAIT_SECONDS)  # 0.1s
    ...
```

- **TTL 缓存**：60 秒内不重复刷新（`HEALTH_COVERAGE_REFRESH_TTL_SECONDS`）
- **异步刷新**：在后台线程中执行 `warehouse.coverage()`，不阻塞 HTTP 响应
- **短等待**：health 请求最多等待 0.1 秒，超时则返回旧快照并标记 `coverage_refreshing=True`
- **强制刷新**：数据导入/同步后调用 `_start_coverage_refresh(force=True)`

**问题：**
1. `_coverage_lock` 是普通 `Lock`，`_start_coverage_refresh` 在持有锁的情况下启动线程，线程内又获取锁。虽然 Python 的 `Lock` 不可重入，但由于锁在启动线程前已释放（`with self._coverage_lock:` 块在 `Thread(target=refresh).start()` 之前结束），目前不会死锁。但这种模式容易在后续修改中引入死锁。
2. coverage 计算逻辑（`warehouse.coverage()`，~180 行）非常复杂，涉及多层 groupby 和集合运算，在全市场数据量大时可能耗时较长。

---

## 4. 安全性审核

### 4.1 CORS 设置 `Access-Control-Allow-Origin: *`（P2 — 建议）

**问题描述：**

`service.py` 中每个响应都设置了：
```python
self.send_header("Access-Control-Allow-Origin", "*")
self.send_header("Access-Control-Allow-Headers", "Content-Type")
self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
```

**影响分析：**
- **在本地桌面应用中风险较低**：Python 服务绑定 `127.0.0.1`，外部网络无法直接访问
- **残余风险**：用户浏览器中打开的恶意网页可以通过 `fetch("http://127.0.0.1:PORT/...")` 访问本地数据服务。虽然端口是动态分配的，但如果攻击者能猜到或探测到端口，就可以读取本地缓存数据或触发回测

**优化方案：**
1. 将 CORS origin 限制为 Tauri WebView 的 origin（通常是 `tauri://localhost` 或 `http://tauri.localhost`）
2. 或在请求中校验 `Origin` header，仅允许本地 Tauri origin
3. 或在 Tauri 配置中添加 CSP 策略限制 `connect-src`

### 4.2 Python HTTP 服务绑定 `127.0.0.1`

**结论：安全实践正确。**

`service_manager.rs` 中 `build_service_args` 硬编码 `--host 127.0.0.1`，确保服务仅监听本地回环地址，外部网络无法访问。

### 4.3 文件路径处理安全性

**结论：处理基本安全，但存在边缘情况。**（P2 — 建议）

- `commands.rs` 中 `backend_command` 通过 `python -m astock_backtester.cli` + stdin 传递 JSON payload，避免了命令行参数注入风险
- `service_manager.rs` 中 `resolve_cache_dir` 使用 `Path` API 而非字符串拼接，避免了路径遍历
- `commands.rs` 中 `open_external_url` 和 `open_ths_original_url` 有严格的 URL 校验：
  - `is_safe_external_http_url`：校验 scheme 为 http/https，无控制字符/空白，无用户名密码
  - `is_ths_original_article_url`：白名单域名 + 路径字符校验
- `commands.rs` 中 `spawn_external_url` 在 Windows 上使用 `rundll32.exe url.dll,FileProtocolHandler` 而非直接 `cmd /c start`，避免了 shell 注入

**潜在风险：**
- `service.py` 中 `/import/daily-bars` 端点接收 `payload["path"]` 作为文件路径，直接传给 `read_daily_bars(payload["path"])`。虽然当前仅从前端调用（用户选择文件），但如果未来有其他调用方，可能存在路径遍历风险。
- 中文路径和空格路径在 Rust → Python 的命令行传递中通过 `--cache-dir` 参数处理，`Command` API 会正确处理参数引用，目前无问题。

### 4.4 用户输入校验完整性（P1 — 重要）

**问题描述：**

后端输入校验存在以下不足：

1. **股票代码校验不完整**：`/fetch/daily-bars` 和 `/sync/full-market` 端点接收 `payload["symbols"]`，但没有在 handler 层校验格式（如长度、字符集）。虽然 `normalize_symbol` 会做标准化，但恶意输入（如超长字符串、特殊字符）仍会传递到 provider 层。
2. **日期格式校验缺失**：`payload["start_date"]` 和 `payload["end_date"]` 未在 handler 层校验格式，直接传递给 `pd.Timestamp()`。虽然 pandas 会抛出异常，但错误信息可能暴露内部实现。
3. **`/import/daily-bars` 的 `path` 参数**：直接使用用户提供的文件路径，未校验路径是否在允许范围内（如限制为用户目录或项目目录）。
4. **`/symbols/validate` 的 `symbols` 参数**：有 `isinstance(symbols, list)` 校验，但未限制列表长度和单个 symbol 格式。

**影响分析：**
- 当前作为本地桌面应用，攻击面有限（主要用户是本机使用者）
- 但如果未来开放网络访问或有多用户场景，这些校验不足会成为安全隐患

**优化方案：**
在 handler 层或中间件层添加统一的输入校验：
```python
def _validate_symbols(symbols: Any) -> list[str]:
    if not isinstance(symbols, list):
        raise ValueError("symbols must be a list")
    if len(symbols) > 10000:
        raise ValueError("too many symbols")
    result = []
    for s in symbols:
        code = normalize_symbol(str(s))
        if not code or not code.isdigit() or len(code) != 6:
            raise ValueError(f"invalid symbol: {s}")
        result.append(code)
    return result
```

---

## 5. 可扩展性

### 5.1 新增数据源 Provider 的扩展难度

**结论：扩展性优秀。**

`data/providers.py` 定义了 `DailyDataProvider` Protocol：
```python
class DailyDataProvider(Protocol):
    name: str
    def list_symbols(self) -> list[str]: ...
    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame: ...
    def fetch_share_history(self, symbol: str) -> pd.DataFrame: ...
```

新增数据源只需实现该 Protocol，然后在 `DataServiceState.__init__` 中添加到 `CompositeProvider` 的 providers 列表：
```python
self.provider = CompositeProvider([HttpAStockProvider(), ADataProvider(), self.akshare_provider])
```

`CompositeProvider` 自动处理 fallback 和错误聚合，新增 provider 无需修改任何现有代码。这是优秀的开闭原则实践。

### 5.2 新增回测条件/策略的扩展难度

**结论：扩展性良好，但条件分发机制有改进空间。**（P2 — 建议）

- `engine.py` 中 `_filter_mask_for_node` 使用 `if/elif` 链分发条件 ID（~70 行），新增条件需要在此函数中添加分支
- `conditions.py`（未直接审核，但从 import 推断）中的 `evaluate_condition` 和 `evaluate_group` 同样可能使用类似模式
- `condition_parser.py` 负责将自然语言/表达式解析为 `ConditionNode`

**优化方案：**
将条件分发改为注册表模式：
```python
CONDITION_HANDLERS: dict[str, Callable[[ConditionNode, pd.DataFrame], pd.Series]] = {}

def register_condition(condition_id: str):
    def decorator(func):
        CONDITION_HANDLERS[condition_id] = func
        return func
    return decorator

@register_condition("market_cap_between")
def _market_cap_between(node, data):
    return data["float_market_cap"].between(float(node.params["min"]), float(node.params["max"]))
```

### 5.3 新增前端页面的扩展难度

**结论：当前扩展性受限，需要重构。**（见 §2.3）

由于 `App.tsx` 集中了所有状态和逻辑，新增页面/功能需要：
1. 在 `App.tsx` 中添加新的 `useState`
2. 在 `App.tsx` 中添加新的 `useEffect` 或回调
3. 在 `App.tsx` 的 JSX 中添加新组件
4. 可能需要修改 `api.ts` 添加新的 API 函数

**优化方案：**
1. 引入路由（React Router 或 Tauri 的窗口管理），将不同功能页面拆分为独立路由
2. 将状态管理迁移到 Zustand store，各页面组件按需订阅
3. 将 `api.ts` 按功能域拆分（`api/backtest.ts`、`api/market.ts`、`api/data.ts`）

---

## 6. 版本一致性

### 6.1 版本号检查（P1 — 重要）

| 文件 | 版本号 | 状态 |
|------|--------|------|
| `package.json` | `1.3.5` | ✅ 当前版本 |
| `pyproject.toml` | `1.3.5` | ✅ 当前版本 |
| `backend/astock_backtester/__init__.py` (`__version__`) | `1.3.5` | ✅ 当前版本 |
| `src-tauri/Cargo.toml` | `1.3.5` | ✅ 当前版本 |
| `src-tauri/tauri.conf.json` | `1.3.5` | ✅ 当前版本 |
| `README.md` | `1.3.4` | ❌ **落后一个版本** |
| `项目说明书.md` | `1.3.1` | ❌ **落后四个版本** |
| `AGENT必读.md` | 无版本号（引用项目说明书） | ⚠️ 间接落后 |

**影响分析：**
- `README.md` 和 `项目说明书.md` 是面向人读的文档，版本不同步会导致混淆
- `项目说明书.md` 中还引用了旧版安装包路径 `A股策略回测工作台_1.3.1_x64-setup.exe`，已过时

**优化方案：**
1. 在 CI/CD 流程中添加版本一致性检查脚本，确保所有版本号同步
2. 或将版本号集中到单一配置文件（如 `version.json`），其他文件从中读取
3. 更新 `README.md` 版本为 `1.3.5`，更新 `项目说明书.md` 版本和安装包路径

### 6.2 `frontend/appVersion.ts` 评估

前端版本通过 `readPackageVersion` 从 `package.json` 读取，确保前端展示版本与 `package.json` 一致。这是一个好的实践。

---

## 7. 其他发现

### 7.1 `service.py` 中 `DataServiceState` 职责过重（P1 — 重要）

**问题描述：**

`DataServiceState` 类（~270 行）承担了过多职责：
- 初始化和管理 10+ 个 provider/cache/manager 实例
- 日志管理（`logs` deque）
- Coverage 缓存与异步刷新
- 股票代码校验（`validate_stock_symbols`）
- 同步符号列表获取（`sync_symbols`）
- 可执行文件哈希计算（`_hash_executable`）
- 身份信息生成（`identity_payload`）
- 资金流获取委托（`_fetch_capital_flow`）

这本质是一个"上帝对象"（God Object），违反了单一职责原则。

**优化方案：**
将 `DataServiceState` 拆分为：
- `ServiceContext`：仅持有各 provider/cache/manager 的引用（依赖注入容器）
- `CoverageCache`：负责 coverage 缓存与刷新
- `SymbolValidator`：负责股票代码校验
- `ServiceLogger`：负责日志管理

### 7.2 `operations.py` 函数过长（P2 — 建议）

`fetch_capital_flow_into_cache` 函数（~260 行）过于冗长，包含多个嵌套的条件分支和诊断逻辑。建议拆分为更小的子函数。

### 7.3 `sync.py` 中 `_count_full_market_filled_missing_rows` 性能隐患（P2 — 建议）

该方法在循环中使用 `existing_by_pair` 字典进行逐行查找，当数据量大时（全市场 5000+ 股票 × 数年日线），性能可能成为瓶颈。建议使用向量化操作替代逐行迭代。

### 7.4 `warehouse.py` 中 `coverage()` 方法复杂度过高（P2 — 建议）

`coverage()` 方法（~180 行）包含多层嵌套循环、groupby 和集合运算，且混用了 OHLC 完整性检查、market_cap 缺失统计、capital_flow 缺失统计和已知缺口日期过滤等多个关注点。建议拆分为独立的子方法。

### 7.5 前端 `api.ts` mock 回退设计（P2 — 表扬）

`api.ts` 中每个 API 函数都有 `if (!isTauriRuntime())` 的 mock 回退，使得前端可以在非 Tauri 环境（如 `vite dev`）下独立开发和测试。这是一个优秀的工程实践。

### 7.6 Rust `commands.rs` 原子文件写入（P2 — 表扬）

`write_saved_strategies_unlocked` 实现了完善的原子写入流程：
1. 先校验和编码 payload
2. 写入唯一临时文件（`pid.seq.tmp`）
3. `sync_all` 确保落盘
4. `rename` 原子替换
5. 失败时清理临时文件

配合 `SavedStrategiesFileLock`（跨进程文件锁）和 `saved_strategies_write_lock`（进程内 Mutex），实现了完善的并发安全。测试覆盖了并发写入、重命名失败、无效 payload 等场景。

### 7.7 `engine.py` 中涨停/跌停判断逻辑（P2 — 建议）

`_stock_limit_pct` 函数根据 symbol 前缀和 ST 状态返回涨停比例（10%/20%/5%），但这个逻辑分散在 engine 中。如果未来 A 股规则变化（如全面注册制），需要修改引擎代码。建议将涨停比例配置化。

### 7.8 错误处理一致性（P2 — 建议）

后端 HTTP 错误响应格式不完全统一：
- 大多数端点返回 `{"code": "request_failed", "message": str(exc)}`
- 但 `do_GET` 的 404 返回 `{"code": "not_found", "message": self.path}`
- 实时行情端点在异常时仍返回 200 + 降级快照

建议统一错误响应格式为 `{"ok": false, "code": "...", "message": "..."}`。

---

## 审核结论

### 优点

1. **三层架构选型合理**：Tauri + React + Python 的组合在 Windows 桌面端金融工具领域是务实且高效的选择
2. **回测引擎设计优秀**：纯函数式、无 IO 依赖，可测试性极高
3. **数据源扩展性强**：Protocol + Composite 模式，新增数据源零侵入
4. **Sidecar 管理健壮**：端口动态分配、健康检查、文件锁、进程清理一应俱全
5. **Rust 层安全实践**：原子文件写入、跨进程锁、URL 白名单校验
6. **前端 mock 回退**：支持非 Tauri 环境独立开发
7. **测试覆盖全面**：Rust 层有 30+ 测试，Python 层有 25 个测试文件

### 需改进

1. **`service.py` 路由-业务耦合**（P1）：需要拆分路由层和业务服务层
2. **前端 `App.tsx` 状态集中**（P1）：需要引入状态管理库并拆分组件
3. **`Warehouse` 与 `LocalCache` 职责重叠**（P1）：需要统一为单一存储层
4. **`DataServiceState` 上帝对象**（P1）：需要拆分为多个职责单一的类
5. **输入校验不完整**（P1）：需要在 handler 层添加统一的参数校验
6. **版本号文档不同步**（P1）：`README.md` 和 `项目说明书.md` 版本落后

### 总体评价

这是一个**架构设计良好、工程质量较高**的项目。三层架构边界清晰，核心引擎解耦优秀，安全实践到位。主要的改进空间在于 Python 后端的路由-业务解耦和前端的状态管理重构，这两项改进将显著提升项目的可维护性和可扩展性。
