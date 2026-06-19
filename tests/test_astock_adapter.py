import pandas as pd

from astock_backtester.cli import handle_command
from astock_backtester.data.astock_adapter import AStockDataAdapter, AStockDataUnavailable, HttpAStockFetcher


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
    assert response["status"]["configured"] is True


def test_http_fetcher_maps_astock_data_sources_to_daily_bars():
    def fake_json_get(url, params, headers, timeout):
        if "getstockquotation" in url:
            return {
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume", "amount"],
                        "marketData": (
                            "2024-01-02,10,10.5,11,9.8,1000,100000;"
                            "2024-01-03,10.5,11,11.2,10.1,1500,165000"
                        ),
                    }
                }
            }
        if "fflow/daykline/get" in url:
            return {"data": {"klines": ["2024-01-02,2000,1,2,3,4", "2024-01-03,3000,1,2,3,4"]}}
        if "api/qt/stock/get" in url:
            return {"data": {"f117": 8_800_000_000, "f189": "20200101"}}
        raise AssertionError(f"unexpected url: {url}")

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["SH600519"], "2024-01-02", "2024-01-03")

    assert result["symbol"].tolist() == ["600519", "600519"]
    assert result["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert result["open"].tolist() == [10.0, 10.5]
    assert result["high"].tolist() == [11.0, 11.2]
    assert result["low"].tolist() == [9.8, 10.1]
    assert result["close"].tolist() == [10.5, 11.0]
    assert result["volume"].tolist() == [1000, 1500]
    assert result["main_net_inflow"].tolist() == [2000.0, 3000.0]
    assert result["float_market_cap"].tolist() == [8_800_000_000, 8_800_000_000]
    assert result["listing_days"].min() > 1000


def test_http_fetcher_maps_baidu_amount_turnover_and_estimated_float_market_cap():
    def fake_json_get(url, params, headers, timeout):
        if "getstockquotation" in url:
            return {
                "Result": {
                    "newMarketData": {
                        "keys": [
                            "time",
                            "open",
                            "close",
                            "high",
                            "low",
                            "volume",
                            "amount",
                            "range",
                            "ratio",
                            "turnoverratio",
                            "preClose",
                        ],
                        "marketData": "2024-01-02,10,10.5,11,9.8,1000,10500,+0.5,+5.0,2.0,10",
                    }
                }
            }
        return {}

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert result.loc[0, "amount"] == 10500
    assert result.loc[0, "change"] == 0.5
    assert result.loc[0, "change_pct"] == 5.0
    assert result.loc[0, "turnover_rate"] == 2.0
    assert result.loc[0, "pre_close"] == 10
    assert result.loc[0, "float_market_cap"] == 525000.0


def test_http_fetcher_keeps_missing_flow_as_missing_value():
    def fake_json_get(url, params, headers, timeout):
        if "getstockquotation" in url:
            return {
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume"],
                        "marketData": "2024-01-02,10,10.5,11,9.8,1000",
                    }
                }
            }
        if "fflow/daykline/get" in url:
            return {"data": {"klines": ["2026-05-20,2000,1,2,3,4"]}}
        if "api/qt/stock/get" in url:
            return {"data": {"f117": 8_800_000_000, "f189": "20200101"}}
        raise AssertionError(f"unexpected url: {url}")

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert pd.isna(result.loc[0, "main_net_inflow"])


def test_http_fetcher_keeps_daily_bars_when_optional_sources_fail():
    def fake_json_get(url, params, headers, timeout):
        if "getstockquotation" in url:
            return {
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume"],
                        "marketData": "2024-01-02,10,10.5,11,9.8,1000",
                    }
                }
            }
        raise OSError("optional source unavailable")

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert len(result) == 1
    assert result.loc[0, "close"] == 10.5
    assert pd.isna(result.loc[0, "main_net_inflow"])
    assert pd.isna(result.loc[0, "float_market_cap"])


