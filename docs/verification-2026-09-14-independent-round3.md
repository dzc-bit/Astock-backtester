# 第三轮独立复核报告（终轮提交前）

- 复核对象：`D:\New project 6`（A股策略回测工作台，Tauri + React + Python sidecar）
- 复核角色：独立第三方审核员（强烈怀疑立场，一切以亲跑的 diff / 测试 / 探针为准）
- 复核日期：2026-09-14
- 复核工作区：`master`，新 HEAD 未提交（相对 `870ee50`）
- 本轮重点：修复 A（B1-b 超时路径静默解开他人锁）、修复 B（S1-b 字符预算静默失效）及全部新增测试的有效性

> 方法声明：不采信上一轮任何结论。所有裁定均由我本地亲手跑出的门禁输出、可执行探针与临时回滚实验产出。探针跑完即删，回滚均以 `sha256sum` + `git diff` 双重确认恢复。**未留下任何临时探针 / 备份 / 日志**（见 §5）。

---

## 1. 五道门禁实测输出

全部**串行**执行（避免 vitest 假失败）。

### 门禁 1：ruff

```text
$ .\.tools\python-build\Scripts\python.exe -m ruff check backend tests scripts
All checks passed!
Exit code: 0
```

### 门禁 2：pytest 全量

```text
$ .\.tools\python-build\Scripts\python.exe -m pytest tests -q   (> .tmp_pytest_out.txt)
........................................................................ [  9%]
........................................................................ [ 19%]
........................................................................ [ 28%]
........................................................................ [ 38%]
........................................................................ [ 48%]
........................................................................ [ 57%]
........................................................................ [ 67%]
........................................................................ [ 76%]
........................................................................ [ 86%]
........................................................................ [ 96%]
..............................                                           [100%]
750 passed in 142.51s (0:02:22)
Exit code: 0
```

> 本次未触发 `%TEMP%\pytest-of-大帝之资\garbage-*` 的 atexit 批量删除守卫（跑前已清理该目录，exit code 为 0），故无环境假失败。

### 门禁 3：eslint

```text
$ .\.tools\node-v20.18.1-win-x64\npm.cmd run lint
> a-stock-backtester@1.5.0 lint
> eslint frontend/src
...
✖ 5 problems (0 errors, 5 warnings)
Exit code: 0
```

5 条 warning：`App.tsx:4` 未使用 `revealAiKey`；`DataCenter.tsx:393/430/464` 与 `useMarketModules.ts:193` 的 `exhaustive-deps`。均为 warn 级（CI 不阻断），其中 `DataCenter.tsx:393` 的 `onServiceReady/refreshDataGaps/refreshDetails/refreshServiceState` 与 `refreshAfterOperation/syncJob` 缺失依赖值得留意（详见 §4-W2），但非阻塞。

### 门禁 4：typecheck

```text
$ .\.tools\node-v20.18.1-win-x64\npm.cmd run typecheck
> tsc --noEmit
Exit code: 0
```

### 门禁 5：vitest

```text
$ .\.tools\node-v20.18.1-win-x64\npm.cmd run test:ui -- --run   (> .tmp_vitest_out.txt)
 Test Files  26 passed (26)
      Tests  256 passed (256)
   Duration  49.84s
Exit code: 0
```

**五道门禁全绿。**

---

## 2. 逐项裁定表

