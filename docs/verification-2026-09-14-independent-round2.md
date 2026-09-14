# 未提交改动独立复核报告 · 第二轮（adversarial verification, round 2）

复核对象：`D:\New project 6` 工作区未提交改动（42 修改 + 8 新增，HEAD `870ee50`，分支 `master`）
复核日期：2026-09-14
复核方式：**独立复跑 + 亲手回滚验证**。不采信上一轮报告的任何结论，所有裁定由我本地可执行探针产出；
探针跑完即删（未留盘），回滚均用 `git diff` 确认恢复干净。
全程只读数据仓，未启动 sidecar，未触发生成/安装流程。

上一轮报告：`docs/verification-2026-09-14-independent.md`（裁定 B1/M2 不成立相关项 + 新发现 B1/B2/S1–S4）

---

## 0. 五道门禁实测（我亲手跑的数字）

| 门禁 | 命令 | 实测结果 | 退出码 |
| --- | --- | --- | --- |
| ruff | `.\.tools\python-build\Scripts\python.exe -m ruff check backend tests scripts` | ✅ `All checks passed!` | 0 |
| pytest | `.\.tools\python-build\Scripts\python.exe -m pytest tests -q` | ✅ **747 passed in 147.88s (0:02:27)** | 0 |
| eslint | `.\.tools\node-v20.18.1-win-x64\npm.cmd run lint` | ✅ **0 errors, 5 warnings**（App.tsx 1×unused-vars；DataCenter.tsx 3×exhaustive-deps；useMarketModules.ts 1×exhaustive-deps） | 0 |
| typecheck | `.\.tools\node-v20.18.1-win-x64\npm.cmd run typecheck` | ✅ `tsc --noEmit` 无输出 | 0 |
| 前端测试 | `.\.tools\node-v20.18.1-win-x64\npm.cmd run test:ui -- --run` | ✅ **26 files / 256 tests passed** | 0 |

**关于 pytest 的 `SystemExit: 1` 假失败**：本轮我未遇到。我在开跑前先删除了 `%TEMP%\pytest-of-大帝之资`，
全量 747 项一次通过、汇总行干净、无 atexit 守卫报错。已知环境陷阱确认**存在但不必然触发**。

**关于前端测试的一次假失败（必须记录）**：我第一次跑 `test:ui` 是在 pytest 全量**并行运行期间**，
结果 `src/strategyEditor.test.tsx > lets the user write and validate Chinese strategy conditions...`
**超时 FAILED（1 failed / 255 passed）**。我做了两次独立复跑：

- 单跑该文件：`51 passed`（EXIT=0）
- 独占重跑全量 `test:ui`：`26 files / 256 tests passed`（EXIT=0）

结论：**这是机器负载导致的抖动，不是真实失败**。但要注意 `strategyEditor.test.tsx` 本身吃 36–46s
测试时间，其中单条用例逼近 5000ms 默认超时，**并行跑门禁时极易假红**。建议后续复核
把 `test:ui` 与 `pytest` 串行执行，或抬高该文件 `testTimeout`。我最终采用的数字是独占重跑的 256。

**门禁副作用确认**：`npm run test:ui` 每次必在 `frontend/` 落下
`vitest.config.ts.timestamp-<ts>-<hash>.mjs`。我本轮实际产生 4 个实例，`git check-ignore` 全部命中
（见 §2 B2），`git status` 中不再出现——B2 修复真实生效。

---

## 1. 逐项裁定表

| 项 | 裁定 | 关键证据 | 复核理由（一句话） |
| --- | --- | --- | --- |
| **B1** 会话锁淘汰竞态 | **部分成立**（淘汰竞态已修，但同一修复在 acquire 超时路径**引入更严重的新竞态**） | `facade.py:237-243, 260-270, 272-277` | `refs>0` 淘汰守卫经回滚验证有效；但超时分支的 `release_session_lock()` 会让**非持有线程** `release()` 掉他人锁 → 互斥彻底失效（见 §3.1） |
| **B2** vitest 临时产物未 gitignore | **成立**（已修复，验证通过） | `.gitignore:29-31` | 两个 pattern 均被 `git check-ignore -v` 命中；本轮 4 个真实产物不再进 untracked |
| **S1** 归档膨胀 + 字符预算失效 | **部分成立** | `agent.py:305-310`（裁剪已修）；`agent.py:282-295`（**字符预算仍未修**） | 裁剪上限 =400、off-by-one 正确、声明数与实际丢弃数一致（见 §2）；但上一轮指出的“字符预算静默失效”**本轮零改动**，形态1/3 实测仍 `归档 0`（见 §3.2） |
| **S2** capital_flow 尾部缺口漏统计 | **成立**（已修复，验证通过） | `warehouse.py:459-479` | 两个 block 结构完全同构；`flow_last` 与 `flow_rows` 键集恒等 ⇒ 第二项迭代源变更语义等价、无回归；补集符号在真实调用点必有 boundary（见 §2） |
| **S3** `thread.start` 失败双重 release | **成立**（已修复，验证通过） | `facade.py:341-348, 356-360` | 实测原始 `RuntimeError: can't start new thread` 原样传播、`refs=0`、`locked=False`、无负计数（见 §2） |
| **S4** `test_warehouse.py` EOF 空行 | **成立**（已修复，验证通过） | `tests/test_warehouse.py` 末尾 | `git diff --check` 退出码 **0**，无 `new blank line at EOF`；文件以单 CRLF 结束 |

