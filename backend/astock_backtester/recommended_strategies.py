from __future__ import annotations

from astock_backtester.models import (
    ConditionGroup,
    ConditionNode,
    ConditionOperator,
    RecommendedStrategiesResponse,
    RecommendedStrategy,
    StrategyConfig,
)


def _node(node_id: str, condition_id: str, params: dict, expression: str) -> ConditionNode:
    return ConditionNode(
        id=node_id,
        condition_id=condition_id,
        params=params,
        data_lag_days=0,
        expression=expression,
    )


def recommended_strategies() -> RecommendedStrategiesResponse:
    items = [
        RecommendedStrategy(
            id="volume-breakout",
            name="放量突破",
            description="价格突破前高并伴随量能放大，适合寻找强势启动点。",
            suitable_market="指数温和上行、红盘家数占优、题材活跃时使用。",
            risk_note="避免连续大涨后追高，最好配合止损和市值过滤。",
            example_conditions=["突破20日新高", "量比2日介于1.2到2.5", "近5日涨幅小于12%"],
            strategy=StrategyConfig(
                name="放量突破",
                market_filters=[
                    _node("market-hot", "market_rising_ratio_at_least", {"min_ratio": 0.5}, "市场上涨家数占比不低于50%")
                ],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("breakout", "breakout_above_n_day_high", {"window": 20}, "突破20日新高"),
                            _node("volume", "volume_ratio_between", {"window": 2, "min": 1.2, "max": 2.5}, "量比2日介于1.2到2.5"),
                            _node("gain", "past_return_at_most", {"window": 5, "max": 0.12}, "近5日涨幅小于12%"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-ma", "close_below_ma", {"window": 3}, "收盘价跌破3日均线")],
            ),
        ),
        RecommendedStrategy(
            id="steady-cap-volume",
            name="市值量价均衡",
            description="过滤超大市值和极端成交，寻找流动性适中的趋势机会。",
            suitable_market="震荡偏强或结构性行情中使用。",
            risk_note="资金面数据缺失时会降低筛选质量。",
            example_conditions=["流通市值10亿到300亿", "换手率2%到8%", "量比2日介于1.2到2.5"],
            strategy=StrategyConfig(
                name="市值量价均衡",
                market_filters=[
                    _node("market-hot", "market_rising_ratio_at_least", {"min_ratio": 0.48}, "市场上涨家数占比不低于48%")
                ],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("cap", "market_cap_between", {"min": 1_000_000_000, "max": 30_000_000_000}, "流通市值10亿到300亿"),
                            _node("turnover", "turnover_between", {"min": 0.02, "max": 0.08}, "换手率2%到8%"),
                            _node("volume", "volume_ratio_between", {"window": 2, "min": 1.2, "max": 2.5}, "量比2日介于1.2到2.5"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-ma", "close_below_ma", {"window": 3}, "收盘价跌破3日均线")],
            ),
        ),
        RecommendedStrategy(
            id="capital-trend",
            name="资金趋势跟随",
            description="把主力净流入与均线趋势结合，优先选择资金确认的趋势股。",
            suitable_market="主线明确、成交活跃时使用。",
            risk_note="需要本地资金流数据完整，否则回测会给出预检提示。",
            example_conditions=["近3日主力净流入大于300万", "收盘价站上20日均线", "MACD柱线大于0"],
            strategy=StrategyConfig(
                name="资金趋势跟随",
                market_filters=[
                    _node("market-hot", "market_rising_ratio_at_least", {"min_ratio": 0.5}, "市场上涨家数占比不低于50%")
                ],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("flow", "capital_flow_n_day_sum_at_least", {"window": 3, "min": 3_000_000}, "近3日主力净流入大于300万"),
                            _node("ma", "close_above_ma", {"window": 20}, "收盘价站上20日均线"),
                            _node("macd", "macd_histogram_at_least", {"min": 0}, "MACD柱线大于0"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-ma", "close_below_ma", {"window": 5}, "收盘价跌破5日均线")],
            ),
        ),
        RecommendedStrategy(
            id="extreme-chasing-stress-test",
            name="极端追高压力测试",
            description="故意追放量突破后的高位票，用来验证回测能暴露大幅亏损，不作为实盘建议。",
            suitable_market="仅用于压力测试回测链路，观察买入、卖出、回撤和交易明细是否完整。",
            risk_note="高位放量后隔日低开会放大亏损，先用它确认系统能把坑跑出来，再看其它策略的漂亮收益。",
            example_conditions=["突破2日新高", "量比2日介于2到5", "跌破2日低点离场"],
            strategy=StrategyConfig(
                name="极端追高压力测试",
                market_filters=[],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("breakout", "breakout_above_n_day_high", {"window": 2}, "突破2日新高"),
                            _node("volume", "volume_ratio_between", {"window": 2, "min": 2.0, "max": 5.0}, "量比2日介于2到5"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-low", "breakdown_below_n_day_low", {"window": 2}, "跌破2日低点")],
            ),
        ),
    ]
    return RecommendedStrategiesResponse(items=items)
