from datetime import date

import pytest
from pydantic import ValidationError

from astock_backtester.models import (
    BacktestSettings,
    ClsFinanceAnchor,
    ClsFinanceEmotion,
    ClsFinancePoolItem,
    ClsFinanceResponse,
    ClsFinanceTlinePoint,
    ConditionGroup,
    ConditionNode,
    ConditionOperator,
    DatasetCoverage,
    MarketBreadth,
    StrategyConfig,
    SyncJobStatus,
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
    assert settings.position_sizing_mode == "equal_slots"
    assert settings.position_size_pct == 0.2


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


def test_market_breadth_keeps_optional_cls_distribution():
    breadth = MarketBreadth(
        up=3322,
        down=2049,
        flat=156,
        total=5527,
        source="cls-quote-breadth",
        distribution={"up_10": 291, "flat": 156, "down_10": 34, "suspend": 12},
    )

    assert breadth.distribution["up_10"] == 291
    assert breadth.distribution["suspend"] == 12


def test_cls_finance_response_serializes_market_board_data():
    response = ClsFinanceResponse(
        updated_at="2026-06-09T09:31:00+08:00",
        source="cls-finance",
        source_url="https://www.cls.cn/finance",
        preclose_px=3959.337,
        tline=[ClsFinanceTlinePoint(date=20260609, minute=930, last_px=3977.539, change=0.0047)],
        anchors=[
            ClsFinanceAnchor(
                code="cls80025",
                name="PCB",
                article_id=2394344,
                c_time="2026-06-09 09:31:30",
                direction="up",
                url="https://www.cls.cn/plate?code=cls80025",
            )
        ],
        emotion=ClsFinanceEmotion(
            market_degree=56.0,
            market_degree_source="ths-market-summary",
            market_degree_label="同花顺大盘评级",
            breadth=MarketBreadth(up=3322, down=2049, flat=156, total=5527, source="cls-finance-emotion"),
            up_limit=130,
            open_limit=25,
            performance="1.74%",
        ),
        up_pool=[
            ClsFinancePoolItem(
                symbol="601869",
                name="长飞光纤",
                change_pct=0.1,
                last=484.33,
                time="2026-06-09 13:34:47",
                reason="光纤",
                limit_up_days=1,
            )
        ],
    )

    payload = response.model_dump(mode="json")

    assert payload["source"] == "cls-finance"
    assert payload["anchors"][0]["name"] == "PCB"
    assert payload["emotion"]["market_degree"] == 56.0
    assert payload["emotion"]["market_degree_source"] == "ths-market-summary"
    assert payload["emotion"]["market_degree_label"] == "同花顺大盘评级"
    assert payload["up_pool"][0]["symbol"] == "601869"


def test_sync_job_status_tracks_batch_progress_and_cancellation():
    status = SyncJobStatus(
        job_id="job-flow",
        mode="capital_flow_backfill",
        status="cancelled",
        total_symbols=5,
        completed_symbols=2,
        failed_symbols=1,
        processed_symbols=3,
        imported_rows=12,
        returned_rows=18,
        filled_missing_rows=7,
        skipped_symbols=1,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        last_error="000003: remote disconnected",
        recent_failures=[{"symbol": "000003", "reason": "remote disconnected"}],
    )

    assert status.status == "cancelled"
    assert status.processed_symbols == 3
    assert status.returned_rows == 18
    assert status.filled_missing_rows == 7
    assert status.skipped_symbols == 1
    assert status.last_error == "000003: remote disconnected"


def test_condition_operator_accepts_and_or_score():
    assert ConditionOperator.AND.value == "and"
    assert ConditionOperator.OR.value == "or"
    assert ConditionOperator.SCORE.value == "score"


def test_backtest_settings_accepts_controlled_stock_pool_and_custom_symbols():
    settings = make_backtest_settings(stock_pool="custom", custom_symbols=["600519", "000001"])

    assert settings.stock_pool == "custom"
    assert settings.custom_symbols == ["600519", "000001"]


def test_backtest_settings_accepts_position_sizing_fields():
    settings = make_backtest_settings(position_sizing_mode="equal_slots", position_size_pct=0.25)

    assert settings.position_sizing_mode == "equal_slots"
    assert settings.position_size_pct == 0.25


def test_backtest_settings_rejects_invalid_position_size_pct():
    with pytest.raises(ValidationError):
        make_backtest_settings(position_size_pct=0)

    with pytest.raises(ValidationError):
        make_backtest_settings(position_size_pct=1.2)


def test_custom_stock_pool_requires_symbols():
    with pytest.raises(ValidationError):
        make_backtest_settings(stock_pool="custom", custom_symbols=[])
