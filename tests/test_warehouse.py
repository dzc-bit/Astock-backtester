from __future__ import annotations

import pandas as pd

from astock_backtester.data.warehouse import Warehouse


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


def test_warehouse_reads_latest_daily_bars_from_recent_partitions(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    latest = warehouse.read_latest_daily_bars(days=1)

    assert latest["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2016-01-04", "2016-01-04"]
    assert set(latest["symbol"]) == {"000001", "600519"}
