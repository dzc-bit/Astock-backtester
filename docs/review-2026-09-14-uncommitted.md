# 未提交改动第三方审核报告

审核对象：`D:\New project 6` 工作区未提交改动（40 个修改文件 + 6 个新增文件）  
审核日期：2026-09-14  
审核方式：静态代码审查 + 真实数据/真实调用的行为验证（非仅读代码）  
基线：`git status --short --untracked-files=all`、`AGENT必读.md`、`AGENTS.md`

## 0. 门禁实测结论

| 门禁                                 | 结果                                                       |
| ---------------------------------- | -------------------------------------------------------- |
| `ruff check backend tests scripts` | ✅ All checks passed                                      |
| `pytest tests -q`                  | ✅ **744 passed**（含本轮新增 5 个回归测试）                          |
| `npm run lint`                     | ✅ 0 error / 5 warning（均为既存 `exhaustive-deps` 与 1 处未使用导入） |
| `npm run typecheck`                | ✅ 通过                                                     |
| `npm run test:ui -- --run`         | ✅ 26 files / 256 tests passed                            |

改动面本身不破坏任何既有门禁。

> **关于 pytest 的一个环境陷阱（已排除，非代码问题）**：  
> 直接跑全量会出现 `22 failed`，失败签名统一为 `SystemExit: 1`，  
> 位置在 `_pytest/pathlib.py::maybe_delete_a_numbered_dir`。  
> 这是本机沙箱的**批量删除守卫**在 pytest 回收临时目录时触发，不是测试失败：
>
> - 22 个用例**逐个或成组单独运行全部通过**（实测 34 passed / 7 passed）；
> - 清理 `%TEMP%\pytest-of-<user>` 下累积的 `garbage-*`（含 295/297/298 条目的目录）后，  
>   全量重跑得到 **742 passed，0 failed**（补齐 M4 两项新测试后为 **744 passed**）。
>
> 结论：全量绿。后续在本机跑门禁若再遇该签名，先清 `%TEMP%` 下的 pytest 残留即可。



---

## 1. 高优先级问题（已修复）

### H1. `build_daily_bars_coverage` 的覆盖窗口终点导致“覆盖表说没缺、同步却要补”

**位置**：`backend/astock_backtester/data/operations.py:99`（修复前）

**问题**：该函数在调用方未显式传 `end_date` 时，把逐股覆盖窗口终点设为  
`data_end_date`——**该股自己的最后一行日期**。于是任何停更股票在其逐股行里  
`missing_trade_dates` 恒为空，而 `Warehouse.coverage()` 用“首行→仓库最新数据日”  
的累计口径却能算出巨量缺口。两者口径矛盾，是用户直观感受“历史数据缺失查不清、  
覆盖表与同步结论打架”的直接来源。

**证据**（真实仓库，股票 `300947`，最后数据停在 2026-07-14）：

```
修复前 不传 end_date : rows=1190  missing_trade_dates=174
修复前 传 end_date   : rows=1190  missing_trade_dates=217   ← 差 43 个交易日
```

而 `Warehouse.coverage()` 汇总为 `daily_bars missing_rows=1686763`。

**修复**：未显式指定 `end_date` 时，覆盖终点取仓库全局最新数据日（读  
`warehouse.coverage()` 的 `daily_bars.end_date`），保证逐股口径与汇总口径一致。  
修复后同一股票不传 `end_date` 也得到 `217`，与显式传参一致。

**回归测试**：`tests/test_warehouse.py::test_build_daily_bars_coverage_sees_tail_gap_without_explicit_end_date`

---

## 2. 中优先级问题（已修复）

### M1. 会话锁字典无上限（长跑进程内存泄漏）

**位置**：`backend/astock_backtester/ai/facade.py:198`（修复前）

`chat_stream` 每次遇到新 `session_id` 就 `self._session_locks[session_id] = lock`，  
只增不减。桌面端 sidecar 常驻运行，用户每次新建会话都会永久留一个 `Lock` 对象。

