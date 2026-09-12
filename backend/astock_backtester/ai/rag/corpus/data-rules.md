# 数据字段与规则

## 主仓字段

日线主仓字段：symbol、stock_name、trade_date、open、high、low、close、volume、amount、change_pct、turnover_rate、volume_ratio、float_market_cap、total_market_cap、main_net_inflow、is_st、is_suspended、source。

## 关键数据规则

- 回测只认 OHLC 完整行；资金流独立行不能让股票变成可回测日线。
- 资金流缺失可以让条件不可用或降权，不能用 0 静默替代真实缺失。
- float_market_cap（流通市值）是回测和筛选的重要字段，缺失会在 preflight issues 中提示。
- 实时行情、新闻和复盘不参与历史回测计算；回测只读本地数据仓。
- 春节、清明、劳动节、国庆等合法休市日不会出现在缺失交易日列表中。

## 候选排序（rank_score）

回测每天先扫描所有符合入场条件的候选，再按多维评分排序买入，直到达到最大持仓数与每日最大买入数：

- 量比 0.25、阶段涨幅/突破强度 0.25、主力净流入 0.20、换手率 0.15、成交量 0.10、流通市值均衡度 0.05。
- 每个维度在当日候选集合内归一化后合成 0-100 分。

## 实时行情来源与完整性

- 实时行情快照含：指数、红绿家数（市场宽度）、强势板块，带 status（live/stale/unavailable）与 diagnostics。
- 红绿家数必须检查完整性（全市场总数），局部样本会被判失败并写入 diagnostics。
- 大盘评分来自同花顺 10 分制评级，失败时显示"暂不可用"，不用无关数字兜底。

## AI 模块边界

- AI 工具对本地数据仓只读，不能写入或修改任何行情数据。
- AI 生成的候选、建议不进入回测结果管线（latest_strategy_matches），两者严格分离。
- AI 快讯属于独立模块，内容标注为 AI 生成，不伪装成行情数据源。
