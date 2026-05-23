from __future__ import annotations

import pandas as pd


def _sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def add_moving_average(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    out = _sorted(df).copy()
    grouped = out.groupby("symbol", group_keys=False)
    for window in windows:
        out[f"ma_{window}"] = grouped["close"].rolling(window=window).mean().reset_index(level=0, drop=True)
    return out


def add_returns(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    out = _sorted(df).copy()
    grouped = out.groupby("symbol", group_keys=False)
    for window in windows:
        out[f"return_{window}d"] = grouped["close"].pct_change(periods=window)
    return out


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    out = _sorted(df).copy()
    pieces: list[pd.DataFrame] = []
    for _, group in out.groupby("symbol", sort=False):
        group = group.copy()
        close = group["close"]
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        group["macd_dif"] = dif
        group["macd_dea"] = dea
        group["macd_hist"] = (dif - dea) * 2
        pieces.append(group)
    return pd.concat(pieces, ignore_index=True)


def add_market_heat(df: pd.DataFrame) -> pd.DataFrame:
    out = _sorted(df).copy()
    previous_close = out.groupby("symbol")["close"].shift(1)
    out["_is_rising"] = out["close"] > previous_close
    heat = (
        out.groupby("trade_date")["_is_rising"]
        .mean()
        .rename("market_rising_ratio")
        .reset_index()
    )
    out = out.merge(heat, on="trade_date", how="left")
    out["market_rising_ratio"] = out["market_rising_ratio"].fillna(0.0)
    return out.drop(columns=["_is_rising"])
