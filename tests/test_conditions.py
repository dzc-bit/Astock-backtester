import pandas as pd

from astock_backtester.condition_parser import (
    condition_examples,
    exit_condition_examples,
    validate_condition_text,
    validate_exit_condition_text,
)
from astock_backtester.conditions import evaluate_condition, evaluate_group, registered_conditions
from astock_backtester import indicators
from astock_backtester.indicators import (
    add_macd,
    add_market_heat,
    add_moving_average,
    add_returns,
    add_volume_ratio,
)
from astock_backtester.models import ConditionGroup, ConditionNode, ConditionOperator
from astock_backtester.sample_data import sample_daily_bars


def enriched_frame() -> pd.DataFrame:
    frame = add_market_heat(add_moving_average(sample_daily_bars(), [3]))
    frame = add_returns(frame, [2])
    frame = add_macd(frame)
    frame = add_volume_ratio(frame, [2])
    return frame


def test_registry_contains_core_first_version_conditions():
    ids = {item.condition_id for item in registered_conditions()}

    assert "market_cap_between" in ids
    assert "capital_flow_n_day_sum_at_least" in ids
    assert "capital_flow_today_at_least" in ids
    assert "capital_flow_n_day_positive_count_at_least" in ids
    assert "market_rising_ratio_at_least" in ids
    assert "close_above_ma" in ids
    assert "macd_histogram_at_least" in ids
    assert "volume_ratio_between" in ids
    assert "past_return_between" in ids
    assert "breakout_above_n_day_high" in ids
    assert "breakdown_below_n_day_low" in ids


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


def test_turnover_between_accepts_percent_unit_values():
    row = pd.Series({"turnover_rate": 4.5})
    node = ConditionNode(
        id="turnover",
        condition_id="turnover_between",
        params={"min": 0.02, "max": 0.08},
    )

    result = evaluate_condition(node, row, pd.DataFrame([row]))

    assert result.passed is True
    assert result.observed_value == 0.045
    assert "turnover 4.50%" in result.reason


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


def test_capital_flow_today_condition_uses_signal_day_value():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(id="flow-today", condition_id="capital_flow_today_at_least", params={"min": 4_000_000})

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert result.observed_value == 4_000_000


def test_capital_flow_positive_count_uses_precomputed_column():
    assert hasattr(indicators, "add_capital_flow_positive_count")

    df = indicators.add_capital_flow_positive_count(enriched_frame(), [3])
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-05"))].iloc[0]
    node = ConditionNode(
        id="flow-days",
        condition_id="capital_flow_n_day_positive_count_at_least",
        params={"window": 3, "min_count": 2},
    )

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert result.observed_value == 2


def test_capital_flow_positive_count_requires_enough_history():
    assert hasattr(indicators, "add_capital_flow_positive_count")

    df = indicators.add_capital_flow_positive_count(enriched_frame(), [3])
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-03"))].iloc[0]
    node = ConditionNode(
        id="flow-days",
        condition_id="capital_flow_n_day_positive_count_at_least",
        params={"window": 3, "min_count": 2},
    )

    result = evaluate_condition(node, row, df)

    assert result.passed is False
    assert result.observed_value is None


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


def test_volume_ratio_between_uses_prior_average_volume():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(id="vr", condition_id="volume_ratio_between", params={"window": 2, "min": 1.7, "max": 2.0})

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert round(result.observed_value or 0, 4) == round(2200 / ((1000 + 1500) / 2), 4)


def test_macd_histogram_condition_evaluates_registered_indicator():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(id="macd", condition_id="macd_histogram_at_least", params={"min": 0})

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert "MACD histogram" in result.reason


def test_past_return_between_supports_prior_gain_ranges():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(
        id="gain",
        condition_id="past_return_between",
        params={"window": 2, "min": 0.15, "max": 0.25},
    )

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert round(result.observed_value or 0, 6) == round((12 / 10) - 1, 6)


def test_breakout_above_n_day_high_uses_prior_highs_only():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(id="breakout", condition_id="breakout_above_n_day_high", params={"window": 2})

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert result.observed_value == 12.0 - 11.2


