from __future__ import annotations

import pandas as pd

from astock_backtester.data.sync import SyncJobManager
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