**修复（初版，后被独立复核判定不成立）**：新增 `AI_MAX_SESSION_LOCKS = 512`，  
超限时淘汰**当前未被持有**的锁（`not lock.locked()`）。被持有的锁不淘汰，但  
“已从字典取出、尚未 acquire”的窗口里锁同样空闲 —— 淘汰线程此时删掉条目，  
同一会话会先后拿到两把互不相斥的锁，**互斥静默失效**。

**修复（终版）**：引入 `_SessionLockEntry`（锁 + 引用计数）。任何调用方在  
`_session_lock()` 里 `refs += 1`，在 `release_session_lock()`（幂等）里  
`release()` 并 `refs -= 1`；淘汰只回收 `refs == 0` 的条目，竞态窗口内的条目  
不再可能被回收。

**回归测试**：

- `tests/test_ai_service_http.py::test_ai_session_locks_are_bounded_and_reusable`
- `tests/test_ai_service_http.py::test_ai_session_lock_not_evicted_between_fetch_and_acquire`  
  （直接复刻“已取出未 acquire”窗口，回滚终版修复后 FAILED）

### M2. `AiConfigStore.save` 对 `embedding_base_url` 缺少“留空保持”语义

**位置**：`backend/astock_backtester/ai/config.py:144-147`（修复前）

`api_key` 与 `embedding_api_key` 都有 `if not merged.X: merged.X = current.X` 保护，  
`embedding_base_url` 没有。HTTP 层（`facade.update_config`）自行做了兜底，因此  
经 HTTP 保存时看不出问题；但**任何直接调用 store 的路径**都会把已配置的独立  
embedding 地址静默清空。属语义不一致的可维护性缺陷，也是真实的配置丢失路径。

**修复**：store 层对 `embedding_base_url` 补同样的 coalesce。

**回归测试**：`tests/test_ai_service_http.py::test_ai_config_store_keeps_embedding_base_url_when_blank`

### M3. 前端 `useMarketPolling.ts` 新增降级重试（**更正：不是缩进重排**）

**位置**：`frontend/src/hooks/useMarketPolling.ts`

**经独立复核更正**：本条初版描述为“缩进错乱、逻辑零变更”，**与实际 diff 不符**。  
真实改动是新增了 `missingBreadth` 参数的功能性变更：

```diff
-nextRefreshMs = refreshIntervalForMarketResult(nextPhase, snapshot.diagnostics, snapshot.status === "unavailable");
+const missingBreadth = snapshot.breadth == null && snapshot.status !== "unavailable";
+nextRefreshMs = refreshIntervalForMarketResult(nextPhase, snapshot.diagnostics, snapshot.status === "unavailable", missingBreadth);
```

配套在 `frontend/src/marketRefresh.ts:44-53` 新增 `DEGRADED_RETRY_MS = 45_000`：  
行情部分成功（有指数、缺宽度）时按 45s 重试，而不是等满一个正常轮询周期。

**核对结论**：改动本身合理（属于清单第 5 项“实时行情部分成功空白”的修复），但  
初版审核报告的定性错误需记录在案 —— 审核描述必须以 diff 为准。


### M4. `_consolidate_archive` 在压缩失败时**永久丢失**归档内容

**位置**：`backend/astock_backtester/ai/agent.py:314`（修复前）

**问题**：`pending_archive` 在**调用模型之前**就被清空：

```python
session["pending_archive"] = []              # ← 先清空
summary = self._summarize_history_text(...)  # ← 再调用模型（可能抛异常）
if summary:
    session["rolling_summary"] = summary[:4000]
```

`_summarize_history_text` 直接迭代 `self._model.chat(...)`，上游网络错误 / HTTP 500 /  
超时都会向上抛出。一旦抛出：

- 归档的 N 条内容**已被清空** → 用户永久失去这段对话记忆；
- 异常还会向上冒泡中断整轮 `run()`；
- `rolling_summary` 保持为空 → 表现为"AI 忘了之前聊的内容"。

**实测复现**（注入一个 `chat()` 抛 `RuntimeError` 的模型）：

