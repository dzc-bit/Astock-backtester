from __future__ import annotations

import math

import pandas as pd

from astock_backtester.data.cache import LocalCache
from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.data.operations import (
    build_daily_bars_coverage,
    build_service_health,
    fetch_daily_bars_into_cache,
    import_daily_bars_into_cache,
)
from astock_backtester.data.realtime import (
    _aggregate_ths_hot_topics,
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


def test_cache_merge_preserves_existing_optional_values(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2024-01-03", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 91),
            ]
        )
    )

    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-01-03", 20.0, 21.0, 19.0, 20.5, 2200, 0.2, float("nan"), float("nan"), False, False, 91),
                ("AAA", "2024-01-04", 21.0, 22.0, 20.0, 21.5, 2400, 0.2, 9_300_000_000.0, 1_800_000.0, False, False, 92),
            ]
        )
    )

    loaded = cache.read_daily_bars()

    assert loaded["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03", "2024-01-04"]
    merged = loaded.loc[loaded["trade_date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert merged["open"] == 20.0
    assert merged["close"] == 20.5
    assert merged["float_market_cap"] == 9_100_000_000.0
    assert merged["main_net_inflow"] == 1_600_000.0


def test_importer_keeps_missing_capital_flow_as_missing():
    result = normalize_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["AAA"],
                "trade_date": ["2024-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [1000],
            }
        )
    )

    assert math.isnan(result.loc[0, "main_net_inflow"])


def test_coverage_reports_missing_ranges_and_optional_field_gaps(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2024-01-04", 10.7, 11.7, 9.7, 11.1, 1100, 0.1, float("nan"), float("nan"), False, False, 92),
                ("BBB", "2024-01-03", 20.0, 21.0, 19.0, 20.5, 900, 0.2, 20_000_000_000.0, float("nan"), False, False, 120),
            ]
        )
    )

    datasets = {item.dataset: item for item in cache.coverage()}
    details = build_daily_bars_coverage(cache)

    assert set(datasets) == {"daily_bars", "capital_flow", "market_cap"}
    assert datasets["capital_flow"].missing_rows == 2
    assert datasets["market_cap"].missing_rows == 1

    aaa = next(item for item in details.items if item.symbol == "AAA")
    assert aaa.start_date.isoformat() == "2024-01-02"
    assert aaa.end_date.isoformat() == "2024-01-04"
    assert [day.isoformat() for day in aaa.missing_trade_dates] == ["2024-01-03"]
    assert [day.isoformat() for day in aaa.missing_capital_flow_dates] == ["2024-01-04"]
    assert [day.isoformat() for day in aaa.missing_market_cap_dates] == ["2024-01-04"]


def test_coverage_filters_symbols_dates_and_ignores_weekends(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2024-01-05", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 93),
                ("BBB", "2024-01-03", 20.0, 21.0, 19.0, 20.5, 900, 0.2, 20_000_000_000.0, 1_000_000.0, False, False, 120),
            ]
        )
    )

    details = build_daily_bars_coverage(
        cache,
        symbols=["AAA"],
        start_date="2024-01-02",
        end_date="2024-01-08",
    )

    assert [item.symbol for item in details.items] == ["AAA"]
    aaa = details.items[0]
    assert aaa.start_date.isoformat() == "2024-01-02"
    assert aaa.end_date.isoformat() == "2024-01-05"
    assert aaa.rows == 2
    assert [day.isoformat() for day in aaa.missing_trade_dates] == ["2024-01-03", "2024-01-04"]


def test_coverage_uses_a_share_trading_calendar_for_2026_holidays(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2026-02-13", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2026-02-23", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 91),
                ("AAA", "2026-04-03", 11.0, 11.8, 10.8, 11.4, 1300, 0.1, 9_200_000_000.0, 1_700_000.0, False, False, 92),
                ("AAA", "2026-04-07", 11.4, 12.0, 11.2, 11.7, 1400, 0.1, 9_300_000_000.0, 1_800_000.0, False, False, 93),
                ("AAA", "2026-04-30", 11.7, 12.2, 11.4, 11.9, 1500, 0.1, 9_400_000_000.0, 1_900_000.0, False, False, 94),
                ("AAA", "2026-05-06", 11.9, 12.4, 11.6, 12.1, 1600, 0.1, 9_500_000_000.0, 2_000_000.0, False, False, 95),
            ]
        )
    )

    details = build_daily_bars_coverage(
        cache=cache,
        symbols=["AAA"],
        start_date="2026-02-13",
        end_date="2026-05-06",
    )

    missing = {day.isoformat() for day in details.items[0].missing_trade_dates}
    assert not (missing & {"2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20"})
    assert "2026-04-06" not in missing
    assert not (missing & {"2026-05-01", "2026-05-04", "2026-05-05"})


