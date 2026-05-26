from __future__ import annotations

import math

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.data.providers import (
    CompositeProvider,
    enrich_market_cap_from_share_history,
)


def test_normalize_daily_bars_preserves_market_cap_fields():
    frame = pd.DataFrame(
        {
            "symbol": ["600519"],
            "trade_date": ["2024-01-02"],
            "open": [1608.68],
            "high": [1611.87],
            "low": [1571.78],
            "close": [1578.69],
            "volume": [3215600],
            "amount": [5440083000.0],
            "change_pct": [-2.53],
            "change": [-40.99],
            "turnover_rate": [0.0026],
            "pre_close": [1619.68],
            "float_market_cap": [1980000000000.0],
            "total_market_cap": [1985000000000.0],
        }
    )

    result = normalize_daily_bars(frame)

    assert result.loc[0, "amount"] == 5440083000.0
    assert result.loc[0, "change_pct"] == -2.53
    assert result.loc[0, "change"] == -40.99
    assert result.loc[0, "pre_close"] == 1619.68
    assert result.loc[0, "float_market_cap"] == 1980000000000.0
    assert result.loc[0, "total_market_cap"] == 1985000000000.0


def test_normalize_daily_bars_defaults_missing_market_cap_to_nan():
    frame = pd.DataFrame(
        {
            "symbol": ["000001"],
            "trade_date": ["2024-01-02"],
            "open": [9.0],
            "high": [9.3],
            "low": [8.9],
            "close": [9.1],
            "volume": [1000],
        }
    )

    result = normalize_daily_bars(frame)

    assert math.isnan(result.loc[0, "float_market_cap"])
    assert math.isnan(result.loc[0, "total_market_cap"])
    assert result.loc[0, "amount"] == 0.0


def test_enrich_market_cap_from_share_history_uses_effective_share_dates():
    bars = pd.DataFrame(
        {
            "symbol": ["600519", "600519", "600519"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.8, 10.8, 11.8],
            "close": [10.0, 11.0, 12.0],
            "volume": [100, 100, 100],
        }
    )
    shares = pd.DataFrame(
        {
            "stock_code": ["600519", "600519"],
            "change_date": ["2024-01-01", "2024-01-04"],
            "total_shares": [1000, 2000],
            "list_a_shares": [800, 1600],
        }
    )

    result = enrich_market_cap_from_share_history(bars, shares)

    assert result["float_market_cap"].tolist() == [8000.0, 8800.0, 19200.0]
    assert result["total_market_cap"].tolist() == [10000.0, 11000.0, 24000.0]


def test_composite_provider_falls_back_when_primary_returns_empty():
    class EmptyProvider:
        name = "empty"

        def fetch_daily_bars(self, symbol, start_date, end_date):
            return pd.DataFrame()

        def fetch_share_history(self, symbol):
            return pd.DataFrame()

    class FallbackProvider:
        name = "fallback"

        def fetch_daily_bars(self, symbol, start_date, end_date):
            return pd.DataFrame(
                {
                    "symbol": [symbol],
                    "trade_date": [start_date],
                    "open": [1.0],
                    "high": [1.0],
                    "low": [1.0],
                    "close": [1.0],
                    "volume": [1],
                }
            )

        def fetch_share_history(self, symbol):
            return pd.DataFrame()

    provider = CompositeProvider([EmptyProvider(), FallbackProvider()])

    result = provider.fetch_daily_bars("000001", "2024-01-02", "2024-01-02")

    assert result.loc[0, "source"] == "fallback"