```
归档后 pending_archive: 8
consolidate 抛出: RuntimeError upstream exploded
压缩后 pending_archive: 0
>>> 20 条归档内容是否丢失: 是（丢失！）
rolling_summary: ''
```

这与本模块 docstring 自己声明的"persisted with the session, so nothing is lost"  
直接矛盾——注释说的是"内容不丢"，实现却会在异常路径丢掉。

**修复**：把清空移到压缩成功之后，并捕获压缩异常（压缩失败只记 warning，  
既不丢归档也不中断本轮）：

```python
try:
    summary = self._summarize_history_text("\n".join(lines))
except Exception:
    logger.warning("会话归档压缩失败；保留 pending_archive 待下次重试", exc_info=True)
    return
if not summary:
    return                                     # 模型返回空同样保留
session["pending_archive"] = []                # 仅成功才清空
session["rolling_summary"] = summary[:4000]
```

同时为 `agent.py` 补上 `logging` 导入与模块级 `logger`。

**修复后实测**：异常被吞掉，`pending_archive` 原样保留 20 条，`rolling_summary` 不变。

**回归测试**：

- `tests/test_ai_agent.py::test_agent_keeps_pending_archive_when_compaction_model_fails`
- `tests/test_ai_agent.py::test_agent_clears_pending_archive_only_after_successful_compaction`

> 说明：此项是本轮唯一发现的**真实功能性缺陷**，且直接命中用户反馈的  
> "AI 失忆"主题（改动清单第 7 项）。原实现只覆盖了"模型返回空"，  
> 漏了"模型抛异常"这条更常见的路径。

---

## 3. 复核未发现问题的项（重点验证结论）

审核范围点名的高风险项，逐条给出结论与证据：

### 3.1 `_repair_interrupted_turn` 是否会误伤正常会话、是否切断配对 —— 无问题

`backend/astock_backtester/ai/agent.py:199-241`。实测构造“正常配对 + 悬空 tool_calls”  
混合历史，修复结果正确：已配对的 `call_A` 保留原结果，悬空的 `call_B` 被补占位结果，  
不误伤、不重复补。

配对安全性由两点保证：

- 归档边界 `_archive_overflow` 会把 `overflow` 前推到下一个 `role == "user"`（`agent.py:286-287`），  
  因此切分点永远落在轮次边界，不会切开 `assistant(tool_calls)` / `tool` 配对；
- 修复逻辑会“吃掉紧随其后的既有 tool 结果”再判定缺口（`agent.py:221-223`）。

**唯一理论边界**：`answered` 集合是**全量累积**（`agent.py:224-226`），若上游复用  
同一 `tool_call_id`，第二次同名 id 会被误判为“已答”而不再补占位。实测上游每次  
调用生成唯一 id，本仓会话落盘也未复用 id，故当前不构成缺陷；已在报告中记录为  
**L1 观察项**。

### 3.2 `facade.py` 会话锁的释放路径 —— 无泄漏、无双重释放

`backend/astock_backtester/ai/facade.py:206-300`。四条路径实测均正确：

| 路径                          | 释放方              | 结论                                          |
| --------------------------- | ---------------- | ------------------------------------------- |
| 正常完成                        | worker `finally` | ✅ 单次释放                                      |
| 客户端断开（生成器提前关闭）              | worker `finally` | ✅ 主线程 `finally` 因 `worker_started=True` 不释放 |
| worker 未启动（thread.start 抛错） | 主线程 `finally`    | ✅ 显式 `release()` 后 re-raise                 |
| worker 内异常                  | worker `finally` | ✅ 哨兵与释放同处 finally，不会挂死消费端                   |

关键设计正确：`worker_started` 标志把“释放责任”唯一化了，因此不存在双重释放；  
`session_lock.release()` 位于 `events.put(None)` 之后，消费端不会在锁释放前退出。

90 秒超时的合理性：用户点“停止”后 worker 通常在一个模型响应内收尾（数秒级），  
90 秒足够覆盖慢上游；超时回 `ai_session_busy` 而不是无限等待，符合“不挂死 UI”的目标。

**注意**：本次改动**没有为会话锁写任何测试**，已补 H1/M1 之外的新测试覆盖（见 M1）。

