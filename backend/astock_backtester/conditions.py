from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from astock_backtester.models import ConditionGroup, ConditionNode, ConditionOperator


@dataclass(frozen=True)
class ConditionDefinition:
    condition_id: str
    label: str
    category: str
    required_columns: tuple[str, ...]


@dataclass(frozen=True)
class ConditionResult:
    passed: bool
    reason: str
    observed_value: float | None = None


@dataclass(frozen=True)
class GroupResult:
    passed: bool
    reasons: list[str]
    score: float = 0.0


Evaluator = Callable[[ConditionNode, pd.Series, pd.DataFrame], ConditionResult]


def registered_conditions() -> list[ConditionDefinition]:
    return [
        ConditionDefinition("market_cap_between", "Float market cap range", "market_cap", ("float_market_cap",)),
        ConditionDefinition(
            "capital_flow_n_day_sum_at_least",
            "N-day main net inflow",
            "capital_flow",
            ("main_net_inflow",),
        ),
        ConditionDefinition(
            "market_rising_ratio_at_least",
            "Market rising ratio",
            "market_heat",
            ("market_rising_ratio",),
        ),
        ConditionDefinition("close_above_ma", "Close above moving average", "trend", ()),
        ConditionDefinition("close_below_ma", "Close below moving average", "trend", ()),
        ConditionDefinition("turnover_between", "Turnover range", "volume", ("turnover_rate",)),
        ConditionDefinition("past_return_at_most", "Past return upper bound", "price_movement", ()),
        ConditionDefinition("past_return_between", "Past return range", "price_movement", ()),
        ConditionDefinition("volume_ratio_between", "Volume ratio range", "volume", ()),
        ConditionDefinition("macd_histogram_at_least", "MACD histogram floor", "technical", ("macd_hist",)),
        ConditionDefinition("breakout_above_n_day_high", "Breakout above prior high", "pattern", ()),
        ConditionDefinition("breakdown_below_n_day_low", "Breakdown below prior low", "exit_pattern", ()),
    ]


