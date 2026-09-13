# A 股策略回测工作台

Windows 桌面版 A 股策略回测工具。项目使用 React + TypeScript 构建界面，Tauri 提供桌面容器，Python 负责本地数据服务、行情聚合、数据补齐和回测执行，并内置一个基于 LLM 的 AI 投研助手（工具调用 + 本地知识检索 + 快讯推送）。

当前版本：`1.5.0`

## 1.5.0 当前发布内容

本轮以"有专业投研深度、UI 有设计品质、数据模型正确"为目标，包含七块内容（设计决策见 [`design.md`](design.md)）：

- **策略条件编辑器 AI 化瘦身**：策略配置页顶部新增"AI 条件理解"自然语言输入框——写"近5天放量上涨、主力净流入为正，破20日线卖"，点"AI 理解并写入"，后端 `POST /ai/conditions/parse` 用 LLM 生成候选条件 DSL、逐条本地校验、校验失败自动带报错重试（≤2 次），返回可勾选的条件清单（带"近似说明"角标与未识别提示），确认后一键写入策略。原三段式手工编辑器（校验→添加→模板面板）收进"高级模式"折叠区，默认收起，AI 未配置时输入框置灰但不影响高级模式。
- **AI 点评全覆盖**（统一走 `POST /ai/insight/oneshot` 轻路由，失败静默）：回测完成后收益概览指标条下自动出现 ≤80 字 AI 短评；数据中心新增"AI 诊断缺失"按钮（分析覆盖缺失模式并指路补齐按钮）；风险股票清单弹窗顶部新增 AI 一句话解读。
- **数据股票池动态化（新上市/退市感知）**：本地仓 metadata 新增 `symbol_lifecycle` 表（上市日/退市日/状态）。覆盖计算的期望交易日截断到每只股票的上市–退市窗口内——新上市股票上市前的交易日不再记为"缺失"，已退市股票退市后的日期也不再永远缺失；全市场同步股票池自动剔除已退市股票（数据源完整性不足时保守跳过，绝不误杀）；逐股覆盖明细带"未上市（YYYY-MM-DD 起）/ 已退市"徽标。上市日期来自 adata 股票列表与抓取行的 `listing_days` 字段，全市场同步时顺带刷新。
- **策略参数寻优 Agent**：`POST /ai/optimize` 对当前策略的数值参数（持仓天数/止盈止损/仓位/挂牌数等白名单键）做网格搜索，最多 48 个组合，NDJSON 流式返回逐组合收益/回撤/胜率对比表，结束后附 AI 解读（最优区间 + 过拟合警告）；前端策略配置页新增"AI 参数寻优"面板（参数行可增删、候选值可编辑、最优组合高亮）。
- **回测报告 HTML 导出**：回测完成后点"导出报告"即可下载单文件 HTML（权益曲线 SVG、指标卡、策略参数、交易明细、AI 解读），纯前端 Blob 生成，无新后端依赖。
- **数据源健康监控**：`GET /diagnostics/sources` 聚合实时行情/市场新闻/财联社看盘三个数据源最近一次成功状态与距今年代（含诊断文本），数据中心折叠卡片"数据源健康监控"展示，帮助排查"大盘评分不可用"一类问题。
- **前端设计系统（Hallmark 重构）**：`styles.css`/`ai-panel.css` 全部落到命名 token（`:root` 设计令牌块），token 之外 0 处硬编码色值、装饰渐变清零；左侧实色边条统一为顶部 accent 条；数字容器统一 `tabular-nums`（A 股红涨绿跌语义不变）；全局 `:focus-visible` 焦点环；320/375/768/1280 宽度实测无页面级横向滚动。信息架构、中文文案与 aria 标注不变。

## 1.4.0 发布内容（历史）

本轮新增 AI 投研助手模块（`backend/astock_backtester/ai/`，独立子包，对存量模块只读）：

