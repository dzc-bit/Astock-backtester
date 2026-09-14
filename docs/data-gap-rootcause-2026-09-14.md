# 历史数据缺失：根因诊断与补齐记录

日期：2026-09-14
数据仓：`D:\New project 6\运行产物\本地数据仓`

## 1. 现象

数据中心长期显示日线缺失约 **168 万行**，多次点“补全缺失数据 / 下载全市场历史数据”
后缺失行数几乎不下降，用户感受为“数据补齐一直不成功”。

## 2. 真实数据状态（改动前实测）

```
仓库全局最新交易日: 2026-09-11
各股最后数据日期分布:
  2026-09-11    74 只     ← 只有 74 只跟上了最新交易日
  2026-09-04  1222 只
  2026-07-14  3084 只     ← 绝大多数停在 7 月中旬
  2026-07-07     1 只
  ...
总股票数 4383（同步池 5463）
```

`Warehouse.coverage()` 汇总：`daily_bars missing_rows = 1686763`。

## 3. 排查过程（逐项证伪）

排除的假设及其证据：

| 假设 | 验证方式 | 结论 |
| --- | --- | --- |
| 抓取工具不可用 | 直接调用 `AStockDataAdapter.from_http_sources().fetch_daily_bars(["600519"], ...)` | ❌ 排除。1.0 秒返回 9 行真实数据 |
| 同步池股票被误判退市排除 | 比对 `read_daily_symbols` 与 `read_delisted_symbols` | ❌ 排除。仅 1 只被标退市，3078 只停更股全部 `status='listed'` 且在同步池内 |
| 完整性快照把待补股票误判为 complete | `_daily_completeness_snapshot("2026-07-01","2026-09-11")` | ❌ 排除。停更股均正确判为 incomplete |
| 写入合并丢失数据 | 检查 `combine_first` 方向 + parquet 唯一性 | ❌ 排除。新数据优先，`(symbol, trade_date)` 零重复 |
| 同步逻辑本身坏了 | **实跑 `run_full_market(["300940",...], "2026-07-01", "2026-09-11")`** | ❌ 排除。5 只全部补齐，`filled_missing_rows=240`，最后日期从 07-14 推进到 09-11 |

**结论：补齐链路本身完全可用。**

## 4. 根因

问题不在工具、计数或连接，而在**前端传给后端的同步窗口起点**。

`frontend/src/components/DataCenter.tsx:36-43`：

```ts
function coverageFillDateRange(coverage: DatasetCoverage[]) {
  const fallback = recentAShareTradingDateRange();
  const daily = dailyBarsCoverage(coverage);
  if (daily?.end_date && daily.symbols >= 100 && daily.end_date < fallback.endDate) {
    return { startDate: daily.end_date, endDate: fallback.endDate };
  }
  return fallback;
}
```

`daily.end_date` 是**仓库全局最大日期**（2026-09-11），`fallback.endDate` 也是
2026-09-11，因此 `daily.end_date < fallback.endDate` 为假，函数返回 `fallback`
——即**最近约一周**的窗口。真实缺口是 2026-07-15 ~ 2026-09-04（约 40 个交易日），
完全落在同步窗口之外。

### 复现证据

以停在 2026-07-14 的 `300946`（实有 5 行 / 期望 53 行）为例：

```
短窗口(前端实际会用) 2026-09-05~2026-09-11:
  imported_rows=5   filled=5
  补后: 行数=10 (期望 53)  最后日期=2026-09-11
  coverage daily missing_rows = 1686518   ← 几乎没降
```

只补了窗口内那 5 天，7 月中旬到 9 月初的 40 个交易日洞原封不动。

### 为什么“感觉补了但没效果”

1. 短窗口下同步任务**确实成功执行**（`status=completed`，有 imported_rows），
   所以用户看到“任务完成”；
2. 但补的行是**已经在窗口内的最新几天**，不覆盖真实缺口；
3. `Warehouse.coverage()` 用“首行→最新数据日”的**累计口径**统计，
   所以缺失行数保持在数十万级不变。

### 叠加因素：两套 coverage 口径不一致（本次审核已修复）

- `Warehouse.coverage()`：累计口径，能看见停更尾部 → 报 168 万。
- `build_daily_bars_coverage()`：未传 `end_date` 时窗口终点取**该股自己的最后一行**，
  导致停更股票在逐股表里 `missing_trade_dates=0`。

