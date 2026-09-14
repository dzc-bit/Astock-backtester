# 未提交改动独立复核报告（adversarial verification）

复核对象：`D:\New project 6` 工作区未提交改动（41 修改 + 8 新增，HEAD `870ee50`）
复核日期：2026-09-14
复核方式：**独立验证**前一位审核员（`docs/review-2026-09-14-uncommitted.md`）的每条结论，不采信其数字；
所有门禁亲自重跑，所有关键结论用可执行探针复现（探针跑完即删，未落盘）。
全程只读数据仓。

---

## 0. 门禁实测（我亲自跑的数字）

| 门禁 | 命令 | 实测结果 |
| --- | --- | --- |
| ruff | `python -m ruff check backend tests scripts` | ✅ `All checks passed!` |
| pytest | `python -m pytest tests -q`（先清 `%TEMP%\pytest-of-大帝之资`） | ✅ **744 passed in 141.63s**（一次通过，无 `SystemExit: 1` 假失败） |
| eslint | `npm run lint` | ✅ 0 error / 5 warning（4 处 `exhaustive-deps` + 1 处 `revealAiKey` 未使用） |
| typecheck | `npm run typecheck` | ✅ `tsc --noEmit` 无输出 |
| 前端测试 | `npm run test:ui -- --run` | ✅ **26 files / 256 tests passed** |

**结论：五道门禁全绿，与前审核员一致。** 前审核员所述"清 `%TEMP%` 残留"陷阱确认存在且有效——我清理后一次通过 744。

⚠️ **门禁副作用（新增发现，见 §3.1）**：`npm run test:ui` 会在 `frontend/` 落一个
`vitest.config.ts.timestamp-<ts>.mjs` 临时文件，**且未被 .gitignore 覆盖**。跑完门禁直接
`git add -A` 会把它提交进仓库。我已清理，但复现一次即复现。

---

## 1. 对前审核员每条结论的独立裁定

### H1 `build_daily_bars_coverage` 窗口终点 — **成立**（已独立复现）

`backend/astock_backtester/data/operations.py:97-113`。我的实测（真实数据仓，只读）：

```
仓库全局最新数据日: 2026-09-11
300947: 不传end missing=53 | 传end missing=53 | 一致=True
600193: 不传end missing=236 | 传end missing=236 | 一致=True
000638: 不传end missing=261 | 传end missing=261 | 一致=True
```

修复后两口径确实一致（修复前停更股不传参恒为 0）。**显式传 `end_date` 的既有行为未被破坏**：
`end_date=2026-07-14` 时响应 `end_date=2026-07-14`，窗口正确缩短（missing 仍 53 是因为那 53
个洞是 07-14 **之前**的内部洞，不是尾部——语义正确）。

**但引入一个新副作用（前审核员漏了）**：`derived_window_end` 分支每次调用都会执行
`warehouse.coverage()`（`operations.py:99`）。`Warehouse.coverage()` 是全仓分区扫描 + 逐股
累计统计（`warehouse.py:445-480`），在真实仓（5530 只 / 2015-2026）上是秒级到十秒级成本。
而 `build_daily_bars_coverage` 可能被按股票批量调用。本次调用点在 `_tail` 之前只算一次
（循环外），所以**不是** O(n²)，可接受；但它是每次请求一次全仓扫描，属于"为了对齐口径
付出的一次全仓代价"。建议后续用 `self._last_coverage` 之类快照缓存。**裁定：成立，附性能备注。**

### M1 会话锁 `AI_MAX_SESSION_LOCKS = 512` 淘汰 — **不成立（存在真实竞态）**

前审核员称"被持有的锁绝不淘汰，互斥语义不受影响"，其测试
`tests/test_ai_service_http.py::test_ai_session_locks_are_bounded_and_reusable`
只覆盖了「锁已被 `acquire()` 持有时不被淘汰」这一条路径（`facade.py:210` `not stale_lock.locked()`）。

**我复现了它没覆盖的窗口**（`facade.py:200-216` 与 `229-230` 之间）：

