from __future__ import annotations

from astock_backtester.models import (
    ConditionGroup,
    ConditionNode,
    ConditionOperator,
    DatasetCoverage,
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


def dataset_readiness(coverage: list[DatasetCoverage]) -> dict[str, bool]:
    datasets = {item.dataset: item for item in coverage}
    daily = datasets.get("daily_bars")
    market_cap = datasets.get("market_cap")
    capital_flow = datasets.get("capital_flow")
    return {
        "daily_bars": bool(daily and daily.symbols > 0),
        "market_cap": bool(market_cap and market_cap.symbols > 0 and market_cap.missing_rows == 0),
        "capital_flow": bool(capital_flow and capital_flow.symbols > 0 and capital_flow.missing_rows == 0),
    }


def _all_recommendations() -> list[RecommendedStrategy]:
    return [
        RecommendedStrategy(
            id="volume-breakout",
            name="放量突破",
            description="价格突破前高并伴随量能放大，适合寻找强势启动点。",
            suitable_market="指数温和上行、红盘家数占优、题材活跃时使用。",
            risk_note="避免连续大涨后追高，最好配合止损和市值过滤。",
            example_conditions=["突破20日新高", "量比2日介于1.2到2.5", "近5日涨幅小于12%"],
            scenario="温和上行",
            featured=True,
            required_datasets=["daily_bars", "market_cap"],
            capability_note="当前本地日线和市值覆盖足够时可直接套用。",
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
            risk_note="更适合在市场有承接、但不是全面高潮时使用。",
            example_conditions=["流通市值10亿到300亿", "换手率2%到8%", "量比2日介于1.2到2.5"],
            scenario="震荡轮动",
            featured=True,
            required_datasets=["daily_bars", "market_cap"],
            capability_note="当前本地日线和市值覆盖足够时可直接套用。",
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
            risk_note="需要本地资金流数据完整，否则应先补齐资金流覆盖。",
            example_conditions=["近3日主力净流入大于300万", "收盘价站上20日均线", "MACD柱线大于0"],
            scenario="主线加速",
            featured=True,
            required_datasets=["daily_bars", "market_cap", "capital_flow"],
            capability_note="只有资金流覆盖完整时才会展示。",
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
            id="trend-follow-pullback",
            name="均线承接回踩",
            description="趋势未破坏时等待均线附近承接，避免只追最强加速段。",
            suitable_market="温和上行但不想追高时使用。",
            risk_note="如果市场整体转弱，回踩容易演变成破位。",
            example_conditions=["收盘价站上20日均线", "换手率2%到8%", "近5日涨幅小于12%"],
            scenario="温和上行",
            featured=False,
            required_datasets=["daily_bars", "market_cap"],
            capability_note="适合和市值、量比条件一起使用。",
            strategy=StrategyConfig(
                name="均线承接回踩",
                market_filters=[],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("ma", "close_above_ma", {"window": 20}, "收盘价站上20日均线"),
                            _node("turnover", "turnover_between", {"min": 0.02, "max": 0.08}, "换手率2%到8%"),
                            _node("gain", "past_return_at_most", {"window": 5, "max": 0.12}, "近5日涨幅小于12%"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-ma", "close_below_ma", {"window": 5}, "收盘价跌破5日均线")],
            ),
        ),
        RecommendedStrategy(
            id="rotation-liquidity",
            name="轮动活跃承接",
            description="优先选择轮动阶段中流动性适中且换手健康的标的。",
            suitable_market="震荡轮动、板块快速切换时使用。",
            risk_note="如果题材持续性不足，隔日容易冲高回落。",
            example_conditions=["流通市值10亿到300亿", "量比2日介于1.2到2.5", "换手率2%到8%"],
            scenario="震荡轮动",
            featured=False,
            required_datasets=["daily_bars", "market_cap"],
            capability_note="当前本地日线和市值覆盖足够时可直接套用。",
            strategy=StrategyConfig(
                name="轮动活跃承接",
                market_filters=[],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("cap", "market_cap_between", {"min": 1_000_000_000, "max": 30_000_000_000}, "流通市值10亿到300亿"),
                            _node("volume", "volume_ratio_between", {"window": 2, "min": 1.2, "max": 2.5}, "量比2日介于1.2到2.5"),
                            _node("turnover", "turnover_between", {"min": 0.02, "max": 0.08}, "换手率2%到8%"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-ma", "close_below_ma", {"window": 3}, "收盘价跌破3日均线")],
            ),
        ),
        RecommendedStrategy(
            id="defensive-balance",
            name="防守观察筛选",
            description="行情不明朗时先压低追涨冲动，保留对流动性和趋势的底线约束。",
            suitable_market="防守观察阶段、等待主线重新明确时使用。",
            risk_note="更偏保守，可能错过最早启动段。",
            example_conditions=["流通市值10亿到300亿", "换手率2%到8%", "近5日涨幅小于12%"],
            scenario="防守观察",
            featured=False,
            required_datasets=["daily_bars", "market_cap"],
            capability_note="适合在覆盖齐全但市场分歧较大时使用。",
            strategy=StrategyConfig(
                name="防守观察筛选",
                market_filters=[],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("cap", "market_cap_between", {"min": 1_000_000_000, "max": 30_000_000_000}, "流通市值10亿到300亿"),
                            _node("turnover", "turnover_between", {"min": 0.02, "max": 0.08}, "换手率2%到8%"),
                            _node("gain", "past_return_at_most", {"window": 5, "max": 0.12}, "近5日涨幅小于12%"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-ma", "close_below_ma", {"window": 3}, "收盘价跌破3日均线")],
            ),
        ),
        RecommendedStrategy(
            id="oversold-rebound",
            name="超跌修复观察",
            description="只在跌深后出现量价修复时介入，避免把所有下跌都当反弹机会。",
            suitable_market="超跌修复、情绪冰点后尝试回暖时使用。",
            risk_note="修复失败时回撤会很快，应配合短周期离场。",
            example_conditions=["量比2日介于1.2到2.5", "近5日涨幅小于12%", "MACD柱线大于0"],
            scenario="超跌修复",
            featured=False,
            required_datasets=["daily_bars"],
            capability_note="只要求本地日线与指标计算完整。",
            strategy=StrategyConfig(
                name="超跌修复观察",
                market_filters=[],
                entry_groups=[
                    ConditionGroup(
                        id="entry",
                        operator=ConditionOperator.AND,
                        conditions=[
                            _node("volume", "volume_ratio_between", {"window": 2, "min": 1.2, "max": 2.5}, "量比2日介于1.2到2.5"),
                            _node("gain", "past_return_at_most", {"window": 5, "max": 0.12}, "近5日涨幅小于12%"),
                            _node("macd", "macd_histogram_at_least", {"min": 0}, "MACD柱线大于0"),
                        ],
                    )
                ],
                exit_rules=[_node("exit-ma", "close_below_ma", {"window": 3}, "收盘价跌破3日均线")],
            ),
        ),
    ]


def recommended_strategies(coverage: list[DatasetCoverage] | None = None) -> RecommendedStrategiesResponse:
    items = _all_recommendations()
    if coverage is None:
        return RecommendedStrategiesResponse(items=items)

    readiness = dataset_readiness(coverage)
    runnable = [
        item
        for item in items
        if all(readiness.get(dataset, False) for dataset in item.required_datasets)
    ]
    return RecommendedStrategiesResponse(items=runnable)
