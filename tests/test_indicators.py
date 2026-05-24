import pandas as pd

from astock_backtester.indicators import add_macd, add_market_heat, add_moving_average, add_returns, add_volume_ratio
from astock_backtester.sample_data import sample_daily_bars


def test_sample_daily_bars_contract():
    df = sample_daily_bars()
    required_columns = {
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
    }

    assert set(df["symbol"]) == {"AAA", "BBB"}
    assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])
    assert required_columns.issubset(df.columns)
    assert df.equals(df.sort_values(["symbol", "trade_date"]).reset_index(drop=True))


def test_add_moving_average_uses_symbol_boundaries():
    df = sample_daily_bars()
    result = add_moving_average(df, windows=[3])
    aaa = result[result["symbol"] == "AAA"].reset_index(drop=True)
    bbb = result[result["symbol"] == "BBB"].reset_index(drop=True)

    assert pd.isna(aaa.loc[1, "ma_3"])
    assert pd.isna(bbb.loc[0, "ma_3"])
    assert pd.isna(bbb.loc[1, "ma_3"])
    assert aaa.loc[2, "ma_3"] == 11.0
    assert bbb.loc[2, "ma_3"] == 21.0


def test_add_returns_calculates_past_gain_without_future_rows():
    df = sample_daily_bars()
    result = add_returns(df, windows=[2])
    aaa = result[result["symbol"] == "AAA"].reset_index(drop=True)
    bbb = result[result["symbol"] == "BBB"].reset_index(drop=True)

    assert round(aaa.loc[2, "return_2d"], 6) == round((12 / 10) - 1, 6)
    assert pd.isna(bbb.loc[0, "return_2d"])
    assert pd.isna(bbb.loc[1, "return_2d"])
    assert round(bbb.loc[2, "return_2d"], 6) == round((22 / 20) - 1, 6)


def test_add_macd_outputs_expected_columns():
    result = add_macd(sample_daily_bars())

    assert {"macd_dif", "macd_dea", "macd_hist"}.issubset(result.columns)
    assert result["macd_hist"].notna().any()


def test_add_market_heat_computes_rising_ratio_by_date():
    result = add_market_heat(sample_daily_bars())
    heat = result[["trade_date", "market_rising_ratio"]].drop_duplicates()
    row = heat[heat["trade_date"] == pd.Timestamp("2024-01-03")].iloc[0]

    assert row["market_rising_ratio"] == 1.0


def test_add_volume_ratio_uses_prior_window_only():
    result = add_volume_ratio(sample_daily_bars(), windows=[2])
    aaa = result[result["symbol"] == "AAA"].reset_index(drop=True)

    assert pd.isna(aaa.loc[0, "volume_ratio_2d"])
    assert round(aaa.loc[2, "volume_ratio_2d"], 6) == round(2200 / ((1000 + 1500) / 2), 6)