```python
session_lock = self._session_lock(candidate_id)   # ① 从字典取出锁对象，此刻未 acquire
if not session_lock.acquire(timeout=...):          # ② 稍后才 acquire
```

在 ① 与 ② 之间，若另一个线程为**新** session 调用 `_session_lock` 且字典已达上限，
淘汰循环会遍历并把 `victim` 从字典删除（此时 `victim.locked() is False`）。随后：
- 线程 A 仍在用已脱离字典的锁对象 `L1` 跑 worker；
- 第三个请求到达同一 session 时字典里没有 key → 新建 `L2`；
- **同一会话出现两把互不相斥的锁 → 两个 worker 并发写同一会话** —— 正是本次改动
  声称要根除的"悬空 tool_calls / 失忆"根源。

实测输出：

```
B 淘汰后 victim 仍在字典: False
第三个请求拿到的锁 === A 持有的锁: False
两把锁不同对象: True
```

`AGENT必读.md §16.2` 把「per-session 锁串行化」写成不变量的前提，而该实现在高并发
（>512 活跃会话 + 同一用户快速重发）下会**静默失效**。512 的上限本身合理，问题在淘汰
时未检查"锁对象是否已被取出但尚未 acquire"。**裁定：前审核员结论不成立。**

> 修复方向（供决策）：淘汰时对候选做 `lock.acquire(blocking=False)` 试探后再 `release()`，
> 或改用「引用计数 + 只在计数为 0 时淘汰」，或在 `chat_stream` 的 `finally` 里按 id 校验
> `self._session_locks.get(sid) is session_lock` 再操作。

### M2 `embedding_base_url` 留空保持 — **成立**

`config.py:143-151`：`api_key` / `embedding_api_key` / `embedding_base_url` 三者都是
"留空 coalesce 到当前值"，语义一致。且 `embedding_endpoint()`（`config.py:96-101`）
留空回落主配置。测试 `test_ai_config_store_keeps_embedding_base_url_when_blank` 直接
调用 store（不走 HTTP 兜底），确实验证了原缺陷路径。**裁定：成立。**

### M3 `useMarketPolling.ts` 缩进重排"逻辑零变更" — **不成立（描述错误）**

前审核员写的是"缩进错乱，按层级重排，逻辑零变更"。**实际不是缩进重排，而是新增了一个参数**：

```diff
-          nextRefreshMs = refreshIntervalForMarketResult(nextPhase, snapshot.diagnostics, snapshot.status === "unavailable");
+          const missingBreadth = snapshot.breadth == null && snapshot.status !== "unavailable";
+          nextRefreshMs = refreshIntervalForMarketResult(nextPhase, snapshot.diagnostics, snapshot.status === "unavailable", missingBreadth);
```

`git diff -w`（忽略空白）后**仍然显示这两处改动**，证明不是纯缩进。
`marketRefresh.ts:44-53` 同步新增了 `missingBreadth` 形参与 `DEGRADED_RETRY_MS = 45_000`
分支。这是一处**功能性改动**（缺宽度时 45 秒快速重试），与 `realtime.py` 把
`breadth_time_budget` 从 3.0 提到 8.0 是同一组配套改动。

**风险**：改动本身正确且有测试覆盖（`marketRefresh.test.ts` 3 tests 绿），但前审核员
把它归为"代码整洁"（§M3）并据此判断"逻辑零变更"，**会让后续维护者误以为该文件无可审逻辑**。
这属于审核结论失真，不是代码缺陷。**裁定：不成立（分类与描述错误）。**

### M4 `_consolidate_archive` 压缩失败丢归档 — **成立，且回滚验证通过**

前审核员称已修复。我做两重独立验证：

1. **运行时替换为修复前实现**（先清空再调模型）：`pending_archive: 20 → 0`，内容丢失。
   修复后实现：异常被吞、`pending_archive` 保留 20。
2. **真实 pytest 回滚验证**（临时 conftest 覆盖 `_consolidate_archive` 为 buggy 版，
   跑新增的两个测试）：

```
=== 回滚 M4 后 ===
FAILED test_agent_keeps_pending_archive_when_compaction_model_fails
1 failed, 1 passed
=== 未回滚 ===
2 passed
```

