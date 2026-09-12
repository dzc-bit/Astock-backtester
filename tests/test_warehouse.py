from __future__ import annotations

import pandas as pd
import pytest
from astock_backtester.data.warehouse import Warehouse
from pyarrow.lib import ArrowInvalid


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600519", "600519", "000001"],
            "trade_date": ["2015-01-05", "2016-01-04", "2016-01-04"],
            "open": [10.0, 11.0, 8.0],
            "high": [10.5, 11.5, 8.5],
            "low": [9.8, 10.8, 7.9],
            "close": [10.2, 11.2, 8.1],
            "volume": [1000, 1200, 900],
            "amount": [10200.0, 13440.0, 7290.0],
            "float_market_cap": [1000000000.0, 1100000000.0, 800000000.0],
            "total_market_cap": [1200000000.0, 1300000000.0, 900000000.0],
        }
    )


def test_warehouse_writes_year_partitions_and_reads_filtered_data(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    assert (tmp_path / "warehouse" / "daily_bars" / "year=2015" / "daily_bars.parquet").exists()
    assert (tmp_path / "warehouse" / "daily_bars" / "year=2016" / "daily_bars.parquet").exists()

    result = warehouse.read_daily_bars(
        symbols=["600519"],
        start_date="2016-01-01",
        end_date="2016-12-31",
    )

    assert result["symbol"].tolist() == ["600519"]
    assert result["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2016-01-04"]


def test_warehouse_reads_only_year_partitions_overlapping_requested_dates(tmp_path, monkeypatch):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    read_paths = []
    original_read_parquet = pd.read_parquet

    def tracking_read_parquet(path, *args, **kwargs):
        read_paths.append(str(path))
        return original_read_parquet(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", tracking_read_parquet)

    result = warehouse.read_daily_bars(start_date="2016-01-01", end_date="2016-12-31")

    assert set(result["symbol"]) == {"000001", "600519"}
    assert all("year=2016" in path for path in read_paths)
    assert read_paths


def test_warehouse_safe_read_parquet_only_treats_missing_files_as_empty(tmp_path, monkeypatch):
    warehouse = Warehouse(tmp_path)

    assert warehouse._safe_read_parquet(tmp_path / "missing.parquet").empty

    def broken_read_parquet(*_args, **_kwargs):
        raise OSError("corrupt parquet")

    monkeypatch.setattr(pd, "read_parquet", broken_read_parquet)

    with pytest.raises(OSError, match="corrupt parquet"):
        warehouse._safe_read_parquet(tmp_path / "corrupt.parquet")


def test_warehouse_reads_daily_symbols_without_dropping_symbols_missing_recent_dates(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001", "000002", "000003"],
                "trade_date": ["2026-06-18", "2026-06-17", "2026-06-18"],
                "open": [1.0, 2.0, float("nan")],
                "high": [1.0, 2.0, float("nan")],
                "low": [1.0, 2.0, float("nan")],
                "close": [1.0, 2.0, float("nan")],
                "volume": [1, 1, 1],
            }
        )
    )

    all_symbols = warehouse.read_daily_symbols(require_ohlc=True)
    latest_symbols = warehouse.read_daily_symbols(
        start_date="2026-06-18",
        end_date="2026-06-18",
        require_ohlc=True,
    )

    assert all_symbols == ["000001", "000002"]
    assert latest_symbols == ["000001"]


def test_warehouse_merges_rows_by_symbol_and_trade_date(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["600519"],
                "trade_date": ["2016-01-04"],
                "open": [12.0],
                "high": [12.5],
                "low": [11.8],
                "close": [12.2],
                "volume": [2200],
                "amount": [26840.0],
                "float_market_cap": [1500000000.0],
                "total_market_cap": [1600000000.0],
            }
        )
    )

    result = warehouse.read_daily_bars(symbols=["600519"], start_date="2016-01-04", end_date="2016-01-04")

    assert len(result) == 1
    assert result.loc[0, "close"] == 12.2
    assert result.loc[0, "float_market_cap"] == 1500000000.0


