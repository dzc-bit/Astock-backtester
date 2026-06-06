import pandas as pd
import pytest

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


def simple_market_cap_strategy() -> StrategyConfig:
    return StrategyConfig(
        name="simple",
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
        exit_rules=[],
    )


def backtest_row(
    trade_date: str,
    *,
    symbol: str = "000001",
    open_price: float = 10.0,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    pre_close: float | None = None,
    is_st: bool = False,
) -> dict:
    close_price = close if close is not None else open_price
    row = {
        "symbol": symbol,
        "trade_date": pd.Timestamp(trade_date),
        "open": open_price,
        "high": high if high is not None else max(open_price, close_price),
        "low": low if low is not None else min(open_price, close_price),
        "close": close_price,
        "volume": 1000,
        "is_suspended": False,
        "listing_days": 500,
        "float_market_cap": 2_000_000_000,
        "main_net_inflow": 0.0,
        "is_st": is_st,
    }
    if pre_close is not None:
        row["pre_close"] = pre_close
    return row


def test_backtest_buys_next_open_after_signal(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)

    assert result.trades
    first = result.trades[0]
    assert str(first.buy_signal_date) == "2024-01-04"
    assert str(first.buy_date) == "2024-01-05"
    assert first.buy_price == pytest.approx(12.0 * (1 + basic_settings.slippage_rate))
    assert any("float market cap" in reason for reason in first.buy_reason)


def test_backtest_respects_max_daily_buys(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)
    buys_by_day = {}
    for trade in result.trades:
        buys_by_day.setdefault(trade.buy_date, 0)
        buys_by_day[trade.buy_date] += 1

    assert max(buys_by_day.values()) <= 1


def test_backtest_result_reports_latest_trade_day_strategy_matches_without_daily_buy_limit():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    rows = []
    for symbol, name, close, volume, volume_ratio, change_pct in [
        ("AAA", "Alpha", 10.0, 1000, 1.1, 0.01),
        ("BBB", "Bravo", 11.0, 9000, 1.5, 0.03),
        ("CCC", "Charlie", 12.0, 5000, 1.2, -0.01),
    ]:
        for trade_date in dates:
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "trade_date": trade_date,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "change_pct": change_pct,
                    "volume": volume,
                    "volume_ratio_2d": volume_ratio,
                    "is_suspended": False,
                    "listing_days": 500,
                    "float_market_cap": 2_000_000_000,
                    "main_net_inflow": 0.0,
                }
            )
    frame = pd.DataFrame(rows)
    strategy = StrategyConfig(
        name="latest-matches",
        market_filters=[],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(
                        id="cap",
                        condition_id="market_cap_between",
                        params={"min": 1_000_000_000, "max": 3_000_000_000},
                    )
                ],
            )
        ],
        exit_rules=[],
    )
    settings = BacktestSettings(
        start_date=dates[0].date(),
        end_date=dates[-1].date(),
        initial_cash=100_000,
        max_positions=10,
        max_daily_buys=1,
        min_listing_days=0,
    )

    events = []

    result = run_backtest(frame, strategy, settings, on_event=lambda event: events.append(event))

    opened_trades = [event["trade"] for event in events if event["type"] == "trade_opened"]
    assert len(opened_trades) == 1
    assert opened_trades[0].symbol == "BBB"
    assert result.latest_strategy_matches is not None
    assert str(result.latest_strategy_matches.signal_date) == "2024-01-03"
    assert str(result.latest_strategy_matches.trade_date) == "2024-01-03"
    assert [match.symbol for match in result.latest_strategy_matches.matches] == ["BBB", "CCC", "AAA"]

    first_match = result.latest_strategy_matches.matches[0]
    assert first_match.name == "Bravo"
    assert str(first_match.signal_date) == "2024-01-03"
    assert str(first_match.trade_date) == "2024-01-03"
    assert first_match.close == 11.0
    assert first_match.change_pct == 0.03
    assert first_match.rank_score == 1.5
    assert any("float market cap" in reason for reason in first_match.reasons)