---

## 2. 通过项的独立验证细节（可复现）

### B1 淘汰竞态本身：**确已消除**
- 回滚方式：把 `facade.py:239` 的 `stale.refs > 0` 改回旧的 `stale.lock.locked()`，跑两个新测试。
- 结果：`test_ai_session_lock_not_evicted_between_fetch_and_acquire` **FAILED**（`assert None is <_SessionLockEntry>`，
  victim 被淘汰出字典），恢复后 2 passed。
- **该测试确实能测出旧 bug**，是有效回归守卫。
- 但 `test_ai_session_locks_are_bounded_and_reusable` 在回滚下**仍通过**——它只覆盖“已持锁不被淘汰”，
  不是 B1 的回归守卫（与上轮 M4 的同类现象一致：两个测试里只有一个是真守卫）。
- 淘汰循环中 `stale is entry` 是**死代码**（该分支里 `entry` 恒为 `None`），无害但无意义。
- 引用计数本身守恒：正常完成 / 客户端断开 / worker 抛异常 / thread.start 失败四条路径实测
  `refs` 均归 0、`locked=False`、无负数、无泄漏。

### S1 裁剪 off-by-one：**正确**
直接穷举裁剪表达式（`ARCHIVE_MAX_ENTRIES=400`）：

| 输入条数 | 输出条数 | 声明丢弃 | 实际丢弃 | 保留正文 |
| --- | --- | --- | --- | --- |
| 400 | 400 | （不裁剪） | 0 | 400 |
| 401 | 400 | 2 | 2 | 399 |
| 402 | 400 | 3 | 3 | 399 |
| 450 | 400 | 51 | 51 | 399 |
| 5000 | 400 | 4601 | 4601 | 399 |

结论：**输出长度恒为 min(n, 400) ≤ 上限**；`excess = len - 399` ⇒ 占位符占 1 条、正文 399 条，
与注释“保留 `ARCHIVE_MAX_ENTRIES - 1` 条正文”**完全一致，无 off-by-one**。
声明的丢弃条数 == 实际丢弃条数，无谎报。

**与 `_consolidate_archive` 配合**：裁剪后仍有 400 条 ≫ 压缩阈值 12/6000 字符，实测裁剪后调用
压缩仍会触发（模型调用次数 +1，成功后 `pending_archive` 清空）。**不会出现“裁剪到低于压缩阈值导致
永不压缩”的死角**。小归档（3 条）与无溢出场景实测**未被触碰**，不误伤正常归档。

**回滚验证**：移除裁剪逻辑 → `test_agent_caps_pending_archive_when_compaction_keeps_failing`
FAILED（`assert 436 <= 400`）。**测试有效。**

### S2 两 block 同构性：**成立**
- 结构上完全对称：`symbols = set(<rows>) | {s for s in daily_symbols if s not in <rows>}`、
  `boundary = {**ohlc_last(daily_symbols), **<last>(<last> 中不在 ohlc_last 的)}`。
- 迭代源 `flow_rows_by_symbol → flow_last_by_symbol` **不改变语义**：两者由同一个
  `accumulate_symbol_stats(capital_flow_frame, rows=flow_rows_by_symbol, last=flow_last_by_symbol)`
  写入（`warehouse.py:392-397`），键集恒等，故生成字典逐字节相同。
- `boundary is None` 的静默跳过**在真实调用点不可达**：`symbols` 的补集来自 `daily_symbols`，
  而 `daily_symbols` 与 `ohlc_last_by_symbol` 同源于 `ohlc_complete`，其成员必在 boundary 第一项中。
  实测构造 “in symbols 但不在 boundary” 的集合为空。
- **回滚验证**：把 `symbols` 改回 `set(flow_rows_by_symbol)` →
  `test_coverage_capital_flow_counts_symbols_absent_from_flow` FAILED（`assert 2 > 2`，正是旧漏报值）。**测试有效。**