**该测试确实能测出 bug，修复确实有效。** 额外澄清：两个新测试中只有
`test_agent_keeps_pending_archive_when_compaction_model_fails` 是回归守卫；
`test_agent_clears_pending_archive_only_after_successful_compaction` 在 buggy 版本下
**也通过**（因为模型成功返回），它不是回归测试，只是正向路径断言。

**新问题（前审核员漏了）**：见 §3.2 —— 修复后的 `pending_archive` 在"压缩总是失败"
时**确实会无限增长**（因为只在成功时清空）。前审核员 §3.3 断言"不存在无限增长"，
在异常路径下不成立。

### 3.1 `_repair_interrupted_turn` 误伤/切断配对 — **基本成立，但漏了一条静默失效**

`agent.py:202-244`。我构造多种形态验证：
- 正常配对 + 悬空 `tool_calls` → 正确补齐、不误伤（`test_agent_repair_keeps_intact_sessions_unchanged` 绿）；
- 归档边界前推到下一个 `role == "user"`（`agent.py:289`）→ 正常轮次边界不切配对。

**但发现前审核员未提及的边界**：当 `overflow` 前推越过最后一条 `user` 时，
`agent.py:291-292` 直接 `return`，**放弃归档**。见 §3.2。

「`answered` 全量累积」观察项（前审核员 L1）我认同：理论上限存在，当前上游唯一 id，不触发。

### 3.2 `warehouse.py` 新口径 — **日线成立；市值部分成立；资金流尾部漏统计（新缺陷）**

用 tmp 小仓做语义验证（真实仓太慢且不必要）：

```
内部洞场景:      daily missing=10  (期望 14-4=10)  ✅
停更尾部场景:    daily missing=11  (期望 14-3=11)  ✅
市值(内部NaN1 + 尾部11): market_cap=12 (期望 12)   ✅ 无重复计数
资金流(B无资金流, OHLC仅3行): capital_flow=3        ❌ 期望 3内部+11尾部=14
```

**新发现缺陷（前审核员漏了）**：`warehouse.py:467-473` 资金流尾部统计的
`boundary_by_symbol` 对"有 OHLC 行但该股资金流已有值"的股票会退回 `flow_last_by_symbol`，
而 `symbols=set(flow_rows_by_symbol)` 又**排除了完全没有资金流值的股票**。结果是：
**一只股票如果完全没有资金流数据（`main_net_inflow` 全 NaN），它既进不了
`flow_rows_by_symbol`（没有非 NaN 值），也不在 tail 的 `symbols` 集合里** →
它的资金流缺口被完全漏统计。

这与真实仓数据吻合：`capital_flow missing_rows = 913,371`，但 `capital_flow`
`stale_distribution` 显示 **4152 只停在 2026-06-18、1373 只停在 2026-06-29**
——大量股票资金流远落后于日线，却只报 91 万缺口，说明尾部大段未被计入。
（对比：`daily_bars` 5511/5530 更新到最新，缺口 79 万主要是历史区间天然缺失。）

注意：`market_cap` 的 `symbols` 用 `set(cap_rows_by_symbol) | {daily_symbols 中缺 cap 的}`
（`warehouse.py:459`）做了补集，所以市值没有这个问题；**资金流少了这一步补集**。
不一致，看起来是遗漏。**裁定：前审核员"H2/L2 仅偏保守"的判断不覆盖此处——这里偏乐观（少报）。**

### 3.3 `data_gap_profile` 旧格式分区安全 — **成立**

我构造缺 `float_market_cap` / `main_net_inflow` 列的旧分区：`data_gap_profile()`
正常返回、`available=True`、`symbols=0`，**不抛异常**；`coverage()` 走
`market_cap_missing_rows += len(ohlc_complete)` 分支正确（=2）。**裁定：成立。**

### 3.4 `realtime.py` 预算调整最坏延迟 — **部分成立**