def test_breakdown_below_n_day_low_uses_prior_lows_only():
    df = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "AAA"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
            "open": [10.0, 10.3, 10.1, 9.5],
            "high": [10.5, 10.6, 10.4, 9.8],
            "low": [9.8, 9.9, 10.0, 9.4],
            "close": [10.2, 10.1, 10.2, 9.6],
            "volume": [1000, 1000, 1000, 1000],
        }
    )
    row = df[df["trade_date"] == pd.Timestamp("2024-01-05")].iloc[0]
    node = ConditionNode(id="breakdown", condition_id="breakdown_below_n_day_low", params={"window": 3})

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert round(result.observed_value or 0, 6) == round(9.6 - 9.8, 6)
    assert "prior 3d low" in result.reason


def test_breakout_breakdown_and_capital_flow_use_precomputed_columns():
    row = pd.Series(
        {
            "symbol": "AAA",
            "trade_date": pd.Timestamp("2024-01-04"),
            "close": 12.0,
            "prior_high_2d": 11.2,
            "prior_low_2d": 10.8,
            "main_net_inflow_sum_3d": 9_000_000,
        }
    )
    frame_without_history = pd.DataFrame([row])

    breakout = evaluate_condition(
        ConditionNode(id="breakout", condition_id="breakout_above_n_day_high", params={"window": 2}),
        row,
        frame_without_history,
    )
    breakdown = evaluate_condition(
        ConditionNode(id="breakdown", condition_id="breakdown_below_n_day_low", params={"window": 2}),
        row,
        frame_without_history,
    )
    flow = evaluate_condition(
        ConditionNode(id="flow", condition_id="capital_flow_n_day_sum_at_least", params={"window": 3, "min": 8_000_000}),
        row,
        frame_without_history,
    )

    assert breakout.passed is True
    assert round(breakout.observed_value or 0, 6) == round(12.0 - 11.2, 6)
    assert breakdown.passed is False
    assert round(breakdown.observed_value or 0, 6) == round(12.0 - 10.8, 6)
    assert flow.passed is True
    assert flow.observed_value == 9_000_000


def test_user_written_condition_text_is_validated_into_executable_node():
    result = validate_condition_text("收盘价站上20日均线")

    assert result.ok is True
    assert result.condition is not None
    assert result.condition.condition_id == "close_above_ma"
    assert result.condition.params == {"window": 20}
    assert result.normalized_text == "收盘价站上20日均线"
    assert result.errors == []


def test_user_written_exit_condition_supports_breaking_prior_low_text():
    result = validate_exit_condition_text("突破20日最低")

    assert result.ok is True
    assert result.condition is not None
    assert result.condition.condition_id == "breakdown_below_n_day_low"
    assert result.condition.params == {"window": 20}
    assert result.normalized_text == "突破20日最低"
    assert "跌破20日低点" in result.examples
    assert exit_condition_examples()


def test_user_written_exit_condition_has_exit_specific_error_message():
    result = validate_exit_condition_text("突破20日前高")

    assert result.ok is False
    assert result.condition is None
    assert result.errors[0].code == "unrecognized_exit_condition"
    assert "离场条件" in result.errors[0].message
    assert "跌破N日低点" in result.errors[0].message


def test_user_written_condition_supports_market_cap_and_percent_ranges():
    cap = validate_condition_text("流通市值10亿到300亿")
    turnover = validate_condition_text("换手率2%到8%")

    assert cap.ok is True
    assert cap.condition is not None
    assert cap.condition.condition_id == "market_cap_between"
    assert cap.condition.params == {"min": 1_000_000_000, "max": 30_000_000_000}
    assert turnover.ok is True
    assert turnover.condition is not None
    assert turnover.condition.condition_id == "turnover_between"
    assert turnover.condition.params == {"min": 0.02, "max": 0.08}


def test_user_written_condition_reports_examples_for_unrecognized_text():
    result = validate_condition_text("随便乱写一个无法执行的条件")

    assert result.ok is False
    assert result.condition is None
    assert result.errors[0].code == "unrecognized_condition"
    assert "无法识别" in result.errors[0].message
    assert "收盘价站上20日均线" in result.examples
    assert condition_examples()


def test_user_written_condition_reports_supported_templates_for_unrecognized_text():
    result = validate_condition_text("随便乱写一个无法执行的条件")

    assert result.ok is False
    assert result.condition is None
    assert "收盘价站上N日均线" in result.errors[0].message
    assert "量比N日介于A到B" in result.errors[0].message
    assert "近N日主力净流入大于X万/亿" in result.errors[0].message
