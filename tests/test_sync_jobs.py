from __future__ import annotations

import time
import pandas as pd
from time import sleep
from threading import Event

from astock_backtester.data.sync import SyncJobManager
from astock_backtester.data.cache import LocalCache
from astock_backtester.data.warehouse import Warehouse


class FakeProvider:
    def __init__(self, fail_symbols=None):
        self.fail_symbols = set(fail_symbols or [])

    def fetch_daily_bars(self, symbol, start_date, end_date):
        if symbol in self.fail_symbols:
            raise RuntimeError("source unavailable")
        return pd.DataFrame(
            {
                "symbol": [symbol],
                "trade_date": [start_date],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [1],
                "float_market_cap": [100.0],
                "total_market_cap": [120.0],
            }
        )


def test_full_market_job_counts_empty_provider_rows_as_failure(tmp_path):
    class EmptyProvider(FakeProvider):
        def fetch_daily_bars(self, symbol, start_date, end_date):
            if symbol == "000002":
                return pd.DataFrame()
            return super().fetch_daily_bars(symbol, start_date, end_date)

    warehouse = Warehouse(tmp_path)
    manager = SyncJobManager(warehouse=warehouse, provider=EmptyProvider())

    status = manager.run_full_market(
        symbols=["000001", "000002"],
        start_date="2015-01-01",
        end_date="2015-01-05",
    )

    assert status.completed_symbols == 1
    assert status.failed_symbols == 1
    assert status.status == "completed_with_errors"
    assert status.errors == ["000002: provider returned no daily rows"]
    assert warehouse.read_daily_bars()["symbol"].tolist() == ["000001"]


def test_full_market_job_persists_success_and_failure(tmp_path):
    warehouse = Warehouse(tmp_path)
    manager = SyncJobManager(warehouse=warehouse, provider=FakeProvider(fail_symbols={"000002"}))

    status = manager.run_full_market(
        symbols=["000001", "000002", "000003"],
        start_date="2015-01-01",
        end_date="2015-01-05",
    )

    assert status.total_symbols == 3
    assert status.completed_symbols == 2
    assert status.failed_symbols == 1
    assert status.imported_rows == 2
    loaded = warehouse.read_daily_bars()
    assert sorted(loaded["symbol"].tolist()) == ["000001", "000003"]


def test_full_market_job_can_run_asynchronously_and_report_progress(tmp_path):
    class SlowProvider(FakeProvider):
        def fetch_daily_bars(self, symbol, start_date, end_date):
            sleep(0.02)
            return super().fetch_daily_bars(symbol, start_date, end_date)

    warehouse = Warehouse(tmp_path)
    manager = SyncJobManager(warehouse=warehouse, provider=SlowProvider())

    status = manager.start_full_market(
        symbols=["000001", "000002", "000003"],
        start_date="2015-01-01",
        end_date="2015-01-05",
    )

    assert status.status == "running"
    assert status.total_symbols == 3
    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status == "completed":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "completed"
    assert eventually.completed_symbols == 3
    assert warehouse.read_daily_bars()["symbol"].nunique() == 3


def test_full_market_job_uses_large_write_batches_for_daily_incremental_import(tmp_path):
    class CountingWarehouse(Warehouse):
        def __init__(self, cache_root):
            super().__init__(cache_root)
            self.write_batches = []

        def write_daily_bars(self, frame):
            self.write_batches.append(int(len(frame)))
            super().write_daily_bars(frame)

    warehouse = CountingWarehouse(tmp_path)
    manager = SyncJobManager(warehouse=warehouse, provider=FakeProvider())
    symbols = [f"{index:06d}" for index in range(251)]

    status = manager.start_full_market(
        symbols=symbols,
        start_date="2026-06-09",
        end_date="2026-06-09",
    )

    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status == "completed":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "completed"
    assert eventually.imported_rows == 251
    assert warehouse.write_batches == [251]


