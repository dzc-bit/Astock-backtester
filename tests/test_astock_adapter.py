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
        if "fqkline/get" in url:
            return {}
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


def test_http_fetcher_prefers_sina_kline_when_text_getter_is_configured():
    calls: list[str] = []

    def fake_text_get(url, params, headers, timeout):
        calls.append("sina")
        assert "CN_MarketDataService.getKLineData" in url
        assert params["symbol"] == "sh600519"
        return (
            "var x=(["
            '{"day":"2024-01-02","open":"10","high":"10.5","low":"9.8","close":"10.2","volume":"1000"},'
            '{"day":"2024-01-03","open":"10.2","high":"10.8","low":"10.1","close":"10.7","volume":"1500"}'
            "]);"
        )

    def fake_json_get(url, params, headers, timeout):
        calls.append("json")
        return {}

    fetcher = HttpAStockFetcher(json_get=fake_json_get, text_get=fake_text_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-03")

    assert calls[0] == "sina"
    assert "tencent" not in calls
    assert result["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert result["close"].tolist() == [10.2, 10.7]


def test_http_fetcher_uses_tencent_when_sina_kline_is_empty():
    calls: list[str] = []

    def fake_text_get(url, params, headers, timeout):
        calls.append("sina")
        return "var x=([]);"

    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            calls.append("tencent")
            assert timeout <= 5
            assert params["param"].startswith("sh600519,day,2024-01-02,2024-01-03")
            return {
                "code": 0,
                "data": {
                    "sh600519": {
                        "qfqday": [
                            ["2024-01-02", "10", "10.2", "10.5", "9.8", "1000"],
                            ["2024-01-03", "10.2", "10.7", "10.8", "10.1", "1500"],
                        ]
                    }
                },
            }
        if "stock/kline/get" in url:
            calls.append("eastmoney")
            return {}
        if "getstockquotation" in url:
            calls.append("baidu")
            return {}
        return {}

    fetcher = HttpAStockFetcher(json_get=fake_json_get, text_get=fake_text_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-03")

    assert calls == ["sina", "tencent"]
    assert result["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert result["close"].tolist() == [10.2, 10.7]


def test_http_fetcher_prefers_eastmoney_kline_before_baidu():
    calls: list[str] = []

    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            return {}
        if "stock/kline/get" in url:
            calls.append("eastmoney")
            assert timeout <= 5
            return {
                "data": {
                    "klines": [
                        "2024-01-02,10,10.2,10.5,9.8,1000,10200,0,2.0,0.2,0.02",
                        "2024-01-03,10.2,10.7,10.8,10.1,1500,16050,0,4.9,0.5,0.05",
                    ]
                }
            }
        if "getstockquotation" in url:
            calls.append("baidu")
            return {}
        return {}

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-03")

    assert calls == ["eastmoney"]
    assert result["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert result["close"].tolist() == [10.2, 10.7]
    assert result["amount"].tolist() == [10200.0, 16050.0]


def test_http_fetcher_falls_back_to_baidu_when_eastmoney_kline_disconnects():
    calls: list[str] = []

    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            return {}
        if "stock/kline/get" in url:
            calls.append("eastmoney")
            raise OSError("remote end closed connection")
        if "getstockquotation" in url:
            calls.append("baidu")
            return {
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume"],
                        "marketData": "2024-01-02,10,10.5,11,9.8,1000",
                    }
                }
            }
        return {}

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert calls == ["eastmoney", "baidu"]
    assert len(result) == 1
    assert result.loc[0, "close"] == 10.5


def test_http_fetcher_tries_next_eastmoney_transport_before_baidu():
    calls: list[str] = []

    def failing_eastmoney(url, params, headers, timeout):
        calls.append("eastmoney-requests")
        raise OSError("remote end closed connection")

    def working_eastmoney(url, params, headers, timeout):
        calls.append("eastmoney-curl")
        return {"data": {"klines": ["2024-01-02,10,10.2,10.5,9.8,1000,10200,0,2.0,0.2,0.02"]}}

    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            return {}
        if "getstockquotation" in url:
            calls.append("baidu")
        return {}

    fetcher = HttpAStockFetcher(
        json_get=fake_json_get,
        eastmoney_json_getters=(("requests", failing_eastmoney), ("curl_cffi", working_eastmoney)),
    )

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert calls == ["eastmoney-requests", "eastmoney-curl"]
    assert len(result) == 1
    assert result.loc[0, "close"] == 10.2


def test_http_fetcher_suspends_repeated_eastmoney_disconnects_for_batch_speed():
    calls: list[tuple[str, str]] = []

    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            return {}
        if "stock/kline/get" in url:
            code = str(params["secid"]).split(".", 1)[1]
            calls.append(("eastmoney", code))
            raise OSError("remote end closed connection")
        if "getstockquotation" in url:
            code = str(params["code"])
            calls.append(("baidu", code))
            return {
                "Result": {
                    "newMarketData": {
                        "keys": ["time", "open", "close", "high", "low", "volume"],
                        "marketData": "2024-01-02,10,10.5,11,9.8,1000",
                    }
                }
            }
        return {}

    fetcher = HttpAStockFetcher(json_get=fake_json_get)

    result = fetcher.fetch_daily_bars(["600519", "000001"], "2024-01-02", "2024-01-02")

    assert calls == [("eastmoney", "600519"), ("baidu", "600519"), ("baidu", "000001")]
    assert result["symbol"].tolist() == ["600519", "000001"]


def test_http_fetcher_maps_baidu_amount_turnover_and_estimated_float_market_cap():
    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            return {}
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
        if "fqkline/get" in url:
            return {}
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
        if "fqkline/get" in url:
            return {}
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


def test_http_fetcher_can_skip_optional_enrichment_for_fast_full_market_sync():
    calls: list[str] = []

    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            calls.append("tencent")
            return {}
        if "fflow/daykline/get" in url:
            calls.append("fund-flow")
            raise AssertionError("optional fund flow should be skipped")
        if "api/qt/stock/get" in url:
            calls.append("stock-info")
            raise AssertionError("optional stock info should be skipped")
        return {}

    def fake_text_get(url, params, headers, timeout):
        calls.append("sina")
        return (
            "var x=(["
            '{"day":"2024-01-02","open":"10","high":"10.5","low":"9.8","close":"10.2","volume":"1000"}'
            "]);"
        )

    fetcher = HttpAStockFetcher(
        json_get=fake_json_get,
        text_get=fake_text_get,
        include_optional_enrichment=False,
    )

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert calls == ["sina"]
    assert len(result) == 1
    assert result.loc[0, "close"] == 10.2
    assert pd.isna(result.loc[0, "main_net_inflow"])


def test_http_fetcher_keeps_daily_bars_when_optional_sources_return_unexpected_shapes():
    def fake_json_get(url, params, headers, timeout):
        if "fqkline/get" in url:
            return {}
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
        if "fqkline/get" in url:
            return {}
        if "getstockquotation" in url:
            calls += 1
            if calls == 1:
                return {"ResultCode": "0", "Result": []}
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


def test_http_fetcher_fast_fails_baidu_for_explicit_403_shape(monkeypatch):
    calls = 0
    sleeps: list[float] = []

    def fake_json_get(url, params, headers, timeout):
        nonlocal calls
        if "fqkline/get" in url:
            return {}
        if "getstockquotation" in url:
            calls += 1
            return {"ResultCode": "403", "Result": []}
        return {}

    monkeypatch.setattr("astock_backtester.data.astock_adapter.time.sleep", lambda seconds: sleeps.append(seconds))
    fetcher = HttpAStockFetcher(json_get=fake_json_get, eastmoney_json_getters=())

    result = fetcher.fetch_daily_bars(["600519"], "2024-01-02", "2024-01-02")

    assert result.empty
    assert calls == 1
    assert sleeps == []


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