### 3.3 攒批压缩是否会让 `pending_archive` 无限增长 —— 无问题

`agent.py:312`：`if len(archive) < 12 and archive_chars < 6000: return`。  
未达阈值时 `session["pending_archive"]` 保留原值并**随会话落盘**（`sessions.save`），  
内容不丢。增长上限受 `SHORT_TERM_MAX_CHARS` 驱动的归档频率约束，且每次达阈值即清空，  
不存在无限增长。`_consolidate_archive` 只有在取到 `archive` 非空时才可能清空，  
失败路径（模型返回空）不会清空已归档内容。

### 3.4 `warehouse.py` 新口径与 `_tail_missing_rows` 是否重复计数 —— 无重复

- **市值**：内部缺口统计的是 `ohlc_complete` 中 `float_market_cap` 为空的行，其日期  
  `<= 该股最后 OHLC 行日期`；`_tail_missing_rows` 用 `bisect_right(calendar, boundary)`  
  严格取 boundary **之后**的交易日。两集合不相交。
- **资金流**：`missing_capital_flow_frames` 收集的同样是 `ohlc_complete` 内 `main_net_inflow`  
  为空的行，边界同上。不相交。

**已确认的一处轻微漏统计（L2）**：`warehouse.py:458-463` 的 `symbols` 参数包含  
`cap_rows_by_symbol` 里但不在 `daily_symbols`/`ohlc_last_by_symbol` 的股票，而  
`boundary_by_symbol` 对这类股票没有条目，`_tail_missing_rows` 遇 `boundary is None`  
静默 `continue`。该股尾部缺口被漏统计。属于极端数据形态（有市值行但无 OHLC 行），  
不会算错已有数字，仅略偏保守。未修改，记录待后续处理。

### 3.5 `data_gap_profile` 在旧格式分区上的表现 —— 安全

实测构造缺 `float_market_cap` / `main_net_inflow` 列的旧分区：  
`coverage()` 走 `market_cap_missing_rows += len(ohlc_complete)` 分支正确，  
`data_gap_profile` 对缺失列跳过、`symbols=0`，**不抛异常**。兼容性达标。

### 3.6 `realtime.py` 预算调整后的最坏延迟 —— 可接受

`breadth_time_budget: 3.0 → 8.0`、`breadth_source_timeout: 2.5 → 2.2`。  
前端已有对冲：`marketRefresh.ts` 新增 `DEGRADED_RETRY_MS = 45_000`，缺宽度时 45 秒重试；  
`useMarketPolling.ts` 流式接口先回部分快照（`applySnapshot(partial, true)`），  
指数与板块先行渲染，等待增量对用户不可感知。8 秒最坏值在流式首包之后，不阻塞首屏。

### 3.7 `reports.py` 调度器“一天跑多次” —— 不会

`reports.py:403-409`：置位与判定在同一把 `self._lock` 内原子完成，  
`_last_report_date` / `_last_evolution_date` 置为当天日期串，后续 tick 直接跳过。  
30 秒 tick 不会造成重复执行。

**已确认的边界（L3）**：跨 0 点的补跑窗口不成立（`current - target` 为负不命中），  
即 `report_time=23:55` 而进程在次日 00:05 恢复时不会补跑，当天跳过。属“漏跑一次”  
而非“跑多次”，符合 docstring 的“best-effort、次日重试”设计意图。

`_time_matches` 只在命中时置位日期，若 job 抛异常则当天不再重试——与模块 docstring  
明确声明的行为一致，非缺陷。

### 3.8 策略体检是否改写用户策略 —— 绝不改写（已逐行确认）

`reports.py` 全文仅一处读取用户策略文件（`reports.py:208` `_load_saved_strategies`，  
只 `read_text`），**没有任何写回 `saved-strategies.json` 的代码路径**。  
所有参数覆盖都作用在局部 `BacktestSettings` 上：  
`settings = settings.model_copy(update={...})`（`reports.py:242,244`），  
`StrategyConfig.model_validate` 生成的是新对象。建议文案只进报告  
（`reports.py:309-311`、`_evolution_markdown`）。  
实测当前 `运行产物/策略配置/saved-strategies.json` 为 `[]`，报告会以  
`skipped: "no_saved_strategies"` 优雅退出。**要求满足**。