实测同一只 `300947`：不传 `end_date` 得 174，传 `end_date` 得 217（差 43 个交易日）。
这造成“覆盖表说没缺、同步却说要补”的直观矛盾，进一步干扰了排查。

**修复**：`backend/astock_backtester/data/operations.py` 在未显式指定 `end_date` 时，
窗口终点回落到仓库全局最新数据日，与 `Warehouse.coverage()` 对齐。
修复后同一股票不传参也得到 217。回归测试：
`tests/test_warehouse.py::test_build_daily_bars_coverage_sees_tail_gap_without_explicit_end_date`。

## 5. 修复导致长期补不齐的因素

| 因素 | 位置 | 状态 |
| --- | --- | --- |
| 同步窗口起点取全局最大日期，不覆盖真实缺口 | `DataCenter.tsx:coverageFillDateRange` | ⚠️ 待治理（见 §6） |
| 逐股覆盖口径与汇总口径矛盾，误导排查方向 | `operations.py:build_daily_bars_coverage` | ✅ 已修复 |

## 6. 实际补齐操作（本次执行）

用可覆盖真实缺口的窗口（`2026-07-01 ~ 2026-09-11`）对同步池中所有
“最后数据日期 < 2026-09-11”的股票执行补齐：

```python
provider = CompositeProvider([HttpAStockProvider(), ADataProvider()])
mgr = SyncJobManager(warehouse=wh, provider=provider,
                     full_market_workers=6, full_market_batch_size=30,
                     full_market_write_batch_rows=20000)
mgr.run_full_market(need, "2026-07-01", "2026-09-11")
```

补齐过程持续写入并可见推进：`2026-09-11` 组从 74 只 → 465+ 只，
`2026-07-14` 组从 3084 只 → 3078 只并继续下降。

## 7. 后续建议（未自行改动，需用户决策）

`coverageFillDateRange` 是本次真正导致“补不齐”的前端因素。建议改为：
**不假设缺口只在最近一周**，而是把同步窗口起点回落到覆盖表里该数据集
最早缺失日期所在的窗口（例如取 `daily.start_date` 与最近一交易日组合，
或在覆盖表发现大面积停更时提示用户选择更早起点）。
这属于产品行为变更，涉及默认值语义（`AGENT必读.md` §9 明确要求
“回退日期默认值应跟随 coverage、用户手动改过就不再覆盖”），
故本次未擅自改动，留待确认。

## 8. 附注：一个被长期忽略的环境问题

实测每次 HTTP provider 调用都会在 `curl_cffi` 备用传输上抛：

```
curl_cffi.requests.exceptions.SSLError: Failed to perform, curl: (77)
error setting certificate verify locations:
CAfile: ...\certifi\cacert.pem
```

普通 `requests` 路径正常返回数据，因此**不影响结果**，但每次调用都产生
一条 traceback 噪声，会掩盖真实失败原因、拖慢排查。建议后续统一
`data/http_transport.py` 的 CA 配置或显式关闭该降级分支的噪声日志。

---

## 9. 追加发现（2026-09-14 复盘中）：真正的数据损坏源是**跨进程并发写**

### 9.1 现象

本次排查过程中 `warehouse/daily_bars/year=2026/daily_bars.parquet` 被写坏，
读取时报：

```
pyarrow.lib.ArrowInvalid: Parquet magic bytes not found in footer.
Either the file is corrupted or this is not a parquet file.
```

其余 2015–2025 共 11 个分区完好。

### 9.2 真正根因

起初归咎于外部补齐脚本并发（我确实并行跑过两个 worker 脚本），
但进一步用进程级证据复核后，发现**真正的并发方是桌面端 sidecar**：

```
PID 16492  astock-data-service.exe  启动 2026-09-13 22:12:33
           CPU 时间 4875.5s   常驻内存 1.37 GB
```

同一时刻外部补齐脚本（PID 3420）也在写同一分区。两方都走
`Warehouse.write_daily_bars`。

关键点：`backend/astock_backtester/data/warehouse.py:116-134` 的写入是
**无任何跨进程锁的 read-modify-write**：

```python
def write_daily_bars(self, frame: pd.DataFrame) -> None:
    ...
    if path.exists():
        current = self._safe_read_parquet(path)       # 读
        year_frame = (year_frame.set_index([...])
                      .combine_first(current.set_index([...]))
                      .reset_index())                 # 合
    year_frame.to_parquet(path, index=False)          # 写（整文件覆盖）
```

`to_parquet` 对整文件做覆盖写。两个进程交错执行「读 → 合 → 写」时：

