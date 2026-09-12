# AGENTS.md

A股策略回测工作台（Tauri + React 前端 + Python sidecar 数据服务）。接手前**必须先完整阅读 `AGENT必读.md`**——路径边界、架构不变量、红线、验证命令全在那里，本文件只是导引。

## 门禁命令（提交前全绿，按顺序跑）

```powershell
python -m ruff check backend tests scripts
python -m pytest tests -q
.\.tools\node-v20.18.1-win-x64\npm.cmd run lint
.\.tools\node-v20.18.1-win-x64\npm.cmd run typecheck
.\.tools\node-v20.18.1-win-x64\npm.cmd run test:ui -- --run
cargo test --manifest-path src-tauri\Cargo.toml   # 需设 CARGO_HOME/RUSTUP_HOME，见 AGENT必读 §13
```

或用斜杠命令 `/gates` 依次跑完并汇总。

## AI 子系统边界（违反即回退）

`backend/astock_backtester/ai/` 独立子包：对数据仓默认只读（唯一写路径 `update_stock_data`）；错误必须带稳定 code（`ai_not_configured`/`ai_upstream_error`）；测试零网络零 key（FakeModel/client_factory 注入）；爬取内容进模型上下文前必须过 `ai/context.py::wrap_untrusted`。完整不变量见 `AGENT必读.md` §15。

## 常见坑

- **cmd 壳没有 grep/head/ls/tail**：用 PowerShell（`Select-String`）或 Python 单行脚本；PowerShell 多行 here-string 在部分调用链里会解析失败，多行内容优先写成临时 `.py` 跑完即删。
- **路径含空格和中文**（`D:\New project 6\运行产物\…`）：永远用参数数组/引号，不要拼未转义字符串。
- **本机可能开着 Clash 等系统代理**：回环测试必须走 `ProxyHandler({})` 的 opener（见 `tests/test_ai_service_http.py` 顶部）。
- 仓库工作目录是 `D:\New project 6`（`C:\Users\…\Documents\New project 6` 是 Junction，不要在那边操作）。
- 分域测试子集命令见 `AGENT必读.md` §13 与 `.zcode/skills/astock-dev/SKILL.md`。

## 关于 pre-commit hook 的取舍（任务书要求的评估结论）

不加 `.zcode/hooks` 提交前自动跑 ruff + eslint：本仓的门禁是"提交前人工跑 `/gates` 全量六项"，hook 只能覆盖 ruff/eslint 两项、却会拖慢每次小提交并在分语义化多次提交时重复执行；且 hook 依赖本地工具链路径（`.tools`），换机/CI 不可移植。真正的兜底是 `.github/workflows/ci.yml`（push/PR 三 job）。若未来要加，建议只挂 ruff（秒级）且提供 `--no-verify` 逃生口。