- **评股 Agent**：`POST /ai/chat/stream` NDJSON 流式对话。Agent 通过 17 个工具（实时行情、新闻、复盘、风险清单、本地日线+均线、条件校验、受控回测、腾讯估值、东财研报、龙虎榜、涨停池、DuckDB 只读 SQL、统计函数、受控数据补齐、知识检索、多股对比、AI 聚合要点）完成个股诊断与行情问答；正文流式输出，工具调用过程可视化，所有数字要求标注来源工具。其中 `update_stock_data` 是唯一写工具（走数据中心同款补齐链路）。
- **多协议接入**：设置里可选 API 协议格式——`chat-completions`（OpenAI 兼容，默认）、`responses`（OpenAI Responses API）、`anthropic`（Anthropic Messages API，含 tool_use/tool_result 流式映射）；密钥/协议等配置仅存本地。
- **启动 AI 资讯聚合**：服务启动时（已配置模型）Agent 自动汇总新闻/涨停池/昨日涨停表现/实时行情/复盘等多源数据，生成 3-6 条结构化"AI 聚合要点"，展示在资讯面板顶部（标注 ai-agent，与原始资讯模块严格分离），也可通过 `GET /ai/news` 与 `latest_market_digest` 工具消费；之后按固定间隔自动刷新。
- **NL→策略 DSL**：自然语言生成条件 DSL → 先校验（校验失败带模板示例自我修正）→ 受控运行本地回测 → 结果可一键"应用到策略工作台"。
- **上下文工程与分层记忆**（参考 MemGPT/Letta、mem0 的分层思路，本地化裁剪）：短期上下文窗口硬性保留最近 10 条协议消息，溢出部分归档并压缩为会话滚动纪要；长期记忆由模型在每轮结束后提取持久事实（关注标的/策略偏好/参数习惯），去重合并进 `运行产物/AI记忆/memory.json`，并按更新时间注入后续 system prompt。工具全量结果留在后端 `ToolResultStore`，进上下文的只有每工具摘要；爬取内容以不可信分隔符包裹（提示词注入防御）。
- **真实执行能力（NL→SQL + 计算函数 + 受控写入）**：Agent 可对本地日线数据仓发起 DuckDB 只读 SQL 查询（`query_warehouse_sql`，hive 分区 parquet 直查，强制 SELECT/WITH、自动 LIMIT 500），可调用统计函数（`compute_stock_stats`：区间收益/年化波动/最大回撤/资金合计），可通过 `update_stock_data` 用数据中心同款补齐链路把指定股票区间数据写回仓库——这是唯一的写路径，SQL 层禁止任何写语句。
- **本地知识检索（RAG）**：投研方法论 / 条件 DSL 语法 / 数据字段规则三份语料，langchain-text-splitters 分块 + OpenAI 兼容 embedding（磁盘缓存）+ numpy 余弦 Top-K，以 `retrieve_knowledge` 工具挂给 Agent。
- **AI 快讯推送**：`GET /ai/events/stream` 长连接。规则触发器（新闻更新 / 市场宽度异动 / 风险清单变化）发出 `data_fresh` 信号，前端立即刷新对应模块（推拉结合，替代死等轮询）；配置模型后按小时级配额生成 AI 快讯（`insight`，强制标注 ai-insight，不构成投资建议）。
- **配置与安全**：LLM 配置存于 `运行产物/AI配置/ai-config.json`（不进 Git；设置弹窗可显示/隐藏自己的 API Key，接口默认只回掩码）；AI 模块对数据仓默认只读，唯一写路径是 `update_stock_data` 补齐链路；AI 生成的策略/结论不进入 `latest_strategy_matches` 候选管线；评测集见 `scripts/ai_eval.py`（20 条 NL→DSL 用例，本地跑，不进 CI）。

LLM 客户端复用官方 `openai` SDK（任何 OpenAI 兼容服务商均可，配置默认留空，由用户在应用内"AI 助手 → 设置"填写）。

## 面向用户

