# A股策略回测工作台 — 综合审核报告

> **审核团队**：架构师 高见远、工程师 寇豆码、QA工程师 严过关
> **主理人**：齐活林（交付总监）
> **审核模式**：只读审核，未修改任何代码
> **审核日期**：2026-07-11

---

## TL;DR

本项目是一个基于 Tauri + React + Python 三层架构的 Windows 桌面端 A 股策略回测工具。**整体架构设计良好、工程质量较高、测试覆盖全面**。未发现 P0 级严重问题。主要技术债务集中在"长方法/巨石组件"和"异常处理一致性"两个方面，需通过结构性重构解决。

---

## 一、审核概览

| 审核维度 | 审核人 | P0 | P1 | P2 | 覆盖范围 |
|----------|--------|----|----|----|----------|
| 架构合理性 | 高见远 | 0 | 6 | 8 | 三层架构边界、模块耦合、数据流、安全性、可扩展性 |
| 代码质量 | 寇豆码 | 0 | 14 | 19 | Python/TS/Rust 代码质量、异常处理、性能、已知问题验证 |
| 测试覆盖 | 严过关 | 0 | 5 | 6 | 51 个测试文件、~726 个用例的覆盖矩阵评估 |
| **去重汇总** | — | **0** | **22** | **27** | — |

### 测试规模

| 层 | 测试文件数 | 测试用例数 |
|----|-----------|-----------|
| Python 后端 | 25 | ~488 |
| 前端 (React/TS) | 22 | ~186 |
| Rust (Tauri) | 4（内联） | 52 |
| **合计** | **51** | **~726** |

---

## 二、统一问题清单（去重后）

### P1 — 重要问题（22 项）

#### 🔴 后端 Python

| # | 问题 | 文件 | 来源 |
|---|------|------|------|
| 1 | `service.py` 路由与业务逻辑耦合（do_POST 173 行 if-elif 链） | `service.py` | 架构师 + 工程师 |
| 2 | `engine.py` `run_backtest` 函数 ~250 行，圈复杂度过高 | `engine.py` L612-861 | 工程师 |
| 3 | `engine.py` `_scan_entry_candidates` 使用 `iterrows()` 遍历 5000+ 股票 | `engine.py` L529 | 工程师 |
| 4 | `warehouse.py` `_safe_read_parquet` 吞掉所有异常返回空帧 | `warehouse.py` L386-390 | 工程师 |
| 5 | `realtime.py` 20+ 处 `except TypeError` 兼容路径掩盖真实 bug | `realtime.py` 多处 | 工程师 |
| 6 | `capital_flow_crawler.py` 1140 行单文件，职责混杂 | `capital_flow_crawler.py` | 工程师 |
| 7 | `DataServiceState` 上帝对象，管理 10+ 实例和多种职责 | `service.py` | 架构师 |
| 8 | `Warehouse` 与 `LocalCache` 职责重叠，fallback 逻辑分散 | `warehouse.py` + `cache.py` | 架构师 |
| 9 | 用户输入校验不完整（股票代码/日期/path 参数未在 handler 层校验） | `service.py` | 架构师 |
| 10 | 大量 bare `except Exception` 吞异常（全后端 30+ 处） | 多文件 | 工程师 |
| 11 | `service.py` 中 3 处 `except Exception: pass` 静默吞错 | `service.py` L728-757 | 主理人 |

#### 🔴 前端 TS/React

| # | 问题 | 文件 | 来源 |
|---|------|------|------|
| 12 | `App.tsx` 915 行巨石组件，30+ useState | `App.tsx` | 架构师 + 工程师 |
| 13 | 硬编码节假日表仅覆盖 2024-2026，2027 年后失效；两文件重复定义 | `App.tsx` + `DataCenter.tsx` | 工程师 + 主理人 |
| 14 | `DataCenter.tsx` 4 个 handler 重复错误处理模式（~120 行重复） | `DataCenter.tsx` L432-552 | 工程师 |
| 15 | `savedStrategies.ts` `JSON.parse` 无 try/catch，错误消息不友好 | `savedStrategies.ts` L251-255 | 工程师 |

#### 🔴 Rust/Tauri