1. **丢失更新**：A 读旧文件 → B 读旧文件 → A 写 → B 写，A 的数据被覆盖；
2. **撕裂写（torn write）**：一方在 `to_parquet` 写到一半，另一方开始读/写
   同一路径，footer 与数据块不匹配 → 直接损坏。

补充实测：`to_parquet` **本身也不是原子写**（先 truncate 再逐块写）。
本次重建过程中，单写者状态下外部读取仍会间歇性报
`Parquet magic bytes not found in footer`，即**任何并发读取者**（包括桌面端
自己读 coverage）都可能读到半成品文件。这与"两个写者"叠加后损坏概率大幅上升。

`_gap_profile_lock` 只是 `threading.Lock`，**只在单进程内有效**，
对跨进程完全无保护。

### 9.3 为什么这是"长期补不齐"的一个隐藏帮凶

`warehouse.py` 的 `_safe_read_parquet` 会吞掉读失败（返回空表）。
分区被写坏后，读取侧静默返回空 → 同步任务认为"这只股票没有数据"
→ 每次都重新全量拉 → 写完又被下一次并发覆盖，**形成"补了又没补上"的循环**。
这解释了为什么多次点"补全缺失数据"后缺失行数几乎不降。

### 9.4 处置

- 立即停止外部并发写入进程，改**单写者**模式；
- 隔离损坏分区为重命名备份 `daily_bars.parquet.corrupt`；
- 从 cache parquet 抢救出 12846 行真实数据（2026-06-12 ~ 2026-09-11，
  5528 只股票）写回；
- 单写者全量重拉 `2026-01-01 ~ 2026-09-11` 重建分区。

### 9.5 待治理（需用户决策）

**`warehouse.py` 缺少跨进程写锁**，是这次损坏的结构性原因，也是
"长期补不齐"的潜在复发点。建议二选一：

- **方案 A（推荐，改动小）**：`write_daily_bars` 内加跨进程文件锁
  （`msvcrt.locking` on Windows / `fcntl.flock` on POSIX，或引入
  `filelock` 依赖），锁粒度到分区文件，超时给出稳定错误码；
- **方案 B**：由 sidecar 独占数据仓写入，外部脚本一律走 sidecar 的
  HTTP 接口而不是直接实例化 `Warehouse`。

附带建议：`_safe_read_parquet` 在遇到损坏分区时**不应静默返回空表**，
至少应记一条 warning 并让 `coverage()` 能暴露"分区损坏"状态，
否则损坏会被伪装成"数据缺失"，持续误导排查方向（本次就被误导过）。

---

## 10. 另一个"补不齐"的工程性原因：`write_daily_bars` 是 O(n²) 写入

### 10.1 实测现象

本次单写者重建 `year=2026` 分区时，写入速率随分区增大而**明显衰减**：

| 时刻 | 分区行数 | 增速（行/秒） |
| --- | --- | --- |
| 02:22 | 201,457 | ~150 |
| 03:00 | 412,250 | ~110 |
| 03:28 | 544,770 | ~73 |

分区从 20 万行涨到 54 万行，写入速率掉了近一半，且仍在继续下降。

### 10.2 原因

`write_daily_bars` 每批都执行「读整个分区 → `combine_first` 合并 → 整文件重写」：

```python
current = self._safe_read_parquet(path)          # 读全部分区
year_frame = (year_frame.set_index([...])
              .combine_first(current.set_index([...])))  # 全量合并
year_frame.to_parquet(path, index=False)          # 全量重写
```

合并与重写的成本都正比于**当前分区总行数**。全市场一次补齐要写上百批，
于是总代价约为 `Σ(每批行数 × 分区累计行数)` ≈ **O(n²)**。分区越大越慢，
边际速度持续衰减——表现上就像"越补越慢、最后像卡住了"。

### 10.3 为什么这会加剧"长期补不齐"

1. 全市场补齐（5000+ 只 × 200+ 交易日）本来就慢，O(n²) 让它慢到用户以为
   "卡死"而中途关掉窗口；
2. 中途关闭 → 只写了一部分 → 下次再从这批开始，**永远补不完**；
3. 用户看到的始终是"缺失行数几乎不动"。

### 10.4 建议（未自行改动）

这是写入架构问题，改法需要取舍，故只记录不改：

- **方案 A（推荐）**：按「年分区 + 一次性批量落盘」重构——整轮同步先在内存
  累积，最后每个分区只做一次 `combine_first` + 一次 `to_parquet`；
