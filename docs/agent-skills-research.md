# 股票投资/分析类 AI Agent 调研（2026-09）

针对“A股投研助手距离真正 agent 还有差距”的问题，调研了 GitHub 上
**股票投资/金融分析方向**的开源 agent 项目（不是通用开发技能库）。
结论分四部分：对标项目、可借鉴模式、本次已落地的改动、后续候选。

## 一、对标项目

| 项目 | Stars | 与我们的相关性 |
| --- | --- | --- |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | 105k+ | 多智能体 LLM 金融交易框架。结构：analysts（行情/新闻/情绪/基本面/社媒五位分析师）→ researchers（多空辩论）→ managers → trader → risk_mgmt 风险组。utils 含数据源健康检查。 |
| [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | 31.8k+ | TradingAgents 中文增强版：A 股数据（akshare/通达信）、中文报告、A 股规则。证明“A 股本地化 agent”是独立赛道。 |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 63k+ | 投资人风格 agent 团队模拟对冲基金，结构分层清晰：signals/pipeline/risk/portfolio/backtesting/validation，每个 agent 输出 signal+confidence+reasoning。 |
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | 73k+ | “Open Data Platform for analysts, quants and **AI agents**”——数据平台把数据源抽象成 agent 可调用工具，与我们 `tools/` 注册表同构。 |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 48.5k+ | AI 量化平台 + RD-Agent 自动研发；回测与因子工程的工具化思路。 |
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 21k+ | 金融 LLM 本体（模型层，我们不走训练路线，仅参考其数据与评测结构）。 |
| [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 8k+ | 金融 agent 平台：workflow 编排 + 金融工具集，agent 分层参考。 |

## 二、可借鉴的核心模式

1. **分析师角色分工**（TradingAgents）：行情/新闻/情绪/基本面分别成"分析师"，每个只对自己的
   数据源负责，最后由 manager 汇总。我们是单 agent + 工具，对应做法是**按角色顺序组织
   研究流程**（深研流程已入人设：技术面/资金面/估值面/消息面/风险逐条取证）。
2. **数据源健康自检**（TradingAgents utils / OpenBB 数据平台）：agent 在做任何结论前
   先检查数据源可用性与缺口——这是金融 agent 的标配。本次已落地
   `data_health_report` 工具 + `/diagnostics/data-gaps` 端点，AI 能查到
   具体哪些股票停更在哪一天、哪些日期疑似写入失败。
3. **结论三件套**（ai-hedge-fund：signal + confidence + reasoning）：结论先行、
   给出置信度与论据。我们的人设已要求"结论先行 + 标注来源工具 + 风险提示"，
   快讯/oneshot 已带免责声明，结构一致。
4. **多步深研**（deep-research/recursive-research，见附录）：计划→分步取证→
   来源分级→标注未验证。已入人设。
5. **渐进加载语料**（anthropics/skills）：知识以"先描述后正文"方式供给，
   我们对应的是 RAG `retrieve_knowledge` + corpus markdown。

## 三、本次已落地的改动

- **缺失数据监控（数据源健康自检）**：
  - `Warehouse.data_gap_profile()`：停更分布（多少只停在哪个日期）、疑似写入失败日
    （薄行日）、市值/资金流字段尾部；10 分钟缓存、写入自动失效，只读最近年分区。
  - AI 工具 `data_health_report`：模型在回答"数据为什么缺/哪些没更新/能不能回测"前
    可查到内部具体缺口明细（人设提示词已写明先调用）。
  - `GET /diagnostics/data-gaps`：前端数据中心"数据源健康监控"旁新增"缺失数据监控"折叠区，
    展示同一明细（停更分布/失败日/字段尾部）。
- **深研流程与工具自愈**入人设（见上文模式 4、5）。
- 知识库新增异动/监管/量能语料（`anomaly-supervision-volume.md`）。

## 四、后续可借鉴候选（按性价比排序）

1. **TradingAgents 的五位分析师式"深研任务"**：把个股深研做成受控多阶段流程
   （行情分析师→情绪分析师→基本面分析师→汇总），复用现有工具注册表与数据仓；
   适合做成 `/ai/research` 流式端点。TradingAgents-CN 的 A 股数据层（akshare 工具封装）
   可参考其接口设计。
2. **ai-hedge-fund 的 signal/confidence/reasoning 结构化输出**：
   快讯与复盘报告可升级为固定三段式，便于下游消费与历史对比。
3. **OpenBB 式数据源注册表**：我们 `tools/` 已同构；若后续数据源继续增多，
   可参考其"每个数据源一份工具描述文件"的组织方式，便于维护。
4. **qlib/RD-Agent 的因子-回测自动化**：策略库体检已是雏形（定时重跑+小网格），
   后续可按其"因子生成→回测→筛选"流水线扩展。

## 附录：通用 Agent Skills 生态（次要参考）

- [anthropics/skills](https://github.com/anthropics/skills)（176k+）：官方技能仓库，
  SKILL.md 渐进加载结构；docx/pdf/xlsx、skill-creator、mcp-builder。
- [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills)（74k+）：
  精选清单，Data & Analysis 分类含 deep-research、recursive-research、postgres（只读 SQL）。
- 结论同前：不建议整体 fork 通用 skills 仓库（Claude Code 特化）；
  金融 agent 领域的项目才是我们的直接对标。
