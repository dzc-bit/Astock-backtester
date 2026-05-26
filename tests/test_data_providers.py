from __future__ import annotations

import math

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars


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