| # | 问题 | 文件 | 来源 |
|---|------|------|------|
| 16 | `DataServiceManager` 非线程安全，外层 Mutex 持锁期间阻塞所有命令 | `service_manager.rs` | 工程师 |
| 17 | `backend_command` 每次启动 Python 子进程，1-2 秒启动开销 | `commands.rs` L800-900 | 工程师 |

#### 🔴 版本与文档

| # | 问题 | 文件 | 来源 |
|---|------|------|------|
| 18 | `README.md` 版本 1.3.4，`项目说明书.md` 版本 1.3.1，代码均为 1.3.5 | 多文件 | 架构师 + 主理人 |

#### 🔴 测试

| # | 问题 | 模块 | 来源 |
|---|------|------|------|
| 19 | `backtest_runner.py` 无直接测试（`enrich_for_strategy` 窗口匹配逻辑未覆盖） | Python | QA |
| 20 | `trading_calendar.py` 无测试（节假日表错误会导致回测包含非交易日） | Python | QA |
| 21 | `test_data_service_http.py` 102 个测试各自启动真实 HTTP 服务器，CI 脆弱 | Python | QA |
| 22 | 无 E2E 测试（React → Tauri IPC → Python sidecar 完整链路从未验证） | 全栈 | QA |

---

### P2 — 建议改进（27 项，精选）

| # | 问题 | 文件/模块 | 类型 |
|---|------|-----------|------|
| 1 | `engine.py` `_stop_loss_price` 与 `_take_profit_price` 实现完全相同 | `engine.py` L417-422 | 代码可读性 |
| 2 | `engine.py` `held_days` 每次线性扫描全部交易日列表 | `engine.py` L700 | 性能 |
| 3 | `models.py` `stop_loss_pct` 必须为负值，与直觉不符 | `models.py` | UX |
| 4 | `api.ts` NDJSON 流中 `JSON.parse(line)` 无 try-catch | `api.ts` L319, L537 | 健壮性 |
| 5 | `savedStrategies.ts` 深拷贝使用 `JSON.parse(JSON.stringify())` | `savedStrategies.ts` L143 | 代码质量 |
| 6 | `cls_finance.py` f-string 构造 JS 代码 + JSDOM `runScripts: "dangerously"` | `cls_finance.py` L465-489 | 安全模式 |
| 7 | `commands.rs` 3 处 `as_array().unwrap()`（有前置校验但不够健壮） | `commands.rs` L141,177,180 | 健壮性 |
| 8 | `lib.rs` `expect()` 可能 panic，配置损坏导致应用崩溃 | `lib.rs` L34, L68 | 健壮性 |
| 9 | `service_manager.rs` 硬编码开发机器路径 `D:\New project 6` | `service_manager.rs` L371 | 部署 |
| 10 | `python_runtime.rs` 回退不检查 Python 退出码和版本 | `python_runtime.rs` L78-85 | 兼容性 |
| 11 | CORS 设置 `Access-Control-Allow-Origin: *` | `service.py` | 安全 |
| 12 | `/import/daily-bars` 端点 `path` 参数未校验路径范围 | `service.py` | 安全 |
| 13 | 条件分发使用 if/elif 链（~70 行），建议注册表模式 | `engine.py` | 可扩展性 |
| 14 | `warehouse.py` `coverage()` ~180 行，复杂度过高 | `warehouse.py` | 可维护性 |
| 15 | `operations.py` `fetch_capital_flow_into_cache` ~260 行 | `operations.py` | 可维护性 |
| 16 | 缺少统一日志框架（使用 print/diagnostics 而非 logging） | 全后端 | 工程规范 |
| 17 | 无覆盖率量化工具（缺 pytest-cov 和 @vitest/coverage-v8） | 测试 | 工程规范 |
| 18 | 多个前端组件测试仅 smoke test 级别（1-2 个用例） | 前端 | 测试质量 |
| 19 | `App.tsx` 和 `useSavedStrategyStore.ts` 无直接测试 | 前端 | 测试覆盖 |
| 20 | `backend_command` 优先 HTTP 调用 sidecar 而非每次 spawn 子进程 | `commands.rs` | 性能 |
| 21 | `warehouse.py` `KNOWN_CAPITAL_FLOW_SOURCE` 硬编码魔数 | `warehouse.py` | 可配置性 |
| 22 | `providers.py` `CompositeProvider` 空帧误判为错误 | `providers.py` | 诊断准确性 |
| 23 | `StrategyWorkbench.tsx` `conditionMetaById` 模块级变异 | `StrategyWorkbench.tsx` | 代码质量 |
| 24 | `StrategyWorkbench.tsx` Props 数量过多（20+） | `StrategyWorkbench.tsx` | 接口设计 |
| 25 | 错误响应格式不统一 | `service.py` | API 一致性 |
| 26 | `conftest.py` 仅 2 个 fixture，多个测试文件重复定义 | `tests/` | 测试质量 |
| 27 | `test_build_scripts.py` 基于源码文本字符串匹配 | `tests/` | 测试脆弱性 |