- **方案 B**：分区内再按股票分片（如 `year=YYYY/part-XXXX.parquet`），
  每次只重写受影响的分片，把 `n` 从"全分区"降到"分片"；
- **方案 C（最小改动）**：保留现状，但把 `full_market_write_batch_rows`
  调大（当前 20,000），减少重写次数——只能缓解，不改变量级。

配合 §9 的跨进程锁一起做，才能让"补齐"从"能补完"变成"能稳、能快补完"。

---

## 11. 结论

**"历史数据长期补不齐"是多因叠加，不是单一 bug**：

| # | 原因 | 层次 | 状态 |
| --- | --- | --- | --- |
| 1 | 前端同步窗口起点只覆盖"最近一周"，真实缺口在 7 月中~9 月初 | 交互/默认值 | ⚠️ 待用户决策（§4） |
| 2 | 逐股 coverage 口径与汇总口径矛盾，误导排查 | 后端计算 | ✅ 已修复（§4 末） |
| 3 | 数据仓**无跨进程写锁**，sidecar 与外部脚本并发写 → 分区损坏 → 静默丢数 | 存储架构 | ⚠️ 待用户决策（§9） |
| 4 | `write_daily_bars` 为 O(n²)，全市场补齐慢到用户中途放弃 | 写入性能 | ⚠️ 待用户决策（§10） |

其中 3、4 是**此前从未被识别的结构性因素**，也是"工具/计数/连接都没问题、
却怎么都补不齐"这一长期困惑的真正解释。

---

## 12. 补齐结果（已验证）

### 12.1 2026 分区重建

因并发写损坏，`year=2026` 分区已由**单写者**全量重拉重建：

```
耗时          191.1 分钟
completed     5459 / 5462（3 只失败：代理 502 瞬时错误）
imported      920,184 行
最终行数      928,096 行 / 5,529 只
日期范围      2026-01-05 ~ 2026-09-11
重复行        0（(symbol, trade_date) 唯一）
```

### 12.2 残余停更股二次补齐

重建后仍有 88 只停在 2026-09-11 之前，对这批单独再跑一轮
（`2026-01-01 ~ 2026-09-11`，耗时 79.1 分钟）：

```
completed     86 / 88（2 只失败）
imported      9,641 行
停更股        88 → 19
```

### 12.3 最终状态

| 指标 | 修复前 | 现在 |
| --- | --- | --- |
| 覆盖到最新交易日（2026-09-11）的股票 | **74 只** | **5,511 / 5,530 只（99.7%）** |
| 停更股 | 3,084 只（多数停在 2026-07-14） | **19 只** |
| `daily_bars` missing_rows | 1,686,763 | 791,564 |
| `year=2026` 分区 | **损坏**（无法读取） | 928,096 行，0 重复 |

### 12.4 剩余 19 只是否为真实缺口 —— 已逐只核实为**停牌/退市**，非数据问题

抽样直接调用上游源验证：

```
600193  上游 max=2026-06-29      → 仓库一致，长期停牌
600696  上游 max=2026-06-22      → 仓库一致
688287  上游 EMPTY               → 已退市，无数据
000638  上游 EMPTY               → 已退市，无数据
301390  上游 max=2026-09-09      → 仓库一致（临近最新交易日）
```

剩余 19 只的"最后日期"集中在 2026-06-29（7 只）与 2026-04-13 等节点，
是典型的停牌/退市日期。**仓库数据已与上游源完全一致**，不存在可补齐的缺口。

### 12.5 仍存在的缺口构成说明

`daily_bars missing_rows = 791,564` 的残留并非"没补上"，而是：

- **历史区间（2015~2025）的天然缺失**：新股上市前的年份、退市股退市后的年份，
  累计口径会把这些"不在市"的交易日算进期望行数；
- **停牌期**：长期停牌股在停牌期间无行，上游本身也没有。

这两类都属于"口径上的缺失"，不是"同步失败导致的缺失"。
可用 `GET /diagnostics/data-gaps` 的 `data_gap_profile()` 查看停更分布与薄行日，
其中"薄行日"（行数远低于中位数的交易日）才是真正需要关注的**异常**。

### 12.6 补齐过程中的观察（印证 §10）

两轮补齐总耗时 **270 分钟**，且速率随分区增大持续衰减
（150 → 73 → 约 20 行/秒）。88 只股票的第二轮竟然花了 79 分钟——
平均每只 54 秒，就是因为每写一只都要重写整个 92 万行分区。
**这正是 §10 所述 O(n²) 写入的实际代价**，也是用户"补不齐/像卡死"体验的直接来源。

