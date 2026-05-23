from __future__ import annotations

import pandas as pd


def sample_daily_bars() -> pd.DataFrame:
    rows = [
        ("AAA", "2024-01-02", 10.0, 10.5, 9.8, 10.0, 1000, 0.03, 8_000_000_000, 2_000_000, False, False, 90),
        ("AAA", "2024-01-03", 10.0, 11.2, 9.9, 11.0, 1500, 0.04, 8_800_000_000, 3_000_000, False, False, 91),
        ("AAA", "2024-01-04", 11.0, 12.4, 10.8, 12.0, 2200, 0.06, 9_600_000_000, 4_000_000, False, False, 92),
        ("AAA", "2024-01-05", 12.0, 12.2, 10.6, 11.0, 1600, 0.05, 8_800_000_000, -1_000_000, False, False, 93),
        ("AAA", "2024-01-08", 11.0, 11.5, 10.1, 10.2, 1300, 0.04, 8_160_000_000, -2_000_000, False, False, 96),
        ("BBB", "2024-01-02", 20.0, 20.5, 19.8, 20.0, 800, 0.01, 40_000_000_000, 500_000, False, False, 200),
        ("BBB", "2024-01-03", 20.0, 21.2, 19.9, 21.0, 900, 0.02, 42_000_000_000, 400_000, False, False, 201),
        ("BBB", "2024-01-04", 21.0, 22.0, 20.5, 22.0, 950, 0.02, 44_000_000_000, 300_000, False, False, 202),
        ("BBB", "2024-01-05", 22.0, 22.1, 21.5, 21.8, 700, 0.01, 43_600_000_000, -300_000, False, False, 203),
        ("BBB", "2024-01-08", 21.8, 22.4, 21.2, 22.2, 850, 0.02, 44_400_000_000, 700_000, False, False, 206),
    ]
    columns = [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover_rate",
        "float_market_cap",
        "main_net_inflow",
        "is_st",
        "is_suspended",
        "listing_days",
    ]
    df = pd.DataFrame(rows, columns=columns)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
