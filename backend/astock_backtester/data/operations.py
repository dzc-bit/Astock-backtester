from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd

from astock_backtester.data.cache import LocalCache
from astock_backtester.data.importer import normalize_daily_bars
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
CapitalFlowFetcher = Callable[[Sequence[str], str, str], dict[str, Any]]


def _date_range(start_date: pd.Timestamp, end_date: pd.Timestamp) -> set[pd.Timestamp]:
    return a_share_trade_dates(start_date, end_date)


def build_daily_bars_coverage(
    cache: LocalCache,
    warehouse: Warehouse | None = None,
    symbols: Sequence[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> DailyBarsCoverageResponse:
    requested_start_date = pd.Timestamp(start_date) if start_date else None
    requested_end_date = pd.Timestamp(end_date) if end_date else None
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
        data_start_date = frame["trade_date"].min()
        data_end_date = frame["trade_date"].max()
        coverage_start_date = requested_start_date if requested_start_date is not None else data_start_date
        coverage_end_date = requested_end_date if requested_end_date is not None else data_end_date
        present_dates = set(frame["trade_date"])
        expected_dates = _date_range(coverage_start_date, coverage_end_date)
        missing_trade_dates = sorted(expected_dates - present_dates)
        items.append(
            DailyBarsCoverageItem(
                symbol=str(symbol),
                start_date=data_start_date.date(),
                end_date=data_end_date.date(),
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
    capital_flow_fetcher: CapitalFlowFetcher | None = None,
) -> DataOperationResult:
    requested_symbols = [str(symbol) for symbol in symbols]
    frame = fetcher(requested_symbols, start_date, end_date)
    logs = [ServiceLogEntry(level="info", message=f"Fetched {len(frame)} daily bar rows")]
    diagnostics: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    capital_flow_missing_symbols: list[str] = []
    if not frame.empty and capital_flow_fetcher is not None:
        frame, merge_logs, merge_diagnostics, failures, _ = _merge_capital_flow_from_fetcher(
            frame=frame,
            fetcher=capital_flow_fetcher,
            requested_symbols=requested_symbols,
            start_date=start_date,
            end_date=end_date,
            only_missing=False,
        )
        logs.extend(merge_logs)
        diagnostics.extend(merge_diagnostics)
        capital_flow_missing_symbols = _symbols_with_missing_main_net_inflow(frame, requested_symbols)
        if capital_flow_missing_symbols:
            diagnostics.append(
                {
                    "code": "capital_flow_crawler_unfilled_main_net_inflow",
                    "source": "capital_flow_crawler",
                    "symbols": capital_flow_missing_symbols,
                    "start_date": start_date,
                    "end_date": end_date,
                    "message": "Capital-flow crawler did not fill main_net_inflow for all fetched daily-bar rows",
                }
            )
            logs.append(
                ServiceLogEntry(
                    level="warning",
                    message=f"Capital-flow crawler left missing main_net_inflow for symbols: {', '.join(capital_flow_missing_symbols)}",
                )
            )
    if frame.empty:
        fetched_symbols: list[str] = []
    else:
        cache.write_daily_bars(frame)
        if warehouse is not None:
            warehouse.write_daily_bars(frame)
        fetched_symbols = sorted(frame["symbol"].astype(str).unique().tolist())
    missing_symbols = sorted(
        {
            *(symbol for symbol in requested_symbols if symbol not in fetched_symbols),
            *capital_flow_missing_symbols,
        }
    )
    if capital_flow_fetcher is not None and frame.empty:
        diagnostics.append(
            {
                "code": "capital_flow_crawler_skipped",
                "reason": "no_daily_bar_rows",
                "source": "capital_flow_crawler",
            }
        )
    if missing_symbols:
        logs.append(ServiceLogEntry(level="warning", message=f"Missing symbols: {', '.join(missing_symbols)}"))
    if failures:
        failed_symbols = sorted({str(item.get("symbol", "")) for item in failures if item.get("symbol")})
        if failed_symbols:
            logs.append(
                ServiceLogEntry(
                    level="warning",
                    message=f"Capital-flow crawler failed for symbols: {', '.join(failed_symbols)}",
                )
            )
    coverage = _safe_coverage(cache, warehouse)
    return DataOperationResult(
        status="partial" if missing_symbols or failures else "ok",
        imported_rows=int(len(frame)),
        requested_symbols=requested_symbols,
        fetched_symbols=fetched_symbols,
        missing_symbols=missing_symbols,
        coverage=coverage,
        logs=logs,
        diagnostics=diagnostics,
        failures=failures,
    )


def fetch_capital_flow_into_cache(
    cache: LocalCache,
    capital_flow_fetcher: CapitalFlowFetcher,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    warehouse: Warehouse | None = None,
) -> DataOperationResult:
    requested_symbols = [str(symbol) for symbol in symbols]
    frame = _read_existing_daily_bars(cache, warehouse, requested_symbols, start_date, end_date)
    logs: list[ServiceLogEntry] = []
    diagnostics: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if frame.empty:
        coverage = _safe_coverage(cache, warehouse)
        return DataOperationResult(
            status="partial",
            imported_rows=0,
            requested_symbols=requested_symbols,
            fetched_symbols=[],
            missing_symbols=requested_symbols,
            coverage=coverage,
            logs=[ServiceLogEntry(level="warning", message="No existing daily bars found for capital-flow backfill")],
            diagnostics=[
                {
                    "code": "capital_flow_backfill_no_daily_rows",
                    "source": "capital_flow_crawler",
                    "requested_symbols": len(requested_symbols),
                }
            ],
        )

    existing_symbols = {str(symbol) for symbol in frame["symbol"].dropna().astype(str).unique()}
    symbols_without_daily_rows = sorted(symbol for symbol in requested_symbols if symbol not in existing_symbols)
    if symbols_without_daily_rows:
        diagnostics.extend(
            {
                "code": "capital_flow_backfill_no_daily_rows_for_symbol",
                "source": "capital_flow_crawler",
                "symbol": symbol,
                "message": f"No existing daily bars found for {symbol}; capital-flow backfill skipped for that symbol",
            }
            for symbol in symbols_without_daily_rows
        )

    candidate_frame = frame
    if "main_net_inflow" in candidate_frame.columns:
        candidate_frame = candidate_frame.loc[candidate_frame["main_net_inflow"].isna()]
    if candidate_frame.empty:
        coverage = _safe_coverage(cache, warehouse)
        missing_symbols = symbols_without_daily_rows
        if missing_symbols:
            logs.append(
                ServiceLogEntry(
                    level="warning",
                    message=f"Missing daily bars for capital-flow symbols: {', '.join(missing_symbols)}",
                )
            )
        return DataOperationResult(
            status="partial" if missing_symbols else "ok",
            imported_rows=0,
            requested_symbols=requested_symbols,
            fetched_symbols=[],
            missing_symbols=missing_symbols,
            coverage=coverage,
            logs=[
                ServiceLogEntry(level="info", message="Capital-flow coverage already complete for requested rows"),
                *logs,
            ],
            diagnostics=[
                {
                    "code": "capital_flow_backfill_not_needed",
                    "source": "capital_flow_crawler",
                    "requested_symbols": len(requested_symbols),
                },
                *diagnostics,
            ],
        )

    fetch_symbols = sorted(candidate_frame["symbol"].astype(str).unique().tolist())
    merged_frame, merge_logs, merge_diagnostics, failures, fetched_symbols = _merge_capital_flow_from_fetcher(
        frame=frame,
        fetcher=capital_flow_fetcher,
        requested_symbols=fetch_symbols,
        start_date=start_date,
        end_date=end_date,
        only_missing=True,
    )
    logs.extend(merge_logs)
    diagnostics.extend(merge_diagnostics)

    if fetched_symbols:
        cache.write_daily_bars(merged_frame)
        if warehouse is not None:
            warehouse.write_daily_bars(merged_frame)

    missing_symbols = sorted(
        {
            *(symbol for symbol in fetch_symbols if symbol not in fetched_symbols),
            *symbols_without_daily_rows,
        }
    )
    if failures:
        failed_symbols = sorted({str(item.get("symbol", "")) for item in failures if item.get("symbol")})
        if failed_symbols:
            logs.append(
                ServiceLogEntry(
                    level="warning",
                    message=f"Capital-flow crawler failed for symbols: {', '.join(failed_symbols)}",
                )
            )
    if missing_symbols:
        logs.append(ServiceLogEntry(level="warning", message=f"Missing capital-flow symbols: {', '.join(missing_symbols)}"))
    coverage = _safe_coverage(cache, warehouse)
    return DataOperationResult(
        status="partial" if missing_symbols or failures else "ok",
        imported_rows=int(_count_merged_main_net_inflow(frame, merged_frame, only_missing=True)),
        requested_symbols=requested_symbols,
        fetched_symbols=fetched_symbols,
        missing_symbols=missing_symbols,
        coverage=coverage,
        logs=logs,
        diagnostics=diagnostics,
        failures=failures,
    )


def _read_existing_daily_bars(
    cache: LocalCache,
    warehouse: Warehouse | None,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if warehouse is not None:
        try:
            warehouse_frame = warehouse.read_daily_bars(symbols=symbols, start_date=start_date, end_date=end_date)
            if not warehouse_frame.empty:
                frames.append(warehouse_frame)
        except Exception:
            pass
    cache_frame = cache.read_daily_bars()
    if not cache_frame.empty:
        selected = {str(symbol) for symbol in symbols}
        cache_frame = cache_frame.loc[cache_frame["symbol"].astype(str).isin(selected)]
        cache_frame = cache_frame.loc[cache_frame["trade_date"] >= pd.Timestamp(start_date)]
        cache_frame = cache_frame.loc[cache_frame["trade_date"] <= pd.Timestamp(end_date)]
        if not cache_frame.empty:
            frames.append(cache_frame)
    if not frames:
        return pd.DataFrame()
    frame = normalize_daily_bars(pd.concat(frames, ignore_index=True))
    frame = frame.drop_duplicates(["symbol", "trade_date"], keep="first")
    return frame.reset_index(drop=True)


def _merge_capital_flow_from_fetcher(
    frame: pd.DataFrame,
    fetcher: CapitalFlowFetcher,
    requested_symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    only_missing: bool,
) -> tuple[pd.DataFrame, list[ServiceLogEntry], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    logs: list[ServiceLogEntry] = []
    diagnostics: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        result = fetcher(list(requested_symbols), start_date, end_date)
    except Exception as exc:
        failure = {"code": "capital_flow_crawler_error", "error": str(exc), "source": "capital_flow_crawler"}
        failures.append(failure)
        diagnostics.append({**failure, "message": str(exc)})
        logs.append(ServiceLogEntry(level="warning", message=f"Capital-flow crawler failed: {exc}"))
        return frame, logs, diagnostics, failures, []

    rows = result.get("rows", []) if isinstance(result, dict) else []
    raw_failures = result.get("failures", []) if isinstance(result, dict) else []
    raw_diagnostics = result.get("diagnostics", []) if isinstance(result, dict) else []
    failures = [item for item in raw_failures if isinstance(item, dict)]
    diagnostics.extend(item for item in raw_diagnostics if isinstance(item, dict))
    merged_frame, merged_rows, fetched_symbols = _merge_capital_flow_rows(frame, rows, only_missing=only_missing)
    logs.append(
        ServiceLogEntry(
            level="warning" if merged_rows == 0 else "info",
            message=f"Capital-flow crawler merged {merged_rows} rows as primary main_net_inflow source",
        )
    )
    diagnostics.append(
        {
            "code": "capital_flow_crawler_merge",
            "requested_symbols": len(list(requested_symbols)),
            "merged_rows": merged_rows,
            "source": "capital_flow_crawler",
        }
    )
    if merged_rows == 0:
        diagnostics.append(
            {
                "code": "capital_flow_crawler_zero_merge",
                "requested_symbols": len(list(requested_symbols)),
                "source": "capital_flow_crawler",
                "message": "Capital-flow crawler returned no rows that could be merged into main_net_inflow",
            }
        )
    return merged_frame, logs, diagnostics, failures, fetched_symbols


def _symbols_with_missing_main_net_inflow(frame: pd.DataFrame, symbols: Sequence[str]) -> list[str]:
    if frame.empty or "main_net_inflow" not in frame.columns:
        return sorted({str(symbol) for symbol in symbols})
    selected = {str(symbol) for symbol in symbols}
    data = frame.loc[frame["symbol"].astype(str).isin(selected)]
    if data.empty:
        return []
    missing = data.loc[data["main_net_inflow"].isna(), "symbol"]
    return sorted({str(symbol) for symbol in missing.tolist()})


def _merge_capital_flow_rows(
    frame: pd.DataFrame,
    rows: Sequence[dict[str, Any]],
    *,
    only_missing: bool,
) -> tuple[pd.DataFrame, int, list[str]]:
    if frame.empty:
        return frame, 0, []
    out = normalize_daily_bars(frame)
    if not rows:
        return out, 0, []
    flow = pd.DataFrame(list(rows))
    if not {"symbol", "trade_date", "main_net_inflow"}.issubset(flow.columns):
        return out, 0, []
    flow = flow[["symbol", "trade_date", "main_net_inflow"]].copy()
    flow["symbol"] = flow["symbol"].astype(str)
    flow["trade_date"] = pd.to_datetime(flow["trade_date"], errors="coerce")
    flow["main_net_inflow"] = pd.to_numeric(flow["main_net_inflow"], errors="coerce")
    flow = flow.dropna(subset=["trade_date", "main_net_inflow"])
    if flow.empty:
        return out, 0, []

    out = out.set_index(["symbol", "trade_date"]).sort_index()
    flow = flow.drop_duplicates(["symbol", "trade_date"], keep="last").set_index(["symbol", "trade_date"]).sort_index()
    common_index = flow.index.intersection(out.index)
    if common_index.empty:
        return out.reset_index(), 0, []
    if only_missing:
        target_index = common_index[out.loc[common_index, "main_net_inflow"].isna().to_numpy()]
    else:
        target_index = common_index
    if target_index.empty:
        return out.reset_index(), 0, []
    out.loc[target_index, "main_net_inflow"] = flow.loc[target_index, "main_net_inflow"]
    fetched_symbols = sorted({str(symbol) for symbol, _date in target_index})
    return out.reset_index().sort_values(["symbol", "trade_date"]).reset_index(drop=True), int(len(target_index)), fetched_symbols


def _count_merged_main_net_inflow(before: pd.DataFrame, after: pd.DataFrame, *, only_missing: bool) -> int:
    if before.empty or after.empty:
        return 0
    left = normalize_daily_bars(before).set_index(["symbol", "trade_date"])
    right = normalize_daily_bars(after).set_index(["symbol", "trade_date"])
    common = left.index.intersection(right.index)
    if common.empty:
        return 0
    before_values = left.loc[common, "main_net_inflow"]
    after_values = right.loc[common, "main_net_inflow"]
    if only_missing:
        return int((before_values.isna() & after_values.notna()).sum())
    return int(after_values.notna().sum())


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
