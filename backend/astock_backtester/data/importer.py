from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_DAILY_COLUMNS = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]


def normalize_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "trade_date" not in out.columns and "date" in out.columns:
        out = out.rename(columns={"date": "trade_date"})
    missing = [column for column in REQUIRED_DAILY_COLUMNS if column not in out.columns]
    if missing:
        raise ValueError(f"daily bars missing required columns: {', '.join(missing)}")

    out["symbol"] = out["symbol"].astype(str)
    out["trade_date"] = pd.to_datetime(out["trade_date"]).astype("datetime64[ns]")
    for column in ["open", "high", "low", "close", "volume"]:
        out[column] = pd.to_numeric(out[column], errors="raise")

    optional_defaults = {
        "amount": 0.0,
        "change_pct": 0.0,
        "change": 0.0,
        "turnover_rate": 0.0,
        "pre_close": float("nan"),
        "float_market_cap": float("nan"),
        "total_market_cap": float("nan"),
        "main_net_inflow": float("nan"),
        "is_st": False,
        "is_suspended": False,
        "listing_days": 9999,
    }
    for column, default in optional_defaults.items():
        if column not in out.columns:
            out[column] = default

    for column in [
        "amount",
        "change_pct",
        "change",
        "turnover_rate",
        "pre_close",
        "float_market_cap",
        "total_market_cap",
        "main_net_inflow",
    ]:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    return out.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def read_daily_bars(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        return normalize_daily_bars(pd.read_csv(source))
    if source.suffix.lower() in {".parquet", ".pq"}:
        return normalize_daily_bars(pd.read_parquet(source))
    raise ValueError(f"unsupported daily bars file extension: {source.suffix}")
