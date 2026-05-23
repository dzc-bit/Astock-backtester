from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars


class AStockDataUnavailable(RuntimeError):
    pass


DailyBarsFetcher = Callable[[Sequence[str], str, str], pd.DataFrame]


class AStockDataAdapter:
    def __init__(self, fetcher: DailyBarsFetcher | None = None) -> None:
        self.fetcher = fetcher

    def fetch_daily_bars(self, symbols: Sequence[str], start_date: str, end_date: str) -> pd.DataFrame:
        if self.fetcher is None:
            raise AStockDataUnavailable(
                "a-stock-data fetcher is not configured. Configure a fetcher that returns daily OHLCV, "
                "market cap, turnover, and capital-flow columns."
            )
        return normalize_daily_bars(self.fetcher(symbols, start_date, end_date))