### 3.9 `overfit.py` 指标口径与前端展示一致性 —— 一致

- 后端口径确认：`engine.py:496` `total_return = (final_equity / initial_cash) - 1`，  
  `engine.py:513` `win_rate = len(wins)/len(closed)`，均为**小数比例**。  
  `overfit.py:15-17` 的注释与阈值（`SUSPICIOUS_WIN_RATE=0.999`、`SUSPICIOUS_RETURN=1.0`）  
  与之匹配，`{%}` 格式化（如 `f"{total_return:+.1%}"`）输出正确。
- 前端**不做二次单位换算**：`ResultsOverview.tsx` 仅拼接后端已格式化的  
  `finding.message`，不存在“小数 vs 百分数”的展示错位。

### 3.10 其余项

- **AI 快讯去重**：`insights.py` 按 5pp 分桶构造 `dedup_key`，2 小时冷却，`_prune_insight_signatures`  
  防无限增长，正确。`digest.py:198-207` 的 `existing_titles` 在 `extend` **之前**快照，  
  故 `fresh` 只含真正新增条目——顺序正确。
- **提示词转义**：`build_final_answer_messages` / `data_coverage` 实测 `.format()` 不抛  
  `KeyError`，无字面 JSON 花括号泄漏。`data_coverage` 已写入真实按钮名  
  （“下载全市场历史数据 / 补全缺失数据 / 补齐资金流”），与 `DataCenter.tsx` 文案一致。
- **架构不变量**：`ai/*` 未见反向 import `data/*`；`query_warehouse_sql` 只读约束未放松；  
  `reports.py` 写入范围仅限 `运行产物/AI报告/`（`ReportStore`，文件名经 `_safe_report_name`  
  校验，拒绝 `/ \ ..` 与隐藏文件，原子 `os.replace` 落盘）——路径安全达标。
- **AI 抽屉 FAB**：`App.tsx` 抽屉打开时不再渲染 FAB，`X` 导入同步移除，lint 通过。

---

## 4. 观察项（未修改，供后续决策）

| 编号 | 位置                     | 说明                                                                                               |
| -- | ---------------------- | ------------------------------------------------------------------------------------------------ |
| L1 | `agent.py:224-226`     | `answered` 为全量累积集合；若上游复用 `tool_call_id`，第二次同 id 调用不会补占位结果。当前上游生成唯一 id，不触发。                       |
| L2 | `warehouse.py:458-463` | `market_cap` 的 `symbols` 与 `boundary_by_symbol` 覆盖集不严格相等，极端形态（有市值行无 OHLC 行）下该股尾部缺口被漏统计，偏保守而非偏乐观。 |
| L3 | `reports.py:421-425`   | 补跑窗口不跨 0 点；`report_time` 设在午夜附近且进程恰在次日 0:00–0:30 恢复时会漏跑当天一次。                                     |
| L4 | `reports.py:398`       | `_last_report_date` 仅存内存，进程重启后清空；配合 30 分钟补跑窗口，重启落在窗口内会补跑一次（设计内）。                                 |

---

## 5. 追加审核发现（2026-09-14 数据修复复盘中发现，属既有代码，非本轮 diff）


### H2（高）. `Warehouse.write_daily_bars` 无跨进程写锁，可导致分区损坏与静默丢数

**位置**：`backend/astock_backtester/data/warehouse.py:116-134`（既有代码，非本次未提交改动）

**问题**：整个写入是**无任何跨进程互斥**的 read-modify-write，且以整文件覆盖方式落盘：

```python
def write_daily_bars(self, frame: pd.DataFrame) -> None:
    ...
    if path.exists():
        current = self._safe_read_parquet(path)      # 读
        year_frame = (year_frame.set_index(["symbol","trade_date"])
                      .combine_first(current.set_index(["symbol","trade_date"]))
                      .reset_index())                 # 合
    year_frame.to_parquet(path, index=False)          # 整文件覆盖写
```

