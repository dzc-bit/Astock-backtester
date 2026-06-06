from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.models import DatasetCoverage


class LocalCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.parquet_dir = self.root / "parquet"
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = self.root / "metadata.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @property
    def daily_bars_path(self) -> Path:
        return self.parquet_dir / "daily_bars.parquet"

    @property
    def daily_bars_pickle_path(self) -> Path:
        return self.parquet_dir / "daily_bars.pkl"

    def write_daily_bars(self, frame: pd.DataFrame) -> None:
        normalized = normalize_daily_bars(frame)
        current = self.read_daily_bars()
        if not current.empty:
            normalized = (
                normalized.set_index(["symbol", "trade_date"])
                .combine_first(current.set_index(["symbol", "trade_date"]))
                .reset_index()
                .sort_values(["symbol", "trade_date"])
                .reset_index(drop=True)
            )
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        try:
            normalized.to_parquet(self.daily_bars_path, index=False)
            if self.daily_bars_pickle_path.exists():
                self.daily_bars_pickle_path.unlink()
        except ImportError:
            normalized.to_pickle(self.daily_bars_pickle_path)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO datasets(dataset, updated_at) VALUES('daily_bars', CURRENT_TIMESTAMP)"
            )

    def read_daily_bars(self) -> pd.DataFrame:
        if self.daily_bars_path.exists():
            return pd.read_parquet(self.daily_bars_path).sort_values(["symbol", "trade_date"]).reset_index(drop=True)
        if self.daily_bars_pickle_path.exists():
            return pd.read_pickle(self.daily_bars_pickle_path).sort_values(["symbol", "trade_date"]).reset_index(drop=True)
        return pd.DataFrame()

    def coverage(self) -> list[DatasetCoverage]:
        bars = self.read_daily_bars()
        if bars.empty:
            return [
                DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="capital_flow", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="market_cap", symbols=0, start_date=None, end_date=None),
            ]
        start_date = bars["trade_date"].min().date()
        end_date = bars["trade_date"].max().date()
        return [
            DatasetCoverage(
                dataset="daily_bars",
                symbols=int(bars["symbol"].nunique()),
                start_date=start_date,
                end_date=end_date,
                missing_rows=int(bars[["open", "high", "low", "close"]].isna().any(axis=1).sum()),
            ),
            DatasetCoverage(
                dataset="capital_flow",
                symbols=int(bars.loc[bars["main_net_inflow"].notna(), "symbol"].nunique()),
                start_date=start_date,
                end_date=end_date,
                missing_rows=int(bars["main_net_inflow"].isna().sum()),
            ),
            DatasetCoverage(
                dataset="market_cap",
                symbols=int(bars.loc[bars["float_market_cap"].notna(), "symbol"].nunique()),
                start_date=start_date,
                end_date=end_date,
                missing_rows=int(bars["float_market_cap"].isna().sum()),
            ),
        ]
