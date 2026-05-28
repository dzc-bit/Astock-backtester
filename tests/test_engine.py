import pandas as pd

from astock_backtester.engine import run_backtest
from astock_backtester.indicators import add_market_heat, add_moving_average, add_returns
from astock_backtester.models import BacktestSettings, ConditionGroup, ConditionNode, ConditionOperator, StrategyConfig
from astock_backtester.sample_data import sample_daily_bars


def enriched_data():
    frame = sample_daily_bars()
    frame = add_moving_average(frame, [3])
    frame = add_returns(frame, [2])
    frame = add_market_heat(frame)
    return frame


def test_backtest_buys_next_open_after_signal(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)

    assert result.trades
    first = result.trades[0]
    assert str(first.buy_signal_date) == "2024-01-04"
    assert str(first.buy_date) == "2024-01-05"
    assert first.buy_price == 12.0
    assert any("float market cap" in reason for reason in first.buy_reason)


def test_backtest_respects_max_daily_buys(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)
    buys_by_day = {}
    for trade in result.trades:
        buys_by_day.setdefault(trade.buy_date, 0)
        buys_by_day[trade.buy_date] += 1

    assert max(buys_by_day.values()) <= 1


def test_backtest_reports_metrics_and_equity_curve(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)

    assert result.metrics.trade_count >= 1
    assert result.equity_curve
    assert result.metrics.max_drawdown_pct <= 0
    assert result.metrics.average_position_pct > 0
    assert result.metrics.max_position_pct >= result.metrics.average_position_pct


def test_preflight_reports_missing_capital_flow_when_required(basic_strategy, basic_settings):
    data = enriched_data().drop(columns=["main_net_inflow"])

    result = run_backtest(data, basic_strategy, basic_settings)

    assert any(issue.dataset == "capital_flow" and issue.severity == "error" for issue in result.preflight_issues)
    assert result.trades == []


def test_preflight_reports_empty_capital_flow_values_when_required(basic_strategy, basic_settings):
    data = enriched_data()
    data["main_net_inflow"] = float("nan")

    result = run_backtest(data, basic_strategy, basic_settings)

    assert any(issue.code == "empty_capital_flow" and issue.severity == "error" for issue in result.preflight_issues)
    assert result.trades == []


def test_market_cap_strategy_requires_non_empty_market_cap(basic_strategy, basic_settings):
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": pd.to_datetime(["2024-01-02"]),
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000],
            "is_suspended": [False],
            "listing_days": [100],
            "float_market_cap": [float("nan")],
            "main_net_inflow": [1000000.0],
        }
    )

    result = run_backtest(frame, basic_strategy, basic_settings)

    assert any(issue.code == "empty_market_cap" for issue in result.preflight_issues)


def test_backtest_filters_to_custom_stock_pool(basic_strategy, basic_settings):
    basic_settings.stock_pool = "custom"
    basic_settings.custom_symbols = ["BBB"]

    result = run_backtest(enriched_data(), basic_strategy, basic_settings)

    assert result.trades == []
    assert len(result.equity_curve) == 5


def test_backtest_excludes_st_symbols_when_enabled(basic_strategy, basic_settings):
    data = enriched_data()
    data.loc[data["symbol"] == "AAA", "is_st"] = True

    result = run_backtest(data, basic_strategy, basic_settings)

    assert result.trades == []


def test_backtest_candidate_selection_is_not_biased_to_low_symbol_codes():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    rows = []
    for symbol, close, volume, market_cap in [
        ("000001", 10.0, 1000, 2_000_000_000),
        ("300001", 11.0, 9000, 9_000_000_000),
        ("600001", 12.0, 5000, 5_000_000_000),
    ]:
        for date in dates:
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": volume,
                    "is_suspended": False,
                    "listing_days": 500,
                    "float_market_cap": market_cap,
                    "main_net_inflow": 0.0,
                    "market_rising_ratio": 1.0,
                    "volume_ratio_2d": 1.2,
                    "ma_3": close,
                }
            )
    frame = pd.DataFrame(rows)
    strategy = StrategyConfig(
        name="ranking",
        market_filters=[
            ConditionNode(id="market", condition_id="market_rising_ratio_at_least", params={"min_ratio": 0.5})
        ],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(
                        id="cap",
                        condition_id="market_cap_between",
                        params={"min": 1_000_000_000, "max": 10_000_000_000},
                    ),
                    ConditionNode(
                        id="volume",
                        condition_id="volume_ratio_between",
                        params={"window": 2, "min": 1.0, "max": 2.0},
                    ),
                ],
            )
        ],
        exit_rules=[ConditionNode(id="exit", condition_id="close_below_ma", params={"window": 3})],
    )
    settings = BacktestSettings(
        start_date=dates[0].date(),
        end_date=dates[-1].date(),
        initial_cash=100_000,
        fixed_holding_days=2,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
    )

    result = run_backtest(frame, strategy, settings)

    assert result.trades
    assert result.trades[0].symbol == "300001"


