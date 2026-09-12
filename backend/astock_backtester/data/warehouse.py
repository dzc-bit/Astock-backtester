from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.models import DatasetCoverage

OHLC_COLUMNS = ["open", "high", "low", "close"]
KNOWN_CAPITAL_FLOW_SOURCE_GAP_DATES = {
    pd.Timestamp("2018-08-07"),
    pd.Timestamp("2019-04-04"),
    pd.Timestamp("2019-04-19"),
    pd.Timestamp("2022-12-14"),
    pd.Timestamp("2024-07-16"),
}
KNOWN_CAPITAL_FLOW_SOURCE_START_SYMBOL_PREFIXES = ("920",)
KNOWN_CAPITAL_FLOW_SOURCE_START_SYMBOLS = {"001872", "001914", "601360"}
KNOWN_CAPITAL_FLOW_SOURCE_START_DATES = {pd.Timestamp("2021-12-29")}
KNOWN_CAPITAL_FLOW_LISTING_LAG_DAYS = 90


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_lifecycle (
                    symbol TEXT PRIMARY KEY,
                    listing_date TEXT,
                    delisted_date TEXT,
                    status TEXT NOT NULL DEFAULT 'listed',
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

    def daily_bars_parquet_glob(self) -> str | None:
        """Hive-style glob for the daily-bars parquet partitions.

        Public read-only helper for the AI module's DuckDB query tool; returns
        ``None`` when no partition exists yet.
        """
        if not self._partition_paths_for_range(None, None):
            return None
        return str(self.daily_bars_root / "year=*" / "daily_bars.parquet")

    def daily_bars_parquet_paths(self) -> list[str]:
        """Explicit partition file paths (no glob) for sandboxed DuckDB views."""
        return [str(path) for path in self._partition_paths_for_range(None, None)]

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
        require_ohlc: bool = False,
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
        if require_ohlc:
            frame = _require_ohlc_rows(frame)
        return frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    def read_daily_symbols(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        require_ohlc: bool = False,
    ) -> list[str]:
        paths = self._partition_paths_for_range(start_date, end_date)
        if not paths:
            return []
        symbols: set[str] = set()
        for path in paths:
            try:
                available_columns = set(pq.ParquetFile(path).schema_arrow.names)
            except FileNotFoundError:
                continue
            selected_columns = ["symbol"]
            if start_date or end_date:
                selected_columns.append("trade_date")
            if require_ohlc:
                selected_columns.extend(OHLC_COLUMNS)
            selected_columns = [column for column in selected_columns if column in available_columns]
            if "symbol" not in selected_columns:
                continue
            if (start_date or end_date) and "trade_date" not in selected_columns:
                continue
            if require_ohlc and not all(column in selected_columns for column in OHLC_COLUMNS):
                continue

            frame = self._safe_read_parquet(path, columns=selected_columns)
            if frame.empty:
                continue
            if start_date or end_date:
                frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
                frame = frame.dropna(subset=["trade_date"])
                if start_date:
                    frame = frame[frame["trade_date"] >= pd.Timestamp(start_date)]
                if end_date:
                    frame = frame[frame["trade_date"] <= pd.Timestamp(end_date)]
            if require_ohlc:
                frame = _require_ohlc_rows(frame)
            if frame.empty:
                continue
            symbols.update(str(symbol) for symbol in frame["symbol"].dropna().astype(str).unique())
        return sorted(symbol for symbol in symbols if symbol)

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
            frame = _require_ohlc_rows(frame)
            if frame.empty:
                continue
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
        daily_symbols: set[str] = set()
        market_cap_symbols: set[str] = set()
        capital_flow_symbols: set[str] = set()
        daily_start: date | None = None
        daily_end: date | None = None
        market_cap_start: date | None = None
        market_cap_end: date | None = None
        capital_flow_start: date | None = None
        capital_flow_end: date | None = None
        daily_missing_rows = 0
        market_cap_missing_rows = 0
        capital_flow_missing_rows = 0
        first_daily_date_by_symbol: dict[str, pd.Timestamp] = {}
        flow_start_by_symbol: dict[str, pd.Timestamp] = {}
        daily_symbols_by_date: dict[pd.Timestamp, set[str]] = {}
        missing_capital_flow_frames: list[pd.DataFrame] = []

        def update_range(current_start: date | None, current_end: date | None, frame: pd.DataFrame) -> tuple[date | None, date | None]:
            if frame.empty:
                return current_start, current_end
            part_start = frame["trade_date"].min().date()
            part_end = frame["trade_date"].max().date()
            return (
                part_start if current_start is None else min(current_start, part_start),
                part_end if current_end is None else max(current_end, part_end),
            )

        for path in paths:
            try:
                available_columns = set(pq.ParquetFile(path).schema_arrow.names)
            except FileNotFoundError:
                continue
            selected_columns = [column for column in wanted_columns if column in available_columns]
            if "symbol" not in selected_columns or "trade_date" not in selected_columns:
                continue

            frame = self._safe_read_parquet(path, columns=selected_columns)
            if frame.empty:
                continue
            frame["trade_date"] = pd.to_datetime(frame["trade_date"])

            present_ohlc = [column for column in OHLC_COLUMNS if column in frame]
            if len(present_ohlc) < 4:
                ohlc_complete = frame.iloc[0:0]
            else:
                ohlc_complete_mask = frame[present_ohlc].notna().all(axis=1)
                ohlc_complete = frame.loc[ohlc_complete_mask]

            if not ohlc_complete.empty:
                daily_symbols.update(str(symbol) for symbol in ohlc_complete["symbol"].dropna().astype(str).unique())
                daily_start, daily_end = update_range(daily_start, daily_end, ohlc_complete)
                for trade_date, date_frame in ohlc_complete.groupby("trade_date"):
                    daily_symbols_by_date.setdefault(pd.Timestamp(trade_date), set()).update(
                        str(symbol) for symbol in date_frame["symbol"].dropna().astype(str).unique()
                    )
                daily_starts = (
                    ohlc_complete.groupby(ohlc_complete["symbol"].astype(str))["trade_date"]
                    .min()
                    .to_dict()
                )
                for symbol, trade_date in daily_starts.items():
                    current = first_daily_date_by_symbol.get(symbol)
                    timestamp = pd.Timestamp(trade_date)
                    if current is None or timestamp < current:
                        first_daily_date_by_symbol[symbol] = timestamp

            if "float_market_cap" in ohlc_complete:
                market_cap_mask = ohlc_complete["float_market_cap"].notna()
                market_cap_frame = ohlc_complete.loc[market_cap_mask]
                market_cap_symbols.update(str(symbol) for symbol in market_cap_frame["symbol"].dropna().astype(str).unique())
                market_cap_missing_rows += int((~market_cap_mask).sum())
                market_cap_start, market_cap_end = update_range(market_cap_start, market_cap_end, market_cap_frame)
            else:
                market_cap_missing_rows += int(len(ohlc_complete))

            if "main_net_inflow" in frame:
                capital_flow_mask = frame["main_net_inflow"].notna()
                capital_flow_frame = frame.loc[capital_flow_mask]
                capital_flow_symbols.update(str(symbol) for symbol in capital_flow_frame["symbol"].dropna().astype(str).unique())
                capital_flow_start, capital_flow_end = update_range(capital_flow_start, capital_flow_end, capital_flow_frame)
                flow_starts = (
                    capital_flow_frame.groupby(capital_flow_frame["symbol"].astype(str))["trade_date"]
                    .min()
                    .to_dict()
                    if not capital_flow_frame.empty
                    else {}
                )
                for symbol, trade_date in flow_starts.items():
                    current = flow_start_by_symbol.get(symbol)
                    timestamp = pd.Timestamp(trade_date)
                    if current is None or timestamp < current:
                        flow_start_by_symbol[symbol] = timestamp
                if not ohlc_complete.empty:
                    missing_flow = frame.loc[
                        ohlc_complete.index[frame.loc[ohlc_complete.index, "main_net_inflow"].isna()],
                        ["symbol", "trade_date"],
                    ]
                    if not missing_flow.empty:
                        missing_capital_flow_frames.append(
                            missing_flow.assign(symbol=missing_flow["symbol"].astype(str))
                            .reset_index(drop=True)
                        )
            elif not ohlc_complete.empty:
                missing_capital_flow_frames.append(
                    ohlc_complete[["symbol", "trade_date"]]
                    .assign(symbol=ohlc_complete["symbol"].astype(str))
                    .reset_index(drop=True)
                )

        if missing_capital_flow_frames:
            missing_flow = pd.concat(missing_capital_flow_frames, ignore_index=True)
            missing_flow["trade_date"] = pd.to_datetime(missing_flow["trade_date"], errors="coerce")
            missing_flow = missing_flow.dropna(subset=["trade_date"])
            if not missing_flow.empty:
                missing_flow = missing_flow.loc[
                    ~missing_flow["trade_date"].isin(KNOWN_CAPITAL_FLOW_SOURCE_GAP_DATES)
                ]
            if not missing_flow.empty and flow_start_by_symbol:
                source_start_symbols = {
                    symbol
                    for symbol, flow_start in flow_start_by_symbol.items()
                    if uses_symbol_capital_flow_source_start(
                        symbol,
                        flow_start,
                        first_daily_date_by_symbol.get(symbol),
                        pd.Timestamp(daily_start) if daily_start is not None else None,
                    )
                }
                if source_start_symbols:
                    mapped_flow_start = missing_flow["symbol"].map(flow_start_by_symbol)
                    before_source_start = (
                        missing_flow["symbol"].isin(source_start_symbols)
                        & mapped_flow_start.notna()
                        & (missing_flow["trade_date"] < mapped_flow_start)
                    )
                    missing_flow = missing_flow.loc[~before_source_start]
            capital_flow_missing_rows += int(len(missing_flow))

        if daily_symbols and daily_end is not None:
            latest_symbols = daily_symbols_by_date.get(pd.Timestamp(daily_end), set())
            lifecycle = self.read_symbol_lifecycle()
            delisted_before_end = {
                symbol
                for symbol, record in lifecycle.items()
                if _lifecycle_bound(record, "delisted_date") is not None
                and _lifecycle_bound(record, "delisted_date") < pd.Timestamp(daily_end)
            }
            active_symbols = daily_symbols - delisted_before_end
            daily_missing_rows = max(0, len(active_symbols) - len(latest_symbols - delisted_before_end))

        return [
            DatasetCoverage(
                dataset="daily_bars",
                symbols=len(daily_symbols),
                start_date=daily_start,
                end_date=daily_end,
                missing_rows=daily_missing_rows,
            ),
            DatasetCoverage(
                dataset="market_cap",
                symbols=len(market_cap_symbols),
                start_date=market_cap_start,
                end_date=market_cap_end,
                missing_rows=market_cap_missing_rows,
            ),
            DatasetCoverage(
                dataset="capital_flow",
                symbols=len(capital_flow_symbols),
                start_date=capital_flow_start,
                end_date=capital_flow_end,
                missing_rows=capital_flow_missing_rows,
            ),
        ]

    def upsert_symbol_lifecycle(self, rows: Sequence[dict[str, str | None]]) -> int:
        """Insert or update ``symbol_lifecycle`` rows.

        Each row needs ``symbol`` and may carry ``listing_date`` /
        ``delisted_date`` (ISO strings or ``None``) plus ``status``
        (``listed`` / ``delisted`` / ``unknown``). Returns the number of rows
        written; the write is atomic per call.
        """
        payload = []
        for row in rows:
            symbol = str(row.get("symbol", "")).strip()
            if not symbol:
                continue
            status = str(row.get("status") or "").strip()
            if not status:
                status = "delisted" if row.get("delisted_date") else "listed"
            payload.append(
                (
                    symbol,
                    _clean_lifecycle_date(row.get("listing_date")),
                    _clean_lifecycle_date(row.get("delisted_date")),
                    status,
                )
            )
        if not payload:
            return 0
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.executemany(
                """
                INSERT INTO symbol_lifecycle (symbol, listing_date, delisted_date, status, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol) DO UPDATE SET
                    listing_date = COALESCE(excluded.listing_date, symbol_lifecycle.listing_date),
                    delisted_date = COALESCE(excluded.delisted_date, symbol_lifecycle.delisted_date),
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                payload,
            )
        return len(payload)

    def read_symbol_lifecycle(self, symbols: Sequence[str] | None = None) -> dict[str, dict[str, str | None]]:
        """Return ``{symbol: {listing_date, delisted_date, status}}`` records.

        ``listing_date`` / ``delisted_date`` are ISO strings or ``None``;
        symbols without a lifecycle record are absent from the mapping, and the
        caller is expected to fall back to the conservative (unclipped) window.
        """
        selected = None
        if symbols is not None:
            selected = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
            if not selected:
                return {}
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            if selected is None:
                rows = conn.execute("SELECT symbol, listing_date, delisted_date, status FROM symbol_lifecycle").fetchall()
            else:
                marks = ",".join("?" for _ in selected)
                rows = conn.execute(
                    f"SELECT symbol, listing_date, delisted_date, status FROM symbol_lifecycle WHERE symbol IN ({marks})",
                    tuple(sorted(selected)),
                ).fetchall()
        return {
            str(row["symbol"]): {
                "listing_date": row["listing_date"],
                "delisted_date": row["delisted_date"],
                "status": row["status"],
            }
            for row in rows
        }

    def read_delisted_symbols(self) -> set[str]:
        """Symbols whose lifecycle record marks them delisted (delisted_date set)."""
        with sqlite3.connect(self.sqlite_path) as conn:
            rows = conn.execute(
                "SELECT symbol FROM symbol_lifecycle WHERE delisted_date IS NOT NULL OR status = 'delisted'"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def read_capital_flow_missing_symbols(self, start_date: str, end_date: str) -> set[str]:
        """Return symbols whose rows in the latest daily-bars partition have no
        ``main_net_inflow`` value within ``[start_date, end_date]``.

        Rows outside a symbol's ``symbol_lifecycle`` window (before listing /
        after delisting) are ignored, so a delisted stock no longer reports its
        post-delisting dates as missing. Symbols without a lifecycle record
        keep the conservative legacy behaviour.

        Encapsulates the parquet layout so HTTP/service layers do not need to
        know how daily bars are stored.
        """
        paths = sorted(self.daily_bars_root.glob("year=*/daily_bars.parquet"))
        if not paths:
            return set()
        latest_path = paths[-1]
        columns_to_read = ["symbol", "trade_date", "main_net_inflow"]
        try:
            available = set(pq.ParquetFile(latest_path).schema_arrow.names)
        except FileNotFoundError:
            return set()
        columns_to_read = [column for column in columns_to_read if column in available]
        if "symbol" not in columns_to_read or "main_net_inflow" not in columns_to_read:
            return set()
        frame = self._safe_read_parquet(latest_path, columns=columns_to_read)
        if frame.empty:
            return set()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame = frame.dropna(subset=["trade_date"])
        frame = frame[frame["trade_date"] >= pd.Timestamp(start_date)]
        frame = frame[frame["trade_date"] <= pd.Timestamp(end_date)]
        if frame.empty:
            return set()
        lifecycle = self.read_symbol_lifecycle(
            [str(symbol) for symbol in frame["symbol"].dropna().astype(str).unique()]
        )
        if lifecycle:
            listing_by_symbol = frame["symbol"].astype(str).map(
                lambda symbol: _lifecycle_bound(lifecycle.get(symbol), "listing_date")
            )
            delisted_by_symbol = frame["symbol"].astype(str).map(
                lambda symbol: _lifecycle_bound(lifecycle.get(symbol), "delisted_date")
            )
            in_window = (
                (listing_by_symbol.isna() | (frame["trade_date"] >= listing_by_symbol))
                & (delisted_by_symbol.isna() | (frame["trade_date"] <= delisted_by_symbol))
            )
            frame = frame.loc[in_window]
        if frame.empty:
            return set()
        has_any_flow = frame.groupby(frame["symbol"].astype(str))["main_net_inflow"].any()
        return set(has_any_flow[~has_any_flow].index)

    def _safe_read_parquet(self, path: Path, **kwargs) -> pd.DataFrame:
        try:
            return pd.read_parquet(path, **kwargs)
        except FileNotFoundError:
            return pd.DataFrame()


def _require_ohlc_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    if not all(column in frame for column in OHLC_COLUMNS):
        return pd.DataFrame()
    return frame.dropna(subset=OHLC_COLUMNS)


def _clean_lifecycle_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return None
    return text[:10]


def lifecycle_bound(record: dict[str, str | None] | None, key: str) -> pd.Timestamp | None:
    """Parse a lifecycle date field (``listing_date``/``delisted_date``) into a
    ``pd.Timestamp``; returns ``None`` for missing records or values."""
    if not record:
        return None
    raw = record.get(key)
    if not raw:
        return None
    try:
        return pd.Timestamp(str(raw)[:10])
    except ValueError:
        return None


_lifecycle_bound = lifecycle_bound


def uses_symbol_capital_flow_source_start(
    symbol: str,
    flow_start: pd.Timestamp,
    first_daily_date: pd.Timestamp | None = None,
    warehouse_start: pd.Timestamp | None = None,
) -> bool:
    if (
        symbol in KNOWN_CAPITAL_FLOW_SOURCE_START_SYMBOLS
        or symbol.startswith(KNOWN_CAPITAL_FLOW_SOURCE_START_SYMBOL_PREFIXES)
        or pd.Timestamp(flow_start) in KNOWN_CAPITAL_FLOW_SOURCE_START_DATES
    ):
        return True
    if first_daily_date is None or warehouse_start is None:
        return False
    first_daily = pd.Timestamp(first_daily_date)
    start = pd.Timestamp(warehouse_start)
    if first_daily <= start:
        return False
    lag_days = (pd.Timestamp(flow_start) - first_daily).days
    return 0 <= lag_days <= KNOWN_CAPITAL_FLOW_LISTING_LAG_DAYS