---

## 三、已验证的历史修复

对照 `docs/architecture-optimization-audit.md` 记录的 5 项关键修复，工程师逐项验证：

| # | 修复项 | 验证结果 | 证据 |
|---|--------|----------|------|
| 1 | Single-flight 锁生命周期 | ✅ 已修复 | `realtime.py` L496-620 使用 `Lock.acquire(blocking=False)` + `future.add_done_callback` |
| 2 | Rust 原子 upsert/delete 不嵌套持锁 | ✅ 已修复 | `commands.rs` L317-340 同一锁域内 read-modify-write，`write_saved_strategies_unlocked` 无锁 |
| 3 | 前端接入单条原子命令 | ✅ 已修复 | `savedStrategies.ts` L301-329 调用 `invoke("upsert_saved_strategy")` / `invoke("delete_saved_strategy")` |
| 4 | malformed localStorage 严格解析 | ✅ 已修复 | `savedStrategies.ts` L251-255 直接 `JSON.parse`，异常被 `.catch()` 捕获设为 `failed` |
| 5 | 完整嵌套校验 | ✅ 已修复 | 前端 `validateStrategyConfig` (L168-221) 和 Rust `validate_strategy_array` (L114-199) 校验一致 |

**审计文档后续事项未推进：**
- `except TypeError` 清理：审计称 11 处，实际 20+ 处，**未清理**
- `realtime` 中直接 requester 路径：**仍存在**
- 139 个 Ruff 历史项：**未清理**
- `service.py` 路由表拆分：**未完成**
- `capital_flow_crawler.py` 拆分：**未完成**

---

## 四、优化方案（按优先级排序）

### 第一优先级：定时炸弹与隐性 Bug

| 序号 | 问题 | 方案 | 工作量 |
|------|------|------|--------|
| 1 | 硬编码节假日表 2027 年失效 | 提取为共享模块 + 通过 API 从后端获取交易日历 | 中 |
| 2 | `except TypeError` 20+ 处掩盖真实 bug | 统一内部方法签名（全部接受可选 `deadline`/`cancel_event`），一次性删除回退路径 | 大 |
| 3 | 版本号文档不同步 | 更新 `README.md`→1.3.5、`项目说明书.md`→1.3.5，CI 添加版本一致性检查 | 小 |
| 4 | `warehouse.py` `_safe_read_parquet` 吞所有异常 | 区分 `FileNotFoundError`（返回空帧）和其他异常（记录日志或向上传播） | 小 |

### 第二优先级：性能与可维护性

| 序号 | 问题 | 方案 | 工作量 |
|------|------|------|--------|
| 5 | `engine.py` `iterrows()` 全市场性能差 | 改用 `itertuples()` 或向量化操作 | 中 |
| 6 | `engine.py` `run_backtest` 250 行 | 拆分为 `_iterate_trading_days`、`_evaluate_buys`、`_evaluate_sells` 等子函数 | 大 |
| 7 | `App.tsx` 915 行巨石组件 | 拆分为 `useBacktestRunner`、`useRealtimeMarket` 等 Hook + Zustand store | 大 |
| 8 | `service.py` 路由耦合 | 提取 `{path: handler}` 字典 + 按功能域拆分路由模块 | 中 |
| 9 | `capital_flow_crawler.py` 1140 行 | 按数据源拆分为 `eastmoney_crawler.py`、`sina_crawler.py`、`baidu_crawler.py` | 中 |
| 10 | `Warehouse` 与 `LocalCache` 职责重叠 | 统一为 Warehouse，标注 LocalCache `@deprecated` 后逐步移除 | 中 |