def test_backtest_emits_progress_and_open_trade_events_before_close(basic_strategy, basic_settings):
    events = []

    result = run_backtest(
        enriched_data(),
        basic_strategy,
        basic_settings,
        on_event=lambda event: events.append(event),
    )

    assert result.trades
    assert any(event["type"] == "progress" for event in events)
    opened_index = next(index for index, event in enumerate(events) if event["type"] == "trade_opened")
    closed_index = next(index for index, event in enumerate(events) if event["type"] == "trade_closed")
    assert opened_index < closed_index
    assert events[opened_index]["trade"].symbol == "AAA"
    assert events[closed_index]["trade"].symbol == "AAA"


def test_backtest_never_sells_on_the_buy_date_under_t_plus_one(basic_strategy, basic_settings):
    settings = basic_settings.model_copy(
        update={
            "fixed_holding_days": 1,
            "take_profit_pct": 0.001,
            "stop_loss_pct": -0.001,
        }
    )

    result = run_backtest(enriched_data(), basic_strategy, settings)

    assert result.trades
    same_day_exits = [
        trade for trade in result.trades
        if trade.sell_date is not None and trade.sell_date <= trade.buy_date
    ]
    assert same_day_exits == []


def test_backtest_applies_single_position_ratio_and_board_lot_rounding(basic_strategy, basic_settings):
    settings = basic_settings.model_copy(
        update={
            "position_sizing_mode": "fixed_ratio",
            "position_size_pct": 0.15,
            "slippage_rate": 0,
            "fee_rate": 0,
            "stamp_tax_rate": 0,
        }
    )

    result = run_backtest(enriched_data(), basic_strategy, settings)

    assert result.trades
    trade = result.trades[0]
    assert trade.shares == 1200
    assert trade.planned_amount == 15000
    assert trade.buy_amount == 14400
    assert trade.target_position_pct == 0.15
    assert trade.actual_position_pct == 0.144


def test_exit_rule_can_sell_when_price_breaks_prior_low():
    dates = pd.to_datetime(
        [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-08",
            "2024-01-09",
        ]
    )
    rows = []
    closes = [10.0, 10.1, 10.3, 10.4, 10.5, 9.4]
    lows = [9.8, 9.9, 10.0, 10.2, 10.3, 9.2]
    for date, close, low in zip(dates, closes, lows, strict=True):
        rows.append(
            {
                "symbol": "AAA",
                "trade_date": date,
                "open": close,
                "high": close + 0.3,
                "low": low,
                "close": close,
                "volume": 1000,
                "is_suspended": False,
                "listing_days": 500,
                "float_market_cap": 5_000_000_000,
                "main_net_inflow": 1_000_000,
                "market_rising_ratio": 1.0,
                "ma_3": close - 0.1,
            }
        )
    frame = pd.DataFrame(rows)
    strategy = StrategyConfig(
        name="prior-low-exit",
        market_filters=[],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(
                        id="cap",
                        condition_id="market_cap_between",
                        params={"min": 1_000_000_000, "max": 10_000_000_000},
                    )
                ],
            )
        ],
        exit_rules=[
            ConditionNode(
                id="exit-low",
                condition_id="breakdown_below_n_day_low",
                params={"window": 3},
                expression="突破3日最低",
            )
        ],
    )
    settings = BacktestSettings(
        start_date=dates[0].date(),
        end_date=dates[-1].date(),
        initial_cash=100_000,
        fixed_holding_days=20,
        take_profit_pct=None,
        stop_loss_pct=None,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
    )

    result = run_backtest(frame, strategy, settings)

    assert result.trades
    trade = result.trades[0]
    assert str(trade.buy_date) == "2024-01-03"
    assert str(trade.sell_date) == "2024-01-09"
    assert any("prior 3d low" in reason for reason in trade.sell_reason)


