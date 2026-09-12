"""Lifecycle-aware coverage: listing/delisting windows must not report as gaps."""

from __future__ import annotations

import pandas as pd
from astock_backtester.data.cache import LocalCache
from astock_backtester.data.operations import (
    build_daily_bars_coverage,
    derive_listing_dates_from_frame,
    fetch_daily_bars_into_cache,
    refresh_symbol_lifecycle,
)
from astock_backtester.data.warehouse import Warehouse


def _bars(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover_rate",
            "float_market_cap",
            "main_net_inflow",
            "is_st",
            "is_suspended",
            "listing_days",
        ],
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def test_import_does_not_crash_when_warehouse_lifecycle_write_fails(tmp_path, monkeypatch):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    monkeypatch.setattr(warehouse, "upsert_symbol_lifecycle", lambda rows: (_ for _ in ()).throw(OSError("locked")))

    result = fetch_daily_bars_into_cache(
        cache=cache,
        fetcher=lambda symbols, start, end: _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        ),
        symbols=["AAA"],
        start_date="2024-01-02",
        end_date="2024-01-02",
        warehouse=warehouse,
    )

    assert result.imported_rows == 1


def test_fetch_daily_bars_derives_listing_dates_into_lifecycle(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)

    fetch_daily_bars_into_cache(
        cache=cache,
        fetcher=lambda symbols, start, end: _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        ),
        symbols=["AAA"],
        start_date="2024-01-02",
        end_date="2024-01-02",
        warehouse=warehouse,
    )

    lifecycle = warehouse.read_symbol_lifecycle(symbols=["AAA"])
    assert lifecycle["AAA"]["listing_date"] == "2023-10-04"
    assert lifecycle["AAA"]["status"] == "listed"


def test_coverage_clips_expected_window_to_symbol_lifecycle(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        _bars(
            [
                # NEW lists mid-window: 2024-01-02 has no rows and is not a gap.
                ("NEW", "2024-01-03", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 1),
                ("NEW", "2024-01-04", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 2),
                # DELIST stops trading after 2024-01-03; later window days are not gaps.
                ("DELIST", "2024-01-02", 20.0, 21.0, 19.0, 20.5, 900, 0.2, 20_000_000_000.0, 1_000_000.0, False, False, 120),
                ("DELIST", "2024-01-03", 20.2, 21.2, 19.2, 20.7, 800, 0.2, 20_100_000_000.0, 1_100_000.0, False, False, 121),
            ]
        )
    )
    warehouse.upsert_symbol_lifecycle(
        [
            {"symbol": "NEW", "listing_date": "2024-01-03", "status": "listed"},
            {"symbol": "DELIST", "listing_date": "2024-01-02", "delisted_date": "2024-01-03", "status": "delisted"},
        ]
    )

    details = build_daily_bars_coverage(
        cache,
        warehouse=warehouse,
        symbols=["NEW", "DELIST"],
        start_date="2024-01-02",
        end_date="2024-01-05",
    )

    items = {item.symbol: item for item in details.items}
    new_item = items["NEW"]
    assert [day.isoformat() for day in new_item.missing_trade_dates] == ["2024-01-05"]
    assert new_item.listing_date.isoformat() == "2024-01-03"
    assert new_item.delisted_date is None
    assert new_item.lifecycle_status == "listed"

    delist_item = items["DELIST"]
    assert [day.isoformat() for day in delist_item.missing_trade_dates] == []
    assert delist_item.delisted_date.isoformat() == "2024-01-03"
    assert delist_item.lifecycle_status == "delisted"


def test_coverage_without_lifecycle_records_keeps_legacy_missing_window(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        _bars(
            [
                ("NEW", "2024-01-03", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 1),
            ]
        )
    )

    details = build_daily_bars_coverage(
        cache,
        warehouse=warehouse,
        symbols=["NEW"],
        start_date="2024-01-02",
        end_date="2024-01-04",
    )

    item = details.items[0]
    assert [day.isoformat() for day in item.missing_trade_dates] == ["2024-01-02", "2024-01-04"]
    assert item.listing_date is None
    assert item.lifecycle_status == "unknown"


def test_derive_listing_dates_from_frame_uses_listing_days_column():
    frame = _bars(
        [
            ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ("AAA", "2024-01-03", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 91),
            ("BBB", "2024-01-03", 20.0, 21.0, 19.0, 20.5, 900, 0.2, 20_000_000_000.0, 1_000_000.0, False, False, 9999),
        ]
    )

    listings = derive_listing_dates_from_frame(frame)

    assert listings == {"AAA": "2023-10-04"}


def test_refresh_symbol_lifecycle_marks_absent_stale_symbols_delisted(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        _bars(
            [
                ("600001", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("DEAD", "2020-06-01", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        )
    )

    summary = refresh_symbol_lifecycle(
        warehouse,
        {"600001": "1991-04-03", "600002": None},
        min_current_symbols=2,
        stale_delist_days=30,
    )

    assert summary["status"] == "ok"
    lifecycle = warehouse.read_symbol_lifecycle()
    assert lifecycle["600001"]["listing_date"] == "1991-04-03"
    assert lifecycle["600002"]["listing_date"] is None
    assert lifecycle["DEAD"]["status"] == "delisted"
    assert lifecycle["DEAD"]["delisted_date"] == "2020-06-01"


def test_refresh_symbol_lifecycle_never_delists_from_a_suspiciously_small_source(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        _bars(
            [
                ("DEAD", "2020-06-01", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        )
    )

    summary = refresh_symbol_lifecycle(warehouse, {"600001": "1991-04-03"}, min_current_symbols=1000)

    assert summary["status"] == "ok"
    assert warehouse.read_delisted_symbols() == set()
    assert warehouse.read_symbol_lifecycle()["600001"]["listing_date"] == "1991-04-03"


def test_sync_pool_excludes_delisted_symbols(tmp_path):
    from astock_backtester.service import DataServiceState

    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        _bars(
            [
                ("600001", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("DEAD", "2020-06-01", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        )
    )
    warehouse.upsert_symbol_lifecycle(
        [{"symbol": "DEAD", "delisted_date": "2020-06-01", "status": "delisted"}]
    )
    state = DataServiceState(str(tmp_path), 0)

    symbols = state.sync_symbols("2024-01-01", "2024-01-31")

    assert symbols == ["600001"]