`realtime.py:206-212`：`breadth_time_budget 3.0→8.0`、`breadth_source_timeout 2.5→2.2`。
前端对冲确实存在（`marketRefresh.ts` `DEGRADED_RETRY_MS=45_000` + 流式首包先回指数/板块）。
但"最坏 8 秒"是否被前端 idle 超时覆盖，前审核员**没有给出前端超时值**。
我未在本机复现真实上游慢源（需外网 + 8 秒真实等待，且当前 sidecar 未运行）。
**裁定：部分成立（论证不完整，未能实测）。** 不阻塞提交，但建议补一条
"流式接口 idle 超时 > 8s + 首包间隔"的显式断言。

### 3.5 `reports.py` 一天跑多次 — **成立**（我用注入时钟实测）

`reports.py:398-425`。注入 Clock：

```
now=15:30 tick=['report','evolution']
now=15:31/35/45/16:00 tick=[]          ← 同一天不再触发
now=16:01 tick=[]                      ← 超出 30 分钟窗口
total jobs: ['review','evo']  ← 单进程当天恰好一次
```

**单进程一天最多一次，成立。** 跨 0 点不补跑（`target=23:55, now=00:05 → False`）确认。
进程重启落在窗口内会补跑一次（前审核员 L4 已列，设计内）。

### 3.6 策略体检绝不改写用户策略 — **成立**

`reports.py` 全文写入点只有 4 处：`reports.py:98-99`（ReportStore 内）、
`reports.py:119-120`（evolution state 内）。用户策略文件
`saved-strategies.json`（`reports.py:207-208`）**只有 `_load_saved_strategies` 读取**，
全文无任何写回。参数覆盖都用 `settings.model_copy(update=...)`（`reports.py:242,244`）
作用在局部对象。**裁定：成立。**

### 3.7 `overfit.py` 指标口径 — **成立**

`engine.py:496,513` 确认 `total_return_pct` / `win_rate_pct` / `max_drawdown_pct` 均为
**小数比例**（`total_return = final_equity/initial_cash - 1`）。`overfit.py:14-21`
阈值（`SUSPICIOUS_WIN_RATE=0.999`、`SUSPICIOUS_RETURN=1.0`）与 `{%}` 格式化匹配。
前端 `ResultsOverview.tsx` 只拼 `finding.message`，不做二次换算，且
`aiOverfitCheck(aiBaseUrl, { metrics: result.metrics })` 原样透传。**裁定：成立。**

### 3.8 其余复核项

- **`/ai/report/file` 路径穿越**：实侧 `_safe_report_name` 拒绝 `..\escape.md`、`../x.md`、
  `a/b.md`、`.hidden.md`、`C:\evil.md`、`x.txt`、`''` → 全部 `None`。安全。**成立。**
- **`data_health_report` 边界**：`local_tools.py:143` 调 `backend.warehouse.data_gap_profile()`
  —— 公共方法，符合 §15.3「禁止跨模块私有访问」。**成立。**
- **`AiSessionBusy` 错误码**：`errors.py` 新增 `code="ai_session_busy"`，前端
  `aiTypes.ts::translateAiError` 已同步按码翻译，符合 §15.6。**成立。**

---

## 2. 前审核员的自我更正是否到位

前审核员在数据仓报告里更正过两件事：(a) 损坏归因从"自己的脚本"改为"桌面端 sidecar 并发写"；
(b) coverage 口径误判。我复核：

- (a) **方向正确**：`warehouse.py:116-134` 的 `write_daily_bars` 确为无跨进程锁的
  read-modify-write + 整文件 `to_parquet`，`_gap_profile_lock` 只是 `threading.Lock`
  （进程内），跨进程无保护。结论与我一致。我实测当前**无** `astock-data-service.exe`
  在运行（`Get-Process` 空），故本报告全部走只读路径，未触发该风险。
- (b) **H1 修正确实落地**（§1 H1 已独立复现）。

但前审核员把 `write_daily_bars` 无锁（H2）与 O(n²)（§10）都归为"既有代码，不在本轮 diff"
——这个定性**正确**，它们确实不在 `git status` 改动面内，不应作为本次提交的阻塞项。

---

## 3. 新发现的问题（本轮独立价值）

