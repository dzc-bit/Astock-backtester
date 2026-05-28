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


def add_volume_ratio(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    out = _sorted(df).copy()
    prior_volume = out.groupby("symbol")["volume"].shift(1)
    for window in windows:
        prior_average = (
            prior_volume.groupby(out["symbol"])
            .rolling(window=window)
            .mean()
            .reset_index(level=0, drop=True)
        )
        out[f"volume_ratio_{window}d"] = out["volume"] / prior_average
    return out


def add_capital_flow_sum(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    out = _sorted(df).copy()
    for window in windows:
        out[f"main_net_inflow_sum_{window}d"] = (
            out.groupby("symbol")["main_net_inflow"]
            .rolling(window=window)
            .sum()
            .reset_index(level=0, drop=True)
        )
    return out


def add_prior_high_low(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    out = _sorted(df).copy()
    prior_high = out.groupby("symbol")["high"].shift(1)
    prior_low = out.groupby("symbol")["low"].shift(1)
    for window in windows:
        out[f"prior_high_{window}d"] = (
            prior_high.groupby(out["symbol"])
            .rolling(window=window)
            .max()
            .reset_index(level=0, drop=True)
        )
        out[f"prior_low_{window}d"] = (
            prior_low.groupby(out["symbol"])
            .rolling(window=window)
            .min()
            .reset_index(level=0, drop=True)
        )
    return out


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    out = _sorted(df).copy()
    grouped_close = out.groupby("symbol")["close"]
    out["macd_dif"] = grouped_close.transform(lambda close: close.ewm(span=fast, adjust=False).mean()) - grouped_close.transform(
        lambda close: close.ewm(span=slow, adjust=False).mean()
    )
    out["macd_dea"] = out.groupby("symbol")["macd_dif"].transform(lambda dif: dif.ewm(span=signal, adjust=False).mean())
    out["macd_hist"] = (out["macd_dif"] - out["macd_dea"]) * 2
    return out


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