### S3 双重 release：**已修复**
实测 `thread.start()` 抛错时：传播出的异常为原始 `RuntimeError: can't start new thread`（未被替换）、
`refs=0`、`locked=False`、无负 refs。幂等闭包在该路径上确实只 release 一次。

### S4 EOF：**已修复**
`git diff --check` 退出码 **0**，无任何 `new blank line at EOF`。上轮的
`tests/test_warehouse.py:617` 告警消失。

---

## 3. 新发现的问题（本轮独立价值）

### 3.1 【提交阻塞·功能】B1 的修复在 `acquire` 超时路径引入**更严重**的互斥失效

**位置**：`facade.py:260-270`（`release_session_lock`）、`facade.py:272-277`（超时分支）

**机理**：`AI_SESSION_LOCK_TIMEOUT_SECONDS` 到点后走：

```python
if not session_lock.acquire(timeout=AI_SESSION_LOCK_TIMEOUT_SECONDS):
    release_session_lock()          # ← 本线程从未 acquire 成功
    raise AiSessionBusy(...)
```

而 `release_session_lock()` 无条件调用 `session_lock.release()` →
`_SessionLockEntry.release()` → `self.lock.release()`。
**Python 的 `threading.Lock` 不做持有者校验**（与 `RLock` 不同），非持有线程 `release()` **静默成功**，
直接解开**正在持有该锁的另一线程**的锁。

**实测链路**（探针直接驱动真实 `chat_stream`）：

```
步骤1: A 持锁 → locked=True
步骤2: B 同会话请求 → AiSessionBusy；B 之后 locked=False   ← A 的锁被 B 解开了
步骤3: C 同会话请求 → 立即拿到锁；A 与 C 同时认为独占该会话 ← 互斥失效
步骤4: 生成器 close → RuntimeError: release unlocked lock  ← 二次释放抛错
```

**后果**：A 与 C 两个 worker **并发写同一会话** —— 这正是 `AGENT必读.md §16.2` 把
“per-session 锁串行化”写成不变量、以及本轮改动**声称要根除**的“悬空 tool_calls / 失忆”根源。
且触发条件比原 B1 更宽松：**不需要 512 个会话**，只需“一个慢请求 + 同一会话 90 秒内重发一次”，
属正常用户行为（点停止后重发）。生产环境 90s 超时下，任何一次超时都会留下这把被提前解开的锁。

**附带缺陷**：步骤4 的 `RuntimeError: release unlocked lock` 会从生成器的 `finally` 逃逸
（`facade.py:360`）。上一轮 S3 修的“双重 release 掩盖异常”在这里**以新形态复发**——
这次的成因是**跨调用方**的重复 release，实例级 `lock_released` 布尔守卫**无法防御**。

**该缺陷未被任何新测试覆盖**：两个 B1 测试都只走淘汰路径，不含 `acquire` 超时分支。

> 建议修复方向（供决策，非强制）：
> 1. 超时分支**不要**走 `release_session_lock()`，改为只归还引用计数（`refs -= 1`）并让条目保持可用；
>    或在 `_SessionLockEntry` 内记录 owner，`release()` 前校验持有者。
> 2. 或改用带 owner 语义的原语（`RLock` + 同线程释放），让误释放直接抛错而非静默破坏互斥。

### 3.2 【中·功能】上一轮 S1 的“字符预算静默失效”本轮未修

**位置**：`agent.py:282-295`（本轮**零改动**，`git diff` 可见该段无增删）

实测（`SHORT_TERM_MAX_CHARS=36000`、`SHORT_TERM_WINDOW=24`）：

| 形态 | 条数 | 字符 | 归档 | 是否生效 |
| --- | --- | --- | --- | --- |
| `[user, 超长assistant(40000字)]` | 2 → 2 | 40002 → 40002 | **0** | ❌ 未生效 |
| `[user + 5次工具往返 + 长final]` | 12 → 12 | 70002 → 70002 | **0** | ❌ 未生效 |
| `[user,长a,user,长b]` | 4 → 2 | 40006 → 20003 | 2 | ✅ 生效 |

根因同上一轮：字符循环把 `overflow` 推到 `index+1` 后，`:292` 的 `while` 找下一个 `user` 边界，
若溢出点之后**没有** `user`（形态1/3 正是每轮追加的真实形状），`overflow >= len(messages)` →
`:294-295` 直接 `return`，**静默放弃归档**。`SHORT_TERM_MAX_CHARS` 在这两种常见形态下形同虚设。