- 策略条件一句话生成：在"策略配置 → AI 条件理解"里用口语描述买卖规则，AI 解析成可勾选的条件清单（含近似说明），确认后写入策略；需要精细控制时展开"高级模式"手工编辑。
- AI 助手：右上角"AI 助手"唤起右侧抽屉，支持个股诊断（技术/资金/估值/消息四维）、大盘快评、自然语言生成策略并一键回测、回测结果解读；工具调用过程与数据来源全部可见。
- AI 参数寻优：策略配置页底部"AI 参数寻优"面板，选 2–4 个参数给候选值（最多 48 组合），一键网格回测出对比表 + AI 解读最优区间与过拟合警告。
- 回测报告导出：回测完成后"导出报告"一键下载单文件 HTML（权益曲线、指标、交易明细、AI 解读），可直接存档或分享。
- 数据中心：维护 A 股日线、资金流、市值和覆盖信息，支持导入、全市场同步、指定股票补齐和资金流补齐；"AI 诊断缺失"按钮分析覆盖缺口并指路补齐操作；"数据源健康监控"折叠卡实时展示各数据源最近成功状态。
- 覆盖口径可信：新上市股票上市前、已退市股票退市后不再算"缺失"，覆盖表与同步进度反映真实缺口（逐股明细带"未上市/已退市"徽标）。
- 策略回测：支持入场/离场条件、仓位参数、止盈止损、涨跌停约束和流式回测结果。
- 行情看板：展示指数、红绿家数、强势板块、行情评价、新闻摘要、资讯事件、同花顺复盘/早盘和风险提示；后端有新数据或出现 AI 快讯时通过事件流即时提醒。
- 候选股票：回测结果通过 `latest_strategy_matches.matches` 展示符合当前策略的个股。
- 桌面更新：通过 GitHub Releases 发布 Windows 安装包，并由应用内更新入口检查新版本。