def test_async_full_market_job_flushes_successful_rows_after_a_batch_failure(tmp_path):
    class BlockingProvider(FakeProvider):
        def __init__(self):
            super().__init__(fail_symbols={"000002"})
            self.third_started = Event()
            self.release_third = Event()

        def fetch_daily_bars(self, symbol, start_date, end_date):
            if symbol == "000003":
                self.third_started.set()
                self.release_third.wait(timeout=5)
            return super().fetch_daily_bars(symbol, start_date, end_date)

    provider = BlockingProvider()
    warehouse = Warehouse(tmp_path)
    manager = SyncJobManager(
        warehouse=warehouse,
        provider=provider,
        full_market_batch_size=2,
        full_market_workers=1,
        full_market_write_batch_rows=25_000,
    )

    status = manager.start_full_market(
        symbols=["000001", "000002", "000003"],
        start_date="2026-06-09",
        end_date="2026-06-09",
    )

    assert provider.third_started.wait(timeout=5)
    running = manager.get_job(status.job_id)
    assert running is not None
    assert running.status == "running"
    assert running.completed_symbols == 1
    assert running.failed_symbols == 1
    assert sorted(warehouse.read_daily_bars()["symbol"].tolist()) == ["000001"]

    provider.release_third.set()
    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status == "completed":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "completed_with_errors"
    assert sorted(warehouse.read_daily_bars()["symbol"].tolist()) == ["000001", "000003"]


def test_full_market_job_skips_symbols_already_complete_in_local_warehouse(tmp_path):
    class CountingProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.calls = []

        def fetch_daily_bars(self, symbol, start_date, end_date):
            self.calls.append(symbol)
            return super().fetch_daily_bars(symbol, start_date, end_date)

    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001"],
                "trade_date": ["2026-06-18"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000],
                "float_market_cap": [100.0],
                "total_market_cap": [120.0],
            }
        )
    )
    provider = CountingProvider()
    manager = SyncJobManager(warehouse=warehouse, provider=provider)

    status = manager.run_full_market(
        symbols=["000001", "000002"],
        start_date="2026-06-18",
        end_date="2026-06-19",
    )

    assert provider.calls == ["000002"]
    assert status.processed_symbols == 2
    assert status.skipped_symbols == 1
    assert status.completed_symbols == 1
    assert status.failed_symbols == 0
    assert status.status == "completed"


def test_capital_flow_job_reports_completed_with_errors_when_rows_import_with_failures(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
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
                "main_net_inflow": [float("nan")],
            }
        )
    )

    def fake_capital_flow_fetcher(symbols, start_date, end_date):
        return {
            "rows": [{"symbol": "000001", "trade_date": "2026-05-26", "main_net_inflow": 8800000.0}],
            "failures": [{"symbol": "000001", "code": "date_coverage_shortfall", "message": "partial range"}],
            "diagnostics": [],
        }

    manager = SyncJobManager(
        warehouse=warehouse,
        provider=FakeProvider(),
        cache=cache,
        capital_flow_fetcher=fake_capital_flow_fetcher,
    )

    status = manager.start_capital_flow_backfill(["000001"], "2026-05-26", "2026-05-29")

    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status != "running":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "completed_with_errors"
    assert eventually.completed_symbols == 0
    assert eventually.failed_symbols == 1
    assert eventually.imported_rows == 1
    assert eventually.errors == ["000001: partial range"]


def test_capital_flow_job_counts_no_failure_zero_import_as_completed(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)

    def fake_capital_flow_fetcher(symbols, start_date, end_date):
        return {
            "rows": [],
            "failures": [],
            "diagnostics": [{"code": "capital_flow_backfill_not_needed"}],
        }

    manager = SyncJobManager(
        warehouse=warehouse,
        provider=FakeProvider(),
        cache=cache,
        capital_flow_fetcher=fake_capital_flow_fetcher,
    )

    status = manager.start_capital_flow_backfill(["000001"], "2026-05-26", "2026-05-29")

    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status != "running":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "completed"
    assert eventually.completed_symbols == 1
    assert eventually.failed_symbols == 0
    assert eventually.imported_rows == 0
    assert eventually.errors == []


