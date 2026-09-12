"""Strategy parameter grid search: deterministic sweep + one AI commentary.

``POST /ai/optimize`` streams NDJSON events (progress / combination / result)
while re-running ``run_configured_backtest`` over a bounded cartesian grid of
whitelisted numeric settings knobs. The AI part is a single final commentary
call; the sweep itself works without a configured model.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from typing import Any

from pydantic import ValidationError

from astock_backtester.backtest_runner import run_configured_backtest
from astock_backtester.models import BacktestMetrics, BacktestSettings, StrategyConfig

MAX_GRID_COMBINATIONS = 48
# Only vetted numeric knobs are grid-searchable; strategy conditions stay fixed.
GRID_KEYS = (
    "fixed_holding_days",
    "max_positions",
    "max_daily_buys",
    "position_size_pct",
    "take_profit_pct",
    "stop_loss_pct",
    "min_listing_days",
)


class GridTooLargeError(ValueError):
    pass


def normalize_grid(payload_grid: dict[str, Any]) -> dict[str, list[float]]:
    """Validate the requested grid: whitelisted keys, finite values, bounded size."""
    grid: dict[str, list[float]] = {}
    for key, values in (payload_grid or {}).items():
        if key not in GRID_KEYS:
            raise ValueError(f"不支持寻优的参数：{key}（可选：{', '.join(GRID_KEYS)}）")
        if not isinstance(values, list) or not values:
            raise ValueError(f"参数 {key} 的候选值必须是非空数组")
        cleaned = [float(value) for value in values]
        if not all(value == value and abs(value) != float("inf") for value in cleaned):
            raise ValueError(f"参数 {key} 的候选值必须是有限数字")
        grid[key] = cleaned
    keys = list(grid)
    total = 1
    for key in keys:
        total *= len(grid[key])
    if total == 0:
        raise ValueError("网格为空，请至少为一个参数提供候选值")
    if total > MAX_GRID_COMBINATIONS:
        raise GridTooLargeError(f"网格组合数 {total} 超过上限 {MAX_GRID_COMBINATIONS}，请减少候选值")
    return grid


def iter_grid(grid: dict[str, list[float]]) -> Iterator[dict[str, float]]:
    keys = list(grid)
    for values in itertools.product(*(grid[key] for key in keys)):
        yield dict(zip(keys, values, strict=True))


def metrics_row(metrics: BacktestMetrics) -> dict[str, float | int]:
    return metrics.model_dump(mode="json")


def rank_combinations(combinations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best combination by total return among those with at least one trade."""
    candidates = [combo for combo in combinations if combo.get("metrics", {}).get("trade_count", 0) > 0]
    if not candidates:
        return None

    def sort_key(combo: dict[str, Any]) -> tuple[float, float]:
        metrics = combo["metrics"]
        return (float(metrics.get("total_return_pct", 0.0)), -abs(float(metrics.get("max_drawdown_pct", 0.0))))

    return max(candidates, key=sort_key)


def run_optimization(
    frame: Any,
    strategy: StrategyConfig,
    settings: BacktestSettings,
    grid: dict[str, list[float]],
    on_event: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Run every grid combination and emit progress/combination events."""
    combos = list(iter_grid(grid))
    combinations: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, overrides in enumerate(combos, start=1):
        try:
            combo_settings = settings.model_copy(update=overrides)
            result = run_configured_backtest(frame, strategy, combo_settings)
        except ValidationError as exc:
            failures.append({"params": overrides, "error": str(exc.errors()[0].get("msg", exc))})
            on_event({"type": "progress", "completed": index, "total": len(combos)})
            continue
        row = {
            "index": index,
            "params": overrides,
            "metrics": metrics_row(result.metrics),
        }
        combinations.append(row)
        on_event({"type": "combination", **row})
        on_event({"type": "progress", "completed": index, "total": len(combos)})
    best = rank_combinations(combinations)
    return {
        "combinations": combinations,
        "best": best,
        "failures": failures,
        "total": len(combos),
        "evaluated": len(combinations),
    }


def build_optimize_insight_context(summary: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "params": combo["params"],
            "total_return_pct": combo["metrics"].get("total_return_pct"),
            "max_drawdown_pct": combo["metrics"].get("max_drawdown_pct"),
            "win_rate_pct": combo["metrics"].get("win_rate_pct"),
            "trade_count": combo["metrics"].get("trade_count"),
        }
        for combo in summary.get("combinations", [])
    ]
    return {
        "best": summary.get("best"),
        "combinations": rows[:48],
        "evaluated": summary.get("evaluated", 0),
        "failures": summary.get("failures", [])[:3],
    }
