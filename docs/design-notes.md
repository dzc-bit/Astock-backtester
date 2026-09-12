# v1.5.0 前端设计说明（Hallmark audit + redesign）

本次按 Hallmark 技能流程对前端做了一次完整 audit + redesign。设计系统的权威定义在仓库根目录 **`design.md`**，本文件记录审计结论与执行摘要。

## 审计结论（重构前基线）

| 严重度 | 问题 | 位置 |
| --- | --- | --- |
| critical | 510 处硬编码 hex / 仅 19 处 var()，127 处裸字号、92 处裸圆角（mid-render token improvisation） | `styles.css` 全文件 |
| critical | body 三色 120° 渐变背景 + 约 30 处卡片级多色渐变（AI 高级感 tell） | `styles.css:88` 等 |
| critical | `.ai-oneshot-line` 左侧 3px 实色边条（side-stripe card）；既有代码里 `.news-summary-panel` 4px 左边条、`.ths-briefing-card::before` 5px 左边条、`.risk-alert` 5px 严重度左边条 | 各面板 |
| critical | `.surface` 白卡内再嵌带边框卡片（card-in-card） | 数据中心/工作台 |
| major | 关键数字容器只有 6 处 tabular-nums | 指标条/表格 |
| major | 字阶 14 种裸值、圆角 9 种裸值、focus-visible 仅 3 处 | 全局 |
| minor | `.optimizer-table tr.best-row` 用绿底——A 股语境绿色=跌，语义事故 | 寻优表 |
| minor | 15 处 box-shadow 无系统 | 全局 |

计数：**4 critical · 6 major · 3 minor**。

## 执行的重构

1. **Token 收敛**：`:root` 建立 60+ 个命名 token（表面/墨色/分隔线/accent/A股语义红绿/警示/信息蓝/AI 紫/焦点/阴影/字阶/圆角），`styles.css` 与 `ai-panel.css` 在 token 块之外 **0 处硬编码色值**，`gradient` 关键字清零。旧的 `--blue/--amber/--violet` 保留为别名。
2. **渐变扁平化**：body 改纯色 `--backdrop`；所有卡片级装饰渐变改为纯色表面/语义 wash；"三色彩虹条"统一为 accent。
3. **条纹语言统一**：全部左侧实色边条改为**顶部 3–4px accent 条**（与既有 modal 语言一致），`.ai-oneshot-line` 改 hairline 全边框 + `--accent-wash` 底。
4. **语义修正**：`best-row` 绿底 → accent 选中色（绿=跌，不得用于"最优"）；`market-degree-card-low` 底色从 accent-wash 修正为 `--fall-wash`。
5. **数字纪律**：指标条/表格/摘要卡等数字容器统一 `font-variant-numeric: tabular-nums`。
6. **焦点系统**：全局 `:focus-visible` 统一 `--focus` ring（2px，不动画）。
7. **响应式**：移除 `body { min-width: 320px }`（320 视口减去滚动条后必出横向滚动）；实测 320/375/768/1280 无页面级横向滚动，表格由 `.table-wrap` 内部滚动。
8. **新组件沿用系统**：AI 条件面板、解析清单、参数寻优面板、数据源健康卡、`parse-badge`/`source-health-*` 全部由 token 构成。

## 刻意保留（记录取舍）

- **Card-in-card**：数据密度要求保留分组容器；处理为统一 hairline 单层语言（`--rule` 系）而非去除嵌套，已在 `design.md` 记录为 app 页面豁免。
- **Motion-cut**：0 处 transition/animation（数据工具，状态即时呈现），因此无需 reduced-motion 分支；后续加动效先补 `prefers-reduced-motion`。
- **字族**：本地中文桌面应用不引入 webfont，保持 Microsoft YaHei 单字族；数字与标题的层级由 tabular-nums + 字阶/字重承担。
- **信息架构/文案/aria**：全部不变（前端测试 252 项守卫；仅 20 个用例因"高级模式折叠"按任务书要求增加了展开步骤）。

## 视觉验证

`npm run dev`（浏览器预览，mock 数据）实测截图确认：1280 桌面整页、工作台 AI 条件面板（解析清单/勾选写入）、高级模式展开、AI 参数寻优面板、数据中心（AI 诊断缺失按钮 + 数据源健康卡）、回测后收益概览（AI 短评行 + 导出报告按钮）、风险弹窗（AI 解读行）、375/320 宽度无横向滚动。
