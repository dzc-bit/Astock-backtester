# 架构优化独立复核与最终收口报告

**分支**：`codex/realtime-crawler-api-stability`
**日期**：2026-07-11
**版本**：1.3.4
**复核范围**：第四轮 realtime 超时边界、策略持久化、测试证据、报告可信度及最终门禁

## 1. 结论

第四轮完成了 deadline 双检、超时 worker 私有结果、generation 仲裁、缓存 TOCTOU 防护、diagnostics 去重、文件锁与原子临时文件写入等有效工作，但其“Realtime 5/5、策略跨实例 5/5 全部关闭”的结论不成立。

独立复核发现 5 组实质问题，其中 4 组直接对应已经明确给出的遗留反例：

1. single-flight 锁随 wrapper 超时返回而释放，worker 未结束时后续任务仍会排队；
2. Rust 原子 upsert/delete 在持锁后调用再次持锁的写入函数，真实命令会自锁阻塞；
3. 前端仍调用整数组 `persist_saved_strategies`，新增原子命令未进入用户路径；
4. malformed localStorage 仍被 authoritative loader 静默吞掉，慢 reload 与 mutation 交错仍可永久停在 `loading`；
5. Rust/TypeScript 仅校验嵌套字段是数组，未校验 condition/group 的必需字段。

上述问题已在本次复核中按 RED→GREEN 修复。最终工作树在提交前通过全部可用门禁。

## 2. 第四轮有效成果

- breadth、sector、local snapshot 使用 monotonic deadline 与完成后二次检查；
- worker diagnostics/rows 私有化，只在预算内成功后发布；
- sector member cache 在锁内二次检查 cancel，关闭 TOCTOU；
- generation-tracked 快照不再被 legacy timestamp 写入覆盖；
- retained diagnostics 对 current/original/hint 全量稳定去重；
- 引入 `fs2` 跨进程文件锁和进程内 Mutex；
- 临时文件使用唯一名称、`write_all`、`sync_all` 和 rename；
- 提取 realtime parser 与 API mock，降低主模块体积；
- 第四轮声称的 8 个 Python RED→GREEN 测试可复跑为 GREEN。

## 3. 独立复核修复

### 3.1 真正的 single-flight 生命周期

锁的释放从 wrapper `finally` 移到 future done callback。超时 wrapper 返回后，只要实际 worker 尚未结束，后续请求就会收到“繁忙”并立即返回，不会排队到 executor。

新增回归测试：`test_single_flight_remains_busy_after_wrapper_timeout_until_worker_finishes`。

### 3.2 可调用的原子 mutation 核心

Rust 写入拆为：

- `write_saved_strategies_unlocked`：仅负责校验、临时文件写入和替换；
- `write_saved_strategies_to`：获取一次跨进程锁和 Mutex 后调用 unlocked 核心；
- `upsert_saved_strategy_in` / `delete_saved_strategy_in`：在同一锁域内 read-modify-write，不再嵌套持锁。

新增并发测试直接调用生产核心，而不是复制一份算法：两个并发 upsert 后两个 id 都必须存在。

### 3.3 前端接入单条原子命令

桌面运行时保存和删除分别调用 `upsert_saved_strategy`、`delete_saved_strategy`，并以 Rust 返回的最新数组作为权威状态。浏览器模式仍使用 localStorage，但 authoritative load 改为严格解析；损坏数据会进入 `failed` 并阻止 mutation。

mutation 成功会显式恢复 `ready` 并使慢 reload 失效，避免状态永久停在 `loading`。

### 3.4 完整嵌套校验

前端和 Rust 现在都校验：

- condition：`id`、`condition_id`、`enabled`、`params`、`data_lag_days`；
- group：`id`、合法 `operator`、`conditions` 数组；
- `market_filters`、`entry_groups.conditions`、`exit_rules` 的每个元素。

## 4. TDD 证据

本次新增测试在修复前的实际失败：

- 前端 3 个核心反例：atomic invoke 未发生、corrupt localStorage 得到 `ready`、mutation 后仍为 `loading`；
- 前端嵌套 schema：残缺 condition 被接受；
- Python：wrapper 超时后第二次调用未报告繁忙；
- Rust：原子核心不存在；补入核心后直接覆盖真实并发 read-modify-write；
- Rust 嵌套 schema：`validate_strategy_array` 对残缺 condition 返回 `Ok(())`。

修复后：`savedStrategyStore.test.ts` 20/20、`test_realtime_transport.py` 26/26、Rust 全量 52/52。

## 5. 最终门禁

所有命令均在 `D:\New project 6` 顺序执行。

| 门禁 | 最终结果 |
|---|---:|
| Python 全量 | **537 passed**, 0 failed，98.16s |
| 前端全量 | **22 files, 211 passed**, 0 failed |
| TypeScript | **0 errors**，direct bundled Node + `tsc --noEmit` |
| Vite build | **exit 0**，2407 modules，7.03s |
| Rust `--lib` | **52 passed**, 0 failed |
| `build:data-service` | **exit 0**，生成 `astock-data-service.exe` |
| Ruff HEAD/当前 | **141 → 139**，新增 Python 文件 0，**0 个新增违规** |
| `git diff --check` | **clean** |

说明：Ruff 并非全局 clean；139 个现存项主要是历史 E501/UP 规则债务。本机 Rust 工具链没有 `rustfmt` 组件，`cargo fmt --check` 无法运行，因此不把它列为通过项。

## 6. 第四 agent 校正评分

**总分：63/100**。

| 维度 | 得分 | 评价 |
|---|---:|---|
| 功能正确性 | 17/30 | realtime 多项修复有效，但 single-flight 生命周期仍错；策略原子命令既未接入又会自锁 |
| TDD 与测试质量 | 12/20 | 有真实 RED 记录，但 Rust upsert/delete 测试复制算法而未调用生产实现，漏掉关键死锁 |
| 工程设计 | 10/15 | deadline、delta publication、file lock 方向合理；锁边界和前后端契约未闭环 |
| 验证门禁 | 10/10 | 原报告主要门禁可复现通过 |
| 报告准确性 | 4/10 | 多个核心关闭结论过度，Ruff 基线计数不准，未披露原子命令未被前端使用 |
| 范围与工作树保护 | 8/10 | 未破坏用户文件，改动总体在范围内；报告把 `.workbuddy` 记为“无无关文件”不准确 |
| 难度、先后顺序与提示词校正 | 2/5 | 第四轮拿到最清晰的反例和前轮实现基础，应降低探索奖励并加重显式漏项扣分 |

该评分只评价第四 agent 提交复核前的成果，不把本次独立复核新增的修复和测试计入其分数。按此前校正分数（第一 74、第二 70、第三 67），第四轮绝对代码量更大，但综合完成可信度排在第四。

## 7. 提交边界

计划提交 17 个 modified 文件和 8 个属于项目的新增源码/测试/文档文件。明确排除：

- `.workbuddy/memory/2026-07-11.md`
- `.workbuddy/memory/MEMORY.md`
- `.tmp`、`.pyinstaller`、`dist`、`src-tauri/bin`、`src-tauri/target`
- `运行产物`、密钥、安装包、签名、日志和本地人工材料

## 8. 后续低优先级事项

- 11 处 `except TypeError` 测试兼容路径可在统一 stub 签名后单独清理；
- realtime 中仍有若干直接 requester 路径，需按各 provider 的 header/encoding/timeout 逐个迁移；
- 139 个 Ruff 历史项应使用独立格式化提交处理；
- `service.py` 路由表和剩余 crawler 拆分应先补 characterization tests，再进行结构调整。
