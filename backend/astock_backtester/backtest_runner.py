from __future__ import annotations

from typing import Any

from astock_backtester.conditions import registered_conditions
from astock_backtester.engine import run_backtest
from astock_backtester.indicators import add_macd, add_market_heat, add_moving_average, add_returns, add_volume_ratio
from astock_backtester.models import ConditionNode, StrategyConfig


def strategy_nodes(strategy: StrategyConfig) -> list[ConditionNode]:
    return [
        *strategy.market_filters,
        *(node for group in strategy.entry_groups for node in group.conditions),
        *strategy.exit_rules,
    ]


def window_params(strategy: StrategyConfig, condition_ids: set[str], defaults: set[int]) -> list[int]:
    windows = set(defaults)
    for node in strategy_nodes(strategy):
        if node.condition_id in condition_ids and "window" in node.params:
            windows.add(int(node.params["window"]))
    return sorted(windows)


def enrich_for_strategy(frame: Any, strategy: StrategyConfig) -> Any:
    ma_windows = window_params(strategy, {"close_above_ma", "close_below_ma"}, {3, 5, 10, 20, 60})
    return_windows = window_params(strategy, {"past_return_at_most", "past_return_between"}, {2, 3, 5, 10, 20})
    volume_windows = window_params(strategy, {"volume_ratio_between"}, {2, 3, 5, 10})
    frame = add_moving_average(frame, ma_windows)
    frame = add_returns(frame, return_windows)
    frame = add_volume_ratio(frame, volume_windows)
    frame = add_macd(frame)
    return add_market_heat(frame)


def condition_definition_json(definition: Any) -> dict[str, Any]:
    return {
        "condition_id": definition.condition_id,
        "label": definition.label,
        "category": definition.category,
        "required_columns": list(definition.required_columns),
    }


def condition_definitions_json() -> list[dict[str, Any]]:
    return [condition_definition_json(item) for item in registered_conditions()]


def run_configured_backtest(frame: Any, strategy: StrategyConfig, settings: Any) -> Any:
    return run_backtest(enrich_for_strategy(frame, strategy), strategy, settings)
