from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
import json
import time
from typing import Any

import pandas as pd
import requests

from astock_backtester.data.importer import normalize_daily_bars


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class AStockDataUnavailable(RuntimeError):
    pass


DailyBarsFetcher = Callable[[Sequence[str], str, str], pd.DataFrame]
JsonGetter = Callable[[str, dict[str, str], dict[str, str], int], dict[str, Any]]
JsonGetterVariants = Sequence[tuple[str, JsonGetter]]


def _normalize_code(symbol: str) -> str:
    code = symbol.strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        code = code[2:]
    if "." in code:
        code = code.split(".", 1)[0]
    return code


def _market_code(code: str) -> int:
    return 1 if code.startswith(("6", "9")) else 0


def _to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "-", "--"):
        return default
    return float(str(value).replace("+", "").replace("%", ""))


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt).date()
        except ValueError:
            continue
    return None


def _should_retry_baidu_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    result_code = str(payload.get("ResultCode") or "")
    result = payload.get("Result")
    return result_code in {"403", "429"} or result == []


def _default_json_get(url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=headers, timeout=timeout, proxies={})
    response.raise_for_status()
    return json.loads(response.text)


def _curl_cffi_json_get(url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    from curl_cffi import requests as curl_requests

    response = curl_requests.get(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        impersonate="chrome124",
    )
    response.raise_for_status()
    return json.loads(response.text)


class HttpAStockFetcher:
    """HTTP subset learned from simonlin1212/a-stock-data for daily backtest cache fills."""

    def __init__(self, json_get: JsonGetter | None = None, json_gets: JsonGetterVariants | None = None) -> None:
        if json_gets is not None:
            self._json_gets = tuple(json_gets)
        elif json_get is not None:
            self._json_gets = (("injected", json_get),)
        else:
            self._json_gets = (("requests", _default_json_get), ("curl_cffi", _curl_cffi_json_get))

    def fetch_daily_bars(self, symbols: Sequence[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = [self._fetch_one(symbol, start_date, end_date) for symbol in symbols]
        rows = [frame for frame in frames if not frame.empty]
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True)

    def _fetch_one(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        code = _normalize_code(symbol)
        bars = self._fetch_baidu_kline(code, start_date, end_date)
        if bars.empty:
            return bars

        info = self._try_fetch_eastmoney_stock_info(code)
        flow_by_date = {item["date"]: item["main_net"] for item in self._try_fetch_eastmoney_fund_flow_120d(code)}
        bars["main_net_inflow"] = bars["trade_date"].dt.strftime("%Y-%m-%d").map(flow_by_date)
        name = str(info.get("name") or "").strip()
        if name:
            bars["name"] = name
        float_market_cap = _to_float(info.get("float_mcap"), float("nan"))
        if float_market_cap > 0:
            bars["float_market_cap"] = float_market_cap
        list_date = _parse_date(info.get("list_date"))
        if list_date is None:
            bars["listing_days"] = 9999
        else:
            bars["listing_days"] = (bars["trade_date"].dt.date - list_date).map(lambda delta: delta.days)
        return bars

    def _try_fetch_eastmoney_fund_flow_120d(self, code: str) -> list[dict[str, Any]]:
        try:
            return self._fetch_eastmoney_fund_flow_120d(code)
        except Exception:
            return []

    def _try_fetch_eastmoney_stock_info(self, code: str) -> dict[str, Any]:
        try:
            return self._fetch_eastmoney_stock_info(code)
        except Exception:
            return {}

    def _fetch_baidu_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        market_data = self._fetch_baidu_market_data(code, start_date)
        if not market_data:
            return pd.DataFrame()
        keys = list(market_data.get("keys") or [])
        rows = []
        for raw_row in str(market_data.get("marketData") or "").split(";"):
            if not raw_row.strip():
                continue
            values = raw_row.split(",")
            item = dict(zip(keys, values, strict=False))
            trade_date = _parse_date(item.get("time"))
            if trade_date is None or not (start_date <= trade_date.isoformat() <= end_date):
                continue
            rows.append(
                {
                    "symbol": code,
                    "trade_date": trade_date.isoformat(),
                    "open": _to_float(item.get("open")),
                    "high": _to_float(item.get("high")),
                    "low": _to_float(item.get("low")),
                    "close": _to_float(item.get("close")),
                    "volume": _to_float(item.get("volume")),
                    "amount": _to_float(item.get("amount")),
                    "change": _to_float(item.get("range")),
                    "change_pct": _to_float(item.get("ratio")),
                    "turnover_rate": _to_float(item.get("turnoverratio")),
                    "pre_close": _to_float(item.get("preClose"), float("nan")),
                }
            )
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        turnover = pd.to_numeric(frame["turnover_rate"], errors="coerce")
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        close = pd.to_numeric(frame["close"], errors="coerce")
        frame["float_market_cap"] = (volume / (turnover / 100.0)) * close
        frame.loc[turnover <= 0, "float_market_cap"] = float("nan")
        return normalize_daily_bars(frame)

    def _fetch_baidu_market_data(self, code: str, start_date: str) -> dict[str, Any]:
        params = {
            "all": "1",
            "isIndex": "false",
            "isBk": "false",
            "isBlock": "false",
            "isFutures": "false",
            "isStock": "true",
            "newFormat": "1",
            "group": "quotation_kline_ab",
            "finClientType": "pc",
            "code": code,
            "start_time": start_date,
            "ktype": "1",
        }
        headers = {
            "User-Agent": UA,
            "Accept": "application/vnd.finance-web.v1+json",
            "Origin": "https://gushitong.baidu.com",
            "Referer": "https://gushitong.baidu.com/",
        }
        for label, json_get in self._json_gets:
            for attempt in range(2):
                try:
                    payload = json_get(
                        "https://finance.pae.baidu.com/selfselect/getstockquotation",
                        params,
                        headers,
                        8,
                    )
                except Exception:
                    break
                result = payload.get("Result") if isinstance(payload, dict) else None
                if isinstance(result, dict):
                    return result.get("newMarketData", {}) or {}
                if not _should_retry_baidu_payload(payload):
                    break
                if label != "injected":
                    break
                if attempt == 0 and label == "injected":
                    time.sleep(0.2)
            if label != "injected":
                continue
        return {}

    def _request_json(self, url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
        last_error: Exception | None = None
        for _label, json_get in self._json_gets:
            try:
                return json_get(url, params, headers, timeout)
            except Exception as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return {}

    def _fetch_eastmoney_fund_flow_120d(self, code: str) -> list[dict[str, Any]]:
        payload = self._request_json(
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
            {
                "secid": f"{_market_code(code)}.{code}",
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                "lmt": "120",
            },
            {
                "User-Agent": UA,
                "Referer": "https://quote.eastmoney.com/",
                "Origin": "https://quote.eastmoney.com",
            },
            15,
        )
        rows = []
        for line in payload.get("data", {}).get("klines", []) or []:
            parts = str(line).split(",")
            if len(parts) >= 2:
                rows.append({"date": parts[0], "main_net": _to_float(parts[1])})
        return rows

    def _fetch_eastmoney_stock_info(self, code: str) -> dict[str, Any]:
        payload = self._request_json(
            "https://push2.eastmoney.com/api/qt/stock/get",
            {
                "fltt": "2",
                "invt": "2",
                "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
                "secid": f"{_market_code(code)}.{code}",
            },
            {"User-Agent": UA},
            10,
        )
        data = payload.get("data", {}) or {}
        return {
            "code": data.get("f57", ""),
            "name": data.get("f58", ""),
            "industry": data.get("f127", ""),
            "total_shares": data.get("f84", 0),
            "float_shares": data.get("f85", 0),
            "mcap": data.get("f116", 0),
            "float_mcap": data.get("f117", 0),
            "list_date": data.get("f189", ""),
            "price": data.get("f43", 0),
        }


class AStockDataAdapter:
    def __init__(self, fetcher: DailyBarsFetcher | None = None) -> None:
        self.fetcher = fetcher

    @classmethod
    def from_http_sources(cls) -> "AStockDataAdapter":
        return cls(fetcher=HttpAStockFetcher().fetch_daily_bars)

    def fetch_daily_bars(self, symbols: Sequence[str], start_date: str, end_date: str) -> pd.DataFrame:
        if self.fetcher is None:
            raise AStockDataUnavailable(
                "a-stock-data fetcher is not configured. Configure a fetcher that returns daily OHLCV, "
                "market cap, turnover, and capital-flow columns."
            )
        frame = self.fetcher(symbols, start_date, end_date)
        return frame if frame.empty else normalize_daily_bars(frame)