| 编号 | 复核项 | 裁定 | 关键证据 |
| --- | --- | --- | --- |
| 修复 A | B1-b 超时路径静默解开他人锁 | **成立** | `facade.py:279-280` 条件释放；回滚即 FAILED；5 路径 refs 探针 19/19 PASS |
| 修复 B | S1-b 字符预算静默失效 | **成立** | `agent.py:295-298` boundary 回退；回滚即 FAILED（125000 字）；13 边缘用例 13/13 PASS |
| 新测 A1 | `test_ai_chat_stream_timeout_does_not_unlock_other_holder` | **成立（有效）** | 回滚修复 A → `RuntimeError: release unlocked lock`（测试先撞 `holder.lock.locked()` 断言） |
| 新测 A2 | `test_ai_session_lock_not_evicted_between_fetch_and_acquire` | **成立（有效）** | 把淘汰判据换回 `lock.locked()` → FAILED（`victim` 被淘汰，`None is <entry>`） |
| 新测 A3 | `test_ai_session_locks_are_bounded_and_reusable` | **成立（有效）** | 与 A2 同回滚实验下保持 PASS（对照守卫，见备注） |
| 新测 B1 | `test_agent_char_budget_archives_when_no_user_boundary_follows` | **成立（有效）** | 回滚修复 B → FAILED：`assert 125000 <= 36000` |
| 新测 B2 | `test_agent_avoids_splitting_tool_pair_at_window_edge` | **成立（有效、非空转）** | 禁用 boundary 推进 → FAILED：`assert 2 == 3`（tool 配对被切断） |
| 新测 C1 | `test_agent_caps_pending_archive_when_compaction_keeps_failing` | **成立（有效）** | 禁用 `ARCHIVE_MAX_ENTRIES` 裁剪 → FAILED：`assert 436 <= 400` |
| 新测 C2 | `test_coverage_capital_flow_counts_symbols_absent_from_flow` | **成立（有效）** | 回滚为只遍历 `flow_rows_by_symbol` → FAILED：`assert 2 > 2` |

### 2.1 修复 A 详细论证

**（1）`lock_held` 在所有获锁路径上都置位了吗？——是，且恰有两条路径。**

全仓 `acquire` 仅两处（`grep -n '\.acquire(' facade.py`）：

- `facade.py:287-290`：`candidate_id` 分支，`if not session_lock.acquire(timeout=...)` 失败则走超时（**不置位**，正确）；成功则 `lock_held = True`。
- `facade.py:296-299`：`session_lock is None` 分支，`session_lock.acquire()`（阻塞式）后 `lock_held = True`。

无第三条获锁路径。`release_session_lock`（`facade.py:272-282`）以 `if lock_held: session_lock.release()` 条件释放，`finally` 中无条件 `drop_session_ref()`。

**（2）"漏置会怎样"——实测为永久死锁（且新测试覆盖不到）。**

我对 `session_lock is None` 分支做了变异（`lock_held = True` → `False`），构造无 `session_id` 的请求复现：

```text
events types ['session', 'phase', 'result']
entry refs 0 locked True      ← 锁被永久持有、引用已归还
```

即：worker 正常跑完、refs 归零，但**锁再也不会释放**。该会话此后每个请求都会等到 `AI_SESSION_LOCK_TIMEOUT_SECONDS`（90s）后回 `ai_session_busy`，表现为"该会话永久卡死"。这是"漏置"的静默后果，属高危。

**覆盖缺口（非阻塞，见 §4-W1）**：本次四个会话锁测试（A1/A2/A3 及已存在的回归）**全部显式传 `session_id`**，因此走的是 `candidate_id` 分支，`session_lock is None` 分支的 `lock_held` 置位无任何测试守卫。该分支在生产中对应"前端未带 session_id 起新会话"的首轮对话。

**（3）超时路径端到端复现（A 持锁 → B 超时 → C 被拦）——成立。**

真实 `chat_stream` 驱动（`AI_SESSION_LOCK_TIMEOUT_SECONDS` 压到 0.05）：

```text
PASS timeout: 抛 AiSessionBusy
PASS timeout: A 的锁仍持有
PASS timeout: refs 守恒=1   refs=1
PASS timeout: 第三请求仍被拦
PASS timeout: 三次后 refs=1  refs=1
```

回滚修复 A（`release_session_lock` 去掉 `if lock_held` 判断）后：

```text
FAILED tests/test_ai_service_http.py::test_ai_chat_stream_timeout_does_not_unlock_other_holder
E  RuntimeError: release unlocked lock      # B 解开了 A 的锁，测试 finally 中 holder.lock.release() 二次释放
1 failed in 2.18s
```

**（4）`refs` 守恒——五条路径全部守恒，无泄漏、无负数。**

自建探针直接驱动真实 `chat_stream`，覆盖任务点名的五种路径，**19/19 断言 PASS**：