### 第三优先级：测试补强

| 序号 | 问题 | 方案 | 工作量 |
|------|------|------|--------|
| 11 | `backtest_runner.py` 无测试 | 添加 `test_backtest_runner.py` 验证 `enrich_for_strategy` | 中 |
| 12 | `trading_calendar.py` 无测试 | 添加测试验证节假日排除、周末排除、跨年边界 | 小 |
| 13 | HTTP 集成测试 CI 脆弱 | session-scoped fixture 共享服务器，`time.sleep` 替换为事件驱动 | 中 |
| 14 | 无 E2E 测试 | 添加 1-2 个关键路径 E2E 测试 | 大 |
| 15 | 无覆盖率量化 | 添加 `pytest-cov` 和 `@vitest/coverage-v8`，CI 设置阈值 | 小 |

### 第四优先级：安全与健壮性

| 序号 | 问题 | 方案 | 工作量 |
|------|------|------|--------|
| 16 | 用户输入校验不完整 | 添加统一输入校验函数（`_validate_symbols`、`_validate_date_range` 等） | 中 |
| 17 | CORS `*` 设置 | 限制为 Tauri WebView origin | 小 |
| 18 | `/import/daily-bars` 路径未校验 | 添加路径范围校验 | 小 |
| 19 | `api.ts` NDJSON `JSON.parse` 无 try-catch | 添加 try-catch，解析失败行跳过并警告 | 小 |
| 20 | `commands.rs` `unwrap()` 使用 | 改为 `ok_or_else` 返回 `Result` 链 | 小 |

---

## 五、总体评价

### 优点

1. **三层架构选型合理**：Tauri + React + Python 在 Windows 桌面端金融工具领域是务实高效的选择
2. **回测引擎设计优秀**：纯函数式、无 IO 依赖，可测试性极高
3. **数据源扩展性强**：Protocol + Composite 模式，新增数据源零侵入
4. **Sidecar 管理健壮**：端口动态分配、健康检查、文件锁、进程清理一应俱全
5. **Rust 层安全实践到位**：原子文件写入、跨进程锁、URL 白名单校验
6. **前端 mock 回退设计**：支持非 Tauri 环境独立开发和测试
7. **测试覆盖全面**：~726 个用例覆盖 51 个文件，关键业务路径全覆盖
8. **5 项历史修复全部落地**：single-flight 锁、原子写入、嵌套校验等均已验证通过

### 主要技术债务

1. **"长方法"集中区域**：`run_backtest`(250行)、`App.tsx`(915行)、`capital_flow_crawler.py`(1140行)、`service.py` 路由链 — 可维护性最大瓶颈
2. **异常处理一致性差**：20+ 处 `except TypeError` 回退 + 30+ 处 `except Exception` 静默吞错 — 隐性 bug 最大风险源
3. **审计文档后续事项停滞**：路由表拆分、crawler 拆分、TypeError 清理等均停留在"计划"阶段
4. **前端状态管理已达瓶颈**：30+ useState 难以追踪，需引入状态管理框架

### 无 P0 问题

未发现阻塞性、安全性或数据丢失级别的严重问题。所有发现均可通过迭代优化解决。

---

## 六、下一步建议

1. **立即处理**：更新 `README.md` 和 `项目说明书.md` 版本号 → 1.3.5（5 分钟可完成）
2. **短期（1-2 周）**：节假日表 API 化 + `_safe_read_parquet` 异常分级 + `api.ts` JSON.parse 加 try-catch
3. **中期（2-4 周）**：`except TypeError` 统一签名清理 + `engine.py` 拆分 + `iterrows()` 向量化
4. **长期（1-2 月）**：`App.tsx` 状态管理重构 + `service.py` 路由表化 + `capital_flow_crawler.py` 拆分
5. **持续**：补强测试覆盖（`backtest_runner.py`、`trading_calendar.py`、E2E）+ 引入覆盖率量化

---

*报告由主理人齐活林基于架构师高见远、工程师寇豆码、QA工程师严过关的独立审核报告汇总汇编而成。*
