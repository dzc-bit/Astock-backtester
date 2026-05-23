import pandas as pd

from astock_backtester.cli import handle_command
from astock_backtester.data.astock_adapter import AStockDataAdapter, AStockDataUnavailable


def test_adapter_reports_unconfigured_fetcher():
    adapter = AStockDataAdapter(fetcher=None)

    try:
        adapter.fetch_daily_bars(["AAA"], "2024-01-02", "2024-01-08")
    except AStockDataUnavailable as exc:
        assert "a-stock-data fetcher is not configured" in str(exc)
    else:
        raise AssertionError("expected AStockDataUnavailable")


def test_adapter_normalizes_fetcher_output():
    def fake_fetcher(symbols, start_date, end_date):
        return pd.DataFrame(
            {
                "symbol": ["AAA"],
                "date": ["2024-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.8],
                "close": [10.5],
                "volume": [1000],
                "float_market_cap": [8_000_000_000],
                "main_net_inflow": [2_000_000],
            }
        )

    adapter = AStockDataAdapter(fetcher=fake_fetcher)
    result = adapter.fetch_daily_bars(["AAA"], "2024-01-02", "2024-01-08")

    assert result.loc[0, "symbol"] == "AAA"
    assert result.loc[0, "main_net_inflow"] == 2_000_000


def test_fetch_status_is_explicit():
    response = handle_command({"command": "fetch_status"})

    assert response["ok"] is True
    assert response["status"]["configured"] is False