def _market_cap_between(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    value = float(row["float_market_cap"])
    minimum = float(node.params["min"])
    maximum = float(node.params["max"])
    passed = minimum <= value <= maximum
    return ConditionResult(passed, f"float market cap {value:.0f} in [{minimum:.0f}, {maximum:.0f}]", value)


def _capital_flow_n_day_sum_at_least(
    node: ConditionNode,
    row: pd.Series,
    frame: pd.DataFrame,
) -> ConditionResult:
    window = int(node.params["window"])
    minimum = float(node.params["min"])
    precomputed_column = f"main_net_inflow_sum_{window}d"
    if precomputed_column in row.index:
        value = pd.to_numeric(row[precomputed_column], errors="coerce")
        if pd.isna(value):
            return ConditionResult(
                False,
                f"{window}d main net inflow unavailable before enough history",
                None,
            )
        value = float(value)
        return ConditionResult(value >= minimum, f"{window}d main net inflow {value:.0f} >= {minimum:.0f}", value)

    symbol_frame = frame[
        (frame["symbol"] == row["symbol"]) & (frame["trade_date"] <= row["trade_date"])
    ].sort_values("trade_date")
    if len(symbol_frame) < window:
        return ConditionResult(
            False,
            f"{window}d main net inflow unavailable before enough history",
            None,
        )
    value = float(symbol_frame.tail(window)["main_net_inflow"].sum())
    passed = value >= minimum
    return ConditionResult(passed, f"{window}d main net inflow {value:.0f} >= {minimum:.0f}", value)


def _market_rising_ratio_at_least(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    value = float(row["market_rising_ratio"])
    minimum = float(node.params["min_ratio"])
    return ConditionResult(value >= minimum, f"market rising ratio {value:.2%} >= {minimum:.2%}", value)


def _close_above_ma(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row["close"] - row[f"ma_{window}"])
    return ConditionResult(value > 0, f"close {row['close']:.2f} above MA{window} {row[f'ma_{window}']:.2f}", value)


def _close_below_ma(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row["close"] - row[f"ma_{window}"])
    return ConditionResult(value < 0, f"close {row['close']:.2f} below MA{window} {row[f'ma_{window}']:.2f}", value)


def _turnover_between(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    value = float(row["turnover_rate"])
    minimum = float(node.params["min"])
    maximum = float(node.params["max"])
    return ConditionResult(
        minimum <= value <= maximum,
        f"turnover {value:.2%} in [{minimum:.2%}, {maximum:.2%}]",
        value,
    )


def _past_return_at_most(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row[f"return_{window}d"])
    maximum = float(node.params["max"])
    return ConditionResult(value <= maximum, f"{window}d return {value:.2%} <= {maximum:.2%}", value)


def _past_return_between(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row[f"return_{window}d"])
    minimum = float(node.params["min"])
    maximum = float(node.params["max"])
    return ConditionResult(
        minimum <= value <= maximum,
        f"{window}d return {value:.2%} in [{minimum:.2%}, {maximum:.2%}]",
        value,
    )


def _volume_ratio_between(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row[f"volume_ratio_{window}d"])
    minimum = float(node.params["min"])
    maximum = float(node.params["max"])
    return ConditionResult(
        minimum <= value <= maximum,
        f"{window}d volume ratio {value:.2f} in [{minimum:.2f}, {maximum:.2f}]",
        value,
    )


def _macd_histogram_at_least(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    value = float(row["macd_hist"])
    minimum = float(node.params["min"])
    return ConditionResult(value >= minimum, f"MACD histogram {value:.4f} >= {minimum:.4f}", value)


def _breakout_above_n_day_high(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    precomputed_column = f"prior_high_{window}d"
    if precomputed_column in row.index:
        prior_high = pd.to_numeric(row[precomputed_column], errors="coerce")
        if pd.isna(prior_high):
            return ConditionResult(False, f"{window}d prior high unavailable before enough history", None)
        prior_high = float(prior_high)
        value = float(row["close"] - prior_high)
        return ConditionResult(value > 0, f"close {row['close']:.2f} broke prior {window}d high {prior_high:.2f}", value)

    symbol_frame = frame[
        (frame["symbol"] == row["symbol"]) & (frame["trade_date"] < row["trade_date"])
    ].sort_values("trade_date")
    if len(symbol_frame) < window:
        return ConditionResult(False, f"{window}d prior high unavailable before enough history", None)
    prior_high = float(symbol_frame.tail(window)["high"].max())
    value = float(row["close"] - prior_high)
    return ConditionResult(value > 0, f"close {row['close']:.2f} broke prior {window}d high {prior_high:.2f}", value)


def _breakdown_below_n_day_low(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    precomputed_column = f"prior_low_{window}d"
    if precomputed_column in row.index:
        prior_low = pd.to_numeric(row[precomputed_column], errors="coerce")
        if pd.isna(prior_low):
            return ConditionResult(False, f"{window}d prior low unavailable before enough history", None)
        prior_low = float(prior_low)
        value = float(row["close"] - prior_low)
        return ConditionResult(value < 0, f"close {row['close']:.2f} broke prior {window}d low {prior_low:.2f}", value)

    symbol_frame = frame[
        (frame["symbol"] == row["symbol"]) & (frame["trade_date"] < row["trade_date"])
    ].sort_values("trade_date")
    if len(symbol_frame) < window:
        return ConditionResult(False, f"{window}d prior low unavailable before enough history", None)
    prior_low = float(symbol_frame.tail(window)["low"].min())
    value = float(row["close"] - prior_low)
    return ConditionResult(value < 0, f"close {row['close']:.2f} broke prior {window}d low {prior_low:.2f}", value)


EVALUATORS: dict[str, Evaluator] = {
    "market_cap_between": _market_cap_between,
    "capital_flow_n_day_sum_at_least": _capital_flow_n_day_sum_at_least,
    "market_rising_ratio_at_least": _market_rising_ratio_at_least,
    "close_above_ma": _close_above_ma,
    "close_below_ma": _close_below_ma,
    "turnover_between": _turnover_between,
    "past_return_at_most": _past_return_at_most,
    "past_return_between": _past_return_between,
    "volume_ratio_between": _volume_ratio_between,
    "macd_histogram_at_least": _macd_histogram_at_least,
    "breakout_above_n_day_high": _breakout_above_n_day_high,
    "breakdown_below_n_day_low": _breakdown_below_n_day_low,
}


def evaluate_condition(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    if not node.enabled:
        return ConditionResult(True, f"{node.condition_id} disabled")
    try:
        evaluator = EVALUATORS[node.condition_id]
    except KeyError as exc:
        raise ValueError(f"unknown condition_id: {node.condition_id}") from exc
    return evaluator(node, row, frame)


def evaluate_group(
    group: ConditionGroup,
    row: pd.Series,
    frame: pd.DataFrame,
    score_threshold: float | None = None,
) -> GroupResult:
    results = [evaluate_condition(node, row, frame) for node in group.conditions]
    reasons = [result.reason for result in results if result.passed]

    if group.operator == ConditionOperator.AND:
        return GroupResult(all(result.passed for result in results), reasons)
    if group.operator == ConditionOperator.OR:
        return GroupResult(any(result.passed for result in results), reasons)

    score = 0.0
    for node, result in zip(group.conditions, results, strict=True):
        if result.passed:
            score += float(node.weight or 0.0)
    threshold = float(score_threshold or 0.0)
    return GroupResult(score >= threshold, reasons, score)