### 3.1 【提交阻塞·卫生】`test:ui` 产物未被 gitignore 覆盖

`frontend/vitest.config.ts.timestamp-<ts>.mjs` 是 vitest 运行时生成的临时配置副本，
跑一次 `npm run test:ui` 必现，**且 `git check-ignore` 返回非忽略**（exit=1）。
`AGENT必读.md §14` 明令"不应留下无归属 untracked 文件"。跑完门禁直接 `git add -A`
会把它提交。我已删除当前实例，但**每次跑门禁都会复现**。
-> 建议在 `.gitignore` 补 `frontend/vitest.config.ts.timestamp-*.mjs`（或 `*.timestamp-*.mjs`）。

### 3.2 【中·功能】字符预算归档失效 + `pending_archive` 可无限增长

`agent.py:270-302` 的字符分支：

```python
overflow = max(overflow, index + 1)              # 逐个累加字符，overflow 推到 index+1
while overflow < len(messages) and messages[overflow].get("role") != "user":
    overflow += 1
if overflow >= len(messages):
    return                                       # ← 直接放弃归档
```

当窗口内最后一条 `user` 之后全是 `assistant`/`tool`（**这正是 `AgentRunner` 每轮追加的形状**）
时，前推会越过末尾 → `overflow >= len(messages)` → **静默放弃归档，字符预算完全不生效**。
实测：

```
形态1 [user, 超长assistant(40000字)]:  条数 2→2, 字符 40002→40002, 归档 0   ← 未生效
形态3 [user + 10次工具往返 + 长final]: 条数 22→22, 字符 70002→70002, 归档 0 ← 未生效
形态4 [user,长a,user,长b]:             条数 4→2, 字符 40004→20002, 归档 2   ← 生效
```

形态 1/3 是真实会话形态（用户粘贴长文、长回答）。后果：`SHORT_TERM_MAX_CHARS=36_000`
形同虚设，请求上下文可能显著超预算；且配合 §3.2 的 M4 修复——
**若压缩长期失败，`pending_archive` 只会越攒越多**（成功才清空），
前审核员 §3.3"不存在无限增长"的结论在异常路径下**不成立**。

> 注：本条与 M4 修复方向不冲突，是 M4 修复引入/暴露的新边界（修复前是"丢内容"，
> 修复后是"内容只增不减"）。二者都需要"压缩成功后按条数上限裁剪/丢弃最旧归档"的兜底。

### 3.3 【中·功能】`capital_flow` 尾部缺口漏统计（少报）

见 §1 "3.2"。`warehouse.py:467-473` 的 `symbols=set(flow_rows_by_symbol)` 排除了
"完全没有资金流值"的股票，导致这部分股票的尾部缺口不计入 `capital_flow missing_rows`。
真实仓 `stale_distribution` 显示 4152 只停在 2026-06-18，与 `missing_rows=913,371`
不成比例，佐证漏报。修法与 `market_cap` 一致：把 `daily_symbols` 的补集并入。

### 3.4 【轻·健壮性】`thread.start()` 失败时锁双重释放，掩盖原始异常

`facade.py:293-299`（内层显式 `release()` + re-raise）与 `facade.py:307-311`
（`finally` 在 `worker_started=False` 时再 `release()`）在 `thread.start()` 抛错时
**释放两次**。实测：

```
[start_raises=True] 传播出的异常: RuntimeError: can't start new thread
[start_raises=True] finally 里 release 失败: RuntimeError: release unlocked lock
```

锁最终未泄漏（`locked=False`，因为首次 release 已生效），但 `finally` 里的
`RuntimeError` 会**替换掉原始异常**，用户看到的是费解的 `release unlocked lock`
而非"线程资源不足"。前审核员 §3.2 把这条路径判为"✅ 显式 release() 后 re-raise"，
**未发现二次释放**。

### 3.5 【轻·卫生】`tests/test_warehouse.py` EOF 多一个空行

`git diff --check` 报 `tests/test_warehouse.py:617: new blank line at EOF.`（exit=2）。
`AGENT必读.md §14` 建议提交前跑 `git diff --check`——这一条会亮红。