def test_backtest_result_reports_empty_matches_for_latest_trade_day_without_reusing_older_hits():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    rows = []
    for trade_date, market_cap in [
        (dates[0], 2_000_000_000),
        (dates[1], 2_000_000_000),
        (dates[2], 9_000_000_000),
    ]:
        rows.append(
            {
                "symbol": "AAA",
                "name": "Alpha",
                "trade_date": trade_date,
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.0,
                "change_pct": 0.01,
                "volume": 1000,
                "is_suspended": False,
                "listing_days": 500,
                "float_market_cap": market_cap,
                "main_net_inflow": 0.0,
            }
        )
    frame = pd.DataFrame(rows)
    strategy = StrategyConfig(
        name="latest-empty-matches",
        market_filters=[],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(
                        id="cap",
                        condition_id="market_cap_between",
                        params={"min": 1_000_000_000, "max": 3_000_000_000},
                    )
                ],
            )
        ],
        exit_rules=[],
    )
    settings = BacktestSettings(
        start_date=dates[0].date(),
        end_date=dates[-1].date(),
        initial_cash=100_000,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
    )

    result = run_backtest(frame, strategy, settings)

    assert result.latest_strategy_matches is not None
    assert str(result.latest_strategy_matches.signal_date) == "2024-01-04"
    assert result.latest_strategy_matches.matches == []


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


def test_annualized_return_uses_equity_curve_date_span_not_total_return():
    frame = pd.DataFrame(
        [
            backtest_row("2024-01-02", close=10.0),
            backtest_row("2024-01-03", open_price=10.0, close=10.0),
            backtest_row("2024-01-22", open_price=12.0, close=12.0),
        ]
    )
    settings = BacktestSettings(
        start_date=pd.Timestamp("2024-01-02").date(),
        end_date=pd.Timestamp("2024-01-22").date(),
        initial_cash=100_000,
        fixed_holding_days=20,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
        slippage_rate=0,
        fee_rate=0,
        stamp_tax_rate=0,
    )

    result = run_backtest(frame, simple_market_cap_strategy(), settings)

    assert result.metrics.total_return_pct == pytest.approx(0.2)
    assert result.metrics.annualized_return_pct == pytest.approx((1.2 ** (365 / 20)) - 1)
    assert result.metrics.annualized_return_pct != result.metrics.total_return_pct


def test_limit_up_blocks_next_day_buy_and_records_chinese_reason():
    frame = pd.DataFrame(
        [
            backtest_row("2024-01-02", close=10.0),
            backtest_row("2024-01-03", open_price=11.0, high=11.0, low=11.0, close=11.0, pre_close=10.0),
            backtest_row("2024-01-04", open_price=12.0, close=12.0, pre_close=11.0),
        ]
    )
    events = []
    settings = BacktestSettings(
        start_date=pd.Timestamp("2024-01-02").date(),
        end_date=pd.Timestamp("2024-01-05").date(),
        initial_cash=100_000,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
        slippage_rate=0,
        fee_rate=0,
        stamp_tax_rate=0,
        limit_up_blocks_buy=True,
    )

    result = run_backtest(frame, simple_market_cap_strategy(), settings, on_event=lambda event: events.append(event))

    assert result.trades == []
    blocked_events = [event for event in events if event["type"] == "trade_blocked"]
    assert blocked_events
    assert "涨停" in blocked_events[0]["trade"].blocked_reason


def test_missing_pre_close_does_not_guess_limit_up_block():
    frame = pd.DataFrame(
        [
            backtest_row("2024-01-02", close=10.0),
            backtest_row("2024-01-03", open_price=99.0, high=99.0, low=99.0, close=99.0),
            backtest_row("2024-01-04", open_price=99.0, close=99.0),
            backtest_row("2024-01-05", open_price=99.0, close=99.0),
        ]
    )
    settings = BacktestSettings(
        start_date=pd.Timestamp("2024-01-02").date(),
        end_date=pd.Timestamp("2024-01-04").date(),
        initial_cash=100_000,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
        slippage_rate=0,
        fee_rate=0,
        stamp_tax_rate=0,
        limit_up_blocks_buy=True,
        fixed_holding_days=1,
    )

    result = run_backtest(frame, simple_market_cap_strategy(), settings)

    assert result.trades
    assert result.trades[0].buy_price == 99.0