def test_warehouse_coverage_reports_daily_and_market_cap(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["daily_bars"].symbols == 2
    assert coverage["daily_bars"].start_date.isoformat() == "2015-01-05"
    assert coverage["market_cap"].missing_rows == 0


def test_warehouse_coverage_uses_partition_stats_without_full_read(tmp_path, monkeypatch):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    def fail_full_read(*args, **kwargs):
        raise AssertionError("coverage should not load the full warehouse")

    monkeypatch.setattr(warehouse, "read_daily_bars", fail_full_read)

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["daily_bars"].symbols == 2
    assert coverage["daily_bars"].start_date.isoformat() == "2015-01-05"
    assert coverage["daily_bars"].end_date.isoformat() == "2016-01-04"
    assert coverage["daily_bars"].missing_rows == 0
    assert coverage["market_cap"].symbols == 2
    assert coverage["market_cap"].missing_rows == 0
    assert coverage["capital_flow"].symbols == 0
    assert coverage["capital_flow"].missing_rows == 3


def test_warehouse_coverage_counts_latest_daily_rows_missing_from_known_symbols(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001", "000002", "000003", "000001"],
                "trade_date": ["2026-06-05", "2026-06-05", "2026-06-05", "2026-06-08"],
                "open": [10.0, 10.0, 10.0, 10.2],
                "high": [10.5, 10.5, 10.5, 10.4],
                "low": [9.8, 9.8, 9.8, 10.0],
                "close": [10.2, 10.2, 10.2, 10.3],
                "volume": [1000, 1000, 1000, 1200],
            }
        )
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["daily_bars"].symbols == 3
    assert coverage["daily_bars"].end_date.isoformat() == "2026-06-08"
    assert coverage["daily_bars"].missing_rows == 2


def test_warehouse_separates_capital_flow_only_rows_from_daily_bar_coverage(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "trade_date": ["2026-06-05", "2026-06-05"],
                "open": [10.0, float("nan")],
                "high": [10.5, float("nan")],
                "low": [9.8, float("nan")],
                "close": [10.2, float("nan")],
                "volume": [1000, 0],
                "main_net_inflow": [float("nan"), 1_000_000.0],
            }
        )
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}
    tradable = warehouse.read_daily_bars(require_ohlc=True)
    all_rows = warehouse.read_daily_bars()

    assert coverage["daily_bars"].symbols == 1
    assert coverage["daily_bars"].missing_rows == 0
    assert coverage["capital_flow"].symbols == 1
    assert coverage["capital_flow"].missing_rows == 1
    assert tradable["symbol"].tolist() == ["000001"]
    assert all_rows["symbol"].tolist() == ["000001", "000002"]


def test_warehouse_coverage_ignores_known_public_capital_flow_source_gaps(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001", "000001"],
                "trade_date": ["2019-04-04", "2019-04-08"],
                "open": [10.0, 10.0],
                "high": [10.5, 10.5],
                "low": [9.8, 9.8],
                "close": [10.2, 10.2],
                "volume": [1000, 1000],
                "main_net_inflow": [float("nan"), float("nan")],
            }
        )
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["capital_flow"].missing_rows == 1


def test_warehouse_coverage_ignores_rows_before_symbol_capital_flow_source_start(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["920001", "920001", "920001"],
                "trade_date": ["2021-11-12", "2021-11-15", "2021-11-16"],
                "open": [10.0, 10.0, 10.0],
                "high": [10.5, 10.5, 10.5],
                "low": [9.8, 9.8, 9.8],
                "close": [10.2, 10.2, 10.2],
                "volume": [1000, 1000, 1000],
                "main_net_inflow": [float("nan"), 1_000_000.0, float("nan")],
            }
        )
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["capital_flow"].missing_rows == 1


