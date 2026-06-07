from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd

from astock_backtester.data.cache import LocalCache
from astock_backtester.data.trading_calendar import a_share_trade_dates
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import (
    DailyBarsCoverageItem,
    DailyBarsCoverageResponse,
    DataOperationResult,
    DatasetCoverage,
    ServiceHealth,
    ServiceLogEntry,
)


DailyBarsFetcher = Callable[[Sequence[str], str, str], pd.DataFrame]


def _date_range(start_date: pd.Timestamp, end_date: pd.Timestamp) -> set[pd.Timestamp]:
    return a_share_trade_dates(start_date, end_date)


def build_daily_bars_coverage(
    cache: LocalCache,
    warehouse: Warehouse | None = None,
    symbols: Sequence[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> DailyBarsCoverageResponse:
    bars = pd.DataFrame()
    used_warehouse = False
    if warehouse is not None:
        try:
            bars = warehouse.read_daily_bars(symbols=symbols, start_date=start_date, end_date=end_date)
            used_warehouse = not bars.empty
        except Exception:
            bars = pd.DataFrame()
            used_warehouse = False
    if bars.empty:
        bars = cache.read_daily_bars()
    if bars.empty:
        return DailyBarsCoverageResponse(items=[])

    if not used_warehouse and symbols:
        selected_symbols = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
        if selected_symbols:
            bars = bars.loc[bars["symbol"].astype(str).isin(selected_symbols)]
    if not used_warehouse and start_date:
        bars = bars.loc[bars["trade_date"] >= pd.Timestamp(start_date)]
    if not used_warehouse and end_date:
        bars = bars.loc[bars["trade_date"] <= pd.Timestamp(end_date)]
    if bars.empty:
        return DailyBarsCoverageResponse(items=[])

    items = []
    for symbol, frame in bars.groupby("symbol", sort=True):
        frame = frame.sort_values("trade_date")
        start_date = frame["trade_date"].min()
        end_date = frame["trade_date"].max()
        present_dates = set(frame["trade_date"])
        expected_dates = _date_range(start_date, end_date)
        missing_trade_dates = sorted(expected_dates - present_dates)
        items.append(
            DailyBarsCoverageItem(
                symbol=str(symbol),
                start_date=start_date.date(),
                end_date=end_date.date(),
                rows=int(len(frame)),
                missing_trade_dates=[item.date() for item in missing_trade_dates],
                missing_capital_flow_dates=[
                    item.date()
                    for item in frame.loc[frame["main_net_inflow"].isna(), "trade_date"].tolist()
                ],
                missing_market_cap_dates=[
                    item.date()
                    for item in frame.loc[frame["float_market_cap"].isna(), "trade_date"].tolist()
                ],
            )
        )
    return DailyBarsCoverageResponse(items=items)


def import_daily_bars_into_cache(
    cache: LocalCache,
    frame: pd.DataFrame,
    source: str,
    warehouse: Warehouse | None = None,
) -> DataOperationResult:
    cache.write_daily_bars(frame)
    if warehouse is not None:
        warehouse.write_daily_bars(frame)
    coverage = _safe_coverage(cache, warehouse)
    return DataOperationResult(
        status="ok",
        imported_rows=int(len(frame)),
        coverage=coverage,
        logs=[ServiceLogEntry(level="info", message=f"Imported daily bars from {source}")],
    )


def fetch_daily_bars_into_cache(
    cache: LocalCache,
    fetcher: DailyBarsFetcher,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    warehouse: Warehouse | None = None,
) -> DataOperationResult:
    requested_symbols = [str(symbol) for symbol in symbols]
    frame = fetcher(requested_symbols, start_date, end_date)
    if frame.empty:
        fetched_symbols: list[str] = []
    else:
        cache.write_daily_bars(frame)
        if warehouse is not None:
            warehouse.write_daily_bars(frame)
        fetched_symbols = sorted(frame["symbol"].astype(str).unique().tolist())
    missing_symbols = sorted(symbol for symbol in requested_symbols if symbol not in fetched_symbols)
    logs = [ServiceLogEntry(level="info", message=f"Fetched {len(frame)} daily bar rows")]
    if missing_symbols:
        logs.append(ServiceLogEntry(level="warning", message=f"Missing symbols: {', '.join(missing_symbols)}"))
    coverage = _safe_coverage(cache, warehouse)
    return DataOperationResult(
        status="partial" if missing_symbols else "ok",
        imported_rows=int(len(frame)),
        requested_symbols=requested_symbols,
        fetched_symbols=fetched_symbols,
        missing_symbols=missing_symbols,
        coverage=coverage,
        logs=logs,
    )


def _safe_coverage(cache: LocalCache, warehouse: Warehouse | None) -> list[DatasetCoverage]:
    if warehouse is not None:
        try:
            coverage = warehouse.coverage()
            if any(item.symbols > 0 for item in coverage):
                return coverage
        except Exception:
            pass
    try:
        return cache.coverage()
    except Exception:
        return [
            DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None),
            DatasetCoverage(dataset="market_cap", symbols=0, start_date=None, end_date=None),
            DatasetCoverage(dataset="capital_flow", symbols=0, start_date=None, end_date=None),
        ]


def build_service_health(cache: LocalCache, warehouse: Warehouse, port: int | None = None) -> ServiceHealth:
    try:
        coverage = warehouse.coverage()
    except Exception:
        coverage = []
    if not any(item.symbols > 0 for item in coverage):
        try:
            coverage = cache.coverage()
        except Exception:
            coverage = [
                DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="market_cap", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="capital_flow", symbols=0, start_date=None, end_date=None),
            ]
    return ServiceHealth(
        ok=True,
        cache_path=str(cache.root.resolve()),
        port=port,
        coverage=coverage,
    )
