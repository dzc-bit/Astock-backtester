from datetime import date

import pytest
from pydantic import ValidationError

from astock_backtester.models import (
    BacktestSettings,
    ConditionGroup,
    ConditionNode,
    ConditionOperator,
    DatasetCoverage,
    StrategyConfig,
)


def make_backtest_settings(**overrides):
    settings = {
        "start_date": date(2024, 1, 2),
        "end_date": date(2024, 1, 10),
        "initial_cash": 100_000,
    }
    settings.update(overrides)
    return BacktestSettings(**settings)


def test_strategy_config_rejects_empty_entry_groups():
    with pytest.raises(ValidationError):
        StrategyConfig(
            name="bad",
            market_filters=[],
            entry_groups=[],
            exit_rules=[],
            score_threshold=None,
        )


def test_condition_node_keeps_signal_date_boundary_metadata():
    node = ConditionNode(
        id="cap-small",
        condition_id="market_cap_between",
        enabled=True,
        params={"min": 2_000_000_000, "max": 20_000_000_000},
        weight=15.0,
        data_lag_days=0,
    )

    assert node.condition_id == "market_cap_between"
    assert node.params["max"] == 20_000_000_000
    assert node.data_lag_days == 0


def test_backtest_settings_defaults_to_conservative_execution():
    settings = BacktestSettings(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 10),
        initial_cash=100_000,
    )

    assert settings.conservative_execution is True
    assert settings.buy_price == "next_open"
    assert settings.limit_up_blocks_buy is True
    assert settings.limit_down_blocks_sell is True
    assert settings.stock_pool == "all"
    assert settings.custom_symbols == []


def test_backtest_settings_rejects_negative_fee_rate():
    with pytest.raises(ValidationError):
        make_backtest_settings(fee_rate=-0.0001)


def test_backtest_settings_rejects_negative_stamp_tax_rate():
    with pytest.raises(ValidationError):
        make_backtest_settings(stamp_tax_rate=-0.0001)


def test_backtest_settings_rejects_negative_slippage_rate():
    with pytest.raises(ValidationError):
        make_backtest_settings(slippage_rate=-0.0001)


def test_backtest_settings_rejects_negative_min_listing_days():
    with pytest.raises(ValidationError):
        make_backtest_settings(min_listing_days=-1)


def test_condition_node_rejects_negative_data_lag_days():
    with pytest.raises(ValidationError):
        ConditionNode(
            id="cap-small",
            condition_id="market_cap_between",
            data_lag_days=-1,
        )


def test_condition_group_rejects_empty_conditions():
    with pytest.raises(ValidationError):
        ConditionGroup(id="entry", operator=ConditionOperator.AND, conditions=[])


def test_dataset_coverage_tracks_market_cap_and_capital_flow():
    coverage = DatasetCoverage(
        dataset="capital_flow",
        symbols=12,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 10),
        missing_rows=3,
    )

    assert coverage.dataset == "capital_flow"
    assert coverage.missing_rows == 3


def test_condition_operator_accepts_and_or_score():
    assert ConditionOperator.AND.value == "and"
    assert ConditionOperator.OR.value == "or"
    assert ConditionOperator.SCORE.value == "score"


def test_backtest_settings_accepts_controlled_stock_pool_and_custom_symbols():
    settings = make_backtest_settings(stock_pool="custom", custom_symbols=["600519", "000001"])

    assert settings.stock_pool == "custom"
    assert settings.custom_symbols == ["600519", "000001"]


def test_custom_stock_pool_requires_symbols():
    with pytest.raises(ValidationError):
        make_backtest_settings(stock_pool="custom", custom_symbols=[])