def test_capital_flow_job_treats_shortfall_diagnostics_as_retryable_failure(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)

    def fake_capital_flow_fetcher(symbols, start_date, end_date):
        return {
            "rows": [{"symbol": "000001", "trade_date": "2026-05-26", "main_net_inflow": 8800000.0}],
            "failures": [],
            "diagnostics": [
                {
                    "symbol": "000001",
                    "code": "date_coverage_shortfall",
                    "message": "returned 2026-05-26 to 2026-05-26 for requested 2026-05-26 to 2026-05-29",
                }
            ],
        }

    manager = SyncJobManager(
        warehouse=warehouse,
        provider=FakeProvider(),
        cache=cache,
        capital_flow_fetcher=fake_capital_flow_fetcher,
    )

    status = manager.start_capital_flow_backfill(["000001"], "2026-05-26", "2026-05-29")

    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status != "running":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "completed_with_errors"
    assert eventually.processed_symbols == 1
    assert eventually.completed_symbols == 0
    assert eventually.failed_symbols == 1
    assert eventually.imported_rows == 1
    assert eventually.returned_rows == 1
    assert eventually.last_error is not None
    assert "000001" in eventually.last_error
    assert "date_coverage_shortfall" in eventually.last_error


def test_capital_flow_job_can_be_cancelled_between_batches(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    started = Event()
    release = Event()

    def fake_capital_flow_fetcher(symbols, start_date, end_date):
        started.set()
        release.wait(timeout=5)
        return {
            "rows": [
                {"symbol": symbols[0], "trade_date": "2026-06-05", "main_net_inflow": 1000000.0}
            ],
            "failures": [],
            "diagnostics": [],
        }

    manager = SyncJobManager(
        warehouse=warehouse,
        provider=FakeProvider(),
        cache=cache,
        capital_flow_fetcher=fake_capital_flow_fetcher,
        capital_flow_batch_size=1,
    )

    status = manager.start_capital_flow_backfill(["000001", "000002", "000003"], "2026-06-05", "2026-06-05")
    assert started.wait(timeout=5)
    cancelled = manager.cancel_job(status.job_id)
    assert cancelled is not None
    assert cancelled.status == "cancelling"
    release.set()

    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status == "cancelled":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "cancelled"
    assert eventually.processed_symbols == 1
    assert eventually.completed_symbols == 1
    assert eventually.imported_rows == 1
    assert warehouse.read_daily_bars()["symbol"].tolist() == ["000001"]


def test_capital_flow_job_batches_symbols_and_accumulates_row_stats(tmp_path):
    cache = LocalCache(tmp_path)
    warehouse = Warehouse(tmp_path)
    calls = []

    def fake_capital_flow_fetcher(symbols, start_date, end_date):
        calls.append(list(symbols))
        rows = [
            {"symbol": symbol, "trade_date": "2026-06-05", "main_net_inflow": 1000000.0}
            for symbol in symbols
            if symbol != "000003"
        ]
        failures = (
            [{"symbol": "000003", "code": "network_error", "error": "remote disconnected"}]
            if "000003" in symbols
            else []
        )
        return {"rows": rows, "failures": failures, "diagnostics": failures}

    manager = SyncJobManager(
        warehouse=warehouse,
        provider=FakeProvider(),
        cache=cache,
        capital_flow_fetcher=fake_capital_flow_fetcher,
        capital_flow_batch_size=2,
    )

    status = manager.start_capital_flow_backfill(["000001", "000002", "000003"], "2026-06-05", "2026-06-05")

    eventually = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        eventually = manager.get_job(status.job_id)
        if eventually and eventually.status != "running":
            break
        sleep(0.02)

    assert eventually is not None
    assert eventually.status == "completed_with_errors"
    assert calls == [["000001", "000002"], ["000003"]]
    assert eventually.processed_symbols == 3
    assert eventually.completed_symbols == 2
    assert eventually.failed_symbols == 1
    assert eventually.returned_rows == 2
    assert eventually.imported_rows == 2
    assert eventually.last_error == "000003: remote disconnected"
    assert eventually.recent_failures[-1]["symbol"] == "000003"