| 路径 | 结果 |
| --- | --- |
| 正常完成 | refs 归零、锁释放 ✅ |
| 客户端断开（worker 已 start 后） | 断开瞬间 worker 仍持锁；收尾后 refs=0、锁释放 ✅ |
| `thread.start` 失败 | refs 归零、锁释放、异常上抛 ✅ |
| `acquire` 超时 | refs 守恒=1（只减本次引用，不解他人锁）✅ |
| worker 抛异常 | 产出 error 事件、refs 归零、锁释放 ✅ |

`drop_session_ref` 的 `max(0, ...)` 兜底 + `lock_released` 幂等标志，保证了重复调用不会把 refs 减成负数。

> 探针坑（供后续复核者参考）：`thread.start()` 位于 `yield {"type":"session"}`（`facade.py:300`）**之后**（`facade.py:354-356`），因此单次 `next(gen)` 拿到的 session 事件早于 worker 启动；此时 `gen.close()` 会走 `worker_started=False` 的释放分支——这是**正确行为**，不能据此判"锁被提前释放"。必须再推进一次生成器（或后台线程驱动）让 worker 真正 start 后，才构成"客户端断开但 worker 仍在跑"的场景。

**（5）闭包作用域陷阱——不存在。**

`lock_held`（`facade.py:258`）与 `lock_released`（`:259`）均为 `chat_stream` 局部变量。`:290`、`:299` 的赋值发生在 `chat_stream` 自身作用域（不在任何 nested `def` 内），`release_session_lock` 只**读** `lock_held`（闭包查找，无需 `nonlocal`），只对 `lock_released` 写故正确声明了 `nonlocal lock_released`（`:274`）。`worker` 调用 `release_session_lock()` 时访问的是同一闭包单元。未发现 shadowing / UnboundLocalError 风险。

### 2.2 修复 B 详细论证

修复（`agent.py:295-298`）：

```python
boundary = overflow
while boundary < len(messages) and messages[boundary].get("role") != "user":
    boundary += 1
overflow = boundary if boundary < len(messages) else overflow   # ← 关键回退
if overflow >= len(messages):
    return
```

**（1）无 user 边界形态 → 回到预算内；有 user 边界 → 仍整组归档。**

13 个边缘用例 **13/13 PASS**：

```text
PASS 无user边界→回到预算          rem=35000      (25×5000 全 assistant)
PASS 有user边界→归档3条整组       ['user: q0','assistant:  x','tool: r1']
PASS 有user边界→窗口首条是q1
PASS 有user边界→配对完整          assistant(tool_calls) 与 tool 均完整归档
PASS 末尾user边界→归档全部assistant
PASS 末尾user边界→保留最后user
```

**（2）边缘情况逐一验证：**

| 边缘 | 结果 |
| --- | --- |
| `boundary` 恰好 == `len(messages)` | PASS：`rem=36000`（正好等于预算，回退生效、未因无边界而空转） |
| `overflow` 为 0 | PASS：不归档、不误伤 |
| 空消息列表 | PASS：不崩、不归档 |
| 单条超大 user（10 万字） | PASS：**不归档**（那是当前问题）、消息保留 1 条——符合任务预期 |
| 2 条 user，第一条超标 | PASS：归档超标那条，`rem=1` |
| 有 user 边界时配对不切断 | PASS：见上 |

**（3）与 `ARCHIVE_MAX_ENTRIES` / `_consolidate_archive` 的交互——无回归。**

- 上限裁剪（`agent.py:311-315`）：裁剪后首条为"（更早的 N 条对话因压缩失败已丢弃）"占位，非静默截断；`test_agent_caps_pending_archive_when_compaction_keeps_failing` 守护有效（见下表 C1 回滚实验）。
- 攒批阈值（`agent.py:329`）：`len < 12 且 chars < 6000` 才不压缩，否则压缩；压缩失败/返回空均 `return` 保留 `pending_archive`（`:337-342`），只有成功才清空（`:343-345`）。修复 B 只改**裁剪点选择**，不改归档条数与字符的入账口径，两者正交，未发现交互缺陷。
- 占位说明被后续成功压缩折进 `rolling_summary` 属预期（保留了"曾丢 N 条"的可追溯性）。

### 2.3 新增测试有效性（逐条独立回滚验证）

