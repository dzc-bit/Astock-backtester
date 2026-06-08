import pytest

from astock_backtester.data.capital_flow_crawler import (
    CapitalFlowCrawler,
    CapitalFlowFetchError,
    _normalize_code,
)


def test_fetch_fund_flow_builds_eastmoney_request_and_filters_dates():
    calls = []

    def fake_json_get(url, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return {
            "data": {
                "klines": [
                    "2024-01-02,2000000,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                    "2024-01-03,-3000000,2500000,500000,-2000000,-1000000,-6.0,5.0,1.0,-4.0,-2.0,1690.0,-0.5",
                    "2024-01-04,6000000,-5000000,-1000000,4000000,2000000,8.1,-6.7,-1.4,5.4,2.7,1700.0,0.8",
                ]
            }
        }

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    rows = crawler.fetch_fund_flow("SH600519", "2024-01-03", "2024-01-04", limit=20)

    assert rows == [
        {
            "symbol": "600519",
            "trade_date": "2024-01-03",
            "close": 1690.0,
            "change_pct": -0.5,
            "main_net_inflow": -3000000.0,
            "main_net_inflow_pct": -6.0,
            "small_net_inflow": 2500000.0,
            "small_net_inflow_pct": 5.0,
            "medium_net_inflow": 500000.0,
            "medium_net_inflow_pct": 1.0,
            "large_net_inflow": -2000000.0,
            "large_net_inflow_pct": -4.0,
            "super_large_net_inflow": -1000000.0,
            "super_large_net_inflow_pct": -2.0,
        },
        {
            "symbol": "600519",
            "trade_date": "2024-01-04",
            "close": 1700.0,
            "change_pct": 0.8,
            "main_net_inflow": 6000000.0,
            "main_net_inflow_pct": 8.1,
            "small_net_inflow": -5000000.0,
            "small_net_inflow_pct": -6.7,
            "medium_net_inflow": -1000000.0,
            "medium_net_inflow_pct": -1.4,
            "large_net_inflow": 4000000.0,
            "large_net_inflow_pct": 5.4,
            "super_large_net_inflow": 2000000.0,
            "super_large_net_inflow_pct": 2.7,
        },
    ]

    url, params, headers, timeout = calls[0]
    assert url == "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    assert params["secid"] == "1.600519"
    assert params["lmt"] == "20"
    assert params["klt"] == "101"
    assert params["fields2"] == "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
    assert headers["Referer"] == "https://data.eastmoney.com/zjlx/detail.html"
    assert timeout == 15


def test_fetch_fund_flow_returns_empty_rows_for_missing_payload():
    crawler = CapitalFlowCrawler(json_get=lambda url, params, headers, timeout: {"data": None})

    with pytest.raises(CapitalFlowFetchError, match="empty_payload"):
        crawler.fetch_fund_flow("600519", "2024-01-01", "2024-01-31")


def test_fetch_many_fund_flows_reports_empty_payload_and_empty_klines_as_failures():
    def fake_json_get(url, params, headers, timeout):
        if params["secid"] == "1.600519":
            return {"data": None}
        return {"data": {"klines": []}}

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    result = crawler.fetch_many_fund_flows(["600519", "000001"], "2024-01-01", "2024-01-31")

    assert result["rows"] == []
    assert result["failures"] == [
        {"symbol": "600519", "code": "empty_payload", "error": "empty_payload: Eastmoney payload missing data for 600519"},
        {"symbol": "000001", "code": "empty_klines", "error": "empty_klines: Eastmoney payload has no klines for 000001"},
    ]


def test_fetch_many_fund_flows_keeps_bad_numeric_rows_and_reports_diagnostics():
    def fake_json_get(url, params, headers, timeout):
        return {
            "data": {
                "klines": [
                    "2024-01-02,bad-number,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                    "2024-01-03,2000000,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                ]
            }
        }

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    result = crawler.fetch_many_fund_flows(["600519"], "2024-01-01", "2024-01-31")

    assert len(result["rows"]) == 2
    assert result["rows"][0]["main_net_inflow"] is None
    assert result["rows"][1]["main_net_inflow"] == 2000000.0
    assert result["failures"] == []
    assert any(
        item["symbol"] == "600519"
        and item["code"] == "malformed_numeric"
        and item["field"] == "main_net_inflow"
        and item["trade_date"] == "2024-01-02"
        for item in result["diagnostics"]
    )


def test_fetch_many_fund_flows_reports_date_coverage_shortfall():
    def fake_json_get(url, params, headers, timeout):
        return {
            "data": {
                "klines": [
                    "2024-01-03,2000000,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                ]
            }
        }

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    result = crawler.fetch_many_fund_flows(["600519"], "2024-01-02", "2024-01-05")

    assert len(result["rows"]) == 1
    assert result["failures"] == []
    assert any(
        item["symbol"] == "600519"
        and item["code"] == "date_coverage_shortfall"
        and item["first_trade_date"] == "2024-01-03"
        and item["last_trade_date"] == "2024-01-03"
        for item in result["diagnostics"]
    )


def test_fetch_fund_flow_estimates_limit_from_date_span():
    calls = []

    def fake_json_get(url, params, headers, timeout):
        calls.append(params)
        return {"data": {"klines": []}}

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    with pytest.raises(CapitalFlowFetchError, match="empty_klines"):
        crawler.fetch_fund_flow("600519", "2024-01-01", "2024-03-31")

    assert calls[0]["lmt"] == "118"


def test_fetch_fund_flow_skips_malformed_and_blank_numeric_values():
    def fake_json_get(url, params, headers, timeout):
        return {
            "data": {
                "klines": [
                    "not-a-date,2000000,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                    "2024-01-02,--,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                    "2024-01-03,-3000000,2500000,500000,-2000000,-1000000,-6.0,5.0,1.0,-4.0,-2.0,1690.0,-0.5",
                    "2024-01-04,too-short",
                ]
            }
        }

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    rows = crawler.fetch_fund_flow("600519", "2024-01-01", "2024-01-31")

    assert len(rows) == 2
    assert rows[0]["trade_date"] == "2024-01-02"
    assert rows[0]["main_net_inflow"] is None
    assert rows[1]["trade_date"] == "2024-01-03"
    assert rows[1]["main_net_inflow"] == -3000000.0


def test_fetch_fund_flow_raises_clear_error_when_network_fails():
    def fake_json_get(url, params, headers, timeout):
        raise OSError("remote disconnected")

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    with pytest.raises(CapitalFlowFetchError, match="600519"):
        crawler.fetch_fund_flow("600519", "2024-01-01", "2024-01-31")


def test_fetch_fund_flow_retries_with_header_variants_after_remote_disconnect():
    calls = []

    def fake_json_get(url, params, headers, timeout):
        calls.append((url, headers["Referer"], timeout))
        if len(calls) == 1:
            raise OSError("remote disconnected")
        return {
            "data": {
                "klines": [
                    "2024-01-02,2000000,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                ]
            }
        }

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    rows = crawler.fetch_fund_flow("600519", "2024-01-01", "2024-01-31", timeout=9)

    assert rows[0]["main_net_inflow"] == 2000000.0
    assert len(calls) == 2
    assert calls[0][1] == "https://data.eastmoney.com/zjlx/detail.html"
    assert calls[1][1] == "https://quote.eastmoney.com/"
    assert calls[0][2] == 9
    assert calls[1][2] == 9


def test_fetch_many_fund_flows_keeps_successful_rows_and_reports_failures():
    def fake_json_get(url, params, headers, timeout):
        if params["secid"] == "1.600519":
            return {
                "data": {
                    "klines": [
                        "2024-01-02,2000000,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                    ]
                }
            }
        raise OSError("remote disconnected")

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    result = crawler.fetch_many_fund_flows(["600519", "000001"], "2024-01-01", "2024-01-31")

    assert len(result["rows"]) == 1
    assert result["rows"][0]["symbol"] == "600519"
    assert result["failures"][0]["symbol"] == "000001"
    assert "Failed to fetch Eastmoney capital flow for 000001" in result["failures"][0]["error"]
    assert "https://data.eastmoney.com/zjlx/detail.html: remote disconnected" in result["failures"][0]["error"]
    assert "https://quote.eastmoney.com/: remote disconnected" in result["failures"][0]["error"]


def test_fetch_many_fund_flows_uses_recent_success_cache_after_disconnect():
    calls = 0

    def fake_json_get(url, params, headers, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "data": {
                    "klines": [
                        "2024-01-02,2000000,-1500000,-500000,1200000,800000,4.2,-3.1,-1.1,2.5,1.7,1688.0,1.5",
                    ]
                }
            }
        raise OSError("remote disconnected")

    crawler = CapitalFlowCrawler(json_get=fake_json_get)

    first = crawler.fetch_many_fund_flows(["600519"], "2024-01-02", "2024-01-02")
    second = crawler.fetch_many_fund_flows(["600519"], "2024-01-02", "2024-01-02")

    assert first["rows"][0]["main_net_inflow"] == 2000000.0
    assert second["rows"][0]["main_net_inflow"] == 2000000.0
    assert second["failures"][0]["symbol"] == "600519"
    assert second["failures"][0]["code"] == "network_error"
    assert any(
        item["symbol"] == "600519" and item["code"] == "recent_success_cache_used"
        for item in second["diagnostics"]
    )


def test_normalize_code_accepts_common_a_share_symbol_forms():
    assert _normalize_code("SH600519") == "600519"
    assert _normalize_code("600519.SH") == "600519"
    assert _normalize_code(" sz000001 ") == "000001"