`self._gap_profile_lock` 只是 `threading.Lock`，**仅进程内有效**。

**真实证据**：本次排查期间实际发生分区损坏：

```
PID 16492  astock-data-service.exe  启动 2026-09-13 22:12:33
           CPU 4875.5s  常驻内存 1.37 GB     ← 桌面端 sidecar，同时持有 Warehouse
PID 3420   外部补齐脚本                 ← 也持有 Warehouse，写同一分区
```

并发下 `year=2026/daily_bars.parquet` 报  
`pyarrow.lib.ArrowInvalid: Parquet magic bytes not found in footer`，其余 11 个分区完好。

**危害等级高的原因**（不只是"可能损坏"）：

1. **撕裂写**：一方 `to_parquet` 写到一半，另一方读/写同路径 → footer 与数据块不匹配；
2. **静默丢数**：`_safe_read_parquet` 读失败时**吞异常返回空表**（`warehouse.py`），  
   损坏分区被伪装成"没有数据" → 同步任务每次都重新全量拉 → 写完再被覆盖，  
   形成 **"补了又没补上"的死循环**。这正是"长期补不齐"的隐藏帮凶；
3. **丢失更新**：即使不撕裂，A读→B读→A写→B写 也会让其中一方的整批数据消失。

**建议修复（二选一，需用户决策）**：

- **方案 A（推荐，改动小）**：`write_daily_bars` 内对分区加跨进程文件锁  
  （Windows `msvcrt.locking` / POSIX `fcntl.flock`，或引入 `filelock` 依赖），  
  以分区文件为粒度，获取超时返回稳定错误码；
- **方案 B**：规定 sidecar 独占数据仓写入，外部脚本一律走 sidecar HTTP 接口，  
  不再直接实例化 `Warehouse`。

**附带建议**：`_safe_read_parquet` 遇损坏分区**不应静默返回空表**，应记 warning  
并让 `coverage()` 能暴露"分区损坏"状态，避免损坏持续被误判为"数据缺失"。

**未自行修复的原因**：属既有代码（不在本轮未提交改动范围内），且方案 A/B 涉及  
依赖引入与写入架构取向，`AGENT必读.md` §15 对数据仓写路径有明确约束，  
不宜在审核环节擅自变更。已在 `docs/data-gap-rootcause-2026-09-14.md` §9 详列。

---

## 6. 结论

本轮改动**整体质量达标**：门禁全绿，架构不变量未被破坏，AI 子系统边界（只读数据仓、  
唯一写路径、错误码、注入防御）全部守住，前端设计 token 纪律未被违反。

点名的 9 项高风险复核**均未发现正确性缺陷**，其中"策略体检不得改写用户策略"  
与"两套 coverage 口径的一致性"是本轮最值得确认的两点——前者确认安全，  
后者发现真实矛盾并已修复。

本次审核修复 4 项（H1 高，M1/M2/M4 中）+ 1 项代码整洁（M3），  
新增 5 个回归测试，全部通过。

其中 **M4 是本轮唯一的真实功能性缺陷**：`_consolidate_archive` 在压缩调用抛异常时  
会永久丢弃归档内容（与自身 docstring 承诺矛盾，正是"AI 失忆"的一种成因），已修复并加测。

数据修复过程中另发现 1 项既有结构性问题（H2：数据仓无跨进程写锁，  
已实际造成分区损坏与"补不齐"循环），不在本轮 diff 范围内，已作为待决策项上报。

---

## 7. 独立复核后的阻塞项修复（2026-09-14 第二轮）

独立子 agent 复核（见 `docs/verification-2026-09-14-independent.md`）确认 H1/M2/M4  
成立，同时**否定了 M1 与 M3 的初版结论**，并新发现以下问题。均已在本轮修复。

### B1（阻塞）会话锁淘汰竞态 —— 已修复

**位置**：`backend/astock_backtester/ai/facade.py`