def test_warehouse_coverage_ignores_late_2021_public_source_start_gap(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["688272", "688272", "688272"],
                "trade_date": ["2021-12-28", "2021-12-29", "2021-12-30"],
                "open": [10.0, 10.0, 10.0],
                "high": [10.5, 10.5, 10.5],
                "low": [9.8, 9.8, 9.8],
                "close": [10.2, 10.2, 10.2],
                "volume": [1000, 1000, 1000],
                "main_net_inflow": [float("nan"), 1_000_000.0, float("nan")],
            }
        )
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["capital_flow"].missing_rows == 1


def test_warehouse_coverage_uses_global_capital_flow_start_across_partitions(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["688272", "688272", "688272"],
                "trade_date": ["2020-12-31", "2021-12-28", "2021-12-29"],
                "open": [10.0, 10.0, 10.0],
                "high": [10.5, 10.5, 10.5],
                "low": [9.8, 9.8, 9.8],
                "close": [10.2, 10.2, 10.2],
                "volume": [1000, 1000, 1000],
                "main_net_inflow": [float("nan"), float("nan"), 1_000_000.0],
            }
        )
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["capital_flow"].missing_rows == 0


def test_warehouse_coverage_ignores_short_listing_lag_but_counts_later_capital_flow_gaps(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["603027", "603027", "603027", "000001", "000001"],
                "trade_date": ["2016-03-07", "2016-03-08", "2016-03-09", "2015-01-05", "2015-01-06"],
                "open": [10.0, 10.0, 10.0, 9.0, 9.1],
                "high": [10.5, 10.5, 10.5, 9.5, 9.6],
                "low": [9.8, 9.8, 9.8, 8.8, 8.9],
                "close": [10.2, 10.2, 10.2, 9.2, 9.3],
                "volume": [1000, 1000, 1000, 900, 900],
                "main_net_inflow": [float("nan"), 1_000_000.0, float("nan"), float("nan"), 500_000.0],
            }
        )
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["capital_flow"].missing_rows == 2


def test_warehouse_reads_latest_daily_bars_from_recent_partitions(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    latest = warehouse.read_latest_daily_bars(days=1)

    assert latest["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2016-01-04", "2016-01-04"]
    assert set(latest["symbol"]) == {"000001", "600519"}


def test_warehouse_latest_daily_bars_ignore_capital_flow_only_rows(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "trade_date": ["2026-06-05", "2026-06-05"],
                "open": [10.0, float("nan")],
                "high": [10.5, float("nan")],
                "low": [9.8, float("nan")],
                "close": [10.2, float("nan")],
                "volume": [1000, 0],
                "main_net_inflow": [float("nan"), 1_000_000.0],
            }
        )
    )

    latest = warehouse.read_latest_daily_bars(days=1)

    assert latest["symbol"].tolist() == ["000001"]
    assert latest[["open", "high", "low", "close"]].notna().all().all()


def test_warehouse_surfaces_corrupt_recent_partition_for_latest_and_coverage(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())
    corrupt_path = tmp_path / "warehouse" / "daily_bars" / "year=2026" / "daily_bars.parquet"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"not a parquet file")

    with pytest.raises(ArrowInvalid, match="Parquet magic bytes"):
        warehouse.read_latest_daily_bars(days=1)
    with pytest.raises(ArrowInvalid, match="Parquet magic bytes"):
        warehouse.read_daily_symbols(require_ohlc=True)
    with pytest.raises(ArrowInvalid, match="Parquet magic bytes"):
        warehouse.coverage()


def test_warehouse_does_not_overwrite_corrupt_partition_when_new_rows_arrive(tmp_path):
    warehouse = Warehouse(tmp_path)
    corrupt_path = tmp_path / "warehouse" / "daily_bars" / "year=2026" / "daily_bars.parquet"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"not a parquet file")

    with pytest.raises(ArrowInvalid, match="Parquet magic bytes"):
        warehouse.write_daily_bars(
            pd.DataFrame(
                {
                    "symbol": ["000001"],
                    "trade_date": ["2026-05-26"],
                    "open": [10.0],
                    "high": [10.5],
                    "low": [9.8],
                    "close": [10.2],
                    "volume": [1000],
                }
            )
        )

    assert corrupt_path.read_bytes() == b"not a parquet file"