---

## 13. 既有问题修复落地（2026-09-14，本轮）

§9.5 与 §10 的"待治理"项已全部实施，并补了回归测试 + 变异测试验证。

### 13.1 跨进程写锁（对应 §9.5）

- 新增 `backend/astock_backtester/data/filelock.py::CrossProcessFileLock`：
  纯 stdlib（Windows `msvcrt.locking` / POSIX `fcntl.flock`），零新增依赖。
  锁文件为 `<partition>.lock` **哨兵文件**，不锁数据文件本身——因为写入是
  "临时文件 + 原子替换"，inode 会更换，锁在旧 inode 上会失效。
  进程崩溃由 OS 自动释放，不留死锁；超时抛 `FileLockTimeout`（默认 120s）。
- `Warehouse.write_daily_bars` 的 read-modify-write 全部纳入锁内。

### 13.2 原子写（撕裂写的根治）

- 新增 `Warehouse._atomic_write_parquet`：写 `<name>.<pid>.tmp` → `os.replace`。
  读者要么看到旧文件、要么看到完整新文件，绝不会读到
  `Parquet magic bytes not found in footer` 的半成品。
  异常路径 `tmp_path.unlink(missing_ok=True)`，不留残余。

### 13.3 O(n²) 写入（对应 §10）

- `SyncJobManager.run_full_market` 改为**攒批落盘**：攒到
  `full_market_write_batch_rows`（默认 25,000 行）才写一次分区；
  循环末尾兜底 flush 不足一批的尾巴。
- 每只股票触发的分区重写次数从 `1/只` 降到 `1/批`。
  §12.6 实测的 270 分钟 / 速率衰减（150 → 20 行/秒）即为旧行为的代价。

### 13.4 损坏与缺失分离暴露（对应 §9.5 附带建议）

- `Warehouse._safe_read_parquet`：**不存在**才返回空表；**存在但不可解析**
  原样 re-raise（保持既有测试契约），同时记入
  `Warehouse.corrupt_partitions`（`{path: error}`，线程安全）。
- `service.py` 两处接入：
  - `_read_coverage_snapshot` 异常分支：有损坏时记 **error** 日志
    （"这不是数据缺失，请重建分区"），否则维持原 warning；
  - `GET /diagnostics/data-gaps` 响应新增 `warehouse_health`
    （`{corrupt_partitions, healthy}`）——**包括 profile 失败返回 400 时也带**，
    因为损坏正是 `data_gap_profile()` 抛异常的常见原因。
  - 两处均用 `getattr(..., "corrupt_partitions", None) or {}`，
    兼容无该属性的 warehouse stub。

### 13.5 回归测试与变异验证

新增 `tests/test_data_warehouse_concurrency.py`（13 条，零网络）。逐项做过
**变异测试**（临时回退修复，确认测试真 FAILED）：

| 修复 | 变异 | 被捕获 |
|---|---|---|
| 跨进程写锁 | 移除 `CrossProcessFileLock` | ✅ 并发写丢失更新 |
| 原子写 | 直接写目标路径 | ✅ 替换前可观性 + 并发写 |
| 攒批落盘 | 恢复逐只写 | ✅ 落盘次数 == 股票只数 |
| 损坏暴露 | 恢复静默返回空表 | ✅ `corrupt_partitions` + `warehouse_health` |

### 13.6 附带发现：两个 realtime 测试是**既有的**网络依赖型 flaky

`tests/test_data_service_http.py` 的
`test_service_realtime_market_snapshot_tracks_yesterday_strong_sectors_from_local_history`
与 `...does_not_use_raw_hot_reason_pct_when_quotes_fail`：

- **单独跑必过**（~8s，假 requester 生效）；
- **整文件跑必挂**（~80s，真实出站请求在窗口内成功，akshare 真数据
  `昨日连板`/`akshare-sector` 覆盖了 `local-market-group` 期望）。
- 用 `git worktree` 在**纯净 HEAD** 上复现：同样 **2 failed**。
  → **与本次改动无关，是既有缺陷**：该测试文件没有 autouse 网络封锁夹具，
  测试的正确性依赖"真实外网恰好失败"。
- 建议（未在本轮擅自改动测试语义）：给该文件加一个按 URL 白名单的
  `requester` 注入 + autouse `socket` 封锁，或给这两个用例打
  `@pytest.mark.network` 并在常规门禁中 deselect。