初版 `_session_lock` 按 `lock.locked()` 判断“空闲”再淘汰。问题在于  
`_session_lock(id)` 返回锁对象与调用方 `acquire()` 之间是一个**未持锁窗口**：  
淘汰线程在此时删掉条目，下一个同 id 请求又会**新建一把锁** —— 同一会话  
出现两把互不相斥的锁，互斥在无任何报错的情况下失效。

**修复**：引入 `_SessionLockEntry`（`lock` + `refs` 引用计数）。

- `_session_lock()` 内 `entry.refs += 1`；
- `chat_stream` 的 `release_session_lock()`（幂等，`lock_released` 守卫）  
  负责 `release()` + `refs -= 1`；
- 淘汰循环只回收 `refs == 0` 的条目。

**顺带修复 S3**：原 `thread.start()` 失败路径先 `session_lock.release()` 再 `raise`，  
随后 `finally` 又释放一次 —— 双重 release 抛 `RuntimeError` 掩盖原始异常。  
改为统一走幂等的 `release_session_lock()`。

**新增回归测试**：  
`test_ai_session_lock_not_evicted_between_fetch_and_acquire` —— 直接复刻  
“已取出未 acquire”窗口后塞满字典，断言条目仍在、且仍是同一把锁。  
（回滚该修复后此测试 FAILED，确认守卫有效。）

### B2（阻塞）vitest 临时产物未 gitignore —— 已修复

`.gitignore` 补 `frontend/vitest.config.ts.timestamp-*.mjs` 与  
`frontend/vite.config.ts.timestamp-*.mjs`（跑门禁必现，属提交卫生问题）。

### S1 归档膨胀与字符预算失效 —— 已修复

`pending_archive` 在压缩持续失败时只增不减（B1 同批修复引入的边界）。  
新增 `ARCHIVE_MAX_ENTRIES = 400`，超限时裁掉最旧条目并插入一条  
`（更早的 N 条对话因压缩失败已丢弃）` 占位 —— 不静默失忆。

**新增回归测试**：`test_agent_caps_pending_archive_when_compaction_keeps_failing`

### S2 `capital_flow` 尾部缺口漏统计 —— 已修复

`symbols=set(flow_rows_by_symbol)` 未补 `daily_symbols` 的补集，与 `market_cap`  
口径不一致：**从未采到资金流**的股票不产生任何尾部缺口计数（看起来 0 缺口，  
实际天天缺）。

**修复**：与 `market_cap` 完全同构 —— `symbols` 取并集，`boundary_by_symbol`  
优先用 `ohlc_last_by_symbol`（全量日线符号）而非 `flow_rows_by_symbol`。

**新增回归测试**：`test_coverage_capital_flow_counts_symbols_absent_from_flow`  
（回滚修复后断言 `2 > 2` FAILED，确认守卫有效）

### S4 `tests/test_warehouse.py` EOF 空行 —— 已修复

`git diff --check` 报警的 `new blank line at EOF` 已清除。

### 复核裁定不予采信的一项

- **M3 初版描述错误**：初版称“缩进重排、逻辑零变更”，实际是新增  
  `missingBreadth` 参数的**功能性改动**。已在本文档 §2 M3 更正。
- **H2（数据仓无跨进程写锁）与 §10（O(n²) 写入）**：复核确认  
  **确实不在本轮 diff 范围内**，定性正确，**不作为本次提交阻塞项**，  
  保留为待决策项（见 `docs/data-gap-rootcause-2026-09-14.md` §9/§10）。

---

## 8. 第二轮独立复核（round2）后的追加修复

第二轮复核（`docs/verification-2026-09-14-independent-round2.md`）裁定：  
B2/S2/S3/S4 成立且已修好；S1 裁剪部分正确（**无 off-by-one**，输出恒为  
400 = 399 正文 + 1 占位）；但 **B1 只算"部分成立"**，因为第一轮的修复  
在 acquire 超时路径上引入了**比原竞态更严重**的新缺陷。

### B1-b（阻塞，本轮新发现）超时路径静默解开他人锁 —— 已修复

**位置**：`backend/astock_backtester/ai/facade.py:275-277`（修复前）