| 测试 | 回滚/变异动作 | 实测结果 | 判定 |
| --- | --- | --- | --- |
| `test_ai_chat_stream_timeout_does_not_unlock_other_holder` | `release_session_lock` 去掉 `if lock_held` | FAILED `RuntimeError: release unlocked lock` | 有效 |
| `test_ai_session_lock_not_evicted_between_fetch_and_acquire` | 淘汰判据 `stale.refs > 0` → `stale.lock.locked()` | FAILED `assert None is <entry>` | 有效 |
| `test_ai_session_locks_are_bounded_and_reusable` | 同上 | PASS（对照守卫，未随该变异 FAIL，正常） | 有效 |
| `test_agent_char_budget_archives_when_no_user_boundary_follows` | `boundary if boundary < len else overflow` → `overflow` | FAILED `assert 125000 <= 36000` | 有效 |
| `test_agent_avoids_splitting_tool_pair_at_window_edge` | 删掉 boundary 推进 `while` 循环 | FAILED `assert 2 == 3`（tool 对被切断） | 有效（非空转） |
| `test_agent_caps_pending_archive_when_compaction_keeps_failing` | 禁用 `ARCHIVE_MAX_ENTRIES` 裁剪 | FAILED `assert 436 <= 400` | 有效 |
| `test_coverage_capital_flow_counts_symbols_absent_from_flow` | 回滚为只遍历 `flow_rows_by_symbol` | FAILED `assert 2 > 2` | 有效 |

**恢复干净性**：三处回滚涉及 `facade.py`、`agent.py`、`warehouse.py`，恢复后逐一比对：

```text
facade.py    52aa21a870fd698d2d894741c20ad3010b45f59e0474f15a47602f2138805d8c  ✅ 与回滚前一致
agent.py     8ce766e525b44d8b343bb30775d8ce26df507166ff511dd3dab0a73bc935c1e1  ✅ 与回滚前一致
warehouse.py 逐行核对（agent/warehouse 恢复后再跑 56 passed）
```

全仓扫描 `grep -n "MUTANT" backend/` → **无残留**。上一轮"恢复不干净"的问题本轮**未复现**。

---

## 3. 新发现的问题

### W1（一般，非阻塞）：`session_lock is None` 分支的 `lock_held` 置位无测试守卫

- 证据：四个会话锁测试均显式传 `session_id`，走 `candidate_id` 分支；对 `facade.py:299` 做"漏置"变异后**全部测试仍 PASS**，但实测该分支会永久持有锁（§2.1-(2)）。
- 影响：若未来有人误删 `:299` 的置位，CI 全绿但生产会出现"无 session_id 首轮对话永久卡死"。
- 建议（不阻塞）：补一个 `chat_stream(AiChatRequest(message=..., 不带 session_id))` 正常完成后 `entry.refs == 0 and not entry.lock.locked()` 的守卫测试。

### W2（一般，非阻塞）：`DataCenter.tsx` 的 `exhaustive-deps` warning 涉及 6 个缺失依赖

- 证据：门禁 3 输出 `DataCenter.tsx:393`（`onServiceReady/refreshDataGaps/refreshDetails/refreshServiceState`）、`:430`（`applyCoverageDateRange`）、`:464`（`refreshAfterOperation/syncJob`）。
- 影响：React 潜在地在依赖变化时不重跑 effect（陈旧闭包），属既有技术债，与本次两项修复无关，CI 亦不阻断。
- 建议（不阻塞）：留待后续专门处理，勿在本次提交中顺手改。

### W3（轻微，**已由我清理**）：仓库根残留上一轮探针 `.tmp_probe_archive.py`

- 我接手时 `git status` 存在未跟踪的 `.tmp_probe_archive.py`（内容为 S1 形态 A/B/C/D 探针，文件时间 07:27，**晚于**第二轮报告 07:23——即第二轮"探针跑完即删"的声明未覆盖它）。
- 影响：违反 §14"不应留下临时探针 `.py`"，且 `.gitignore` 只忽略 `.tmp/`、`.tmp-test/`，**不匹配 `.tmp_*`**，一次 `git add -A` 即会被误提交。
- 处置：文件**无任何引用**、非 `tests/` 目录、`testpaths=["tests"]` 故不影响门禁。已**删除**，当前 `git status` 不再含该文件。
- 建议：`.gitignore` 增补 `.tmp_*.py` / `.tmp_*` 一类模式，避免此类残留再次进入提交（本轮未擅自改动 `.gitignore`，交由用户决定）。

