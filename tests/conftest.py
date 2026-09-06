from datetime import date

import pytest
from astock_backtester.models import (
    BacktestSettings,
    ConditionGroup,
    ConditionNode,
    ConditionOperator,
    StrategyConfig,
)


@pytest.fixture
def basic_strategy() -> StrategyConfig:
    return StrategyConfig(
        name="basic",
        market_filters=[
            ConditionNode(
                id="market-hot",
                condition_id="market_rising_ratio_at_least",
                params={"min_ratio": 0.5},
            )
        ],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(
                        id="cap",
                        condition_id="market_cap_between",
                        params={"min": 1_000_000_000, "max": 30_000_000_000},
                    ),
                    ConditionNode(
                        id="flow",
                        condition_id="capital_flow_n_day_sum_at_least",
                        params={"window": 3, "min": 3_000_000},
                    ),
                ],
            )
        ],
        exit_rules=[
            ConditionNode(
                id="exit-ma",
                condition_id="close_below_ma",
                params={"window": 3},
            )
        ],
    )


@pytest.fixture
def basic_settings() -> BacktestSettings:
    return BacktestSettings(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 12),
        initial_cash=100_000,
        fixed_holding_days=3,
        take_profit_pct=0.08,
        stop_loss_pct=-0.05,
        max_positions=2,
        max_daily_buys=1,
    )
