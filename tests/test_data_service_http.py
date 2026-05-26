from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

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

