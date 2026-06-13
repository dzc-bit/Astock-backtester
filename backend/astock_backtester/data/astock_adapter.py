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
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
BAIDU_KLINE_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"
SINA_KLINE_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData"


class AStockDataUnavailable(RuntimeError):
    pass


DailyBarsFetcher = Callable[[Sequence[str], str, str], pd.DataFrame]
JsonGetter = Callable[[str, dict[str, str], dict[str, str], int], dict[str, Any]]
TextGetter = Callable[[str, dict[str, str], dict[str, str], int], str]
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


def _tencent_symbol(code: str) -> str:
    return ("sh" if _market_code(code) == 1 else "sz") + code


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


def _default_json_get(url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=headers, timeout=timeout, proxies={})
    response.raise_for_status()
    return json.loads(response.text)


def _default_text_get(url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> str:
    response = requests.get(url, params=params, headers=headers, timeout=timeout, proxies={})
    response.raise_for_status()
    return response.text


def _curl_cffi_json_get(url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    try:
        from curl_cffi import requests as curl_requests
    except Exception as exc:
        raise AStockDataUnavailable(f"curl_cffi is not available: {exc}") from exc

    response = curl_requests.get(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        impersonate="chrome124",
    )
    response.raise_for_status()
    return json.loads(response.text)


def _is_remote_disconnect(exc: Exception) -> bool:
    text = repr(exc).lower()
    return any(marker in text for marker in ("remote", "connection", "closed", "disconnect", "reset"))


class HttpAStockFetcher:
    """HTTP subset learned from simonlin1212/a-stock-data for daily backtest cache fills."""

    def __init__(
        self,
        json_get: JsonGetter | None = None,
        text_get: TextGetter | None = None,
        eastmoney_json_getters: JsonGetterVariants | None = None,
        include_optional_enrichment: bool = True,
    ) -> None:
        self._json_get = json_get or _default_json_get
        self._text_get = text_get
        self._include_optional_enrichment = include_optional_enrichment
        if eastmoney_json_getters is not None:
            self._eastmoney_json_getters = tuple(eastmoney_json_getters)
        elif json_get is None:
            self._eastmoney_json_getters: JsonGetterVariants = (
                ("requests", _default_json_get),
                ("curl_cffi", _curl_cffi_json_get),
            )
        else:
            self._eastmoney_json_getters = (("injected", json_get),)
        self._skip_eastmoney_kline = False

    def fetch_daily_bars(self, symbols: Sequence[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = [self._fetch_one(symbol, start_date, end_date) for symbol in symbols]
        rows = [frame for frame in frames if not frame.empty]
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True)

    def _fetch_one(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        code = _normalize_code(symbol)
        bars = self._try_fetch_sina_kline(code, start_date, end_date)
        if bars.empty:
            bars = self._try_fetch_tencent_kline(code, start_date, end_date)
        if bars.empty and not self._skip_eastmoney_kline:
            bars = self._try_fetch_eastmoney_kline(code, start_date, end_date)
        if bars.empty:
            bars = self._fetch_baidu_kline(code, start_date, end_date)
        if bars.empty:
            return bars
        if not self._include_optional_enrichment:
            return bars

        info = self._try_fetch_eastmoney_stock_info(code)
        flow_by_date = {item["date"]: item["main_net"] for item in self._try_fetch_eastmoney_fund_flow_120d(code)}
        bars["main_net_inflow"] = bars["trade_date"].dt.strftime("%Y-%m-%d").map(flow_by_date)
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

    def _try_fetch_tencent_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            return self._fetch_tencent_kline(code, start_date, end_date)
        except Exception:
            return pd.DataFrame()

    def _try_fetch_sina_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if self._text_get is None:
            return pd.DataFrame()
        try:
            return self._fetch_sina_kline(code, start_date, end_date)
        except Exception:
            return pd.DataFrame()

    def _fetch_sina_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        text = self._text_get(
            SINA_KLINE_URL,
            {"symbol": _tencent_symbol(code), "scale": "240", "ma": "no", "datalen": "320"},
            {
                "User-Agent": UA,
                "Accept": "application/javascript, */*;q=0.8",
                "Referer": "https://finance.sina.com.cn/",
            },
            5,
        )
        start = text.find("([")
        end = text.rfind("])")
        if start < 0 or end <= start:
            return pd.DataFrame()
        items = json.loads(text[start + 1 : end + 1])
        if not isinstance(items, list):
            return pd.DataFrame()
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            trade_date = _parse_date(item.get("day"))
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
                }
            )
        return pd.DataFrame() if not rows else normalize_daily_bars(pd.DataFrame(rows))

    def _fetch_tencent_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        tencent_symbol = _tencent_symbol(code)
        payload = self._json_get(
            TENCENT_KLINE_URL,
            {"param": f"{tencent_symbol},day,{start_date},{end_date},640,qfq"},
            {
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://gu.qq.com/",
            },
            5,
        )
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        item = data.get(tencent_symbol, {}) if isinstance(data, dict) else {}
        rows_data = item.get("qfqday") or item.get("day") if isinstance(item, dict) else []
        if not isinstance(rows_data, list) or not rows_data:
            return pd.DataFrame()
        rows = []
        for row in rows_data:
            if not isinstance(row, list) or len(row) < 6:
                continue
            trade_date = _parse_date(row[0])
            if trade_date is None or not (start_date <= trade_date.isoformat() <= end_date):
                continue
            rows.append(
                {
                    "symbol": code,
                    "trade_date": trade_date.isoformat(),
                    "open": _to_float(row[1]),
                    "close": _to_float(row[2]),
                    "high": _to_float(row[3]),
                    "low": _to_float(row[4]),
                    "volume": _to_float(row[5]),
                }
            )
        return pd.DataFrame() if not rows else normalize_daily_bars(pd.DataFrame(rows))

    def _try_fetch_eastmoney_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            return self._fetch_eastmoney_kline(code, start_date, end_date)
        except Exception as exc:
            if _is_remote_disconnect(exc):
                self._skip_eastmoney_kline = True
            return pd.DataFrame()

    def _fetch_eastmoney_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        params = {
            "secid": f"{_market_code(code)}.{code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "beg": start_date.replace("-", ""),
            "end": end_date.replace("-", ""),
            "lmt": "1000000",
        }
        headers = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close",
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }
        last_error: Exception | None = None
        for _label, json_get in self._eastmoney_json_getters:
            try:
                payload = json_get(EASTMONEY_KLINE_URL, params, headers, 5)
                break
            except Exception as exc:
                last_error = exc
        else:
            if last_error is not None:
                raise last_error
            return pd.DataFrame()
        klines = payload.get("data", {}).get("klines", []) if isinstance(payload, dict) else []
        if not isinstance(klines, list) or not klines:
            return pd.DataFrame()
        rows = []
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 7:
                continue
            trade_date = _parse_date(parts[0])
            if trade_date is None or not (start_date <= trade_date.isoformat() <= end_date):
                continue
            rows.append(
                {
                    "symbol": code,
                    "trade_date": trade_date.isoformat(),
                    "open": _to_float(parts[1]),
                    "close": _to_float(parts[2]),
                    "high": _to_float(parts[3]),
                    "low": _to_float(parts[4]),
                    "volume": _to_float(parts[5]),
                    "amount": _to_float(parts[6]),
                    "change_pct": _to_float(parts[8]) if len(parts) > 8 else 0.0,
                    "change": _to_float(parts[9]) if len(parts) > 9 else 0.0,
                    "turnover_rate": _to_float(parts[10]) if len(parts) > 10 else 0.0,
                }
            )
        return pd.DataFrame() if not rows else normalize_daily_bars(pd.DataFrame(rows))

    def _fetch_baidu_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        market_data: dict[str, Any] = {}
        for attempt in range(3):
            payload = self._json_get(
                BAIDU_KLINE_URL,
                {
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
                },
                {
                    "User-Agent": UA,
                    "Accept": "application/vnd.finance-web.v1+json",
                    "Origin": "https://gushitong.baidu.com",
                    "Referer": "https://gushitong.baidu.com/",
                },
                5,
            )
            result_code = str(payload.get("ResultCode", "")) if isinstance(payload, dict) else ""
            if result_code in {"403", "401", "429"}:
                break
            result = payload.get("Result") if isinstance(payload, dict) else None
            if isinstance(result, dict):
                market_data = result.get("newMarketData", {}) or {}
                break
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
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

    def _fetch_eastmoney_fund_flow_120d(self, code: str) -> list[dict[str, Any]]:
        payload = self._json_get(
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
        payload = self._json_get(
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
    def from_http_sources(cls, *, include_optional_enrichment: bool = True) -> "AStockDataAdapter":
        return cls(
            fetcher=HttpAStockFetcher(
                text_get=_default_text_get,
                include_optional_enrichment=include_optional_enrichment,
            ).fetch_daily_bars
        )

    def fetch_daily_bars(self, symbols: Sequence[str], start_date: str, end_date: str) -> pd.DataFrame:
        if self.fetcher is None:
            raise AStockDataUnavailable(
                "a-stock-data fetcher is not configured. Configure a fetcher that returns daily OHLCV, "
                "market cap, turnover, and capital-flow columns."
            )
        frame = self.fetcher(symbols, start_date, end_date)
        return frame if frame.empty else normalize_daily_bars(frame)
