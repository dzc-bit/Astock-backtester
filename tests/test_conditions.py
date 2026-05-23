import pandas as pd

from astock_backtester.conditions import evaluate_condition, evaluate_group, registered_conditions
from astock_backtester.indicators import add_market_heat, add_moving_average
from astock_backtester.models import ConditionGroup, ConditionNode, ConditionOperator
from astock_backtester.sample_data import sample_daily_bars


def enriched_frame() -> pd.DataFrame:
    return add_market_heat(add_moving_average(sample_daily_bars(), [3]))


def test_registry_contains_core_first_version_conditions():
    ids = {item.condition_id for item in registered_conditions()}

    assert "market_cap_between" in ids
    assert "capital_flow_n_day_sum_at_least" in ids
    assert "market_rising_ratio_at_least" in ids
    assert "close_above_ma" in ids


def test_market_cap_between_uses_signal_day_value():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(
        id="cap",
        condition_id="market_cap_between",
        params={"min": 8_000_000_000, "max": 10_000_000_000},
    )

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert "float market cap" in result.reason


def test_capital_flow_rolling_sum_is_date_bound():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(
        id="flow",
        condition_id="capital_flow_n_day_sum_at_least",
        params={"window": 3, "min": 9_000_000},
    )

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert result.observed_value == 9_000_000


def test_and_group_requires_all_conditions():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    group = ConditionGroup(
        id="entry",
        operator=ConditionOperator.AND,
        conditions=[
            ConditionNode(id="cap", condition_id="market_cap_between", params={"min": 1, "max": 10_000_000_000}),
            ConditionNode(id="ma", condition_id="close_above_ma", params={"window": 3}),
        ],
    )

    result = evaluate_group(group, row, df)

    assert result.passed is True
    assert len(result.reasons) == 2


def test_score_group_requires_threshold():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    group = ConditionGroup(
        id="score",
        operator=ConditionOperator.SCORE,
        conditions=[
            ConditionNode(id="cap", condition_id="market_cap_between", params={"min": 1, "max": 10_000_000_000}, weight=20),
            ConditionNode(id="hot", condition_id="market_rising_ratio_at_least", params={"min_ratio": 0.5}, weight=15),
        ],
    )

    result = evaluate_group(group, row, df, score_threshold=30)

    assert result.passed is True
    assert result.score == 35
