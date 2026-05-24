from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any

from astock_backtester.data.cache import LocalCache
from astock_backtester.conditions import registered_conditions
from astock_backtester.engine import run_backtest
from astock_backtester.indicators import add_macd, add_market_heat, add_moving_average, add_returns, add_volume_ratio
from astock_backtester.models import (
    BacktestSettings,
    ConditionGroup,
    ConditionNode,
    ConditionOperator,
    StrategyConfig,
)
from astock_backtester.sample_data import sample_daily_bars


def _default_strategy() -> StrategyConfig:
    return StrategyConfig(
        name="demo",
        market_filters=[
            ConditionNode(id="market", condition_id="market_rising_ratio_at_least", params={"min_ratio": 0.5})
        ],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(id="cap", condition_id="market_cap_between", params={"min": 1, "max": 30_000_000_000}),
                    ConditionNode(
                        id="flow",
                        condition_id="capital_flow_n_day_sum_at_least",
                        params={"window": 3, "min": 3_000_000},
                    ),
                    ConditionNode(id="ma", condition_id="close_above_ma", params={"window": 3}),
                ],
            )
        ],
        exit_rules=[ConditionNode(id="exit", condition_id="close_below_ma", params={"window": 3})],
    )


def _default_settings() -> BacktestSettings:
    return BacktestSettings(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 8),
        initial_cash=100_000,
        fixed_holding_days=3,
        take_profit_pct=0.08,
        stop_loss_pct=-0.05,
        max_positions=2,
        max_daily_buys=1,
    )


def _jsonable_model(model: Any) -> Any:
    return json.loads(model.model_dump_json())


def _strategy_nodes(strategy: StrategyConfig) -> list[ConditionNode]:
    return [
        *strategy.market_filters,
        *(node for group in strategy.entry_groups for node in group.conditions),
        *strategy.exit_rules,
    ]


def _window_params(strategy: StrategyConfig, condition_ids: set[str], defaults: set[int]) -> list[int]:
    windows = set(defaults)
    for node in _strategy_nodes(strategy):
        if node.condition_id in condition_ids and "window" in node.params:
            windows.add(int(node.params["window"]))
    return sorted(windows)


def _enrich_for_strategy(frame: Any, strategy: StrategyConfig) -> Any:
    ma_windows = _window_params(strategy, {"close_above_ma", "close_below_ma"}, {3, 5, 10, 20, 60})
    return_windows = _window_params(strategy, {"past_return_at_most", "past_return_between"}, {2, 3, 5, 10, 20})
    volume_windows = _window_params(strategy, {"volume_ratio_between"}, {2, 3, 5, 10})
    frame = add_moving_average(frame, ma_windows)
    frame = add_returns(frame, return_windows)
    frame = add_volume_ratio(frame, volume_windows)
    frame = add_macd(frame)
    return add_market_heat(frame)


def _condition_definition_json(definition: Any) -> dict[str, Any]:
    return {
        "condition_id": definition.condition_id,
        "label": definition.label,
        "category": definition.category,
        "required_columns": list(definition.required_columns),
    }


def handle_command(payload: dict[str, Any]) -> dict[str, Any]:
    command = payload.get("command")
    try:
        if command == "coverage":
            cache = LocalCache(payload["cache_dir"])
            return {"ok": True, "coverage": [_jsonable_model(item) for item in cache.coverage()]}
        if command == "fetch_status":
            return {
                "ok": True,
                "status": {
                    "configured": False,
                    "message": "a-stock-data adapter boundary is present; configure fetcher functions before live fetching.",
                },
            }
        if command == "conditions":
            return {"ok": True, "conditions": [_condition_definition_json(item) for item in registered_conditions()]}
        if command == "demo_backtest":
            strategy = _default_strategy()
            frame = _enrich_for_strategy(sample_daily_bars(), strategy)
            result = run_backtest(frame, strategy, _default_settings())
            return {"ok": True, "result": _jsonable_model(result)}
        if command == "run_backtest":
            strategy = StrategyConfig.model_validate(payload["strategy"])
            settings = BacktestSettings.model_validate(payload["settings"])
            cache_dir = payload.get("cache_dir")
            frame = LocalCache(cache_dir).read_daily_bars() if cache_dir else sample_daily_bars()
            if frame.empty:
                raise ValueError("No cached daily bars found. Import or fetch data before running a configured backtest.")
            result = run_backtest(_enrich_for_strategy(frame, strategy), strategy, settings)
            return {"ok": True, "result": _jsonable_model(result)}
        return {"ok": False, "error": {"code": "unknown_command", "message": f"Unknown command: {command}"}}
    except Exception as exc:
        return {"ok": False, "error": {"code": "command_failed", "message": str(exc)}}


def main() -> None:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    print(json.dumps(handle_command(payload), ensure_ascii=False))


if __name__ == "__main__":
    main()
