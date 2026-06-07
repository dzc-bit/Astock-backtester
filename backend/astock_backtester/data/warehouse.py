from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd
import pyarrow.parquet as pq

from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.models import DatasetCoverage


class Warehouse:
    def __init__(self, cache_root: str | Path) -> None:
        self.cache_root = Path(cache_root)
        self.root = self.cache_root / "warehouse"
        self.daily_bars_root = self.root / "daily_bars"
        self.daily_bars_root.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = self.root / "metadata.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_sync_state (
                    symbol TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    rows INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    provider TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _partition_path(self, year: int) -> Path:
        return self.daily_bars_root / f"year={year}" / "daily_bars.parquet"

    def _partition_paths_for_range(self, start_date: str | None, end_date: str | None) -> list[Path]:
        paths = sorted(self.daily_bars_root.glob("year=*/daily_bars.parquet"))
        if not paths or (start_date is None and end_date is None):
            return paths

        start_year = date.min.year if start_date is None else pd.Timestamp(start_date).year
        end_year = date.max.year if end_date is None else pd.Timestamp(end_date).year
        return [
            path
            for path in paths
            if start_year <= int(path.parent.name.split("year=", 1)[1]) <= end_year
        ]

    def write_daily_bars(self, frame: pd.DataFrame) -> None:
        normalized = normalize_daily_bars(frame)
        if normalized.empty:
            return
        normalized["year"] = normalized["trade_date"].dt.year
        for year, year_frame in normalized.groupby("year"):
            path = self._partition_path(int(year))
            path.parent.mkdir(parents=True, exist_ok=True)
            year_frame = year_frame.drop(columns=["year"])
            if path.exists():
                current = self._safe_read_parquet(path)
                if not current.empty and {"symbol", "trade_date"}.issubset(current.columns):
                    year_frame = (
                        year_frame.set_index(["symbol", "trade_date"])
                        .combine_first(current.set_index(["symbol", "trade_date"]))
                        .reset_index()
                    )
            year_frame = year_frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
            year_frame.to_parquet(path, index=False)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute("INSERT OR REPLACE INTO datasets(dataset) VALUES('daily_bars')")

    def read_daily_bars(
        self,
        symbols: Sequence[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        paths = self._partition_paths_for_range(start_date, end_date)
        if not paths:
            return pd.DataFrame()
        frames = []
        for path in paths:
            frame = self._safe_read_parquet(path)
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        frame = pd.concat(frames, ignore_index=True)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        if symbols:
            selected = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
            frame = frame[frame["symbol"].astype(str).isin(selected)]
        if start_date:
            frame = frame[frame["trade_date"] >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame["trade_date"] <= pd.Timestamp(end_date)]
        return frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    def read_latest_daily_bars(self, days: int = 2) -> pd.DataFrame:
        paths = sorted(self.daily_bars_root.glob("year=*/daily_bars.parquet"), reverse=True)
        if not paths:
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []
        unique_dates: set[pd.Timestamp] = set()
        for path in paths:
            frame = self._safe_read_parquet(path)
            if frame.empty:
                continue
            frame["trade_date"] = pd.to_datetime(frame["trade_date"])
            frames.append(frame)
            unique_dates.update(pd.Timestamp(value) for value in frame["trade_date"].drop_duplicates().tolist())
            if len(unique_dates) >= days:
                break

        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        latest_dates = sorted(combined["trade_date"].drop_duplicates().tolist())[-days:]
        return (
            combined[combined["trade_date"].isin(latest_dates)]
            .sort_values(["symbol", "trade_date"])
            .reset_index(drop=True)
        )

    def coverage(self) -> list[DatasetCoverage]:
        paths = sorted(self.daily_bars_root.glob("year=*/daily_bars.parquet"))
        if not paths:
            return [
                DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="market_cap", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="capital_flow", symbols=0, start_date=None, end_date=None),
            ]

        required_columns = ["symbol", "trade_date", "open", "high", "low", "close"]
        optional_columns = ["float_market_cap", "main_net_inflow"]
        wanted_columns = required_columns + optional_columns
        symbols: set[str] = set()
        market_cap_symbols: set[str] = set()
        capital_flow_symbols: set[str] = set()
        start: date | None = None
        end: date | None = None
        daily_missing_rows = 0
        market_cap_missing_rows = 0
        capital_flow_missing_rows = 0

        for path in paths:
            try:
                available_columns = set(pq.ParquetFile(path).schema_arrow.names)
            except Exception:
                continue
            selected_columns = [column for column in wanted_columns if column in available_columns]
            if "symbol" not in selected_columns or "trade_date" not in selected_columns:
                continue

            frame = self._safe_read_parquet(path, columns=selected_columns)
            if frame.empty:
                continue
            row_count = int(len(frame))
            frame["trade_date"] = pd.to_datetime(frame["trade_date"])
            symbols.update(str(symbol) for symbol in frame["symbol"].dropna().astype(str).unique())

            part_start = frame["trade_date"].min().date()
            part_end = frame["trade_date"].max().date()
            start = part_start if start is None else min(start, part_start)
            end = part_end if end is None else max(end, part_end)

            present_ohlc = [column for column in ["open", "high", "low", "close"] if column in frame]
            if len(present_ohlc) < 4:
                daily_missing_rows += row_count
            else:
                daily_missing_rows += int(frame[present_ohlc].isna().any(axis=1).sum())

            if "float_market_cap" in frame:
                market_cap_mask = frame["float_market_cap"].notna()
                market_cap_symbols.update(str(symbol) for symbol in frame.loc[market_cap_mask, "symbol"].dropna().astype(str).unique())
                market_cap_missing_rows += int((~market_cap_mask).sum())
            else:
                market_cap_missing_rows += row_count

            if "main_net_inflow" in frame:
                capital_flow_mask = frame["main_net_inflow"].notna()
                capital_flow_symbols.update(str(symbol) for symbol in frame.loc[capital_flow_mask, "symbol"].dropna().astype(str).unique())
                capital_flow_missing_rows += int((~capital_flow_mask).sum())
            else:
                capital_flow_missing_rows += row_count

        if start is None or end is None:
            return [
                DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="market_cap", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="capital_flow", symbols=0, start_date=None, end_date=None),
            ]

        return [
            DatasetCoverage(
                dataset="daily_bars",
                symbols=len(symbols),
                start_date=start,
                end_date=end,
                missing_rows=daily_missing_rows,
            ),
            DatasetCoverage(
                dataset="market_cap",
                symbols=len(market_cap_symbols),
                start_date=start,
                end_date=end,
                missing_rows=market_cap_missing_rows,
            ),
            DatasetCoverage(
                dataset="capital_flow",
                symbols=len(capital_flow_symbols),
                start_date=start,
                end_date=end,
                missing_rows=capital_flow_missing_rows,
            ),
        ]

    def _safe_read_parquet(self, path: Path, **kwargs) -> pd.DataFrame:
        try:
            return pd.read_parquet(path, **kwargs)
        except Exception:
            return pd.DataFrame()