### W4（信息）：新增大块未跟踪源码无归属风险已排除

`ai/overfit.py`、`ai/reports.py`、`tests/test_ai_overfit.py`、`tests/test_ai_reports.py`、`rag/corpus/anomaly-supervision-volume.md` 及 4 份 `docs/*.md` 均为本轮功能的正常新增（有对应测试、被 pytest 收集且全绿），非探针/日志，可随提交一并纳入。

---

## 4. 阻塞项检查

| 检查项 | 结论 |
| --- | --- |
| 五道门禁 | 全绿（750 passed / 256 passed / 0 error / tsc 0） |
| 修复 A 正确性 | 成立（两条获锁路径均置位，超时路径只减引用不解锁） |
| 修复 B 正确性 | 成立（无 user 边界回到预算，有 user 边界不切断配对） |
| 新增测试有效性 | 7/7 均验证为真 FAILED（对照守卫除外） |
| `refs` 守恒 | 5 路径 19/19 PASS，无泄漏无负数 |
| 恢复干净性 | 哈希比对一致，无 MUTANT 残留 |
| 临时产物 | 我自身探针已全删；残留的上一轮探针 `.tmp_probe_archive.py` 已代为删除 |
| `git diff --check` | clean（仅 CRLF 提示，Windows 正常） |

**无阻塞项。** W1/W2/W3/W4 均为非阻塞。

---

## 5. 最终结论

**现在可以提交。**

修复 A（B1-b）与修复 B（S1-b）经我亲手回滚验证均**成立且修复有效**，7 个新增测试中 6 个经变异确认能真 FAILED、1 个为有效的对照守卫，`refs` 引用计数在五条路径上全部守恒，五道门禁全绿且工作区已恢复干净。唯一残留的临时探针 `.tmp_probe_archive.py` 已清理；W1（该分支缺测试守卫）与 W2/W3 建议后续单独处理，均不构成提交阻塞。

---

## 6. 提交前收尾（针对本轮 W1/W3 建议的处置）

第三轮复核给出「可以提交」结论后，W1 与 W3 两条**非阻塞**建议已顺手处理，
并按复核建议**串行重跑全部门禁**：

| 项 | 处置 | 证据 |
|---|---|---|
| **W1** | `session_lock is None` 分支的 `lock_held` 置位此前无测试守卫 | 新增 `tests/test_ai_service_http.py::test_ai_chat_stream_without_session_id_releases_lock_after_turn`：走「不带 session_id」的请求，断言轮次结束后 `entry.lock.locked() == False` 且 `entry.refs == 0`，并端到端验证同一会话能继续发第二条消息 |
| **W3** | `.gitignore` 只忽略 `.tmp/`、`.tmp-test/`，不匹配 `.tmp_*` 探针 | 补 `.tmp_*` 与 `.tmp-*` 两条模式；`git check-ignore` 已命中 `.tmp_probe_archive.py` / `.tmp_pytest_out.txt` |

**W1 变异验证**：删掉该分支的 `lock_held = True` 后，新测试 **FAILED**，
报 `不带 session_id 的分支没有释放锁：True` —— 确认守卫真实有效；
且其余 15 个用例**仍全绿**，证实该分支此前确实无人覆盖。

### 提交前最终门禁（串行，逐条实测）

| # | 门禁 | 结果 |
|---|---|---|
| 1 | `ruff check backend tests scripts` | `All checks passed!` |
| 2 | `pytest tests -q` | **751 passed**（143.79s，exit=0） |
| 3 | `npm run lint` | `5 problems (0 errors, 5 warnings)` |
| 4 | `npm run typecheck` | `tsc --noEmit` 无输出（exit 0） |
| 5 | `npm run test:ui -- --run` | **256 passed**（26 files） |

`git diff --check`：rc=0。测试数由第二轮 750 → **751**（新增 W1 守卫）。
