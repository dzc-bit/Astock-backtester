from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any

from astock_backtester.backtest_runner import condition_definitions_json, run_configured_backtest
from astock_backtester.data.astock_adapter import AStockDataAdapter
from astock_backtester.data.cache import LocalCache
from astock_backtester.data.importer import read_daily_bars
from astock_backtester.models import (
    BacktestSettings,
    ConditionGroup,
    ConditionNode,
    ConditionOperator,
    StrategyConfig,
)
from astock_backtester.sample_data import sample_daily_bars


def _require_ohlc_rows(frame: Any) -> Any:
    ohlc_columns = ["open", "high", "low", "close"]
    if frame.empty or not all(column in frame for column in ohlc_columns):
        return frame.iloc[0:0] if hasattr(frame, "iloc") else frame
    return frame.dropna(subset=ohlc_columns).reset_index(drop=True)


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
        if command == "import_daily_bars":
            cache = LocalCache(payload["cache_dir"])
            source = payload.get("source", "file")
            if source == "sample":
                frame = sample_daily_bars()
            elif source == "file":
                frame = read_daily_bars(payload["path"])
            else:
                raise ValueError("source must be 'sample' or 'file'")
            cache.write_daily_bars(frame)
            return {
                "ok": True,
                "imported_rows": int(len(frame)),
                "coverage": [_jsonable_model(item) for item in cache.coverage()],
            }
        if command == "fetch_status":
            return {
                "ok": True,
                "status": {
                    "configured": True,
                    "message": (
                        "a-stock-data HTTP sources are configured for Baidu daily K-line, Eastmoney capital flow, "
                        "and Eastmoney stock metadata."
                    ),
                },
            }
        if command == "fetch_daily_bars":
            cache = LocalCache(payload["cache_dir"])
            frame = AStockDataAdapter.from_http_sources().fetch_daily_bars(
                payload["symbols"],
                payload["start_date"],
                payload["end_date"],
            )
            if frame.empty:
                raise ValueError("a-stock-data returned no daily bars for the requested symbols and date range")
            cache.write_daily_bars(frame)
            return {
                "ok": True,
                "imported_rows": int(len(frame)),
                "coverage": [_jsonable_model(item) for item in cache.coverage()],
            }
        if command == "conditions":
            return {"ok": True, "conditions": condition_definitions_json()}
        if command == "demo_backtest":
            strategy = _default_strategy()
            result = run_configured_backtest(sample_daily_bars(), strategy, _default_settings())
            return {"ok": True, "result": _jsonable_model(result)}
        if command == "run_backtest":
            strategy = StrategyConfig.model_validate(payload["strategy"])
            settings = BacktestSettings.model_validate(payload["settings"])
            cache_dir = payload.get("cache_dir")
            frame = _require_ohlc_rows(LocalCache(cache_dir).read_daily_bars()) if cache_dir else sample_daily_bars()
            if frame.empty:
                raise ValueError("No cached daily bars found. Import or fetch data before running a configured backtest.")
            result = run_configured_backtest(frame, strategy, settings)
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
