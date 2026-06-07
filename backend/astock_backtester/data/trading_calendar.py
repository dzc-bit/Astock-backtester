from __future__ import annotations

from datetime import date

import pandas as pd


_A_SHARE_HOLIDAY_RANGES: dict[int, tuple[tuple[str, str], ...]] = {
    2026: (
        ("2026-01-01", "2026-01-03"),
        ("2026-02-15", "2026-02-23"),
        ("2026-04-04", "2026-04-06"),
        ("2026-05-01", "2026-05-05"),
        ("2026-06-19", "2026-06-21"),
        ("2026-09-25", "2026-09-27"),
        ("2026-10-01", "2026-10-07"),
    ),
}


def _holiday_dates(start_date: pd.Timestamp, end_date: pd.Timestamp) -> set[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for year in range(start_date.year, end_date.year + 1):
        for range_start, range_end in _A_SHARE_HOLIDAY_RANGES.get(year, ()):
            for day in pd.date_range(range_start, range_end, freq="D"):
                dates.add(pd.Timestamp(day).normalize())
    return dates


def a_share_trade_dates(start_date: pd.Timestamp | date | str, end_date: pd.Timestamp | date | str) -> set[pd.Timestamp]:
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if end < start:
        return set()
    weekdays = {pd.Timestamp(day).normalize() for day in pd.date_range(start=start, end=end, freq="B")}
    return weekdays - _holiday_dates(start, end)