**注意**：本轮新增的裁剪只解决“归档不无限膨胀”，**不解决“该归档却没归档”**。两者是并列缺陷，
S1 只修了一半。**该缺陷不阻塞提交**（不破坏互斥、不丢数据、不产生错误码），但应在后续轮次补齐。

### 3.3 【轻·可读性】归档占位说明的丢弃计数会被向下重写，不累积

`agent.py:309-310`：每次裁剪都把首条替换成**本次**丢弃数。实测连续裁剪：
第一次首条“更早的 77 条已丢弃”，第二次变为“更早的 6 条已丢弃”——**历史丢弃总量被抹掉**，
用户看到的“已丢弃 N”永远是最近一批，而非累计。不丢数据正确性，仅陈述失真。
建议改为累加（或单列 `archive_dropped_total` 字段）。**不阻塞。**

---

## 4. 未修复的遗留 / 未引入回归的核对

- **B2 已彻底修复**，`git status` 中不再有 vitest 临时产物；本轮跑门禁产生的 4 个 `.mjs` 均被忽略。
- **S1 裁剪部分、S2、S3、S4 已修复且测试有效**；无回归。
- **B1 淘汰竞态已修复**，但同一次改动**新引入** §3.1 的超时释放缺陷——属**新问题**，非遗留。
- 上一轮报告的其它复核项（H1 / M2 / M4 / `reports.py` 调度 / `overfit.py` 口径 / 报告路径安全 /
  `data_gap_profile` 旧格式安全）本轮未发现新的反例，维持其“成立”裁定。
- **架构不变量核对**：只读数据仓未破坏（`update_stock_data` 仍是唯一写路径）、
  稳定错误码未新增裸错误（`AiSessionBusy` → `ai_session_busy` 已有前端翻译）、
  `data/*` 未反向 import `ai`、token 纪律未涉及。**本轮改动未破坏任何架构不变量**——
  但 §3.1 破坏了 §16.2 的**会话互斥运行时不变量**。

---

## 5. 工作区卫生

- 我创建的全部临时探针（13 个 `_probe_*.py`）与回滚备份（`*.r2bak`）**已全部删除**；
  `git status` 与复核开始时**逐行一致**，无新增 untracked 探针、无残留备份。
- `git diff --check` 退出码 0。
- 仍存在的 untracked 文档：`docs/agent-skills-research.md`、`docs/data-gap-rootcause-2026-09-14.md`、
  `docs/review-2026-09-14-uncommitted.md`、`docs/verification-2026-09-14-independent.md`
  （+ 本报告）。前两份含真实运行数据（PID/CPU/路径），是否随 `git add -A` 进公开仓库建议确认。
  这与上一轮 §3.6 一致，**非本轮新增**。

---

## 6. 最终结论

**不建议立即提交。**

- 五道门禁全绿（pytest 747、vitest 256、ruff/eslint/tsc 干净），B2/S2/S3/S4 修复正确且回归测试经回滚
  验证**确实有效**，S1 的裁剪部分也正确（无 off-by-one、不误伤正常归档）。
- **但 B1 的修复不彻底且引入了新缺陷**：`acquire` 超时分支会让非持有线程静默解开他人锁，
  实测可复现“同一会话两把锁并发写”——这直接命中本轮改动声称要根除的目标，并破坏
  `AGENT必读.md §16.2` 的会话互斥不变量，且无任何测试覆盖。**必须修复后才能提交。**
- 附带应在同一批或紧随其后处理：§3.2 字符预算仍静默失效（上轮 S1 的另一半）、
  §3.3 占位计数不累积。

**一句话**：B2/S2/S3/S4 与 S1 的裁剪部分可以放行，但 B1 的修复把一个“高并发才触发”的竞态
换成了“一次超时即触发”的竞态——修掉 §3.1 之前不能提交。

---

## 附：复核方法与可复现性

所有结论均由本地可执行探针产出（运行后即删）：
- **锁语义**：直接构造 `_SessionLockEntry`，验证非持有线程 `release()` 静默成功、
  抢占第三方线程；再用真实 `AiService.chat_stream` 端到端复现 A/B/C 三线程超时链路。
- **refs 守恒**：覆盖正常完成/客户端断开（`generator.close()`）/worker 异常/thread.start 失败/超时五条路径。
- **回滚验证**：就地改源码（`refs>0 → lock.locked()`、删裁剪、`symbols` 去补集），跑对应新测试后
  `git diff --stat` 确认恢复一致。
- **S2 同构**：精确复刻两 block 表达式，构造补集/边界缺失/键集分叉等边界逐一比对。
- **裁剪**：穷举输入规模验证上限与丢弃计数；构造“裁剪后再压缩”验证阈值配合。
- **门禁**：全部用项目自带解释器/Node，命令见 §0。
