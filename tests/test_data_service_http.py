from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

from astock_backtester.sample_data import sample_daily_bars
from astock_backtester.data.news import _parse_time
from astock_backtester.service import create_server


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_ndjson(url: str, payload: dict) -> list[dict]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return [json.loads(line) for line in response.read().decode("utf-8").splitlines() if line.strip()]


def test_service_health_and_logs(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        health = _request_json("GET", f"http://127.0.0.1:{port}/health")
        logs = _request_json("GET", f"http://127.0.0.1:{port}/logs/recent")

        assert health["ok"] is True
        assert health["port"] == port
        assert health["cache_path"] == str(tmp_path.resolve())
        assert isinstance(logs["items"], list)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_ping_is_lightweight(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/ping")

        assert response == {"ok": True}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_coverage_endpoint_returns_symbol_items(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("POST", f"http://127.0.0.1:{port}/coverage/daily-bars", {})

        assert response["items"] == []
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_coverage_endpoint_filters_requested_symbols_and_dates(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.cache.write_daily_bars(sample_daily_bars())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/coverage/daily-bars",
            {"symbols": ["AAA"], "start_date": "2024-01-02", "end_date": "2024-01-08"},
        )

        assert [item["symbol"] for item in response["items"]] == ["AAA"]
        assert response["items"][0]["missing_trade_dates"] == []
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_run_backtest_uses_sidecar_cache(tmp_path, basic_strategy, basic_settings):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.cache.write_daily_bars(sample_daily_bars())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/run/backtest",
            {
                "strategy": json.loads(basic_strategy.model_dump_json()),
                "settings": json.loads(basic_settings.model_dump_json()),
            },
        )

        assert response["result"]["metrics"]["trade_count"] >= 1
        assert response["result"]["trades"]
        latest_matches = response["result"]["latest_strategy_matches"]
        assert latest_matches["signal_date"] == "2024-01-08"
        assert latest_matches["trade_date"] == "2024-01-08"
        assert isinstance(latest_matches["matches"], list)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_starts_full_market_sync_job(tmp_path):
    class FakeManager:
        def run_full_market(self, symbols, start_date, end_date):
            from datetime import date

            from astock_backtester.models import SyncJobStatus

            assert symbols == ["000001", "000002"]
            return SyncJobStatus(
                job_id="job-1",
                mode="full_market_bootstrap",
                status="completed",
                total_symbols=2,
                completed_symbols=2,
                failed_symbols=0,
                imported_rows=2,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.sync_manager = FakeManager()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/sync/full-market",
            {"symbols": ["000001", "000002"], "start_date": "2015-01-01", "end_date": "2015-01-05"},
        )

        assert response["job"]["status"] == "completed"
        assert response["job"]["imported_rows"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_uses_provider_symbols_for_full_market_sync_when_not_supplied(tmp_path):
    class FakeProvider:
        def list_symbols(self):
            return ["000001", "600519"]

    class FakeManager:
        def run_full_market(self, symbols, start_date, end_date):
            from datetime import date

            from astock_backtester.models import SyncJobStatus

            assert symbols == ["000001", "600519"]
            return SyncJobStatus(
                job_id="job-2",
                mode="full_market_bootstrap",
                status="completed",
                total_symbols=2,
                completed_symbols=2,
                failed_symbols=0,
                imported_rows=2,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.provider = FakeProvider()
    server.state.sync_manager = FakeManager()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/sync/full-market",
            {"start_date": "2015-01-01", "end_date": "2015-01-05"},
        )

        assert response["job"]["status"] == "completed"
        assert response["job"]["total_symbols"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_coverage_endpoint_reads_warehouse_when_cache_is_empty(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/coverage/daily-bars",
            {"symbols": ["AAA"], "start_date": "2024-01-02", "end_date": "2024-01-08"},
        )

        assert [item["symbol"] for item in response["items"]] == ["AAA"]
        assert response["items"][0]["rows"] >= 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_streams_backtest_trade_events_before_final_result(tmp_path, basic_strategy, basic_settings):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.cache.write_daily_bars(sample_daily_bars())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        events = _request_ndjson(
            f"http://127.0.0.1:{port}/run/backtest/stream",
            {
                "strategy": json.loads(basic_strategy.model_dump_json()),
                "settings": json.loads(basic_settings.model_dump_json()),
            },
        )

        assert [event["type"] for event in events][:2] == ["phase", "phase"]
        progress_index = next(index for index, event in enumerate(events) if event["type"] == "progress")
        opened_index = next(index for index, event in enumerate(events) if event["type"] == "trade_opened")
        trade_index = next(index for index, event in enumerate(events) if event["type"] == "trade_closed")
        result_index = next(index for index, event in enumerate(events) if event["type"] == "result")
        assert progress_index < result_index
        assert opened_index < trade_index
        assert trade_index < result_index
        assert events[progress_index]["message"].startswith("扫描")
        assert events[opened_index]["trade"]["sell_date"] is None
        assert events[trade_index]["trade"]["symbol"] == "AAA"
        assert events[result_index]["result"]["metrics"]["trade_count"] >= 1
        latest_matches = events[result_index]["result"]["latest_strategy_matches"]
        assert latest_matches["signal_date"] == "2024-01-08"
        assert latest_matches["trade_date"] == "2024-01-08"
        assert isinstance(latest_matches["matches"], list)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_uses_configured_provider(tmp_path):
    class FakeRealtimeProvider:
        def market_snapshot(self):
            from datetime import datetime, timezone

            from astock_backtester.models import (
                MarketBreadth,
                MarketIndexQuote,
                RealtimeMarketSnapshot,
                SectorMover,
            )

            return RealtimeMarketSnapshot(
                status="live",
                source="fake-live",
                updated_at=datetime(2026, 5, 27, 10, 30, tzinfo=timezone.utc),
                indexes=[
                    MarketIndexQuote(
                        symbol="sh000001",
                        name="上证指数",
                        last=3100.0,
                        previous_close=3080.0,
                        change=20.0,
                        change_pct=0.0064935,
                        source="fake-live",
                        updated_at=datetime(2026, 5, 27, 10, 30, tzinfo=timezone.utc),
                    )
                ],
                breadth=MarketBreadth(up=3200, down=1800, flat=120, total=5120, source="fake-live"),
                strong_sectors=[
                    SectorMover(name="半导体", change_pct=0.038, leading_symbol="688001", source="fake-live")
                ],
                yesterday_strong_sectors=[
                    SectorMover(name="机器人", change_pct=0.041, leading_symbol="300024", source="fake-yesterday")
                ],
                message="ok",
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.realtime_provider = FakeRealtimeProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["status"] == "live"
        assert response["source"] == "fake-live"
        assert response["indexes"][0]["name"] == "上证指数"
        assert response["breadth"]["up"] == 3200
        assert response["strong_sectors"][0]["name"] == "半导体"
        assert response["yesterday_strong_sectors"][0]["name"] == "机器人"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_prefers_live_sector_provider(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        params = kwargs.get("params", {})
        fs = str(params.get("fs", ""))
        if "m:90+t:3" in fs:
            return FakeResponse(
                {
                    "data": {
                        "diff": [
                            {"f12": "BK1037", "f14": "电力设备", "f3": 3.2, "f128": "300750"},
                            {"f12": "BK1036", "f14": "半导体", "f3": 2.5, "f128": "688001"},
                        ]
                    }
                }
            )
        return FakeResponse(
            {
                "data": {
                    "diff": [
                        {"f12": "BK0475", "f14": "银行", "f3": 1.5, "f128": "600036"},
                    ]
                }
            }
        )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"][0]["name"] == "电力设备"
        assert response["strong_sectors"][0]["source"] == "eastmoney-sector"
        assert "沪市主板" not in [item["name"] for item in response["strong_sectors"]]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_prefers_ths_concept_quotes_over_industry_quotes(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        if "q.10jqka.com.cn/gn/" in url:
            return FakeResponse(
                text="""
                <html><body>
                <input type="hidden" id="gnSection"
                  value='{"1":{"platecode":"885001","platename":"AI应用","199112":4.6,"zjjlr":12.3,"zfl":77},
                          "2":{"platecode":"885002","platename":"机器人概念","199112":3.1,"zjjlr":8.5,"zfl":68}}'>
                </body></html>
                """
            )
        if "q.10jqka.com.cn/thshy/index/field/199112/order/desc/page/1/" in url:
            return FakeResponse(
                text="""
                <html><body>
                <table class="m-table m-pager-table">
                  <tbody>
                    <tr>
                      <td>1</td><td>白酒</td><td>3.52</td><td>416.94</td><td>272.51</td><td>27.66</td><td>18</td><td>1</td><td>65.36</td><td>酒鬼酒</td><td>45.74</td><td>10.01</td>
                    </tr>
                  </tbody>
                </table>
                </body></html>
                """
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"]
        assert response["strong_sectors"][0]["name"] == "AI应用"
        assert response["strong_sectors"][0]["change_pct"] == 0.046
        assert response["strong_sectors"][0]["source"] == "ths-concept-section"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_parses_sub_one_ths_concept_pct_as_percent_unit(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        if "q.10jqka.com.cn/gn/" in url:
            return FakeResponse(
                text="""
                <html><body>
                <input type="hidden" id="gnSection"
                  value='{"1":{"platecode":"885001","platename":"预制菜","199112":0.99,"zjjlr":10.9,"zfl":62}}'>
                </body></html>
                """
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"][0]["name"] == "预制菜"
        assert abs(response["strong_sectors"][0]["change_pct"] - 0.0099) < 0.000001
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_sorts_ths_concept_percent_units(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        if "q.10jqka.com.cn/gn/" in url:
            return FakeResponse(
                text="""
                <html><body>
                <input type="hidden" id="gnSection"
                  value='{"1":{"platecode":"885001","platename":"预制菜","199112":0.99,"zjjlr":10.9,"zfl":62},
                          "2":{"platecode":"885002","platename":"AI应用","199112":4.6,"zjjlr":12.3,"zfl":77}}'>
                </body></html>
                """
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert [item["name"] for item in response["strong_sectors"][:2]] == ["AI应用", "预制菜"]
        assert abs(response["strong_sectors"][0]["change_pct"] - 0.046) < 0.000001
        assert abs(response["strong_sectors"][1]["change_pct"] - 0.0099) < 0.000001
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_falls_back_to_live_industry_sectors_when_concepts_fail(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        params = kwargs.get("params", {})
        fs = str(params.get("fs", ""))
        if "m:90+t:3" in fs:
            return FakeResponse({"data": {"diff": []}})
        if "m:90+t:2" in fs:
            return FakeResponse(
                {
                    "data": {
                        "diff": [
                            {"f12": "BK1027", "f14": "小金属", "f3": 2.8, "f128": "601899"},
                            {"f12": "BK0917", "f14": "电力", "f3": 2.1, "f128": "600900"},
                        ]
                    }
                }
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"]
        assert response["strong_sectors"][0]["name"] == "小金属"
        assert response["strong_sectors"][0]["source"] == "eastmoney-industry-sector"
        assert "行业板块" in response["message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_uses_live_breadth_counts_when_available(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        params = kwargs.get("params", {})
        fs = str(params.get("fs", ""))
        fields = str(params.get("fields", ""))
        if "m:90+t:3" in fs:
            return FakeResponse({"data": {"diff": [{"f12": "BK1036", "f14": "半导体", "f3": 2.5, "f128": "688001"}]}})
        if "m:0+t:6" in fs and fields == "f12,f14,f3":
            return FakeResponse(
                {
                    "data": {
                        "diff": [
                            {"f12": "000001", "f14": "平安银行", "f3": 1.2},
                            {"f12": "000002", "f14": "万科A", "f3": -0.8},
                            {"f12": "000004", "f14": "国农科技", "f3": 0.0},
                        ]
                    }
                }
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["breadth"] == {"up": 1, "down": 1, "flat": 1, "total": 3, "source": "eastmoney-a-share-live"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_paginates_eastmoney_breadth_rows(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    requested_pages = []

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        params = kwargs.get("params", {})
        fs = str(params.get("fs", ""))
        fields = str(params.get("fields", ""))
        if "m:90+t:3" in fs:
            return FakeResponse({"data": {"diff": [{"f12": "BK1036", "f14": "半导体", "f3": 2.5, "f128": "688001"}]}})
        if fs == "m:0+t:6" and fields == "f12,f14,f3":
            page = int(params.get("pn", "1"))
            requested_pages.append(page)
            pages = {
                1: [
                    {"f12": "000001", "f14": "平安银行", "f3": 1.2},
                    {"f12": "000002", "f14": "万科A", "f3": -0.8},
                ],
                2: [
                    {"f12": "000004", "f14": "国农科技", "f3": 0.0},
                    {"f12": "000005", "f14": "世纪星源", "f3": 2.1},
                ],
            }
            return FakeResponse({"data": {"total": 4, "diff": pages.get(page, [])}})
        if fields == "f12,f14,f3":
            return FakeResponse({"data": {"total": 0, "diff": []}})
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["breadth"] == {"up": 2, "down": 1, "flat": 1, "total": 4, "source": "eastmoney-a-share-live"}
        assert requested_pages[:2] == [1, 2]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_tracks_yesterday_strong_sectors_from_local_history(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-27,10:30:00";'
            )
        params = kwargs.get("params", {})
        fs = str(params.get("fs", ""))
        if "b:BK1037" in fs:
            return FakeResponse(
                {
                    "data": {
                        "diff": [
                            {"f12": "300001"},
                            {"f12": "300002"},
                        ]
                    }
                }
            )
        return FakeResponse(
            {
                "data": {
                    "diff": [
                        {"f12": "BK1037", "f14": "电力设备", "f3": 3.2, "f128": "300750"},
                    ]
                }
            }
        )

    import pandas as pd

    rows = []
    for symbol, sector_prefix, prev_close, yesterday_close, latest_close in [
        ("300001", "创业板", 10.0, 12.0, 12.2),
        ("300002", "创业板", 20.0, 24.0, 24.1),
        ("600001", "沪市主板", 10.0, 10.4, 10.8),
        ("600002", "沪市主板", 20.0, 20.2, 20.5),
    ]:
        rows.extend(
            [
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp("2024-01-03"),
                    "open": prev_close,
                    "high": prev_close,
                    "low": prev_close,
                    "close": prev_close,
                    "volume": 1000,
                    "turnover_rate": 0.02,
                    "float_market_cap": 1_000_000_000,
                    "main_net_inflow": 0.0,
                    "is_st": False,
                    "is_suspended": False,
                    "listing_days": 200,
                },
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp("2024-01-04"),
                    "open": yesterday_close,
                    "high": yesterday_close,
                    "low": yesterday_close,
                    "close": yesterday_close,
                    "volume": 1000,
                    "turnover_rate": 0.02,
                    "float_market_cap": 1_000_000_000,
                    "main_net_inflow": 0.0,
                    "is_st": False,
                    "is_suspended": False,
                    "listing_days": 201,
                },
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp("2024-01-05"),
                    "open": latest_close,
                    "high": latest_close,
                    "low": latest_close,
                    "close": latest_close,
                    "volume": 1000,
                    "turnover_rate": 0.02,
                    "float_market_cap": 1_000_000_000,
                    "main_net_inflow": 0.0,
                    "is_st": False,
                    "is_suspended": False,
                    "listing_days": 202,
                },
            ]
        )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(pd.DataFrame(rows))
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"][0]["name"] == "电力设备"
        assert response["yesterday_strong_sectors"]
        assert response["yesterday_strong_sectors"][0]["name"] == "电力设备"
        assert response["yesterday_strong_sectors"][0]["source"] == "local-yesterday-group"
        assert response["message"].endswith("昨日强势板块追踪来自本地历史。")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_prefers_ths_market_summary_breadth(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

        @property
        def content(self):
            return self.text.encode("gbk", errors="ignore")

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-30,10:30:00";'
            )
        if "q.10jqka.com.cn" in url and "index/index/board/all" in url:
            return FakeResponse(
                text="""
                <html><body>
                <div class="page_info">上涨：3210只 下跌：1820只 平盘：120只</div>
                </body></html>
                """
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["breadth"] == {"up": 3210, "down": 1820, "flat": 120, "total": 5150, "source": "ths-market-summary"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_prefers_ths_industry_quotes_over_hot_reason_labels(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

        @property
        def content(self):
            return self.text.encode("gbk", errors="ignore")

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-30,10:30:00";'
            )
        if "zx.10jqka.com.cn/event/api/getharden" in url:
            return FakeResponse(
                payload={
                    "errocode": 0,
                    "errormsg": "",
                    "data": [
                        {"code": "300001", "name": "A", "reason": "算力租赁+AI政务", "zhangfu": 9.9, "huanshou": 12.0, "chengjiaoe": 100000},
                        {"code": "300002", "name": "B", "reason": "算力租赁+液冷服务器", "zhangfu": 8.2, "huanshou": 9.0, "chengjiaoe": 90000},
                        {"code": "300003", "name": "C", "reason": "液冷服务器+AI政务", "zhangfu": 6.8, "huanshou": 7.0, "chengjiaoe": 70000},
                    ],
                }
            )
        if "q.10jqka.com.cn/thshy/index/field/199112/order/desc/page/1/" in url:
            return FakeResponse(
                text="""
                <html><body>
                <table class="m-table m-pager-table">
                  <tbody>
                    <tr>
                      <td>1</td><td>白酒</td><td>3.52</td><td>416.94</td><td>272.51</td><td>27.66</td><td>18</td><td>1</td><td>65.36</td><td>酒鬼酒</td><td>45.74</td><td>10.01</td>
                    </tr>
                    <tr>
                      <td>2</td><td>电力</td><td>2.40</td><td>15974.60</td><td>1314.34</td><td>69.90</td><td>83</td><td>24</td><td>8.23</td><td>珈伟新能</td><td>5.72</td><td>11.28</td>
                    </tr>
                  </tbody>
                </table>
                </body></html>
                """
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"]
        assert response["strong_sectors"][0]["name"] == "白酒"
        assert response["strong_sectors"][0]["change_pct"] == 0.0352
        assert response["strong_sectors"][0]["source"] == "ths-industry-html"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_uses_hot_reason_only_when_board_quotes_fail(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

        @property
        def content(self):
            return self.text.encode("gbk", errors="ignore")

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-30,10:30:00";'
            )
        if "zx.10jqka.com.cn/event/api/getharden" in url:
            return FakeResponse(
                payload={
                    "errocode": 0,
                    "errormsg": "",
                    "data": [
                        {"code": "300001", "name": "A", "reason": "算力租赁+AI政务", "zhangfu": 9.9, "huanshou": 12.0, "chengjiaoe": 100000},
                        {"code": "300002", "name": "B", "reason": "算力租赁+液冷服务器", "zhangfu": 8.2, "huanshou": 9.0, "chengjiaoe": 90000},
                        {"code": "300003", "name": "C", "reason": "液冷服务器+AI政务", "zhangfu": 6.8, "huanshou": 7.0, "chengjiaoe": 70000},
                    ],
                }
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"]
        assert response["strong_sectors"][0]["name"] == "算力租赁"
        assert response["strong_sectors"][0]["source"] == "ths-hot-reason"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_realtime_market_snapshot_falls_back_to_ths_industry_html(tmp_path):
    class FakeResponse:
        text = ""
        encoding = "utf-8"

        def __init__(self, payload=None, text=""):
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return

        def json(self):
            return self._payload

        @property
        def content(self):
            return self.text.encode("gbk", errors="ignore")

    def requester(url, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeResponse(
                text='var hq_str_sh000001="上证指数,0,100,101,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-05-30,10:30:00";'
            )
        if "zx.10jqka.com.cn/event/api/getharden" in url:
            return FakeResponse(payload={"errocode": 1, "errormsg": "unavailable", "data": []})
        if "q.10jqka.com.cn/thshy/index/field/199112/order/desc/page/1/" in url:
            return FakeResponse(
                text="""
                <html><body>
                <table class="m-table m-pager-table">
                  <tbody>
                    <tr>
                      <td>1</td><td>电力</td><td>2.40</td><td>15974.60</td><td>1314.34</td><td>69.90</td><td>83</td><td>24</td><td>8.23</td><td>珈伟新能</td><td>5.72</td><td>11.28</td>
                    </tr>
                    <tr>
                      <td>2</td><td>白酒</td><td>2.10</td><td>1000</td><td>100</td><td>20</td><td>18</td><td>1</td><td>5.0</td><td>酒鬼酒</td><td>45.74</td><td>10.01</td>
                    </tr>
                  </tbody>
                </table>
                </body></html>
                """
            )
        return FakeResponse({"data": {"diff": []}})

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(sample_daily_bars())
    server.state.realtime_provider.requester = requester
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/realtime/market-snapshot")

        assert response["strong_sectors"]
        assert response["strong_sectors"][0]["name"] == "电力"
        assert response["strong_sectors"][0]["source"] == "ths-industry-html"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_market_news_uses_configured_provider(tmp_path):
    class FakeNewsProvider:
        def latest_news(self, limit=12):
            from datetime import datetime, timezone

            from astock_backtester.models import MarketNewsItem, MarketNewsResponse

            assert limit == 12
            return MarketNewsResponse(
                updated_at=datetime(2026, 5, 27, 10, 30, tzinfo=timezone.utc),
                source="fake-news",
                items=[
                    MarketNewsItem(
                        title="政策利好推动科技板块走强",
                        summary="半导体、AI 应用方向盘中活跃。",
                        source="东方财富",
                        published_at=datetime(2026, 5, 27, 10, 20, tzinfo=timezone.utc),
                        url="https://example.test/news",
                        tags=["科技", "政策"],
                        sentiment="positive",
                    )
                ],
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.news_provider = FakeNewsProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/market/news")

        assert response["source"] == "fake-news"
        assert response["items"][0]["title"] == "政策利好推动科技板块走强"
        assert response["items"][0]["sentiment"] == "positive"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_market_commentary_uses_configured_provider(tmp_path):
    class FakeCommentaryProvider:
        def current_commentary(self):
            from datetime import date, datetime, timezone

            from astock_backtester.models import MarketCommentaryPoint, MarketCommentaryResponse

            return MarketCommentaryResponse(
                updated_at=datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc),
                trade_date=date(2026, 6, 5),
                source="fake-commentary",
                stance="positive",
                summary="红盘家数占优，AI应用延续。",
                drivers=[MarketCommentaryPoint(title="强势题材", detail="AI应用+4.20%", weight="high")],
                risks=["成交量不延续时避免追高。"],
                next_watch=["继续观察AI应用承接。"],
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.commentary_provider = FakeCommentaryProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/market/commentary")

        assert response["source"] == "fake-commentary"
        assert response["stance"] == "positive"
        assert response["drivers"][0]["title"] == "强势题材"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_market_news_summary_uses_configured_provider(tmp_path):
    class FakeNewsSummaryProvider:
        def latest_summary(self):
            from datetime import datetime, timezone

            from astock_backtester.models import MarketNewsSummaryResponse, MarketNewsTheme

            return MarketNewsSummaryResponse(
                updated_at=datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc),
                source="fake-summary",
                item_count=3,
                themes=[
                    MarketNewsTheme(
                        title="AI",
                        summary="AI相关消息集中。",
                        sentiment="positive",
                        source_count=2,
                        headlines=["AI应用产业链午后走强"],
                    )
                ],
                highlights=["AI应用产业链午后走强"],
                risks=["退市风险提示增多"],
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.news_summary_provider = FakeNewsSummaryProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/market/news-summary")

        assert response["source"] == "fake-summary"
        assert response["item_count"] == 3
        assert response["themes"][0]["title"] == "AI"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_market_fupan_uses_configured_provider(tmp_path):
    class FakeBriefingProvider:
        def latest_fupan(self):
            from datetime import datetime, timezone

            from astock_backtester.models import MarketBriefingResponse, MarketBriefingSection

            return MarketBriefingResponse(
                kind="fupan",
                updated_at=datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc),
                source="fake-fupan",
                source_url="https://stock.10jqka.com.cn/fupan/",
                summary="复盘摘要",
                sections=[MarketBriefingSection(title="指数/概念分析", content="煤炭活跃")],
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.briefing_provider = FakeBriefingProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/market/fupan")

        assert response["kind"] == "fupan"
        assert response["source"] == "fake-fupan"
        assert response["sections"][0]["title"] == "指数/概念分析"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_market_zaopan_uses_configured_provider(tmp_path):
    class FakeBriefingProvider:
        def latest_zaopan(self):
            from datetime import datetime, timezone

            from astock_backtester.models import MarketBriefingResponse, MarketBriefingSection

            return MarketBriefingResponse(
                kind="zaopan",
                updated_at=datetime(2026, 6, 1, 8, 30, tzinfo=timezone.utc),
                source="fake-zaopan",
                source_url="https://stock.10jqka.com.cn/zaopan/",
                summary="早盘摘要",
                sections=[MarketBriefingSection(title="早盘要点", content="关注公司事项")],
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.briefing_provider = FakeBriefingProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/market/zaopan")

        assert response["kind"] == "zaopan"
        assert response["source"] == "fake-zaopan"
        assert response["sections"][0]["title"] == "早盘要点"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_market_news_parses_display_time_as_beijing_time():
    parsed = _parse_time("2026-05-27 10:20:00")

    assert parsed is not None
    assert parsed.isoformat() == "2026-05-27T10:20:00+08:00"


def test_service_risk_alerts_uses_configured_provider(tmp_path):
    class FakeRiskProvider:
        def current_alerts(self):
            from datetime import datetime, timezone

            from astock_backtester.models import RiskAlertItem, RiskAlertsResponse

            return RiskAlertsResponse(
                updated_at=datetime(2026, 5, 27, 10, 30, tzinfo=timezone.utc),
                source="fake-risk",
                items=[
                    RiskAlertItem(
                        symbol="000001",
                        name="*ST示例",
                        risk_type="ST风险",
                        reason="股票名称包含 *ST，存在退市风险警示。",
                        severity="high",
                        source="adata",
                        detected_at=datetime(2026, 5, 27, 10, 30, tzinfo=timezone.utc),
                    )
                ],
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.risk_provider = FakeRiskProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/risk/alerts")

        assert response["source"] == "fake-risk"
        assert response["items"][0]["symbol"] == "000001"
        assert response["items"][0]["reason"].startswith("股票名称包含")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_risk_alerts_reports_diagnostics_when_no_risky_symbols(tmp_path):
    class EmptyRiskProvider:
        def current_alerts(self):
            from datetime import datetime, timezone

            from astock_backtester.models import RiskAlertsResponse

            return RiskAlertsResponse(
                updated_at=datetime(2026, 5, 27, 10, 30, tzinfo=timezone.utc),
                source="local",
                items=[],
                diagnostics=["东方财富风险源不可用，已使用本地 ST 字段兜底。"],
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.risk_provider = EmptyRiskProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/risk/alerts")

        assert response["items"] == []
        assert response["diagnostics"] == ["东方财富风险源不可用，已使用本地 ST 字段兜底。"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_validates_user_written_strategy_condition(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/strategy/conditions/validate",
            {"text": "量比2日介于1.2到2.5"},
        )

        assert response["ok"] is True
        assert response["condition"]["condition_id"] == "volume_ratio_between"
        assert response["condition"]["params"] == {"window": 2, "min": 1.2, "max": 2.5}
        assert "量比2日介于1.2到2.5" in response["examples"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_validates_user_written_exit_condition_with_mode(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/strategy/conditions/validate",
            {"text": "突破20日最低", "mode": "exit"},
        )

        assert response["ok"] is True
        assert response["condition"]["condition_id"] == "breakdown_below_n_day_low"
        assert response["condition"]["params"] == {"window": 20}
        assert "跌破20日低点" in response["examples"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_returns_recommended_strategies(tmp_path):
    import pandas as pd

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["AAA", "AAA"],
                "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "open": [10.0, 10.2],
                "high": [10.3, 10.4],
                "low": [9.9, 10.0],
                "close": [10.1, 10.3],
                "volume": [1000, 1200],
                "float_market_cap": [1_000_000_000.0, 1_020_000_000.0],
                "total_market_cap": [1_200_000_000.0, 1_220_000_000.0],
                "main_net_inflow": [float("nan"), float("nan")],
            }
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json("GET", f"http://127.0.0.1:{port}/strategy/recommended")

        names = [item["name"] for item in response["items"]]
        assert "放量突破" in names
        assert "市值量价均衡" in names
        assert "资金趋势跟随" not in names
        assert "极端追高压力测试" not in names
        assert response["items"][0]["strategy"]["entry_groups"][0]["conditions"]
        assert response["items"][0]["example_conditions"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_health_reports_warehouse_market_cap_and_capital_flow_coverage(tmp_path):
    import pandas as pd

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["AAA", "AAA"],
                "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "open": [10.0, 10.2],
                "high": [10.3, 10.4],
                "low": [9.9, 10.0],
                "close": [10.1, 10.3],
                "volume": [1000, 1200],
                "float_market_cap": [1_000_000_000.0, 1_020_000_000.0],
                "total_market_cap": [1_200_000_000.0, 1_220_000_000.0],
                "main_net_inflow": [float("nan"), 2_000_000.0],
            }
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        health = _request_json("GET", f"http://127.0.0.1:{port}/health")

        datasets = {item["dataset"]: item for item in health["coverage"]}
        assert datasets["market_cap"]["symbols"] == 1
        assert datasets["market_cap"]["missing_rows"] == 0
        assert datasets["capital_flow"]["symbols"] == 1
        assert datasets["capital_flow"]["missing_rows"] == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_returns_sync_job_progress_by_id(tmp_path):
    class FakeManager:
        def start_full_market(self, symbols, start_date, end_date):
            from datetime import date

            from astock_backtester.models import SyncJobStatus

            return SyncJobStatus(
                job_id="job-progress",
                mode="full_market_bootstrap",
                status="running",
                total_symbols=len(symbols),
                completed_symbols=1,
                failed_symbols=0,
                imported_rows=100,
                current_symbol="000002",
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
            )

        def get_job(self, job_id):
            from datetime import date

            from astock_backtester.models import SyncJobStatus

            assert job_id == "job-progress"
            return SyncJobStatus(
                job_id=job_id,
                mode="full_market_bootstrap",
                status="completed",
                total_symbols=2,
                completed_symbols=2,
                failed_symbols=0,
                imported_rows=200,
                current_symbol=None,
                start_date=date(2015, 1, 1),
                end_date=date(2015, 1, 5),
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.sync_manager = FakeManager()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        started = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/sync/full-market",
            {"symbols": ["000001", "000002"], "start_date": "2015-01-01", "end_date": "2015-01-05"},
        )
        progress = _request_json("GET", f"http://127.0.0.1:{port}/sync/jobs/{started['job']['job_id']}")

        assert started["job"]["status"] == "running"
        assert started["job"]["current_symbol"] == "000002"
        assert progress["job"]["status"] == "completed"
        assert progress["job"]["imported_rows"] == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)