def test_extreme_chasing_strategy_can_surface_large_loss():
    dates = pd.to_datetime(
        [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-08",
        ]
    )
    rows = []
    opens = [10.0, 10.5, 12.0, 12.5, 7.0]
    closes = [10.0, 10.5, 12.0, 8.0, 7.5]
    volumes = [1000, 1200, 6000, 7000, 6500]
    for date, open_price, close, volume in zip(dates, opens, closes, volumes, strict=True):
        rows.append(
            {
                "symbol": "300999",
                "trade_date": date,
                "open": open_price,
                "high": max(open_price, close) * 1.02,
                "low": min(open_price, close) * 0.98,
                "close": close,
                "volume": volume,
                "is_suspended": False,
                "listing_days": 500,
                "float_market_cap": 2_000_000_000,
                "main_net_inflow": 0.0,
                "market_rising_ratio": 1.0,
                "ma_3": close,
                "volume_ratio_2d": 2.8,
                "return_2d": 0.2,
            }
        )
    frame = pd.DataFrame(rows)
    strategy = StrategyConfig(
        name="极端追高压力测试",
        market_filters=[],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(id="breakout", condition_id="breakout_above_n_day_high", params={"window": 2}),
                    ConditionNode(id="volume", condition_id="volume_ratio_between", params={"window": 2, "min": 2.0, "max": 5.0}),
                ],
            )
        ],
        exit_rules=[],
    )
    settings = BacktestSettings(
        start_date=dates[0].date(),
        end_date=dates[-1].date(),
        initial_cash=100_000,
        fixed_holding_days=2,
        take_profit_pct=None,
        stop_loss_pct=None,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
        slippage_rate=0,
        fee_rate=0,
        stamp_tax_rate=0,
    )

    result = run_backtest(frame, strategy, settings)

    assert result.trades
    assert result.metrics.total_return_pct < -0.3
    assert result.trades[0].pnl_pct is not None
    assert result.trades[0].pnl_pct < -0.3


def test_backtest_uses_precomputed_breakout_and_breakdown_columns():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"])
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"] * 5,
            "trade_date": dates,
            "open": [10.0, 10.2, 10.8, 10.0, 9.7],
            "high": [10.2, 10.4, 11.0, 10.1, 9.9],
            "low": [9.8, 10.0, 10.6, 9.5, 9.2],
            "close": [10.0, 10.2, 10.9, 10.0, 9.4],
            "volume": [1000, 1200, 1400, 1300, 1200],
            "is_suspended": [False] * 5,
            "listing_days": [500] * 5,
            "float_market_cap": [2_000_000_000] * 5,
            "main_net_inflow": [0.0] * 5,
            "market_rising_ratio": [1.0] * 5,
            "prior_high_2d": [float("nan"), float("nan"), 10.4, 11.0, 11.0],
            "prior_low_2d": [float("nan"), float("nan"), 9.8, 10.0, 9.5],
            "volume_ratio_2d": [float("nan"), float("nan"), 1.27, 1.0, 0.92],
        }
    )
    strategy = StrategyConfig(
        name="precomputed",
        market_filters=[],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(id="breakout", condition_id="breakout_above_n_day_high", params={"window": 2}),
                    ConditionNode(id="volume", condition_id="volume_ratio_between", params={"window": 2, "min": 1.0, "max": 2.0}),
                ],
            )
        ],
        exit_rules=[ConditionNode(id="exit-low", condition_id="breakdown_below_n_day_low", params={"window": 2})],
    )
    settings = BacktestSettings(
        start_date=dates[0].date(),
        end_date=dates[-1].date(),
        initial_cash=100_000,
        fixed_holding_days=20,
        take_profit_pct=None,
        stop_loss_pct=None,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
    )

    result = run_backtest(frame, strategy, settings)

    assert result.trades
    trade = result.trades[0]
    assert str(trade.buy_signal_date) == "2024-01-04"
    assert str(trade.buy_date) == "2024-01-05"
    assert any("prior 2d high" in reason for reason in trade.buy_reason)
    assert str(trade.sell_date) == "2024-01-08"
    assert any("prior 2d low" in reason for reason in trade.sell_reason)
