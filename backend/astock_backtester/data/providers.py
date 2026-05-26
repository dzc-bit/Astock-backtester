from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from astock_backtester.data.astock_adapter import AStockDataAdapter
from astock_backtester.data.importer import normalize_daily_bars


class ProviderError(RuntimeError):
    pass


class DailyDataProvider(Protocol):
    name: str

    def list_symbols(self) -> list[str]:
        ...

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        ...

    def fetch_share_history(self, symbol: str) -> pd.DataFrame:
        ...


def normalize_symbol(symbol: str) -> str:
    code = str(symbol).strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        code = code[2:]
    if "." in code:
        code = code.split(".", 1)[0]
    return code.zfill(6) if code.isdigit() else code


def _unique_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for symbol in symbols:
        code = normalize_symbol(symbol)
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def enrich_market_cap_from_share_history(bars: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    if out.empty:
        return out
    if shares.empty:
        out["float_market_cap"] = float("nan")
        out["total_market_cap"] = float("nan")
        return out

    out["trade_date"] = pd.to_datetime(out["trade_date"])
    share_frame = shares.copy()
    share_frame["change_date"] = pd.to_datetime(share_frame["change_date"])
    share_frame = share_frame.sort_values("change_date")
    merged = pd.merge_asof(
        out.sort_values("trade_date"),
        share_frame[["change_date", "total_shares", "list_a_shares"]].sort_values("change_date"),
        left_on="trade_date",
        right_on="change_date",
        direction="backward",
    )
    merged["float_market_cap"] = pd.to_numeric(merged["list_a_shares"], errors="coerce") * merged["close"]
    merged["total_market_cap"] = pd.to_numeric(merged["total_shares"], errors="coerce") * merged["close"]
    return merged.drop(
        columns=[column for column in ["change_date", "total_shares", "list_a_shares"] if column in merged]
    )


@dataclass
class ADataProvider:
    name: str = "adata"

    def _adata(self):
        import adata

        return adata

    def list_symbols(self) -> list[str]:
        adata = self._adata()
        frame = adata.stock.info.all_code()
        if frame is None or frame.empty:
            return []
        code_column = next(
            (column for column in ["stock_code", "code", "symbol"] if column in frame.columns),
            frame.columns[0],
        )
        return _unique_symbols([str(item) for item in frame[code_column].dropna().tolist()])

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        adata = self._adata()
        code = normalize_symbol(symbol)
        frame = adata.stock.market.get_market(stock_code=code, start_date=start_date, end_date=end_date, k_type=1)
        if frame is None or frame.empty:
            return pd.DataFrame()
        frame = frame.rename(columns={"stock_code": "symbol", "turnover_ratio": "turnover_rate"})
        frame["symbol"] = code
        frame["source"] = self.name
        shares = self.fetch_share_history(code)
        return normalize_daily_bars(enrich_market_cap_from_share_history(frame, shares))

    def fetch_share_history(self, symbol: str) -> pd.DataFrame:
        adata = self._adata()
        code = normalize_symbol(symbol)
        frame = adata.stock.info.get_stock_shares(stock_code=code, is_history=True)
        return pd.DataFrame() if frame is None else frame


@dataclass
class HttpAStockProvider:
    name: str = "http"

    def list_symbols(self) -> list[str]:
        return []

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        frame = AStockDataAdapter.from_http_sources().fetch_daily_bars([symbol], start_date, end_date)
        if frame.empty:
            return frame
        frame["source"] = self.name
        return frame

    def fetch_share_history(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame()


@dataclass
class CompositeProvider:
    providers: list[DailyDataProvider]

    def list_symbols(self) -> list[str]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                symbols = provider.list_symbols()
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            normalized = _unique_symbols(symbols)
            if normalized:
                return normalized
        if errors:
            raise ProviderError("; ".join(errors))
        return []

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        errors: list[str] = []
        for provider in self.providers:
            try:
                frame = provider.fetch_daily_bars(symbol, start_date, end_date)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            if not frame.empty:
                if "source" not in frame.columns:
                    frame["source"] = provider.name
                return normalize_daily_bars(frame)
        if errors:
            raise ProviderError("; ".join(errors))
        return pd.DataFrame()
