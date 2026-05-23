from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any

from astock_backtester.data.cache import LocalCache
from astock_backtester.engine import run_backtest
from astock_backtester.indicators import add_market_heat, add_moving_average, add_returns
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
        if command == "demo_backtest":
            frame = sample_daily_bars()
            frame = add_moving_average(frame, [3])
            frame = add_returns(frame, [2])
            frame = add_market_heat(frame)
            result = run_backtest(frame, _default_strategy(), _default_settings())
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
