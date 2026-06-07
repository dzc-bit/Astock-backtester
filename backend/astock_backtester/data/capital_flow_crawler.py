from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from typing import Any

import requests


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
EASTMONEY_FUND_FLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

FIELDS1 = "f1,f2,f3,f7"
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"

JsonGetter = Callable[[str, dict[str, str], dict[str, str], int], dict[str, Any]]

_HEADER_VARIANTS = (
    {
        "User-Agent": UA,
        "Referer": "https://data.eastmoney.com/zjlx/detail.html",
        "Origin": "https://data.eastmoney.com",
    },
    {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    },
)

_FLOW_COLUMNS = (
    "trade_date",
    "main_net_inflow",
    "small_net_inflow",
    "medium_net_inflow",
    "large_net_inflow",
    "super_large_net_inflow",
    "main_net_inflow_pct",
    "small_net_inflow_pct",
    "medium_net_inflow_pct",
    "large_net_inflow_pct",
    "super_large_net_inflow_pct",
    "close",
    "change_pct",
)


class CapitalFlowFetchError(RuntimeError):
    pass


def _normalize_code(symbol: str) -> str:
    code = str(symbol).strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        code = code[2:]
    if "." in code:
        code = code.split(".", 1)[0]
    return code


def _market_code(code: str) -> int:
    return 1 if code.startswith(("6", "9")) else 0


def _parse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        candidate = text[:10] if fmt == "%Y-%m-%d" else text[:8]
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).strip().replace("+", "").replace("%", "")
    if text in ("", "-", "--"):
        return None
    return float(text)


def _estimate_limit(start_date: str, end_date: str) -> int:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    days = max((end - start).days + 1, 1)
    return max(5, int(days * 1.3))


def _default_json_get(url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=headers, timeout=timeout, proxies={})
    response.raise_for_status()
    return json.loads(response.text)


class CapitalFlowCrawler:
    """Standalone Eastmoney capital-flow crawler for later cache backfills."""

    def __init__(self, json_get: JsonGetter | None = None) -> None:
        self._json_get = json_get or _default_json_get

    def fetch_fund_flow(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        *,
        limit: int | None = None,
        timeout: int = 15,
    ) -> list[dict[str, Any]]:
        code = _normalize_code(symbol)
        request_limit = limit if limit is not None else _estimate_limit(start_date, end_date)
        params = {
            "secid": f"{_market_code(code)}.{code}",
            "fields1": FIELDS1,
            "fields2": FIELDS2,
            "klt": "101",
            "lmt": str(request_limit),
        }
        payload = self._fetch_payload_with_variants(code, params, timeout)
        return _parse_payload(code, payload, start_date, end_date)

    def _fetch_payload_with_variants(self, code: str, params: dict[str, str], timeout: int) -> dict[str, Any]:
        errors: list[str] = []
        for headers in _HEADER_VARIANTS:
            try:
                return self._json_get(EASTMONEY_FUND_FLOW_URL, params, headers, timeout)
            except Exception as exc:
                errors.append(f"{headers['Referer']}: {exc}")
        raise CapitalFlowFetchError(f"Failed to fetch Eastmoney capital flow for {code}: {'; '.join(errors)}")

    def fetch_many_fund_flows(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        *,
        limit: int | None = None,
        timeout: int = 15,
    ) -> dict[str, list[dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for symbol in symbols:
            code = _normalize_code(symbol)
            try:
                rows.extend(
                    self.fetch_fund_flow(
                        code,
                        start_date,
                        end_date,
                        limit=limit,
                        timeout=timeout,
                    )
                )
            except CapitalFlowFetchError as exc:
                failures.append({"symbol": code, "error": str(exc)})
        return {"rows": rows, "failures": failures}


def _parse_payload(
    code: str,
    payload: dict[str, Any],
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    rows = []
    for line in data.get("klines", []) or []:
        row = _parse_kline(code, line)
        if row is None:
            continue
        trade_date = str(row["trade_date"])
        if start_date <= trade_date <= end_date:
            rows.append(row)
    return rows


def _parse_kline(code: str, line: Any) -> dict[str, Any] | None:
    parts = str(line).split(",")
    if len(parts) < len(_FLOW_COLUMNS):
        return None
    trade_date = _parse_date(parts[0])
    if trade_date is None:
        return None
    values: dict[str, Any] = {
        "symbol": code,
        "trade_date": trade_date,
    }
    for column, value in zip(_FLOW_COLUMNS[1:], parts[1:], strict=False):
        values[column] = _to_float(value)
    return values