最新安装包见 [GitHub Releases](https://github.com/dzc-bit/Astock-backtester/releases)。

## 数据源概览

- 历史行情：AData、AKShare、百度股市通 / PAE、东方财富公开接口。
- 实时行情：财联社、同花顺、Sina、Tencent、AKShare 及后端公开行情爬虫。
- 强势板块：同花顺概念/行业、Sina 行业、AKShare、东方财富板块接口。
- 新闻资讯：东方财富栏目资讯、东方财富要闻、财联社电报。
- 复盘早盘：同花顺复盘/早盘页面，失败时使用公开行情或本地简短判断兜底。
- 资金流：东方财富公开资金流接口，缺口和失败原因会通过 diagnostics/failures 暴露给上层服务。

## 技术架构

| 层级 | 目录 | 说明 |
| --- | --- | --- |
| 前端 | `frontend/src` | React + TypeScript，页面、状态、图表和结构化接口消费；API 层统一在 `api.ts`（含浏览器预览 mock 双轨），AI 对话流在 `aiApi.ts`，轮询类逻辑收敛在 `hooks/`；视觉系统由根目录 `design.md` 锁定（`:root` token 块 + A 股红涨绿跌语义） |
| 桌面容器 | `src-tauri/src` | Tauri + Rust，负责桌面命令、本地服务启动（含 sidecar 五重身份校验）、策略保存和更新器 |
| 本地后端 | `backend/astock_backtester` | Python，自写 HTTP 服务 + 数据 provider + 仓库 + 回测引擎；回测条件在 `conditions.py` 注册表统一维护（行级求值与向量化预过滤成对注册）；`symbol_lifecycle` 表驱动覆盖/同步的上市–退市窗口口径 |
| AI 子系统 | `backend/astock_backtester/ai` | 独立子包：openai SDK 薄封装、工具注册表（本地数据 + a-stock-data 裁剪端点）、Agent 循环、上下文预算、会话存储、RAG 检索、快讯引擎、条件解析/单段点评/参数寻优轻路由；对数据仓只读 |
| 共享数据设施 | `backend/astock_backtester/data` | `symbols.py`/`parsing.py` 收敛符号与数值解析，`http_transport.py` 统一 UA、代理策略和重试传输 |
| 测试 | `tests`、`frontend/src/*.test.*` | 三层测试：后端（行为级，含 AI 子系统）、前端（≥250 断言）、Rust；回环 HTTP 测试自带代理隔离 |

依赖方向保持单向（`service → data/* → models`，data 层不反向依赖根包），全仓零 import 环。错误响应携带稳定 `code`（`no_local_data` / `validation_error` / `payload_error` / `request_failed`），前端按错误码翻译文案。

## 质量门禁

CI（`.github/workflows/ci.yml`，windows-latest）在 push/PR 时运行三组检查：pytest + ruff、eslint + tsc + vitest、cargo test。本地等价命令：

```powershell
python -m ruff check backend tests scripts
npm run lint
npm run typecheck
npm run test:coverage
cargo test --manifest-path src-tauri/Cargo.toml
```

覆盖率（pytest-cov + vitest v8）当前只出报告不设阈值。

## 本地 HTTP 接口

桌面端启动后会拉起本地 sidecar，前端访问 `http://127.0.0.1:<port>`。

| 能力 | 接口 |
| --- | --- |
| 健康检查 | `GET /ping`、`GET /health`、`GET /logs/recent`、`GET /diagnostics/sources` |
| 覆盖查询 | `POST /coverage/daily-bars` |
| 数据同步 | `POST /sync/full-market`、`GET /sync/jobs/{job_id}` |
| 数据导入与补齐 | `POST /import/daily-bars`、`POST /fetch/daily-bars`、`POST /fetch/capital-flow` |
| 行情与资讯 | `GET /realtime/market-snapshot`、`GET /market/commentary`、`GET /market/news-summary`、`GET /market/news` |
| 复盘/早盘 | `GET /market/fupan`、`GET /market/zaopan` |
| 风险与策略 | `GET /risk/alerts`、`GET /strategy/recommended`、`POST /strategy/conditions/validate` |
| 回测 | `POST /run/backtest/stream` |
| AI 助手 | `GET /ai/status`、`GET /ai/news`、`GET /ai/config`、`POST /ai/config`、`GET /ai/config/reveal`（仅限本机桌面端，带 Host/Origin 校验）、`POST /ai/chat/stream`、`GET /ai/events/stream` |
| AI 轻路由（v1.5.0） | `POST /ai/conditions/parse`（自然语言→条件 DSL，自愈校验）、`POST /ai/insight/oneshot`（场景化单段点评）、`POST /ai/optimize`（参数网格寻优，NDJSON 流式） |

`/run/backtest/stream` 与 `/ai/chat/stream` 返回 NDJSON，需要逐行解析；`/ai/chat/stream` 的最后一个事件为 `{"type":"result", ...}`（错误时为 `error`）。`/ai/events/stream` 为长连接（insight / data_fresh / heartbeat）。

## 开发环境

建议环境：

- Node.js 20+
- Python 3.11+
- Rust stable toolchain
- Windows 桌面构建需要 Tauri 支持的 MSVC 构建工具

安装依赖：

```powershell
npm install
python -m pip install -e .
```

常用命令：

```powershell
npm run test:ui -- --run
npm run lint
npm run typecheck
npm run build
npm run build:data-service
python -m pytest tests -q
python -m ruff check backend tests scripts
cargo test --manifest-path src-tauri/Cargo.toml
```

开发模式：

```powershell
npm run tauri -- dev
```

生产构建：

```powershell
npm run tauri -- build --ci
```

Windows 发布使用项目内固定的 Node、Python、Rust、MSVC 和 NSIS 工具，完整的签名、覆盖安装、sidecar 哈希和 HTTP 探针流程见 [`docs/release.md`](docs/release.md)。

发布前请确认生成的安装包、签名文件、临时更新清单、日志和运行数据没有提交到 Git 仓库。