def test_coverage_uses_a_share_trading_calendar_for_2024_holidays(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-02-08", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2024-02-19", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 91),
                ("AAA", "2024-04-03", 11.0, 11.8, 10.8, 11.4, 1300, 0.1, 9_200_000_000.0, 1_700_000.0, False, False, 92),
                ("AAA", "2024-04-08", 11.4, 12.0, 11.2, 11.7, 1400, 0.1, 9_300_000_000.0, 1_800_000.0, False, False, 93),
                ("AAA", "2024-04-30", 11.7, 12.2, 11.4, 11.9, 1500, 0.1, 9_400_000_000.0, 1_900_000.0, False, False, 94),
                ("AAA", "2024-05-06", 11.9, 12.4, 11.6, 12.1, 1600, 0.1, 9_500_000_000.0, 2_000_000.0, False, False, 95),
                ("AAA", "2024-09-14", 12.1, 12.4, 11.9, 12.2, 1600, 0.1, 9_600_000_000.0, 2_100_000.0, False, False, 96),
                ("AAA", "2024-09-18", 12.2, 12.5, 12.0, 12.3, 1600, 0.1, 9_700_000_000.0, 2_200_000.0, False, False, 97),
                ("AAA", "2024-09-30", 12.3, 12.6, 12.1, 12.4, 1600, 0.1, 9_800_000_000.0, 2_300_000.0, False, False, 98),
                ("AAA", "2024-10-08", 12.4, 12.7, 12.2, 12.5, 1600, 0.1, 9_900_000_000.0, 2_400_000.0, False, False, 99),
            ]
        )
    )

    details = build_daily_bars_coverage(
        cache=cache,
        symbols=["AAA"],
        start_date="2024-02-08",
        end_date="2024-10-08",
    )

    missing = {day.isoformat() for day in details.items[0].missing_trade_dates}
    assert not (missing & {"2024-02-09", "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16"})
    assert not (missing & {"2024-04-04", "2024-04-05"})
    assert not (missing & {"2024-05-01", "2024-05-02", "2024-05-03"})
    assert not (missing & {"2024-09-16", "2024-09-17"})
    assert not (missing & {"2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-07"})


def test_coverage_uses_a_share_trading_calendar_for_2025_holidays(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2025-01-27", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2025-02-05", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 91),
                ("AAA", "2025-04-03", 11.0, 11.8, 10.8, 11.4, 1300, 0.1, 9_200_000_000.0, 1_700_000.0, False, False, 92),
                ("AAA", "2025-04-07", 11.4, 12.0, 11.2, 11.7, 1400, 0.1, 9_300_000_000.0, 1_800_000.0, False, False, 93),
                ("AAA", "2025-04-30", 11.7, 12.2, 11.4, 11.9, 1500, 0.1, 9_400_000_000.0, 1_900_000.0, False, False, 94),
                ("AAA", "2025-05-06", 11.9, 12.4, 11.6, 12.1, 1600, 0.1, 9_500_000_000.0, 2_000_000.0, False, False, 95),
                ("AAA", "2025-09-30", 12.1, 12.4, 11.9, 12.2, 1600, 0.1, 9_600_000_000.0, 2_100_000.0, False, False, 96),
                ("AAA", "2025-10-09", 12.2, 12.5, 12.0, 12.3, 1600, 0.1, 9_700_000_000.0, 2_200_000.0, False, False, 97),
            ]
        )
    )

    details = build_daily_bars_coverage(
        cache=cache,
        symbols=["AAA"],
        start_date="2025-01-27",
        end_date="2025-10-09",
    )

    missing = {day.isoformat() for day in details.items[0].missing_trade_dates}
    assert not (missing & {"2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-03", "2025-02-04"})
    assert not (missing & {"2025-04-04"})
    assert not (missing & {"2025-05-01", "2025-05-02", "2025-05-05"})
    assert not (missing & {"2025-10-01", "2025-10-02", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08"})


def test_fetch_result_reports_partial_success(tmp_path):
    cache = LocalCache(tmp_path)

    def fake_fetcher(symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        assert symbols == ["AAA", "BBB"]
        assert start_date == "2024-01-02"
        assert end_date == "2024-01-03"
        return _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2024-01-03", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, float("nan"), False, False, 91),
            ]
        )

    result = fetch_daily_bars_into_cache(
        cache=cache,
        fetcher=fake_fetcher,
        symbols=["AAA", "BBB"],
        start_date="2024-01-02",
        end_date="2024-01-03",
    )

    assert result.status == "partial"
    assert result.requested_symbols == ["AAA", "BBB"]
    assert result.fetched_symbols == ["AAA"]
    assert result.missing_symbols == ["BBB"]
    assert result.imported_rows == 2
    assert any(entry.level == "warning" and "BBB" in entry.message for entry in result.logs)


def test_health_payload_includes_cache_path_and_port(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    result = import_daily_bars_into_cache(
        cache=cache,
        frame=_bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        ),
        source="unit-test",
    )

    health = build_service_health(cache=cache, warehouse=warehouse, port=8765)

    assert result.imported_rows == 1
    assert health.port == 8765
    assert health.cache_path == str(cache.root.resolve())
    assert [item.dataset for item in health.coverage] == ["daily_bars", "capital_flow", "market_cap"]


def test_health_prefers_warehouse_coverage_when_available(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, float("nan"), False, False, 90),
                ("AAA", "2024-01-03", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_500_000.0, False, False, 91),
            ]
        )
    )

    health = build_service_health(cache=cache, warehouse=warehouse, port=8765)
    datasets = {item.dataset: item for item in health.coverage}

    assert datasets["daily_bars"].symbols == 1
    assert datasets["market_cap"].missing_rows == 0
    assert datasets["capital_flow"].missing_rows == 1