def test_warehouse_symbol_lifecycle_roundtrip_and_delisted_lookup(tmp_path):
    warehouse = Warehouse(tmp_path)

    assert warehouse.read_symbol_lifecycle() == {}
    assert warehouse.read_delisted_symbols() == set()

    written = warehouse.upsert_symbol_lifecycle(
        [
            {"symbol": "600519", "listing_date": "2001-08-27", "status": "listed"},
            {"symbol": "000002", "listing_date": "1991-01-29", "delisted_date": "2026-05-30", "status": "delisted"},
            {"symbol": "600001", "listing_date": "2026-06-01", "status": "listed"},
        ]
    )
    assert written == 3

    lifecycle = warehouse.read_symbol_lifecycle()
    assert lifecycle["600519"] == {"listing_date": "2001-08-27", "delisted_date": None, "status": "listed"}
    assert lifecycle["000002"]["delisted_date"] == "2026-05-30"
    # A later upsert without a listing date keeps the existing one via COALESCE.
    warehouse.upsert_symbol_lifecycle([{"symbol": "600001", "delisted_date": "2026-06-10", "status": "delisted"}])
    lifecycle = warehouse.read_symbol_lifecycle(symbols=["600001"])
    assert lifecycle["600001"]["listing_date"] == "2026-06-01"
    assert lifecycle["600001"]["delisted_date"] == "2026-06-10"

    assert warehouse.read_delisted_symbols() == {"000002", "600001"}


def test_warehouse_capital_flow_missing_symbols_ignores_rows_outside_lifecycle_window(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["600001", "600001", "600002", "600003"],
                "trade_date": ["2026-06-01", "2026-06-02", "2026-06-02", "2026-06-02"],
                "open": [10.0, 10.0, 20.0, 30.0],
                "high": [10.5, 10.5, 20.5, 30.5],
                "low": [9.8, 9.8, 19.8, 29.8],
                "close": [10.2, 10.2, 20.2, 30.2],
                "volume": [1000, 1000, 2000, 3000],
                "main_net_inflow": [100.0, float("nan"), float("nan"), float("nan")],
            }
        )
    )
    warehouse.upsert_symbol_lifecycle(
        [
            # 600001 traded on 06-01 (with flow) and shows a stray 06-02 row
            # after its delisting date; the stray row must not mark it missing.
            {"symbol": "600001", "delisted_date": "2026-06-01", "status": "delisted"},
            # 600002 has no lifecycle record: legacy conservative behaviour.
            # 600003 was delisted before the window entirely.
            {"symbol": "600003", "delisted_date": "2026-05-30", "status": "delisted"},
        ]
    )

    missing = warehouse.read_capital_flow_missing_symbols("2026-06-01", "2026-06-02")

    assert missing == {"600002"}


def test_warehouse_coverage_daily_missing_rows_excludes_delisted_symbols(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001", "000002", "000003", "000001"],
                "trade_date": ["2026-06-05", "2026-06-05", "2026-06-05", "2026-06-08"],
                "open": [10.0, 10.0, 10.0, 10.2],
                "high": [10.5, 10.5, 10.5, 10.4],
                "low": [9.8, 9.8, 9.8, 10.0],
                "close": [10.2, 10.2, 10.2, 10.3],
                "volume": [1000, 1000, 1000, 1200],
            }
        )
    )
    warehouse.upsert_symbol_lifecycle(
        [{"symbol": "000002", "delisted_date": "2026-06-05", "status": "delisted"}]
    )

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["daily_bars"].missing_rows == 1
