from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

from astock_backtester.sample_data import sample_daily_bars
from astock_backtester.service import create_server


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


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