def test_health_falls_back_to_cache_when_warehouse_coverage_fails(tmp_path):
    class BrokenWarehouse:
        def coverage(self):
            raise RuntimeError("bad warehouse partition")

    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        )
    )

    health = build_service_health(cache=cache, warehouse=BrokenWarehouse(), port=8765)
    datasets = {item.dataset: item for item in health.coverage}

    assert health.ok is True
    assert datasets["daily_bars"].symbols == 1


def test_daily_bars_coverage_falls_back_to_cache_when_warehouse_read_fails(tmp_path):
    class BrokenWarehouse:
        def read_daily_bars(self, **kwargs):
            raise RuntimeError("bad warehouse parquet")

    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                ("AAA", "2026-05-26", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2026-06-05", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 91),
            ]
        )
    )

    details = build_daily_bars_coverage(
        cache=cache,
        warehouse=BrokenWarehouse(),
        symbols=["AAA"],
        start_date="2026-05-26",
        end_date="2026-06-05",
    )

    assert [item.symbol for item in details.items] == ["AAA"]
    assert details.items[0].end_date.isoformat() == "2026-06-05"


def test_coverage_prefers_warehouse_rows_when_available(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        _bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
                ("AAA", "2024-01-03", 10.5, 11.5, 10.0, 11.0, 1200, 0.1, 9_100_000_000.0, 1_600_000.0, False, False, 91),
            ]
        )
    )

    details = build_daily_bars_coverage(
        cache=cache,
        warehouse=warehouse,
        symbols=["AAA"],
        start_date="2024-01-02",
        end_date="2024-01-03",
    )

    assert [item.symbol for item in details.items] == ["AAA"]
    assert details.items[0].rows == 2


def test_import_syncs_warehouse_when_provided(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)

    result = import_daily_bars_into_cache(
        cache=cache,
        warehouse=warehouse,
        frame=_bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        ),
        source="unit-test",
    )

    cached = cache.read_daily_bars()
    stored = warehouse.read_daily_bars()
    datasets = {item.dataset: item for item in result.coverage}

    assert len(cached) == 1
    assert len(stored) == 1
    assert stored.loc[0, "symbol"] == "AAA"
    assert datasets["daily_bars"].symbols == 1


def test_import_recreates_missing_local_parquet_directory(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    cache.parquet_dir.rmdir()

    result = import_daily_bars_into_cache(
        cache=cache,
        warehouse=warehouse,
        frame=_bars(
            [
                ("AAA", "2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 0.1, 9_000_000_000.0, 1_500_000.0, False, False, 90),
            ]
        ),
        source="unit-test",
    )

    assert result.imported_rows == 1
    assert cache.daily_bars_path.exists() or cache.daily_bars_pickle_path.exists()
    assert len(cache.read_daily_bars()) == 1


def test_aggregate_ths_hot_topics_ranks_normalized_topics():
    topics = _aggregate_ths_hot_topics(
        [
            {"code": "300001", "name": "A", "reason": "算力租赁+AI政务", "zhangfu": 9.9, "chengjiaoe": 100000},
            {"code": "300002", "name": "B", "reason": "算力租赁+液冷服务器", "zhangfu": 8.2, "chengjiaoe": 90000},
            {"code": "300003", "name": "C", "reason": "液冷服务器+AI政务", "zhangfu": 6.8, "chengjiaoe": 70000},
        ]
    )

    assert topics
    assert topics[0].name == "算力租赁"
    assert topics[0].source == "ths-hot-reason"
    assert all(topic.name not in {"", "A股", "市场"} for topic in topics)