### 3.6 【轻·文档】新增/未跟踪文档未确认是否应入库

`git status` 有 4 个 untracked 文档：`docs/agent-skills-research.md`、
`docs/data-gap-rootcause-2026-09-14.md`、`docs/review-2026-09-14-uncommitted.md`
（+ 本报告）。它们**不在 .gitignore**，会随 `git add -A` 进库。
前两份含真实运行数据（进程 PID、CPU 时间、路径），建议确认是否适合公开进 GitHub。

---

## 4. 明确回答：这份改动可以提交吗？

**不建议立即提交。** 门禁虽全绿，但存在 1 个功能正确性缺陷 + 1 个提交卫生阻塞：

### 阻塞项（必须处理）

| # | 问题 | 位置 | 性质 |
| --- | --- | --- | --- |
| B1 | 会话锁淘汰竞态：锁在"已取出未 acquire"窗口被淘汰 → 同一会话两把锁 → 互斥静默失效 | `facade.py:200-216, 229-230` | 与本次改动**明确宣称修复的目标**（悬空 tool_calls/失忆）直接冲突；`AGENT必读 §16.2` 不变量被破坏 |
| B2 | `frontend/vitest.config.ts.timestamp-*.mjs` 未被 gitignore，跑门禁必现 | `.gitignore` / `frontend/` | `AGENT必读 §14` "不得留无归属 untracked 文件"；会污染提交 |

### 建议同批修（非硬阻塞，但属本次改动自身引入/暴露）

| # | 问题 | 位置 |
| --- | --- | --- |
| S1 | 字符预算归档在常见会话形态下静默失效；`pending_archive` 在压缩持续失败时只增不减 | `agent.py:270-302, 304-331` |
| S2 | `capital_flow` 尾部缺口漏统计（少报，`market_cap` 有补集、`capital_flow` 没有） | `warehouse.py:467-473` |
| S3 | `thread.start()` 失败时双重 release 掩盖原始异常 | `facade.py:293-311` |
| S4 | `test_warehouse.py` EOF 空行（`git diff --check` 红） | `tests/test_warehouse.py:617` |

### 可以提交的部分

- H1（operations 窗口终点）、M2（embedding 留空保持）、M4（压缩失败不丢归档）**修复正确且验证有效**；
- M3 实际是功能改动而非缩进重排——**代码正确，但前审核员的分类描述错误**，需更正记录；
- `reports.py` 调度不重复跑、绝不改写用户策略；`overfit.py` 口径与前端一致；报告路径安全；
  `data_gap_profile` 旧格式安全 —— 这些复核项**均成立**；
- 五道门禁全绿；架构不变量（只读数据仓、唯一写路径、稳定错误码、token 纪律）未被破坏。

**一句话**：H1/M2/M4 的修复是真实有效的，但本次改动同时引入了 1 个会破坏会话互斥语义的
并发缺陷（B1），且留下 1 个必现的提交卫生问题（B2）。修完 B1/B2 后可提交；S1–S4 建议
同批或紧随其后处理。

---

## 附：复核方法与可复现性

所有结论均由可执行探针产出（运行后即删，未留盘）：
- 锁淘汰竞态：绕过完整 `AiService` 构造，直接绑定 `AiService._session_lock`，
  用 `threading.Barrier` 卡在"取出锁/acquire"之间触发淘汰；
- M4 回滚：把测试文件复制到临时目录 + 临时 `conftest.py` 覆盖 `_consolidate_archive`
  为修复前实现，用真实 pytest 跑新增测试；
- coverage 口径：tmp 目录构造最小仓库（内部洞/停更尾部/旧格式缺列）逐项对期望值；
- 调度器：注入可控 `datetime` 子类，逐分钟驱动 `tick()`；
- 真实仓：`Warehouse(root).coverage()` 与 `build_daily_bars_coverage(cache, warehouse, ...)`
  只读调用（本机当前无 `astock-data-service.exe` 运行，无写入竞争）。

报告本身是唯一新增文件，未修改任何其它文件。
