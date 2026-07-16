from __future__ import annotations

import pandas as pd
import pytest
from astock_backtester.data.trading_calendar import a_share_trade_dates


@pytest.mark.parametrize(
    "holiday",
    [
        "2027-02-08",
        "2027-10-04",
        "2028-01-26",
        "2028-10-02",
    ],
)
def test_a_share_trade_dates_excludes_2027_and_2028_holidays(holiday):
    assert pd.Timestamp(holiday) not in a_share_trade_dates(holiday, holiday)