def test_http_fetcher_keeps_daily_bars_when_optional_sources_return_unexpected_shapes():
    def fake_json_get(url, params, headers, timeout):
        if "getstockquotation" in url:
            return {
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume"],
                        "marketData": "2024-01-02,10,10.5,11,9.8,1000",
                    }
                }
            }
        return []

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert len(result) == 1
    assert result.loc[0, "close"] == 10.5
    assert pd.isna(result.loc[0, "main_net_inflow"])
    assert pd.isna(result.loc[0, "float_market_cap"])


def test_http_fetcher_retries_baidu_kline_when_result_shape_is_throttled():
    calls = 0

    def fake_json_get(url, params, headers, timeout):
        nonlocal calls
        if "getstockquotation" in url:
            calls += 1
            if calls == 1:
                return {"ResultCode": "403", "Result": []}
            return {
                "ResultCode": "0",
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume"],
                        "marketData": "2024-01-02,10,10.5,11,9.8,1000",
                    }
                },
            }
        return {}

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert calls == 2
    assert len(result) == 1
    assert result.loc[0, "close"] == 10.5


def test_http_fetcher_tries_browser_transport_when_requests_gets_baidu_403():
    calls = []

    def requests_json_get(url, params, headers, timeout):
        calls.append(("requests", url))
        if "getstockquotation" in url:
            return {"QueryID": "0", "ResultCode": "403", "Result": []}
        raise AssertionError(f"requests transport should not reach optional source: {url}")

    def browser_json_get(url, params, headers, timeout):
        calls.append(("curl_cffi", url))
        if "getstockquotation" in url:
            return {
                "ResultCode": "0",
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume"],
                        "marketData": "2026-06-12,10,10.5,11,9.8,1000",
                    }
                },
            }
        if "fflow/daykline/get" in url:
            return {"data": {"klines": []}}
        if "api/qt/stock/get" in url:
            return {"data": {"f117": 8_800_000_000, "f189": "20200101"}}
        raise AssertionError(f"unexpected url: {url}")

    fetcher = HttpAStockFetcher(json_gets=(("requests", requests_json_get), ("curl_cffi", browser_json_get)))

    result = fetcher.fetch_daily_bars(["600519"], "2026-06-12", "2026-06-18")

    assert result["symbol"].tolist() == ["600519"]
    assert result.loc[0, "close"] == 10.5
    assert [label for label, _ in calls[:2]] == ["requests", "curl_cffi"]


def test_http_fetcher_does_not_retry_plain_empty_baidu_daily_rows():
    calls = 0

    def fake_json_get(url, params, headers, timeout):
        nonlocal calls
        if "getstockquotation" in url:
            calls += 1
            return {"Result": {"newMarketData": {"keys": ["time", "open"], "marketData": ""}}}
        raise AssertionError(f"unexpected optional source call after empty daily rows: {url}")

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["000050"], "2026-06-12", "2026-06-18")

    assert result.empty
    assert calls == 1


def test_cli_fetch_daily_bars_writes_cache(monkeypatch, tmp_path):
    class FakeAdapter:
        def fetch_daily_bars(self, symbols, start_date, end_date):
            assert symbols == ["600519"]
            assert start_date == "2024-01-02"
            assert end_date == "2024-01-08"
            return pd.DataFrame(
                {
                    "symbol": ["600519"],
                    "trade_date": ["2024-01-02"],
                    "open": [10.0],
                    "high": [11.0],
                    "low": [9.8],
                    "close": [10.5],
                    "volume": [1000],
                }
            )

    monkeypatch.setattr(
        "astock_backtester.cli.AStockDataAdapter.from_http_sources",
        lambda: FakeAdapter(),
    )

    response = handle_command(
        {
            "command": "fetch_daily_bars",
            "symbols": ["600519"],
            "start_date": "2024-01-02",
            "end_date": "2024-01-08",
            "cache_dir": str(tmp_path),
        }
    )

    assert response["ok"] is True
    assert response["imported_rows"] == 1
    assert response["coverage"][0]["symbols"] == 1
