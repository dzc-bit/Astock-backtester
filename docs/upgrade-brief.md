# A股策略回测工作台 · 下一轮大更新执行提示词（v1.5.0）

> 本文件是一份完整的执行任务书，交给新的 agent 直接执行。执行前必须先读 `AGENT必读.md`（架构不变量、红线、验证命令全在里面），并跑一遍 `git status --short --untracked-files=all`、`git log --oneline -5` 确认工作区干净、当前版本 1.4.0。
>
> 总目标：把本项目从"功能完整的 AI 应用"升级为"有专业投研深度、UI 有设计品质、数据模型正确的成熟产品"。完成后版本号统一升到 **1.5.0**，全部门禁绿色，commit 并 push 到 `https://github.com/dzc-bit/Astock-backtester`。

---

## 任务一：用 Hallmark 技能做前端整体设计优化

**环境已就绪**：Hallmark 技能（Nutlope/hallmark，反 AI 味设计技能）已安装在 `C:\Users\大帝之资\.agents\skills\hallmark\`（SKILL.md + references/ 共 30 个文件）。执行前端任务前先读该 SKILL.md，按它的流程工作。

1. 先跑 `hallmark audit`（按 SKILL.md 的 audit verb）对以下页面打分并输出 punch list：
   - `frontend/src/App.tsx` 整页布局（顶栏/行情区/概览卡/工作台/数据中心）
   - `frontend/src/components/` 下全部面板组件
   - `frontend/src/styles.css`（59KB 单文件）与 `frontend/src/ai-panel.css`
2. 按 audit 结果 + redesign 流程执行重构，硬约束：
   - **信息架构、中文文案、组件 props 契约、242 个前端测试断言的可见行为不变**（允许因布局调整测试选择器，但语义不得变）
   - 保留既有的 A 股红涨绿跌语义（`--rise`/`--fall`）、aria 无障碍标注、盘面数据密度
   - 顺带把 styles.css 里硬编码的颜色/字号收敛为 CSS 变量 token 块（Hallmark 的 tokens 纪律），不引入 Tailwind/新框架
   - 视觉验证用浏览器打开 `npm run dev`（127.0.0.1:1420，预览模式走 mock 数据）逐页截图确认，重点检查 320/375/768 宽度
3. 产出物：更新后的组件与样式 + 一份简短的 `docs/design-notes.md`（记录采用的设计系统决策）。

## 任务二：策略条件编辑器 AI 化瘦身（模糊语义精准理解）

现状问题：`frontend/src/components/StrategyWorkbench.tsx` 的"写入条件"区有三段式表单（文本框→校验→添加→模板面板→已校验条件→写入），流程臃肿。后端 AI 已具备 NL→DSL 能力（`ai/tools/local_tools.py` 的 `validate_strategy_conditions`、模糊近似映射见 `ai/prompts.py`）。

改造方案：
1. 在"基础配置"页签顶部新增**主输入：一个自然语言条件框**。用户直接写"近5天放量上涨、主力净流入为正、破20日线卖"，点"AI 理解并写入"：
   - 走新增后端路由 `POST /ai/conditions/parse`（实现于 `ai/` 新增轻量函数，复用 llm_client + condition_parser）：LLM 输出候选 DSL → 逐条 validate → 校验失败自动按报错修正重试（≤2 次）→ 返回 `{entry: [...], exit: [...], approximations: ["『放量』→量比2日介于1.2到2.5", ...]}`。
   - 前端把解析结果以**可勾选的清单**展示（每条带"近似说明"角标），用户确认后一键全部写入策略；同时把未识别/被近似的部分明示。
2. 原三段式手工编辑器**收进"高级模式"折叠区**（默认收起），模板面板保留在折叠区内。
3. 离场规则同样处理。
4. 该路由需要 LLM 已配置；未配置时输入框置灰并提示，高级模式不受影响。
5. 后端新增函数必须有单测（FakeModel 脚本化、校验失败自愈分支），前端组件测试覆盖解析结果清单渲染与写入。

## 任务三：接入 AI 后的其他页面优化（全部必做）

1. **收益概览卡片 AI 一句话点评**：回测完成后，在 ResultsOverview 指标条下加一行 AI 短评（复用 `/ai/chat/stream` 的非对话形态或新增 `POST /ai/interpret` 轻路由，输入 metrics 摘要，返回 ≤80 字点评；失败静默不显示）。
2. **数据中心补数助手**：DataCenter 覆盖表旁加"AI 诊断缺失"按钮 → Agent 用 coverage 数据分析缺失模式（新上市/退市/资金流缺口）并给出补齐建议（调用哪些按钮）。
3. **风险卡片 AI 解读**：RiskAlertsModal 顶部加 AI 一句话解读（同类轻路由）。
4. 所有 AI 点评统一走一个可复用的后端轻路由 `POST /ai/insight/oneshot`（输入场景枚举+上下文，输出单段文字），避免到处开流式端点；带 token 上限与失败静默。

## 任务四：数据股票池动态化（新上市 / 退市感知）——数据模型修正

**问题实证**：`data/operations.py::build_daily_bars_coverage` 用 `expected_dates(全交易日历) - present_dates` 计算缺失，完全不知道每只股票的上市日与退市状态。后果：新上市股票上市前的所有交易日被记为"缺失"（实际是完整），已退市股票退市后的日期永远显示缺失（实际也是完整）——"很多时候没缺失是有缺失的，有缺失又是完整的"，覆盖表与全市场同步进度长期失真。

修复方案：
1. `Warehouse` 的 metadata.sqlite 新增 `symbol_lifecycle(symbol PRIMARY KEY, listing_date, delisted_date NULL, status)` 表；数据来源：adata 股票列表自带上市日期，a-stock-data 有上市/退市日端点，在全市场同步时顺带刷新该表（同步进 operations/sync 层，crawler 不直写）。
2. `coverage()`/`build_daily_bars_coverage`：`expected_dates` 截断到 `[listing_date, delisted_date or +∞]` 窗口内；无生命周期记录的股票按旧行为兜底（保守算缺失）。
3. `sync_symbols`/全市场同步股票池：已退市（delisted_date 非空）股票剔除；新上市股票从上市日起纳入。
4. `read_capital_flow_missing_symbols` 同样按生命周期窗口截断。
5. 前端覆盖表：有上市前缺口/退市后区间的股票不再标红缺失，显示"未上市(YYYY-MM-DD 起)"或"已退市"徽标；`missing_rows` 口径同步修正。
6. 测试：构造含"上市中段开始有数据"与"数据到某日戛然而止"两只股票的仓库夹具，断言修正后的 coverage 口径；旧口径行为回归由现有 900+ 测试守卫。

## 任务五：Harness 配置完善（让开发这个项目的 agent 更顺手）

在仓库内新增以下配置（全部提交）：
1. `AGENTS.md`（仓库根）：3-5 行导引——必读 `AGENT必读.md`、门禁命令清单、AI 子系统边界提示、常见坑（cmd 无 grep/head、路径含空格、Clash 代理）。
2. `.zcode/commands/gates.md`：斜杠命令，内容=按顺序跑 `python -m ruff check backend tests scripts`、`python -m pytest tests -q`、`npm run lint`、`npm run typecheck`、`npm run test:ui -- --run`、`cargo test --manifest-path src-tauri/Cargo.toml` 并汇总结果。
3. `.zcode/commands/probe.md`：本地服务探针命令（启动 sidecar、打 /ping /health /market/finance /ai/status /run/backtest/stream 并逐行解析 NDJSON，参考 AGENT必读 §11）。
4. `.zcode/skills/astock-dev/SKILL.md`：项目开发技能——何时跑哪个测试子集（照抄 AGENT必读 §13 的分域命令）、AI 模块注意事项、预览 mock 双轨说明。
5. 评估并（可选）加一个 `.zcode/hooks` 建议：提交前自动跑 ruff + eslint。不强求，写明取舍即可。

## 任务六：进一步大幅优化（按优先级，1-3 必做，4-5 选做）

1. **策略参数寻优 Agent**：新增 `POST /ai/optimize` 工作流——对当前策略的 2-4 个关键参数（窗口/阈值/止盈止损）做网格搜索（复用 run_configured_backtest，限制组合数 ≤48 并显示进度），输出各组合收益/回撤对比表 + AI 解读最优区间与过拟合警告；前端在策略配置页加入口与结果表格。
2. **回测报告导出**：回测完成后可导出单文件 HTML 报告（收益曲线 SVG、指标表、交易明细、AI 解读），纯前端生成（Blob 下载），无新后端依赖。
3. **数据源健康监控**：`/health` 已带 coverage，补充一个轻量 `/diagnostics/sources` 汇总最近一次各 provider 成功/失败与耗时（realtime/news/finance 已有 diagnostics，聚合展示于数据中心一个折叠卡片），帮助排查"大盘评分不可用"这类问题。
4. （选做）Playwright E2E 冒烟：启动预览模式跑"打开页面→运行回测→AI 解读→悬浮球打开抽屉"一条链。
5. （选做）pytest/vitest 覆盖率阈值（如 60%）入 CI。

## 任务七：文档大幅更新

- `AGENT必读.md`：新增 §16 AI 子系统完整手册（目录结构、事件协议、三种 api_style、记忆/简报/快讯引擎、工具清单、测试策略）；§4 模块表补 /ai/*；§15 不变量补第 9 条（symbol_lifecycle 口径）；版本号同步。
- `README.md`：1.5.0 发布章节（本任务书全部内容的产品化描述）、架构表、接口表、截图位（预览模式截图）、面向用户部分重写。
- 两份文档必须互相一致，且与代码实际行为一致（写完后自查一遍）。

## 验收与交付

1. 全门禁绿：`python -m ruff check backend tests scripts`、`python -m pytest tests -q`（预期 ≥700 通过）、`npm run lint`、`npm run typecheck`、`npm run test:ui -- --run`（预期 ≥250 通过）、`cargo test --manifest-path src-tauri/Cargo.toml`。
2. 版本号 1.5.0 同步 7 处（package.json、package-lock×2、pyproject、backend/__init__、Cargo.toml、Cargo.lock、tauri.conf.json），`tests/test_scripts.py` 的版本断言同步。
3. 预览模式人工过一遍全部页面（npm run dev + 浏览器），确认任务一/二/三/四的 UI 均可见且可用。
4. 分多个语义化 commit；最后一个 commit 后 `git push origin master`（remote 已配置为 https://github.com/dzc-bit/Astock-backtester.git）。
5. 红线：遵守 AGENT必读 全部不变量；不动 `.tools`/`运行产物`/签名流程；不引入 LangChain/FastAPI/Tailwind 等重框架；AI 模块保持对数据仓默认只读（唯一写路径 update_stock_data）；测试零网络零 key。