def test_limit_down_blocks_sell_keeps_position_and_reports_reason():
    frame = pd.DataFrame(
        [
            backtest_row("2024-01-02", close=10.0),
            backtest_row("2024-01-03", open_price=10.0, close=10.0, pre_close=10.0),
            backtest_row("2024-01-04", open_price=9.0, high=9.0, low=9.0, close=9.0, pre_close=10.0),
            backtest_row("2024-01-05", open_price=9.5, close=9.5, pre_close=9.0),
        ]
    )
    events = []
    settings = BacktestSettings(
        start_date=pd.Timestamp("2024-01-02").date(),
        end_date=pd.Timestamp("2024-01-05").date(),
        initial_cash=100_000,
        fixed_holding_days=1,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
        slippage_rate=0,
        fee_rate=0,
        stamp_tax_rate=0,
        limit_down_blocks_sell=True,
    )

    result = run_backtest(frame, simple_market_cap_strategy(), settings, on_event=lambda event: events.append(event))

    assert result.trades
    trade = result.trades[0]
    assert str(trade.sell_date) == "2024-01-05"
    assert trade.sell_price == 9.5
    blocked_events = [event for event in events if event["type"] == "trade_blocked"]
    assert blocked_events
    assert "跌停" in blocked_events[0]["trade"].blocked_reason


def test_conservative_execution_records_actual_buy_and_sell_prices_and_amounts():
    frame = pd.DataFrame(
        [
            backtest_row("2024-01-02", close=10.0),
            backtest_row("2024-01-03", open_price=10.0, high=11.0, low=9.0, close=10.5, pre_close=10.0),
            backtest_row("2024-01-04", open_price=12.0, high=12.5, low=11.5, close=12.0, pre_close=10.5),
        ]
    )
    settings = BacktestSettings(
        start_date=pd.Timestamp("2024-01-02").date(),
        end_date=pd.Timestamp("2024-01-04").date(),
        initial_cash=100_000,
        fixed_holding_days=1,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
        slippage_rate=0.01,
        fee_rate=0.001,
        stamp_tax_rate=0.002,
        conservative_execution=True,
    )

    result = run_backtest(frame, simple_market_cap_strategy(), settings)

    trade = result.trades[0]
    assert trade.buy_price == pytest.approx(10.1)
    assert trade.sell_price == pytest.approx(11.88)
    assert trade.buy_amount == pytest.approx(trade.buy_price * trade.shares * 1.001)
    assert trade.sell_amount == pytest.approx(trade.sell_price * trade.shares * (1 - 0.001 - 0.002))
    assert trade.pnl == pytest.approx(trade.sell_amount - trade.buy_amount)
    assert trade.pnl_pct == pytest.approx(trade.sell_amount / trade.buy_amount - 1)


def test_take_profit_uses_trigger_price_instead_of_open_when_not_conservative():
    frame = pd.DataFrame(
        [
            backtest_row("2024-01-02", close=10.0),
            backtest_row("2024-01-03", open_price=10.0, high=10.1, low=9.9, close=10.0, pre_close=10.0),
            backtest_row("2024-01-04", open_price=10.1, high=11.0, low=10.0, close=10.5, pre_close=10.0),
        ]
    )
    settings = BacktestSettings(
        start_date=pd.Timestamp("2024-01-02").date(),
        end_date=pd.Timestamp("2024-01-04").date(),
        initial_cash=100_000,
        fixed_holding_days=20,
        take_profit_pct=0.08,
        max_positions=1,
        max_daily_buys=1,
        min_listing_days=0,
        slippage_rate=0,
        fee_rate=0,
        stamp_tax_rate=0,
        conservative_execution=False,
    )

    result = run_backtest(frame, simple_market_cap_strategy(), settings)

    trade = result.trades[0]
    assert trade.sell_price == pytest.approx(10.8)
    assert any("止盈触发" in reason for reason in trade.sell_reason)