```python
if not session_lock.acquire(timeout=AI_SESSION_LOCK_TIMEOUT_SECONDS):
    release_session_lock()          # ← 本线程从未 acquire 成功
    raise AiSessionBusy(...)
```

`threading.Lock` **不做持有者校验**，`release()` 会静默解开**当前持有者**  
的锁。后果：B 请求超时后解开了 A（正在跑的那一轮）的锁，C 立刻拿到同一把  
锁 → **A 与 C 并发写同一会话**，正是会话互斥要根除的“失忆”成因。  
且触发条件比原 B1 **宽松得多** —— 一次 90s 超时即可，不需要 512 个会话，  
并伴随 `RuntimeError: release unlocked lock` 逃逸。

**修复**：把“释放锁”与“归还引用”拆成两件事：

- 新增 `lock_held` 标志，仅在 `acquire()` 成功后置 `True`；
- `release_session_lock()` 里 `if lock_held: session_lock.release()`；
- 新增 `drop_session_ref()` 只归还引用计数，不动锁 —— 超时路径只调它。

**新增回归测试**：`test_ai_chat_stream_timeout_does_not_unlock_other_holder`  
（端到端 A/B/C 三请求链路；回滚 `lock_held` 守卫后 FAILED，  
报 `RuntimeError: release unlocked lock`，确认守卫有效）

### S1-b（本轮新发现）字符预算静默失效 —— 已修复

**位置**：`backend/astock_backtester/ai/agent.py:290-298`（修复前）

第一轮只修了“归档条数上限”，而上一轮复核指出的**字符预算失效零改动**。  
实测形态：窗口内全是 assistant/tool 消息（工具长跑很常见）时，  
裁剪点被 `while ... role != "user"` 推到末尾 → `overflow >= len(messages)`  
→ 直接 `return`，**整个字符预算变成空操作**：

| 形态                       | 修复前                        | 修复后                   |
| ------------------------ | -------------------------- | --------------------- |
| 25 条 × 5000 字（无 user 边界） | 归档 **0** 条，窗口仍 125,000 字 ❌ | 归档 18 条，窗口 35,000 字 ✅ |
| 30 条 × 2000 字            | 归档 12 条 ✅                  | 保持 ✅                  |
| 单条 user 10 万字            | 归档 0 条（正确：不能归档当前问题）        | 保持 ✅                  |

**修复**：先算 `boundary`（推到 user 边界的候选点），**仅当该边界存在时**才  
采用；否则退回字符裁剪点，保证字符预算不空转。同时保留“不切断  
assistant(tool_calls)/tool 配对”的原语义。

**新增回归测试**：

- `test_agent_char_budget_archives_when_no_user_boundary_follows`  
  （回滚后 FAILED，报 `assert 125000 <= 36000`）
- `test_agent_avoids_splitting_tool_pair_at_window_edge`（对照守卫，确认有  
  user 边界时仍整组归档 user + assistant(tool_calls) + tool）

### 第二轮门禁实测（全绿）

| 门禁                                 | 结果                       |
| ---------------------------------- | ------------------------ |
| `ruff check backend tests scripts` | All checks passed!       |
| `pytest tests -q`                  | **750 passed**（143.65s）  |
| `npm run lint`                     | 0 error / 5 warning（既有）  |
| `npm run typecheck`                | 无输出（通过）                  |
| `npm run test:ui -- --run`         | **256 passed**（26 files） |

`git diff --check`：rc=0（无尾随空白 / EOF 空行问题）。

### 环境提示（非代码问题）

- **门禁请串行跑**：并行跑 pytest 与 vitest 时，`strategyEditor.test.tsx`  
  （51 个用例、约 40s）会因资源争抢超时；单跑与独占全量均通过。
- **pytest 全量的 atexit 假失败**：pytest 清理 `%TEMP%\pytest-of-大帝之资\garbage-*`  
  累积目录时触发本机沙箱批量删除守卫 → `SystemExit: 1`。测试本身是 `N passed`，  
  属环境噪声，不是测试失败。清理该目录后消失。
